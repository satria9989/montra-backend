import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

AUTO_MODE = True
SCAN_INTERVAL = 15  # detik
MIN_SCORE = 80

from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from binance.client import Client
from binance.enums import *

from data import get_ticker, get_ohlcv, get_multi_tickers

# ================= INIT =================
app = FastAPI(title="Montra Backend", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 OPENAI CLIENT
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

binance = Client(
    os.getenv("BINANCE_API_KEY"),
    os.getenv("BINANCE_SECRET")
)

def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    requests.post(url, json={
        "chat_id": chat_id,
        "text": msg
    })

def place_futures_order(symbol, side, quantity, sl, tp):
    try:
        order = binance.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=FUTURE_ORDER_TYPE_MARKET,
            quantity=quantity
        )

        # SL
        binance.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == "BUY" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=sl,
            closePosition=True
        )

        # TP
        binance.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == "BUY" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=tp,
            closePosition=True
        )

        return {"status": "FILLED", "order": order}

    except Exception as e:
        return {"error": str(e)}

def place_split_tp(symbol, side, quantity, tp1, tp2, tp3):
    side_close = SIDE_SELL if side == "BUY" else SIDE_BUY

    q1 = round(quantity * 0.4, 3)
    q2 = round(quantity * 0.3, 3)
    q3 = round(quantity * 0.3, 3)

    for tp, q in [(tp1, q1), (tp2, q2), (tp3, q3)]:
        binance.futures_create_order(
            symbol=symbol,
            side=side_close,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=tp,
            quantity=q
        )

def update_stop_loss(symbol, side, new_sl):
    try:
        binance.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == "BUY" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=new_sl,
            closePosition=True
        )
    except Exception as e:
        print("SL update error:", e)

def adjust_precision(symbol, qty, price):
    info = binance.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            step = float(next(f["stepSize"] for f in s["filters"] if f["filterType"] == "LOT_SIZE"))
            tick = float(next(f["tickSize"] for f in s["filters"] if f["filterType"] == "PRICE_FILTER"))
            # adjust qty
            qty = round(qty / step) * step
            # adjust price
            price = round(price / tick) * tick
            return qty, price
    return qty, price

# ================= BASIC =================
@app.get("/")
def root():
    return {"status": "MONTRA backend running 🚀"}

@app.get("/home")
def home():
    return {"message": "MONTRA BACKEND RUNNING 🔥"}

@app.get("/symbols")
def symbols():
    return {
        "symbols": [
            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT",
            "SOLUSDT",
            "XRPUSDT",
        ]
    }

# ================= MARKET =================

@app.get("/ticker/{symbol}")
def ticker(symbol: str):
    try:
        return get_ticker(symbol)
    except Exception as e:
        return {"error": str(e)}

