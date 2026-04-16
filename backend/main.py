import os
import time
import threading
import requests
import base64
from dotenv import load_dotenv
from decimal import Decimal, ROUND_DOWN, ROUND_UP

load_dotenv()

# ===== CONFIG & ENV CHECK =====
from config import *

print("🔥 FIREBASE_URL:", os.getenv("FIREBASE_URL"))

# 🔒 SAFETY CHECK (WAJIB DI SINI)
if not BINANCE_API_KEY or not BINANCE_SECRET:
    print("⚠️ BINANCE API NOT SET → BOT DISABLED")

if not BINANCE_SECRET:
    raise Exception("BINANCE_SECRET not set")

if not OPENAI_API_KEY:
    print("⚠️ OPENAI_API_KEY not set (AI disabled)")

def check_env():
    if not BINANCE_API_KEY:
        raise Exception("BINANCE_API_KEY not set")
    if not BINANCE_SECRET:
        raise Exception("BINANCE_SECRET not set")

check_env()

AUTO_MODE = True
AUTO_TRADING = True          # ⭐ NEW: switch on/off via Telegram
SCAN_INTERVAL = 15           # detik
MIN_SCORE = 58
MAX_OPEN_TRADES = 3          # ⭐ NEW: batas maksimum posisi terbuka

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

try:
    import lightgbm as lgb
except Exception:
    lgb = None

from data import get_ticker, get_ohlcv, get_multi_tickers

# ================= INIT =================
app = FastAPI(title="Montra Backend", version="1.0")

@app.get("/ai-memory")
def get_ai_memory():
    return ai_memory

@app.get("/accounts")
def get_accounts():
    return {"accounts": []}

@app.get("/positions")
def get_positions():
    return {"positions": []}

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

# ===== SAFETY =====
KILL_SWITCH = False

START_EQUITY = None
MAX_DRAWDOWN_PCT = 10   # stop kalau -10%

DAILY_START_EQUITY = None
DAILY_LOSS_PCT = 3      # stop kalau -3% harian

LAST_DAY = None

# ===== PERFORMANCE TRACKING =====
daily_loss = 0
consecutive_loss = 0
current_risk = BASE_RISK
MIN_RISK = 0.005
MAX_RISK = 0.03

# ✅ PAIR STATS & DISABLED PAIRS
pair_stats = {}
disabled_pairs = set()

EXCHANGE_CACHE = {}
LAST_STOP_PRICE = {}

# ===== AI MEMORY & FIREBASE =====

FIREBASE_URL = os.getenv("FIREBASE_URL")
print("🔥 FIREBASE_URL:", FIREBASE_URL)

# === RL WEIGHTS ===
rl_weights = {
    "memory": 0.25,
    "winrate": 0.25,
    "regime": 0.2,
    "vol": 0.15,
    "journal": 0.15
}

# === PORTFOLIO ALLOCATION ===
portfolio_alloc = {}  # {symbol: weight 0..1}
position_entry_score = {}  # menyimpan score saat entry untuk RL update

LAST_SIGNAL = None

def clean_url(url):
    if not url:
        return None
    url = url.strip()
    if url.startswith("FIREBASE_URL="):
        url = url.split("=", 1)[1].strip()
    return url.rstrip("/")

def firebase_ready():
    return bool(FIREBASE_URL and FIREBASE_URL.startswith("http"))

ai_memory = {}  # simpan skor tiap simbol
trade_history = []  # journal semua trade

ENABLE_ML = os.getenv("ENABLE_ML", "false").lower() == "true"
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "models/lgbm_model.txt")
FALLBACK_MODE = os.getenv("FALLBACK_MODE", "true").lower() == "true"
ML_MODEL = None

# === NEWS ENGINE ===
NEWS_CACHE = {"last_check": 0, "impact": "LOW"}

def get_market_news():
    global NEWS_CACHE

    # cache 5 menit
    if time.time() - NEWS_CACHE["last_check"] < 300:
        return NEWS_CACHE["impact"]

    try:
        # pakai free API (Forex Factory alternatif simple) - FNG API
        res = requests.get("https://api.alternative.me/fng/").json()
        value = int(res["data"][0]["value"])

        # fear = panic → biasanya reversal (atau extreme greed)
        if value < 25:
            impact = "HIGH"
        elif value > 75:
            impact = "HIGH"
        else:
            impact = "NORMAL"

        NEWS_CACHE = {
            "last_check": time.time(),
            "impact": impact
        }

        return impact

    except:
        return "NORMAL"

def save_ai_memory():
    if not firebase_ready():
        return
    try:
        requests.put(f"{FIREBASE_URL}/ai_memory.json", json=ai_memory, timeout=5)
        print("💾 AI memory saved")
    except Exception as e:
        print("Save error:", e)

def save_portfolio():
    if not firebase_ready():
        return
    try:
        requests.put(f"{FIREBASE_URL}/portfolio.json", json=portfolio_alloc, timeout=5)
    except Exception as e:
        print("Save portfolio error:", e)

