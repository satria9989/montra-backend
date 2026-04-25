import os
import json
import time
import threading
from typing import Any, Dict, Iterable, List, Optional, Set

from websocket import WebSocketApp

LIVE_CANDLES: Dict[str, Dict[str, Any]] = {}
LIVE_MARK: Dict[str, Dict[str, Any]] = {}
LAST_UPDATE: Dict[str, float] = {}

WS_THREAD: Optional[threading.Thread] = None
WS_APP: Optional[WebSocketApp] = None
WS_RUNNING = False
WS_LAST_ERROR: Optional[str] = None
WS_LAST_START = 0.0
WS_LAST_CLOSE = 0.0
WS_RESTART_COUNT = 0
WS_MESSAGE_COUNT = 0
WS_LAST_MESSAGE_TS = 0.0
WS_LAST_STREAM: Optional[str] = None
WS_LAST_EVENT: Optional[str] = None
WS_SUBSCRIBED_SYMBOLS: Set[str] = set()
WS_LOCK = threading.RLock()

RECONNECT_SLEEP_SECONDS = 10


def _clean_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def build_stream_url(symbols: Iterable[str], interval: str = "15m") -> str:
    """
    Use one all-market mark-price stream plus per-symbol klines.

    This reduces combined-stream fanout from 2*N streams to N+1 streams and
    also gives us a payload every second even if kline payloads are quiet.
    """
    clean_symbols = [_clean_symbol(s) for s in symbols if _clean_symbol(s)]
    streams: List[str] = ["!markPrice@arr@1s"]
    for sym in clean_symbols:
        streams.append(f"{sym.lower()}@kline_{interval}")
    base_url = os.getenv("BINANCE_FSTREAM_WS_URL", "wss://fstream.binance.com/market/stream").rstrip("/")
    return base_url + "?streams=" + "/".join(streams)


def _touch_message(stream: Optional[str], event: Optional[str]) -> None:
    global WS_MESSAGE_COUNT, WS_LAST_MESSAGE_TS, WS_LAST_STREAM, WS_LAST_EVENT
    WS_MESSAGE_COUNT += 1
    WS_LAST_MESSAGE_TS = time.time()
    WS_LAST_STREAM = stream
    WS_LAST_EVENT = event


def _handle_kline(data: Dict[str, Any]) -> bool:
    try:
        k = data.get("k") or {}
        symbol = _clean_symbol(data.get("s") or k.get("s"))
        if not symbol:
            return False
        LIVE_CANDLES[symbol] = {
            "time": int(k["t"]),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k.get("v", 0)),
            "is_closed": bool(k.get("x", False)),
        }
        LAST_UPDATE[symbol] = time.time()
        return True
    except Exception as exc:
        print("WS kline parse error:", exc, data)
        return False


def _handle_mark(data: Dict[str, Any]) -> bool:
    try:
        symbol = _clean_symbol(data.get("s"))
        if not symbol:
            return False
        # Filter the all-market array to the subscribed universe only.
        if WS_SUBSCRIBED_SYMBOLS and symbol not in WS_SUBSCRIBED_SYMBOLS:
            return False
        price = data.get("p") or data.get("markPrice")
        event_time = data.get("E") or data.get("time") or int(time.time() * 1000)
        LIVE_MARK[symbol] = {
            "price": float(price),
            "time": int(event_time),
        }
        LAST_UPDATE[symbol] = time.time()
        return True
    except Exception as exc:
        print("WS mark parse error:", exc, data)
        return False


def _handle_payload(payload: Any, stream: Optional[str] = None) -> int:
    """Returns number of symbol updates processed."""
    updates = 0

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                updates += _handle_payload(item, stream=stream)
        return updates

    if not isinstance(payload, dict):
        return 0

    event = payload.get("e")
    if event == "kline":
        updates += int(_handle_kline(payload))
    elif event == "markPriceUpdate" or "p" in payload:
        updates += int(_handle_mark(payload))

    return updates


def on_message(ws: WebSocketApp, message: str) -> None:
    try:
        msg = json.loads(message)
        stream = msg.get("stream") if isinstance(msg, dict) else None
        data = msg.get("data", msg) if isinstance(msg, dict) else msg
        event = None
        if isinstance(data, dict):
            event = data.get("e")
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            event = data[0].get("e")

        _touch_message(stream, event)
        updates = _handle_payload(data, stream=stream)

        # Light heartbeat log every 500 messages so Render logs stay useful but not noisy.
        if WS_MESSAGE_COUNT % 500 == 0:
            print(f"WS heartbeat: messages={WS_MESSAGE_COUNT} last_stream={WS_LAST_STREAM} updates={updates}")

    except Exception as exc:
        print("WS message error:", exc)