@app.get("/ohlcv/{symbol}")
def ohlcv(
    symbol: str,
    timeframe: str = Query(default="15m"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    try:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit,
            "data": get_ohlcv(symbol, timeframe=timeframe, limit=limit),
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/tickers")
def tickers(symbols: str = Query(default="BTCUSDT,ETHUSDT,BNBUSDT")):
    try:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        return {"data": get_multi_tickers(symbol_list)}
    except Exception as e:
        return {"error": str(e)}

# ================= AI FILTER =================

@app.post("/ai-filter")
def ai_filter(payload: dict = Body(...)):
    try:
        symbol = payload.get("symbol")
        trade_type = payload.get("type")
        rr = payload.get("rr")

        prompt = f"""
You are a professional trading AI.

Evaluate this trade setup:

Symbol: {symbol}
Type: {trade_type}
Risk Reward: {rr}

Rules:
- RR must be >= 3
- Avoid weak structure
- Avoid low probability setups

Answer format ONLY:
VALID or NO TRADE
Confidence: XX%
""".strip()

        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )

        return {
            "result": res.choices[0].message.content.strip()
        }

    except Exception as e:
        # 🔥 fallback kalau AI down
        return {
            "result": "NO TRADE\nConfidence: 0%",
            "error": str(e),
        }

@app.post("/notify")
def notify(payload: dict = Body(...)):
    try:
        msg = payload.get("text", "")
        send_telegram(msg)
        return {"status": "sent"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/notify-image")
def notify_image(payload: dict = Body(...)):
    try:
        text = payload.get("text", "")
        image = payload.get("image", "")

        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        url = f"https://api.telegram.org/bot{token}/sendPhoto"

        img_data = base64.b64decode(image.split(",")[1])

        files = {
            "photo": ("chart.png", img_data)
        }

        data = {
            "chat_id": chat_id,
            "caption": text
        }

        requests.post(url, files=files, data=data)

        return {"status": "sent"}

    except Exception as e:
        return {"error": str(e)}

@app.post("/trade")
def trade(payload: dict = Body(...)):
    try:
        symbol = payload.get("symbol")
        side = payload.get("type")
        entry = float(payload.get("entry"))
        sl = float(payload.get("sl"))
        tp = float(payload.get("tp"))
        risk_percent = float(payload.get("risk", 1))

        # BALANCE
        balance_info = binance.futures_account_balance()
        usdt_balance = next(
            (b for b in balance_info if b["asset"] == "USDT"), None
        )

        balance = float(usdt_balance["balance"]) if usdt_balance else 0

        # POSITION SIZE
        risk_amount = balance * (risk_percent / 100)
        stop_distance = abs(entry - sl)

        quantity = round(risk_amount / stop_distance, 3)

        result = place_futures_order(symbol, side, quantity, sl, tp)

        send_telegram(f"""
🚀 TRADE EXECUTED
{symbol} {side}
Qty: {quantity}
SL: {sl}
TP: {tp}
""")

        return result

    except Exception as e:
        return {"error": str(e)}

@app.get("/positions")
def get_positions():
    try:
        positions = binance.futures_position_information()

        active = []
        for p in positions:
            amt = float(p["positionAmt"])
            if amt != 0:
                active.append({
                    "symbol": p["symbol"],
                    "side": "BUY" if amt > 0 else "SELL",
                    "entry": float(p["entryPrice"]),
                    "size": abs(amt),
                    "unrealized": float(p["unRealizedProfit"])
                })

        return {"positions": active}

    except Exception as e:
        return {"error": str(e)}

# ✅ POSITION DETAIL + TRADES (new endpoint)
@app.get("/position-detail/{symbol}")
def position_detail(symbol: str):
    try:
        positions = binance.futures_position_information(symbol=symbol)
        trades = binance.futures_account_trades(symbol=symbol)

        # Cari posisi yang sedang aktif (positionAmt != 0)
        pos = next((p for p in positions if float(p["positionAmt"]) != 0), None)

        return {
            "position": pos,
            "trades": trades[-50:]  # ambil 50 transaksi terakhir
        }

    except Exception as e:
        return {"error": str(e)}

def smart_trailing():
    import time

    while True:
        try:
            positions = binance.futures_position_information()

            for p in positions:
                amt = float(p["positionAmt"])
                if amt == 0:
                    continue

                symbol = p["symbol"]
                entry = float(p["entryPrice"])
                price = float(p["markPrice"])
                side = "BUY" if amt > 0 else "SELL"

                move = abs(price - entry)

                # 🎯 BREAK EVEN
                if move > entry * 0.003:
                    update_stop_loss(symbol, side, entry)

                # 🎯 TRAILING PROFIT
                if move > entry * 0.006:
                    if side == "BUY":
                        new_sl = price - (move * 0.3)
                    else:
                        new_sl = price + (move * 0.3)

                    update_stop_loss(symbol, side, new_sl)

            time.sleep(5)

        except Exception as e:
            print("Trailing error:", e)
            time.sleep(5)

def auto_trader():
    while True:
        try:
            if not AUTO_MODE:
                time.sleep(SCAN_INTERVAL)
                continue

            # 🔥 contoh pair (bisa expand)
            pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

            for symbol in pairs:
                try:
                    # ambil data
                    ohlcv = binance.futures_klines(symbol=symbol, interval="15m", limit=100)
                    closes = [float(c[4]) for c in ohlcv]
                    last_price = closes[-1]

                    # 🧠 dummy signal (sementara, nanti bisa connect logic lo)
                    signal = {
                        "symbol": symbol,
                        "type": "BUY" if closes[-1] > closes[-2] else "SELL",
                        "entry": last_price,
                        "sl": last_price * 0.995,
                        "tp": last_price * 1.01,
                        "score": 85
                    }

                    # 🎯 filter
                    if signal["score"] < MIN_SCORE:
                        continue

                    # 4 — LIMIT DUPLICATE TRADE
                    positions = binance.futures_position_information(symbol=symbol)
                    pos = next((p for p in positions if float(p["positionAmt"]) != 0), None)
                    if pos:
                        continue  # skip kalau sudah ada posisi

                    # 5 — RISK SIMPLE + MIN NOTIONAL + PRECISION FIX
                    balance_info = binance.futures_account_balance()
                    usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
                    balance = float(usdt["balance"]) if usdt else 0

                    price = signal["entry"]
                    risk_amount = balance * 0.01
                    stop_distance = abs(signal["entry"] - signal["sl"])
                    qty = risk_amount / stop_distance

                    # 🔥 pastikan minimal $100
                    notional = qty * price
                    if notional < 100:
                        qty = 100 / price

                    # precision fix
                    qty, price = adjust_precision(symbol, qty, price)

                    # 🚀 execute
                    result = place_futures_order(
                        symbol=signal["symbol"],
                        side=signal["type"],
                        quantity=qty,
                        sl=signal["sl"],
                        tp=signal["tp"]
                    )

                    send_telegram(f"""
🤖 AUTO TRADE
{symbol} {signal['type']}
Score: {signal['score']}
""")
                    print("AUTO EXEC:", result)

                except Exception as e:
                    print("Pair error:", symbol, e)

        except Exception as e:
            print("AUTO LOOP ERROR:", e)

        time.sleep(SCAN_INTERVAL)

# Jalankan trailing engine di background
import threading

threading.Thread(target=smart_trailing, daemon=True).start()

# 3 — JALANKAN AUTO BOT
if AUTO_MODE:
    threading.Thread(target=auto_trader, daemon=True).start()