def load_ai_memory():
    global ai_memory
    if not firebase_ready():
        print("⚠️ Firebase invalid → fallback mode")
        return
    try:
        res = requests.get(f"{FIREBASE_URL}/ai_memory.json", timeout=5)
        data = res.json()
        if data:
            ai_memory = data
            print("🧠 AI memory loaded")
    except Exception as e:
        print("Load error:", e)

def save_rl_weights():
    if not firebase_ready():
        return
    try:
        requests.put(f"{FIREBASE_URL}/rl_weights.json", json=rl_weights, timeout=5)
        print("⚖️ RL weights saved")
    except Exception as e:
        print("Save RL weights error:", e)

def load_rl_weights():
    global rl_weights
    if not firebase_ready():
        print("⚠️ Firebase invalid → fallback mode")
        return
    try:
        res = requests.get(f"{FIREBASE_URL}/rl_weights.json", timeout=5)
        data = res.json()
        if data:
            rl_weights = data
            print("⚖️ RL weights loaded")
    except Exception as e:
        print("Load RL weights error:", e)

def load_ml_model():
    global ML_MODEL
    if not ENABLE_ML or lgb is None:
        print("⚠️ LightGBM disabled → fallback mode")
        return
    if not os.path.exists(ML_MODEL_PATH):
        print("⚠️ LightGBM model not found → fallback mode")
        return
    try:
        ML_MODEL = lgb.Booster(model_file=ML_MODEL_PATH)
        print("🧠 LightGBM loaded")
    except Exception as e:
        print("Load ML error:", e)

def ml_predict(features):
    if ML_MODEL is None:
        return 0.5
    try:
        p = ML_MODEL.predict([features])[0]
        return float(max(0, min(1, p)))
    except Exception as e:
        print("ML predict error:", e)
        return 0.5

load_ml_model()
load_ai_memory()
load_rl_weights()

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
        if symbol not in PAIRS:
            continue
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
    requests.post(url, json={"chat_id": chat_id, "text": msg})

def cancel_existing_orders(symbol):
    try:
        orders = binance.futures_get_open_orders(symbol=symbol)
        for o in orders:
            if o["type"] in ["STOP_MARKET", "TAKE_PROFIT_MARKET"]:
                try:
                    binance.futures_cancel_order(symbol=symbol, orderId=o["orderId"])
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
        ACCOUNT_PROFIT[name] = 0

def place_order_multi(symbol, side, sl, tp):
    results = []
    for acc in CLIENTS:
        try:
            c = acc["client"]
            base_risk = acc["risk"]
            profit = ACCOUNT_PROFIT.get(acc["name"], 0)
            if acc.get("compound") and profit > 0:
                risk_pct = base_risk + (profit / 1000)
            else:
                risk_pct = base_risk
            balance_info = c.futures_account_balance()
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
            balance = float(usdt["balance"]) if usdt else 0
            alloc = portfolio_alloc.get(symbol, 0.25)
            risk_amount = balance * risk_pct * alloc
            price = float(c.futures_symbol_ticker(symbol=symbol)["price"])
            stop_distance = abs(price - sl)
            if stop_distance == 0:
                continue
            qty = risk_amount / stop_distance
            if qty * price < 100:
                qty = ceil_to_step(100 / price, EXCHANGE_CACHE.get(symbol, {}).get("stepSize", 0.001))
            qty, price = adjust_precision(symbol, qty, price)
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
        buffer = current_price * 0.001
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

# ================= TOTAL EQUITY & SAFETY =================
def get_total_equity():
    total = 0
    for acc in CLIENTS:
        try:
            c = acc["client"]
            balance_info = c.futures_account_balance()
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
            balance = float(usdt["balance"]) if usdt else 0
            unreal = float(usdt["crossUnPnl"]) if usdt else 0
            total += (balance + unreal)
        except:
            pass
    return total

def safety_check():
    global KILL_SWITCH, DAILY_START_EQUITY, LAST_DAY
    now_day = time.strftime("%Y-%m-%d")
    eq = get_total_equity()
    if now_day != LAST_DAY:
        DAILY_START_EQUITY = eq
        LAST_DAY = now_day
        print("🌅 RESET DAILY EQUITY:", eq)
        reset_pairs()
    dd = ((START_EQUITY - eq) / START_EQUITY) * 100
    if dd >= MAX_DRAWDOWN_PCT:
        KILL_SWITCH = True
        send_telegram(f"🛑 MAX DD HIT: {dd:.2f}% → BOT STOP")
        return False
    daily_loss_pct = ((DAILY_START_EQUITY - eq) / DAILY_START_EQUITY) * 100
    if daily_loss_pct >= DAILY_LOSS_PCT:
        KILL_SWITCH = True
        send_telegram(f"🛑 DAILY LOSS HIT: {daily_loss_pct:.2f}% → BOT STOP")
        return False
    return True

