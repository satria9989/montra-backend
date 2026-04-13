import os
import time
import threading
import requests
import base64
from dotenv import load_dotenv
from decimal import Decimal, ROUND_DOWN, ROUND_UP

load_dotenv()

AUTO_MODE = True
SCAN_INTERVAL = 15  # detik
MIN_SCORE = 80

ACCOUNTS = [
    {
        "name": "MAIN",
        "api_key": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "risk": 0.01,
        "compound": True,
        "withdraw_threshold": 50,   # $ profit
        "withdraw_ratio": 0.3       # 30% ditarik
    },
    {
        "name": "SECOND",
        "api_key": os.getenv("BINANCE_API_KEY_2"),
        "secret": os.getenv("BINANCE_SECRET_2"),
        "risk": 0.02,
        "compound": True,
        "withdraw_threshold": 50,
        "withdraw_ratio": 0.3
    }
]

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

CLIENTS = []
for acc in ACCOUNTS:
    if acc["api_key"] and acc["secret"]:
        CLIENTS.append({
            "name": acc["name"],
            "client": Client(acc["api_key"], acc["secret"]),
            "risk": acc["risk"]
        })
print("🔥 ACTIVE ACCOUNTS:", len(CLIENTS))

ACCOUNT_PROFIT = {}

EXCHANGE_CACHE = {}
LAST_STOP_PRICE = {}

def floor_to_step(value, step):
    d = Decimal(str(value))
    s = Decimal(str(step))
    return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)

def ceil_to_step(value, step):
    d = Decimal(str(value))
    s = Decimal(str(step))
    return float((d / s).to_integral_value(rounding=ROUND_UP) * s)

def normalize_price(symbol, price):
    f = EXCHANGE_CACHE.get(symbol)
    if not f:
        return price
    tick = f["tickSize"]
    return floor_to_step(price, tick)

def load_exchange_cache():
    global EXCHANGE_CACHE
    info = binance.futures_exchange_info()
    for s in info["symbols"]:
        symbol = s["symbol"]
        lot = next(f for f in s["filters"] if f["filterType"] == "LOT_SIZE")
        price = next(f for f in s["filters"] if f["filterType"] == "PRICE_FILTER")
        EXCHANGE_CACHE[symbol] = {
            "stepSize": float(lot["stepSize"]),
            "minQty": float(lot["minQty"]),
            "tickSize": float(price["tickSize"]),
        }
    print("✅ Exchange cache loaded:", len(EXCHANGE_CACHE))

def adjust_precision(symbol, qty, price):
    f = EXCHANGE_CACHE.get(symbol)
    if not f:
        return qty, price

    step = f["stepSize"]
    min_qty = f["minQty"]
    tick = f["tickSize"]

    qty = floor_to_step(qty, step)
    if qty < min_qty:
        qty = min_qty
    qty = floor_to_step(qty, step)

    price = floor_to_step(price, tick)
    return qty, price

def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    requests.post(url, json={
        "chat_id": chat_id,
        "text": msg
    })

def cancel_existing_orders(symbol):
    try:
        orders = binance.futures_get_open_orders(symbol=symbol)

        for o in orders:
            if o["type"] in ["STOP_MARKET", "TAKE_PROFIT_MARKET"]:
                try:
                    binance.futures_cancel_order(
                        symbol=symbol,
                        orderId=o["orderId"]
                    )
                except Exception as e:
                    print("Cancel single order error:", e)

        time.sleep(1.0)
        return True

    except Exception as e:
        print("Cancel error:", e)
        return False

def place_futures_order(symbol, side, quantity, sl, tp):
    try:
        sl = normalize_price(symbol, sl)
        tp = normalize_price(symbol, tp)

        cancel_existing_orders(symbol)
        time.sleep(1.0)

        order = binance.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=FUTURE_ORDER_TYPE_MARKET,
            quantity=quantity
        )

        time.sleep(0.3)

        binance.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == "BUY" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=sl,
            closePosition=True,
            workingType="MARK_PRICE"
        )

        binance.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == "BUY" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=tp,
            closePosition=True,
            workingType="MARK_PRICE"
        )

        return {"status": "FILLED", "order": order}

    except Exception as e:
        return {"error": str(e)}

def update_account_profit(client, name):
    try:
        balance_info = client.futures_account_balance()
        usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
        unrealized = float(usdt["crossUnPnl"]) if usdt else 0
        ACCOUNT_PROFIT[name] = unrealized
    except Exception as e:
        print("Profit error:", name, e)

def check_withdraw(acc, client):
    name = acc["name"]
    profit = ACCOUNT_PROFIT.get(name, 0)
    threshold = acc.get("withdraw_threshold", 100)
    ratio = acc.get("withdraw_ratio", 0.3)
    if profit >= threshold:
        amount = profit * ratio
        print(f"💸 WITHDRAW SIMULASI: {name} ${amount:.2f}")
        send_telegram(f"""
💸 WITHDRAW TRIGGER
{name}
Profit: {profit:.2f}
Withdraw: {amount:.2f}
""")
        ACCOUNT_PROFIT[name] = 0  # reset setelah withdraw

