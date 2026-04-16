import json
import time
import threading
from collections import defaultdict

from websocket import WebSocketApp

LIVE_CANDLES = {}
LIVE_MARK = {}
LAST_UPDATE = {}
WS_THREAD = None
WS_RUNNING = False

def build_stream_url(symbols, interval="15m"):
    streams = []
    for s in symbols:
        sym = s.lower()
        streams.append(f"{sym}@kline_{interval}")
        streams.append(f"{sym}@markPrice@1s")
    return "wss://fstream.binance.com/stream?streams=" + "/".join(streams)

def on_message(ws, message):
    try:
        msg = json.loads(message)
        data = msg.get("data", msg)

        if "e" in data and data["e"] == "kline":
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

        if "e" in data and data["e"] == "markPriceUpdate":
            symbol = data["s"]
            LIVE_MARK[symbol] = {
                "price": float(data["p"]),
                "time": int(data["E"]),
            }
            LAST_UPDATE[symbol] = time.time()

    except Exception as e:
        print("WS message error:", e)

def on_error(ws, error):
    print("WS error:", error)

def on_close(ws, close_status_code, close_msg):
    global WS_RUNNING
    print("WS closed:", close_status_code, close_msg)
    WS_RUNNING = False

def on_open(ws):
    print("WS connected 🚀")

def run_ws(symbols, interval="15m"):
    global WS_RUNNING
    url = build_stream_url(symbols, interval)

    while True:
        try:
            WS_RUNNING = True
            ws = WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print("WS reconnect error:", e)

        WS_RUNNING = False
        time.sleep(5)

def start_ws(symbols, interval="15m"):
    global WS_THREAD
    if WS_THREAD and WS_THREAD.is_alive():
        return
    WS_THREAD = threading.Thread(target=run_ws, args=(symbols, interval), daemon=True)
    WS_THREAD.start()

def get_live_candle(symbol):
    return LIVE_CANDLES.get(symbol)

def get_live_mark(symbol):
    return LIVE_MARK.get(symbol)

def get_live_age(symbol):
    ts = LAST_UPDATE.get(symbol)
    if not ts:
        return 9999
    return time.time() - ts