def check_telegram_commands():
    global KILL_SWITCH, AUTO_TRADING
    token = os.getenv("TELEGRAM_TOKEN")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        res = requests.get(url).json()
        for u in res.get("result", []):
            text = u.get("message", {}).get("text", "")
            if "/stop" in text:
                KILL_SWITCH = True
                send_telegram("🛑 BOT STOPPED via Telegram")
            if "/start" in text:
                KILL_SWITCH = False
                send_telegram("🚀 BOT RESUMED via Telegram")
            if "/auto_on" in text:
                AUTO_TRADING = True
                send_telegram("🟢 AUTO TRADING ENABLED")
            if "/auto_off" in text:
                AUTO_TRADING = False
                send_telegram("🔴 AUTO TRADING DISABLED")
    except:
        pass

# ================= PERFORMANCE UPDATE =================
def update_risk(result, pnl):
    global daily_loss, consecutive_loss, current_risk
    if result == "LOSS":
        daily_loss += abs(pnl)
        consecutive_loss += 1
    else:
        consecutive_loss = 0
    if daily_loss >= MAX_DAILY_LOSS:
        print("🛑 DAILY LOSS LIMIT HIT")
        return False
    if consecutive_loss >= MAX_CONSECUTIVE_LOSS:
        print("🛑 TOO MANY LOSSES")
        return False
    if consecutive_loss >= 2:
        current_risk = max(MIN_RISK, current_risk * 0.7)
    else:
        current_risk = min(MAX_RISK, current_risk * 1.1)
    return True

# ✅ PAIR TRACKING FUNCTIONS
def update_pair_stats(symbol, result, pnl):
    global pair_stats
    if symbol not in pair_stats:
        pair_stats[symbol] = {"wins": 0, "losses": 0, "pnl": 0}
    stats = pair_stats[symbol]
    if result == "WIN":
        stats["wins"] += 1
    else:
        stats["losses"] += 1
    stats["pnl"] += pnl

    if stats["losses"] >= 3:
        disabled_pairs.add(symbol)
        print(f"🚫 Pair {symbol} disabled after {stats['losses']} losses")

def check_pair_health(symbol):
    stats = pair_stats.get(symbol)
    if not stats:
        return True
    total = stats["wins"] + stats["losses"]
    if total >= 5:
        winrate = stats["wins"] / total
        if winrate < 0.3 or stats["pnl"] < -5:
            print(f"🚫 Disable pair {symbol}")
            disabled_pairs.add(symbol)
            return False
    return True

def reset_pairs():
    global disabled_pairs
    disabled_pairs = set()

def safe_score(mem):
    if isinstance(mem, dict):
        return float(mem.get("score", 50))
    try:
        return float(mem)
    except:
        return 50

# ===== AI MEMORY FUNCTIONS =====
def update_ai_memory(symbol, result):
    global ai_memory
    if symbol not in ai_memory or not isinstance(ai_memory.get(symbol), dict):
        ai_memory[symbol] = {"score": 50, "trades": 0}
    mem = ai_memory[symbol]
    mem["trades"] = mem.get("trades", 0) + 1
    if result == "WIN":
        mem["score"] = mem.get("score", 50) + 5
    else:
        mem["score"] = mem.get("score", 50) - 7
    mem["score"] = max(0, min(100, mem["score"]))
    print(f"🧠 AI Memory updated: {symbol} score={mem['score']} after {result}")
    save_ai_memory()

def ai_allow_trade(symbol):
    mem = ai_memory.get(symbol)
    if not mem:
        return True
    score = safe_score(mem)
    if score < 35:
        print(f"🧠 AI BLOCK {symbol} score={score}")
        return False
    return True

# === HELPER FUNCTIONS ===
def _get_trend(symbol):
    try:
        klines = binance.futures_klines(symbol=symbol, interval="1h", limit=50)
        closes = [float(k[4]) for k in klines]
        if closes[-1] > closes[0]:
            return "BULLISH"
        elif closes[-1] < closes[0]:
            return "BEARISH"
        else:
            return "SIDEWAYS"
    except Exception as e:
        print(f"Error get trend {symbol}: {e}")
        return "UNKNOWN"

def _get_strength(symbol):
    try:
        klines = binance.futures_klines(symbol=symbol, interval="1h", limit=2)
        if len(klines) < 2:
            return 0.0
        prev_close = float(klines[0][4])
        curr_close = float(klines[1][4])
        if prev_close == 0:
            return 0.0
        return ((curr_close - prev_close) / prev_close) * 100.0
    except Exception as e:
        print(f"Error get strength {symbol}: {e}")
        return 0.0

def btc_filter(trend):
    btc_trend = _get_trend("BTCUSDT")
    if btc_trend != trend:
        print(f"🧠 BTC filter block: BTC={btc_trend}, Signal={trend}")
        return False
    return True