def on_error(ws: WebSocketApp, error: Any) -> None:
    global WS_LAST_ERROR
    WS_LAST_ERROR = str(error)
    print("WS error:", error)


def on_close(ws: WebSocketApp, close_status_code: Any, close_msg: Any) -> None:
    global WS_RUNNING, WS_LAST_CLOSE
    WS_RUNNING = False
    WS_LAST_CLOSE = time.time()
    print("WS closed:", close_status_code, close_msg)


def on_open(ws: WebSocketApp) -> None:
    global WS_LAST_START, WS_LAST_ERROR, WS_RUNNING
    WS_LAST_START = time.time()
    WS_LAST_ERROR = None
    WS_RUNNING = True
    print(f"WS connected 🚀 subscribed={len(WS_SUBSCRIBED_SYMBOLS)}")


def run_ws(symbols: Iterable[str], interval: str = "15m") -> None:
    global WS_RUNNING, WS_RESTART_COUNT, WS_APP, WS_SUBSCRIBED_SYMBOLS

    clean_symbols = [_clean_symbol(s) for s in symbols if _clean_symbol(s)]
    with WS_LOCK:
        WS_SUBSCRIBED_SYMBOLS = set(clean_symbols)

    url = build_stream_url(clean_symbols, interval)
    print(f"WS stream init: symbols={len(clean_symbols)} streams={len(clean_symbols) + 1} url_len={len(url)}")

    while True:
        ws = None
        try:
            ws = WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            with WS_LOCK:
                WS_APP = ws
                WS_RESTART_COUNT += 1
                WS_RUNNING = False

            ws.run_forever(
                ping_interval=30,
                ping_timeout=10,
                skip_utf8_validation=True,
            )

        except Exception as exc:
            print("WS reconnect error:", exc)
        finally:
            WS_RUNNING = False
            with WS_LOCK:
                if WS_APP is ws:
                    WS_APP = None

        time.sleep(RECONNECT_SLEEP_SECONDS)


def start_ws(symbols: Iterable[str], interval: str = "15m") -> bool:
    global WS_THREAD
    with WS_LOCK:
        if WS_THREAD and WS_THREAD.is_alive():
            return False
        WS_THREAD = threading.Thread(target=run_ws, args=(list(symbols), interval), daemon=True)
        WS_THREAD.start()
        return True


def get_live_candle(symbol: str):
    return LIVE_CANDLES.get(_clean_symbol(symbol))


def get_live_mark(symbol: str):
    return LIVE_MARK.get(_clean_symbol(symbol))


def get_live_age(symbol: str) -> float:
    ts = LAST_UPDATE.get(_clean_symbol(symbol))
    if not ts:
        return 9999
    return time.time() - ts


def is_ws_running() -> bool:
    return WS_RUNNING


def get_ws_status() -> Dict[str, Any]:
    with WS_LOCK:
        thread_alive = WS_THREAD.is_alive() if WS_THREAD else False
        app_alive = WS_APP is not None
        subscribed = sorted(WS_SUBSCRIBED_SYMBOLS)

    last_message_age = 9999 if not WS_LAST_MESSAGE_TS else time.time() - WS_LAST_MESSAGE_TS

    return {
        "running": WS_RUNNING,
        "last_error": WS_LAST_ERROR,
        "last_start": WS_LAST_START,
        "last_close": WS_LAST_CLOSE,
        "restart_count": WS_RESTART_COUNT,
        "thread_alive": thread_alive,
        "app_alive": app_alive,
        "message_count": WS_MESSAGE_COUNT,
        "last_message_age": round(last_message_age, 2),
        "last_stream": WS_LAST_STREAM,
        "last_event": WS_LAST_EVENT,
        "subscribed_count": len(subscribed),
        "subscribed_sample": subscribed[:10],
    }


def count_stale_symbols(symbols: Iterable[str], max_age: float = 20):
    stale = []
    for sym in symbols:
        if get_live_age(sym) > max_age:
            stale.append(_clean_symbol(sym))
    return stale


def restart_ws(symbols: Iterable[str], interval: str = "15m") -> bool:
    """
    Safe restart request.

    If the worker thread is alive, close the current WebSocketApp only. The
    worker loop reconnects by itself, preventing duplicate websocket threads.
    """
    print("🔁 WS restart requested")
    with WS_LOCK:
        app = WS_APP
        thread_alive = WS_THREAD.is_alive() if WS_THREAD else False

    if app is not None:
        try:
            app.close()
        except Exception as exc:
            print("WS close error:", exc)

    if not thread_alive:
        return start_ws(symbols, interval)

    return False