def place_order_multi(symbol, side, sl, tp):
    results = []
    for acc in CLIENTS:
        try:
            c = acc["client"]
            base_risk = acc["risk"]
            profit = ACCOUNT_PROFIT.get(acc["name"], 0)
            # 🔥 compounding
            if acc.get("compound") and profit > 0:
                risk_pct = base_risk + (profit / 1000)  # scaling pelan
            else:
                risk_pct = base_risk
            # balance
            balance_info = c.futures_account_balance()
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
            balance = float(usdt["balance"]) if usdt else 0
            risk_amount = balance * risk_pct
            price = float(c.futures_symbol_ticker(symbol=symbol)["price"])
            stop_distance = abs(price - sl)

            if stop_distance == 0:
                continue

            qty = risk_amount / stop_distance

            # minimal notional
            if qty * price < 100:
                qty = ceil_to_step(100 / price, EXCHANGE_CACHE.get(symbol, {}).get("stepSize", 0.001))

            qty, price = adjust_precision(symbol, qty, price)

            # validasi final
            if qty * price < 100:
                print("❌ SKIP NOTIONAL < 100", symbol)
                continue

            order = c.futures_create_order(
                symbol=symbol,
                side=SIDE_BUY if side == "BUY" else SIDE_SELL,
                type=FUTURE_ORDER_TYPE_MARKET,
                quantity=qty
            )
            results.append({"account": acc["name"], "status": "OK"})
            update_account_profit(c, acc["name"])
            check_withdraw(acc, c)
        except Exception as e:
            results.append({"account": acc["name"], "error": str(e)})
    return results

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
        new_sl = normalize_price(symbol, new_sl)
        
        current_price = float(binance.futures_symbol_ticker(symbol=symbol)["price"])
        
        if side == "BUY" and new_sl >= current_price:
            return

        if side == "SELL" and new_sl <= current_price:
            return
            
        buffer = current_price * 0.001  # 0.1%
        
        if side == "BUY" and new_sl >= current_price - buffer:
            return
        
        if side == "SELL" and new_sl <= current_price + buffer:
            return
    
        last = LAST_STOP_PRICE.get(symbol)
        tick = EXCHANGE_CACHE.get(symbol, {}).get("tickSize", 0.0)

        if last is not None and abs(last - new_sl) <= max(tick, 1e-12):
            return

        for _ in range(3):
            cancel_existing_orders(symbol)
            time.sleep(1.0)

            try:
                binance.futures_create_order(
                    symbol=symbol,
                    side=SIDE_SELL if side == "BUY" else SIDE_BUY,
                    type=FUTURE_ORDER_TYPE_STOP_MARKET,
                    stopPrice=new_sl,
                    closePosition=True,
                    workingType="MARK_PRICE"
                )

                LAST_STOP_PRICE[symbol] = new_sl
                return

            except Exception as e:
                if "-4130" in str(e):
                    time.sleep(1.0)
                    continue
                raise

        print("SL update skipped after retries:", symbol)

    except Exception as e:
        print("SL update error:", e)

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

@app.get("/accounts")
def get_accounts():
    data = []
    for acc in CLIENTS:
        try:
            c = acc["client"]
            balance_info = c.futures_account_balance()
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
            balance = float(usdt["balance"]) if usdt else 0
            unrealized = float(usdt["crossUnPnl"]) if usdt else 0
            equity = balance + unrealized
            positions = c.futures_position_information()
            active = [p for p in positions if float(p["positionAmt"]) != 0]
            data.append({
                "name": acc["name"],
                "balance": balance,
                "equity": equity,
                "unrealized": unrealized,
                "positions": len(active)
            })
        except Exception as e:
            data.append({
                "name": acc["name"],
                "error": str(e)
            })
    return {"accounts": data}

def smart_trailing():
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

                current_sl = LAST_STOP_PRICE.get(symbol)

                # Guard: skip jika SL sudah terlalu dekat dengan entry (tidak perlu update)
                if current_sl is not None and abs(current_sl - entry) <= EXCHANGE_CACHE.get(symbol, {}).get("tickSize", 0.0):
                    continue

                move = abs(price - entry)

                # 🎯 BREAK EVEN
                if move > entry * 0.003:
                    new_sl = entry
                    if current_sl is None or abs(current_sl - new_sl) > EXCHANGE_CACHE.get(symbol, {}).get("tickSize", 0.0):
                        update_stop_loss(symbol, side, new_sl)

                # 🎯 TRAILING PROFIT
                if move > entry * 0.006:
                    if side == "BUY":
                        new_sl = price - (move * 0.3)
                    else:
                        new_sl = price + (move * 0.3)

                    if current_sl is None or abs(current_sl - new_sl) > EXCHANGE_CACHE.get(symbol, {}).get("tickSize", 0.0):
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

                    # 5 — RISK SIMPLE
                    balance_info = binance.futures_account_balance()
                    usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
                    balance = float(usdt["balance"]) if usdt else 0
                    risk_amount = balance * 0.01  # 1%
                    stop_distance = abs(signal["entry"] - signal["sl"])
                    qty = round(risk_amount / stop_distance, 3)

                    # 🚀 execute
                    result = place_order_multi(
                        symbol=symbol,
                        side=signal["type"],
                        sl=signal["sl"],
                        tp=signal["tp"]
                    )

                    send_telegram(f"""
🤖 MULTI AUTO TRADE
{symbol} {signal['type']}
{result}
""")
                    print("AUTO EXEC:", result)

                except Exception as e:
                    print("Pair error:", symbol, e)

        except Exception as e:
            print("AUTO LOOP ERROR:", e)

        time.sleep(SCAN_INTERVAL)

_bot_started = False

def start_bot():
    while True:
        try:
            t = threading.Thread(target=auto_trader, daemon=True)
            t.start()
            print("🚀 BOT STARTED")
            while t.is_alive():
                time.sleep(5)
            print("💀 BOT DEAD → RESTARTING...")
        except Exception as e:
            print("WATCHDOG ERROR:", e)
        time.sleep(3)

def start_background_tasks():
    global _bot_started
    if _bot_started:
        return
    _bot_started = True
    if AUTO_MODE:
        load_exchange_cache()
        threading.Thread(target=smart_trailing, daemon=True).start()
        threading.Thread(target=start_bot, daemon=True).start()

@app.on_event("startup")
def on_startup():
    start_background_tasks()