def get_regime_tf(symbol, interval):
    try:
        klines = binance.futures_klines(symbol=symbol, interval=interval, limit=50)
        closes = [float(k[4]) for k in klines]
        change = (closes[-1] - closes[0]) / closes[0]
        if abs(change) < 0.004:
            return "SIDEWAYS"
        elif change > 0:
            return "BULL"
        else:
            return "BEAR"
    except Exception as e:
        print(f"Error get_regime_tf {symbol} {interval}: {e}")
        return "SIDEWAYS"

def get_multi_tf_regime(symbol="BTCUSDT"):
    tf_15m = get_regime_tf(symbol, "15m")
    tf_1h  = get_regime_tf(symbol, "1h")
    tf_4h  = get_regime_tf(symbol, "4h")
    if tf_15m == tf_1h == tf_4h:
        return tf_1h
    votes = [tf_15m, tf_1h, tf_4h]
    if votes.count("BULL") >= 2:
        return "BULL"
    if votes.count("BEAR") >= 2:
        return "BEAR"
    return "SIDEWAYS"

def get_volatility(symbol="BTCUSDT"):
    try:
        klines = binance.futures_klines(symbol=symbol, interval="15m", limit=20)
        ranges = []
        for k in klines:
            high = float(k[2])
            low = float(k[3])
            if low == 0:
                continue
            ranges.append((high - low) / low)
        if not ranges:
            return 0.0
        return sum(ranges) / len(ranges)
    except Exception as e:
        print(f"Error get_volatility: {e}")
        return 0.0

def get_dynamic_risk(regime, vol):
    risk = current_risk
    if vol < 0.003:
        risk *= 0.5
    if vol > 0.015:
        risk *= 0.6
    if regime in ["BULL", "BEAR"]:
        risk *= 1.2
    return max(MIN_RISK, min(MAX_RISK, risk))

def build_ml_features(symbol, final_side, regime, vol, news_reverse, fvg_up, fvg_down, sweep_high, sweep_low):
    mem = safe_score(ai_memory.get(symbol, {"score": 50}))
    stats = pair_stats.get(symbol, {"wins": 0, "losses": 0})
    total = stats["wins"] + stats["losses"]
    winrate = (stats["wins"] / total) if total > 0 else 0.5

    return [
        mem / 100.0,
        winrate,
        1.0 if regime == "BULL" else 0.0,
        1.0 if regime == "BEAR" else 0.0,
        float(vol),
        1.0 if final_side == "BUY" else 0.0,
        1.0 if news_reverse else 0.0,
        1.0 if fvg_up else 0.0,
        1.0 if fvg_down else 0.0,
        1.0 if sweep_high else 0.0,
        1.0 if sweep_low else 0.0,
    ]

# === JOURNAL & META SCORE ===
def analyze_journal():
    stats = {}
    for t in trade_history:
        key = (t["symbol"], t["regime"])
        if key not in stats:
            stats[key] = {"win": 0, "loss": 0}
        if t["result"] == "WIN":
            stats[key]["win"] += 1
        else:
            stats[key]["loss"] += 1
    return stats

def meta_score(symbol, signal, regime, vol):
    mem = ai_memory.get(symbol, {"score": 50})
    memory_score = safe_score(mem)

    stats = pair_stats.get(symbol, {"wins": 0, "losses": 0})
    total_trades = stats["wins"] + stats["losses"]
    winrate_score = (stats["wins"] / total_trades * 100) if total_trades > 0 else 50

    if regime == "BULL" and signal["type"] == "BUY":
        regime_score = 80
    elif regime == "BEAR" and signal["type"] == "SELL":
        regime_score = 80
    else:
        regime_score = 30

    vol_score = 80 if 0.003 < vol < 0.015 else 40

    journal_stats = analyze_journal()
    j = journal_stats.get((symbol, regime))
    if j:
        t = j["win"] + j["loss"]
        journal_score = (j["win"] / t * 100) if t > 0 else 50
    else:
        journal_score = 50

    score = (
        memory_score * rl_weights["memory"] +
        winrate_score * rl_weights["winrate"] +
        regime_score * rl_weights["regime"] +
        vol_score * rl_weights["vol"] +
        journal_score * rl_weights["journal"]
    )
    return max(0, min(100, score))

# === RL WEIGHTS UPDATE ===
def update_rl_weights(result, score):
    global rl_weights
    adjust = 0.02 if result == "WIN" else -0.02
    for k in rl_weights:
        rl_weights[k] += adjust
    total = sum(rl_weights.values())
    for k in rl_weights:
        rl_weights[k] /= total
    print(f"⚖️ RL weights updated: {rl_weights}")
    save_rl_weights()

# === PORTFOLIO ALLOCATION ===
def update_portfolio_allocation():
    global portfolio_alloc

    scores = {}
    total = 0

    for sym, mem in ai_memory.items():
        if isinstance(mem, dict):
            score = mem.get("score", 50)
        else:
            try:
                score = float(mem)
            except:
                score = 50

        scores[sym] = max(score, 1)
        total += scores[sym]

    if total == 0:
        portfolio_alloc = {}
        return

    for sym in scores:
        portfolio_alloc[sym] = scores[sym] / total

    print("📊 PORTFOLIO:", portfolio_alloc)
    save_portfolio()

