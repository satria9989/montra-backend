import json
import time
import threading

from websocket import WebSocketApp

LIVE_CANDLES = {}
LIVE_MARK = {}
LAST_UPDATE = {}

WS_THREAD = None
WS_APP = None
WS_RUNNING = False
WS_LAST_ERROR = None
WS_LAST_START = 0
WS_RESTART_COUNT = 0
WS_LOCK = threading.RLock()

RECONNECT_SLEEP_SECONDS = 10


def build_stream_url(symbols, interval="15m"):
    streams = []
    for s in symbols:
        sym = str(s).lower()
        streams.append(f"{sym}@kline_{interval}")
        streams.append(f"{sym}@markPrice@1s")
    return "wss://fstream.binance.com/stream?streams=" + "/".join(streams)


def on_message(ws, message):
    try:
        msg = json.loads(message)
        data = msg.get("data", msg)

        if data.get("e") == "kline":
            k = data["k"]
            symbol = data["s"]
            LIVE_CANDLES[symbol] = {
                "time": int(k["t"]),
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "is_closed": bool(k["x"]),
            }
            LAST_UPDATE[symbol] = time.time()

        if data.get("e") == "markPriceUpdate":
            symbol = data["s"]
            LIVE_MARK[symbol] = {
                "price": float(data["p"]),
                "time": int(data["E"]),
            }
            LAST_UPDATE[symbol] = time.time()

    except Exception as e:
        print("WS message error:", e)


def on_error(ws, error):
    global WS_LAST_ERROR
    WS_LAST_ERROR = str(error)
    print("WS error:", error)


def on_close(ws, close_status_code, close_msg):
    global WS_RUNNING
    print("WS closed:", close_status_code, close_msg)
    WS_RUNNING = False


def on_open(ws):
    global WS_LAST_START, WS_LAST_ERROR, WS_RUNNING
    WS_LAST_START = time.time()
    WS_LAST_ERROR = None
    WS_RUNNING = True
    print("WS connected 🚀")


def run_ws(symbols, interval="15m"):
    """
    Single long-lived websocket worker.

    Important: do not create a second worker while this thread is alive.
    restart_ws() closes the active WebSocketApp and lets this loop reconnect.
    """
    global WS_RUNNING, WS_RESTART_COUNT, WS_APP
    url = build_stream_url(symbols, interval)

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

            ws.run_forever(ping_interval=20, ping_timeout=10)

        except Exception as e:
            print("WS reconnect error:", e)
        finally:
            WS_RUNNING = False
            with WS_LOCK:
                if WS_APP is ws:
                    WS_APP = None

        time.sleep(RECONNECT_SLEEP_SECONDS)


def start_ws(symbols, interval="15m"):
    global WS_THREAD
    with WS_LOCK:
        if WS_THREAD and WS_THREAD.is_alive():
            return False
        WS_THREAD = threading.Thread(target=run_ws, args=(symbols, interval), daemon=True)
        WS_THREAD.start()
        return True


def get_live_candle(symbol):
    return LIVE_CANDLES.get(symbol)


def get_live_mark(symbol):
    return LIVE_MARK.get(symbol)


def get_live_age(symbol):
    ts = LAST_UPDATE.get(symbol)
    if not ts:
        return 9999
    return time.time() - ts


def is_ws_running():
    return WS_RUNNING


def get_ws_status():
    with WS_LOCK:
        thread_alive = WS_THREAD.is_alive() if WS_THREAD else False
        app_alive = WS_APP is not None
    return {
        "running": WS_RUNNING,
        "last_error": WS_LAST_ERROR,
        "last_start": WS_LAST_START,
        "restart_count": WS_RESTART_COUNT,
        "thread_alive": thread_alive,
        "app_alive": app_alive,
    }


def count_stale_symbols(symbols, max_age=20):
    stale = []
    for sym in symbols:
        age = get_live_age(sym)
        if age > max_age:
            stale.append(sym)
    return stale


def restart_ws(symbols, interval="15m"):
    """
    Safe restart request.

    If the worker thread is alive, close the current WebSocketApp only. The
    worker loop will reconnect by itself. This prevents duplicated websocket
    threads and restart storms.
    """
    print("🔁 WS restart requested")
    with WS_LOCK:
        app = WS_APP
        thread_alive = WS_THREAD.is_alive() if WS_THREAD else False

    if app is not None:
        try:
            app.close()
        except Exception as e:
            print("WS close error:", e)

    if not thread_alive:
        return start_ws(symbols, interval)

    return False