def get_open_positions():
    try:
        positions = binance.futures_position_information()
        return [p for p in positions if float(p["positionAmt"]) != 0]
    except Exception as e:
        print("Error get_open_positions:", e)
        return []

# ⭐ NEW: centralized decision
def should_execute_trade(signal):
    score = signal.get("score", 0)
    symbol = signal.get("symbol")

    if KILL_SWITCH:
        return False, "KILL_SWITCH"

    if not AUTO_TRADING:
        return False, "AUTO_OFF"

    if symbol in disabled_pairs:
        return False, "DISABLED_PAIR"

    if not ai_allow_trade(symbol):
        return False, "AI_BLOCK"

    if score < MIN_SCORE:
        return False, "LOW_SCORE"

    if len(get_open_positions()) >= MAX_OPEN_TRADES:
        return False, "MAX_POSITION"

    strategy = get_strategy(symbol)
    if strategy == "DEFENSIVE" and score < 75:
        return False, "DEFENSIVE_SKIP"

    return True, "OK"

def get_strategy(symbol):
    mem = ai_memory.get(symbol, {})
    score = safe_score(mem)

    if score >= 60:
        return "AGGRESSIVE"
    elif score >= 50:
        return "BALANCED"
    return "DEFENSIVE"

def scale_in(symbol, side, sl, tp):
    print("➕ SCALE IN", symbol)
    place_order_multi(symbol, side, sl, tp)
    send_telegram(f"➕ SCALE IN {symbol} {side}")

# ===== MONITOR POSISI =====
last_position_state = {}
last_regime = None
last_vol = None

def monitor_positions_for_memory_update():
    global last_position_state, last_regime, last_vol
    while True:
        try:
            try:
                current_regime = get_multi_tf_regime("BTCUSDT")
                current_vol = get_volatility("BTCUSDT")
                last_regime = current_regime
                last_vol = current_vol
            except:
                pass

            positions = binance.futures_position_information()
            current_state = {}
            for p in positions:
                amt = float(p["positionAmt"])
                if amt != 0:
                    symbol = p["symbol"]
                    side = "BUY" if amt > 0 else "SELL"
                    current_state[symbol] = {
                        "side": side,
                        "size": abs(amt),
                        "entry": float(p["entryPrice"]),
                        "unrealized": float(p["unRealizedProfit"]),
                        "leverage": float(p["leverage"])
                    }

            for symbol, last in last_position_state.items():
                if symbol not in current_state:
                    pnl = last.get("unrealized", 0.0)
                    result = "WIN" if pnl > 0 else "LOSS"
                    print(f"📊 Position closed: {symbol} PnL={pnl:.2f} {result}")

                    update_pair_stats(symbol, result, pnl)
                    update_risk(result, pnl)
                    update_ai_memory(symbol, result)

                    entry_score = position_entry_score.pop(symbol, 50)
                    update_rl_weights(result, entry_score)

                    trade_history.append({
                        "symbol": symbol,
                        "result": result,
                        "pnl": pnl,
                        "regime": last_regime if last_regime else "UNKNOWN",
                        "vol": last_vol if last_vol else 0.0,
                        "score": entry_score
                    })
                    print(f"📝 Journal updated: {symbol} {result}")

                    send_telegram(f"✅ Trade closed: {symbol} {result} PnL=${pnl:.2f}")

            last_position_state = current_state

        except Exception as e:
            print("Monitor position error:", e)

        time.sleep(10)

# ================= BASIC ENDPOINTS =================
@app.get("/")
def root():
    return {"status": "MONTRA backend running 🚀"}

@app.get("/home")
def home():
    return {"message": "MONTRA BACKEND RUNNING 🔥"}

@app.get("/trend/{symbol}")
def get_trend(symbol: str):
    trend = _get_trend(symbol)
    return {"symbol": symbol, "trend": trend}

@app.get("/symbols")
def symbols():
    return {"symbols": PAIRS}

@app.get("/ticker/{symbol}")
def ticker(symbol: str):
    try:
        return get_ticker(symbol)
    except Exception as e:
        return {"error": str(e)}

@app.get("/ohlcv/{symbol}")
def ohlcv(symbol: str, timeframe: str = Query(default="15m"), limit: int = Query(default=100, ge=1, le=1000)):
    try:
        return {"symbol": symbol, "timeframe": timeframe, "limit": limit, "data": get_ohlcv(symbol, timeframe=timeframe, limit=limit)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/tickers")
def tickers(symbols: str = Query(default=",".join(PAIRS))):
    try:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        return {"data": get_multi_tickers(symbol_list)}
    except Exception as e:
        return {"error": str(e)}

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
        return {"result": res.choices[0].message.content.strip()}
    except Exception as e:
        return {"result": "NO TRADE\nConfidence: 0%", "error": str(e)}

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
        files = {"photo": ("chart.png", img_data)}
        data = {"chat_id": chat_id, "caption": text}
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
        balance_info = binance.futures_account_balance()
        usdt_balance = next((b for b in balance_info if b["asset"] == "USDT"), None)
        balance = float(usdt_balance["balance"]) if usdt_balance else 0
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

@app.get("/position-detail/{symbol}")
def position_detail(symbol: str):
    try:
        positions = binance.futures_position_information(symbol=symbol)
        trades = binance.futures_account_trades(symbol=symbol)
        pos = next((p for p in positions if float(p["positionAmt"]) != 0), None)
        return {"position": pos, "trades": trades[-50:]}
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
            data.append({"name": acc["name"], "error": str(e)})
    return {"accounts": data}

@app.post("/kill-switch")
def kill_switch(payload: dict = Body(...)):
    global KILL_SWITCH
    state = payload.get("state", True)
    KILL_SWITCH = state
    return {"kill_switch": KILL_SWITCH}

@app.get("/ai-memory")
def get_ai_memory():
    return ai_memory

# ⭐ NEW: signal receiver endpoint
@app.post("/signal")
def receive_signal(signal: dict):
    global LAST_SIGNAL
    LAST_SIGNAL = signal
    ok, reason = should_execute_trade(signal)
    if ok:
        def execute():
            place_order_multi(
                signal["symbol"],
                signal["type"],
                signal["sl"],
                signal["tp"]
            )
            position_entry_score[signal["symbol"]] = signal.get("score", 0)
            send_telegram(f"""
🚀 SIGNAL TRADE
{signal['symbol']} {signal['type']}
Score: {signal.get('score', 0)}
""")
        threading.Thread(target=execute, daemon=True).start()
        return {"status": "executed", "reason": reason}
    else:
        return {"status": "rejected", "reason": reason}

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
                if current_sl is not None and abs(current_sl - entry) <= EXCHANGE_CACHE.get(symbol, {}).get("tickSize", 0.0):
                    continue
                move = abs(price - entry)
                if move > entry * 0.003:
                    new_sl = entry
                    if current_sl is None or abs(current_sl - new_sl) > EXCHANGE_CACHE.get(symbol, {}).get("tickSize", 0.0):
                        update_stop_loss(symbol, side, new_sl)
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

def apply_news_bias(signal_type, news_reverse):
    if news_reverse:
        return "SELL" if signal_type == "BUY" else "BUY"
    return signal_type

def auto_trader():
    while True:
        try:
            check_telegram_commands()
            if KILL_SWITCH:
                print("🛑 KILL SWITCH ACTIVE")
                time.sleep(5)
                continue
            if not safety_check():
                time.sleep(10)
                continue
            if not AUTO_MODE:
                time.sleep(SCAN_INTERVAL)
                continue
            if not AUTO_TRADING:
                print("⏸️ AUTO TRADING DISABLED")
                time.sleep(SCAN_INTERVAL)
                continue
            if daily_loss >= MAX_DAILY_LOSS:
                print("🚫 Skip trade: daily loss limit")
                time.sleep(SCAN_INTERVAL)
                continue

            # 🔥 DEBUG: tampilkan isi ai_memory mentah
            print("AI MEMORY RAW:", ai_memory)

            # 🔥 NEW: perbarui alokasi portofolio berdasarkan AI memory
            update_portfolio_allocation()

            regime = get_multi_tf_regime("BTCUSDT")
            vol = get_volatility("BTCUSDT")
            print(f"🧠 MTF REGIME: {regime}")
            print(f"🌊 VOL: {vol:.4f}")

            # === VOL SPIKE DETECTION ===
            if vol > 0.015:
                print("⚠️ VOL SPIKE → MARKET CHAOS")

            # === NEWS FILTER ===
            news_impact = get_market_news()
            print(f"📰 NEWS IMPACT: {news_impact}")

            # === NEWS STATE ===
            news_reverse = (news_impact == "HIGH")
            if news_reverse:
                print("📰 HIGH IMPACT NEWS → SMC tetap jalan, arah akan di-reverse")

            if vol < 0.0015:
                print("⏸️ Skip: low volatility")
                time.sleep(SCAN_INTERVAL)
                continue
            if vol > 0.03:
                print("⚠️ Skip: high volatility")
                time.sleep(SCAN_INTERVAL)
                continue

            pairs = PAIRS.copy()
            scores_map = {}

            # --- Kumpulkan skor untuk semua pair ---
            for symbol in pairs:
                try:
                    if symbol in disabled_pairs:
                        continue
                    if not check_pair_health(symbol):
                        continue
                    if not ai_allow_trade(symbol):
                        continue

                    ohlcv = binance.futures_klines(symbol=symbol, interval="15m", limit=100)
                    closes = [float(c[4]) for c in ohlcv]
                    last_price = closes[-1]

                    # === STRUCTURE LOGIC ===
                    highs = [float(c[2]) for c in ohlcv]
                    lows = [float(c[3]) for c in ohlcv]

                    hh = highs[-1] > highs[-5]
                    ll = lows[-1] < lows[-5]

                    # === FVG DETECTION ===
                    fvg_up = False
                    fvg_down = False

                    if len(ohlcv) >= 3:
                        c1 = ohlcv[-3]
                        c2 = ohlcv[-2]
                        c3 = ohlcv[-1]

                        if float(c1[2]) < float(c3[3]):
                            fvg_up = True
                        if float(c1[3]) > float(c3[2]):
                            fvg_down = True

                    if hh and fvg_up:
                        signal_type = "BUY"
                    elif ll and fvg_down:
                        signal_type = "SELL"
                    else:
                        continue  # skip kalau no structure

                    # === FILTER FAKE MOVE (liquidity sweep) ===
                    last_candle = ohlcv[-1]
                    prev_candle = ohlcv[-2]

                    wick_up = float(last_candle[2]) - max(float(last_candle[1]), float(last_candle[4]))
                    wick_down = min(float(last_candle[1]), float(last_candle[4])) - float(last_candle[3])

                    if wick_up > wick_down * 2 and signal_type == "BUY":
                        continue
                    if wick_down > wick_up * 2 and signal_type == "SELL":
                        continue

                    # === LIQUIDITY SWEEP CHECK ===
                    recent_high = max(highs[-11:-1])
                    recent_low = min(lows[-11:-1])

                    sweep_high = highs[-1] > recent_high
                    sweep_low = lows[-1] < recent_low

                    if signal_type == "BUY" and not sweep_low:
                        continue
                    if signal_type == "SELL" and not sweep_high:
                        continue

                    # === BUY RUMOR / SELL NEWS ===
                    # [!] LOGIC FIX: Posisi dipindah ke sini agar SL dan TP dihitung dengan arah yang sudah di-reverse
                    # news impact dipakai lewat apply_news_bias() saja, jangan reverse dua kali

                    # === ENTRY, SL, TP ===
                    ob_candle = ohlcv[-4]

                    final_side = apply_news_bias(signal_type, news_reverse)
                    
                    if final_side == "BUY":
                        sl = float(ob_candle[3])  # low OB
                        tp = last_price + (last_price - sl) * 2
                    else:
                        sl = float(ob_candle[2])  # high OB
                        tp = last_price - (sl - last_price) * 2
                    
                    signal = {
                        "symbol": symbol,
                        "type": final_side,
                        "entry": last_price,
                        "sl": sl,
                        "tp": tp,
                        "score": 85
                    }

                    score = meta_score(symbol, signal, regime, vol)
                    
                    ml_prob = ml_predict(build_ml_features(
                        symbol, final_side, regime, vol, news_reverse, fvg_up, fvg_down, sweep_high, sweep_low
                    ))
                    score = round((score * 0.8) + (ml_prob * 100 * 0.2))
                                                          
                    if news_reverse:
                        score -= 10

                    # === SMC BOOST ===
                    if fvg_up or fvg_down:
                        score += 5
                    if sweep_high or sweep_low:
                        score += 5

                    # === NEWS FACTOR ===
                    if news_impact == "HIGH":
                        score -= 10
                    elif news_impact == "NORMAL":
                        score += 8

                    score = min(score, 100)
                    scores_map[symbol] = score

                except Exception as e:
                    print(f"Scoring error {symbol}: {e}")

            # --- Eksekusi trade dengan decision engine ---
            for symbol in pairs:
                try:
                    if symbol in disabled_pairs:
                        continue
                    if not check_pair_health(symbol):
                        continue
                    if not ai_allow_trade(symbol):
                        continue

                    w = portfolio_alloc.get(symbol, 0)
                    if w <= 0:
                        continue

                    ohlcv = binance.futures_klines(symbol=symbol, interval="15m", limit=100)
                    closes = [float(c[4]) for c in ohlcv]
                    last_price = closes[-1]

                    # === STRUCTURE LOGIC ===
                    highs = [float(c[2]) for c in ohlcv]
                    lows = [float(c[3]) for c in ohlcv]

                    hh = highs[-1] > highs[-5]
                    ll = lows[-1] < lows[-5]

                    # === FVG DETECTION ===
                    fvg_up = False
                    fvg_down = False

                    if len(ohlcv) >= 3:
                        c1 = ohlcv[-3]
                        c2 = ohlcv[-2]
                        c3 = ohlcv[-1]

                        if float(c1[2]) < float(c3[3]):
                            fvg_up = True
                        if float(c1[3]) > float(c3[2]):
                            fvg_down = True

                    if hh and fvg_up:
                        signal_type = "BUY"
                    elif ll and fvg_down:
                        signal_type = "SELL"
                    else:
                        continue  # skip kalau no structure

                    # === FILTER FAKE MOVE (liquidity sweep) ===
                    last_candle = ohlcv[-1]
                    prev_candle = ohlcv[-2]

                    wick_up = float(last_candle[2]) - max(float(last_candle[1]), float(last_candle[4]))
                    wick_down = min(float(last_candle[1]), float(last_candle[4])) - float(last_candle[3])

                    if wick_up > wick_down * 2 and signal_type == "BUY":
                        continue
                    if wick_down > wick_up * 2 and signal_type == "SELL":
                        continue

                    # === LIQUIDITY SWEEP CHECK ===
                    recent_high = max(highs[-11:-1])
                    recent_low = min(lows[-11:-1])

                    sweep_high = highs[-1] > recent_high
                    sweep_low = lows[-1] < recent_low

                    if signal_type == "BUY" and not sweep_low:
                        continue
                    if signal_type == "SELL" and not sweep_high:
                        continue

                    # === BUY RUMOR / SELL NEWS ===
                    # [!] LOGIC FIX: Posisi dipindah ke sini agar SL dan TP dihitung dengan arah yang sudah di-reverse
                    # news impact dipakai lewat apply_news_bias() saja, jangan reversal dua kali

                    # === ENTRY, SL, TP ===
                    ob_candle = ohlcv[-4]

                    final_side = apply_news_bias(signal_type, news_reverse)
                    
                    if final_side == "BUY":
                        sl = float(ob_candle[3])  # low OB
                        tp = last_price + (last_price - sl) * 2
                    else:
                        sl = float(ob_candle[2])  # high OB
                        tp = last_price - (sl - last_price) * 2
                    
                    signal = {
                        "symbol": symbol,
                        "type": final_side,
                        "entry": last_price,
                        "sl": sl,
                        "tp": tp,
                        "score": scores_map.get(symbol, 0)
                    }

                    ml_prob = ml_predict(build_ml_features(
                        symbol, final_side, regime, vol, news_reverse, fvg_up, fvg_down, sweep_high, sweep_low
                    ))
                    score = round((scores_map.get(symbol, 0) * 0.8) + (ml_prob * 100 * 0.2))
                    signal["score"] = score
                    
                    ok, reason = should_execute_trade(signal)
                    if not ok:
                        print(f"❌ SKIP {symbol} - {reason}")
                        continue

                    # Filter tambahan (regime, btc, strength)
                    if regime == "SIDEWAYS":
                        print(f"⏸️ Skip {symbol}: market SIDEWAYS")
                        continue
                    if regime == "BULL" and signal["type"] != "BUY":
                        print(f"⏸️ Skip {symbol}: BULL market but signal SELL")
                        continue
                    if regime == "BEAR" and signal["type"] != "SELL":
                        print(f"⏸️ Skip {symbol}: BEAR market but signal BUY")
                        continue

                    signal_trend = "BULLISH" if signal["type"] == "BUY" else "BEARISH"
                    if not btc_filter(signal_trend):
                        continue

                    btc_strength = _get_strength("BTCUSDT")
                    alt_strength = _get_strength(symbol)
                    if abs(btc_strength - alt_strength) > 20.0:
                        print(f"🧠 Strength divergence block: BTC {btc_strength:.2f}% vs {symbol} {alt_strength:.2f}%")
                        continue

                    positions = get_open_positions()
                    if len(positions) >= MAX_OPEN_TRADES:
                        print(f"❌ SKIP {symbol} - MAX_POSITION")
                        continue
                    if any(p["symbol"] == symbol for p in positions):
                        continue

                    dynamic_risk = get_dynamic_risk(regime, vol)
                    balance_info = binance.futures_account_balance()
                    usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
                    balance = float(usdt["balance"]) if usdt else 0
                    risk_amount = balance * dynamic_risk * w

                    stop_distance = abs(signal["entry"] - signal["sl"])
                    qty = round(risk_amount / stop_distance, 3)

                    result = place_order_multi(
                        symbol=symbol,
                        side=signal["type"],
                        sl=signal["sl"],
                        tp=signal["tp"]
                    )

                    position_entry_score[symbol] = signal["score"]

                    send_telegram(f"""
🤖 MULTI AUTO TRADE
{symbol} {signal['type']}
Score: {signal['score']:.1f} | Weight: {w:.2f}
{result}
""")
                    print("AUTO EXEC:", result)

                    if signal["score"] >= 90:
                        scale_in(symbol, signal["type"], signal["sl"], signal["tp"])

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
    global _bot_started, START_EQUITY, DAILY_START_EQUITY, LAST_DAY
    if _bot_started:
        return
    _bot_started = True
    if AUTO_MODE:
        load_exchange_cache()
        eq = get_total_equity()
        START_EQUITY = eq
        DAILY_START_EQUITY = eq
        LAST_DAY = time.strftime("%Y-%m-%d")
        print("🧠 START EQUITY:", eq)
        threading.Thread(target=smart_trailing, daemon=True).start()
        threading.Thread(target=monitor_positions_for_memory_update, daemon=True).start()
        threading.Thread(target=start_bot, daemon=True).start()

@app.on_event("startup")
def on_startup():
    start_background_tasks()