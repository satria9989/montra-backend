import os
import time
import threading
import requests
import base64
import json
from dotenv import load_dotenv
from decimal import Decimal, ROUND_DOWN, ROUND_UP

load_dotenv()

# ===== CONFIG & ENV CHECK =====
# ===== CONFIG & ENV CHECK =====
from config import *

print("🔥 FIREBASE_URL:", os.getenv("FIREBASE_URL"))

# 🔒 SAFE STARTUP CHECK
if not BINANCE_API_KEY or not BINANCE_SECRET:
    print("⚠️ BINANCE API NOT SET → trading client disabled")

if not OPENAI_API_KEY:
    print("⚠️ OPENAI_API_KEY not set (AI disabled)")

def check_env():
    mode = globals().get("MONTRA_MODE", "api_only")
    if mode == "live":
        if not BINANCE_API_KEY:
            raise Exception("BINANCE_API_KEY not set in LIVE mode")
        if not BINANCE_SECRET:
            raise Exception("BINANCE_SECRET not set in LIVE mode")

check_env()

AUTO_MODE = os.getenv("AUTO_MODE", "true").lower() == "true"
AUTO_TRADING = os.getenv("AUTO_TRADING", "true").lower() == "true"

# ===== PROFILE / HARDENING =====
MONTRA_PROFILE = os.getenv("MONTRA_PROFILE", "final_lock").lower()
VALIDATION_MODE = os.getenv(
    "VALIDATION_MODE",
    "true" if MONTRA_PROFILE in ("validation", "sample_hunt") else "false"
).lower() == "true"

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10" if VALIDATION_MODE else "15"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "46" if VALIDATION_MODE else "62"))

# safety core tetap dijaga, tapi live-safe lebih ketat
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "2" if VALIDATION_MODE else "1"))
GLOBAL_SYMBOL_LOCK = set()
SYMBOL_COOLDOWN = {}
ORDER_AUDIT_LOG = []
EXECUTION_IN_PROGRESS = set()
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "180" if VALIDATION_MODE else "900"))
MAX_AUDIT_LOG = 500

# websocket safety
WS_MAX_AGE = int(os.getenv("WS_MAX_AGE", "20"))
WS_STALE_THRESHOLD = int(os.getenv("WS_STALE_THRESHOLD", "5"))
WS_RESTART_COOLDOWN = int(os.getenv("WS_RESTART_COOLDOWN", "30"))
LAST_WS_HEAL = 0

STATE_FILE = os.getenv("STATE_FILE", "runtime_state.json")

# ===== VALIDATION / LIVE GATES =====
VALIDATION_RR_MIN = float(os.getenv("VALIDATION_RR_MIN", "1.8"))
LIVE_RR_MIN = float(os.getenv("LIVE_RR_MIN", "3.0"))
VALIDATION_TARGET_RR = float(os.getenv("VALIDATION_TARGET_RR", "2.0"))
LIVE_TARGET_RR = float(os.getenv("LIVE_TARGET_RR", "3.0"))

VALIDATION_VOL_MIN = float(os.getenv("VALIDATION_VOL_MIN", "0.0004"))
VALIDATION_VOL_MAX = float(os.getenv("VALIDATION_VOL_MAX", "0.07"))

LIVE_VOL_MIN = float(os.getenv("LIVE_VOL_MIN", "0.0015"))
LIVE_VOL_MAX = float(os.getenv("LIVE_VOL_MAX", "0.03"))

VALIDATION_SESSION_ALLOW_ASIA = os.getenv("VALIDATION_SESSION_ALLOW_ASIA", "true").lower() == "true"
VALIDATION_NEWS_BLOCK = os.getenv("VALIDATION_NEWS_BLOCK", "false").lower() == "true"
VALIDATION_REQUIRE_SWEEP = os.getenv("VALIDATION_REQUIRE_SWEEP", "false").lower() == "true"
VALIDATION_REQUIRE_PAIR_REGIME_MATCH = os.getenv("VALIDATION_REQUIRE_PAIR_REGIME_MATCH", "false").lower() == "true"
VALIDATION_ALLOW_SIDEWAYS_SCORE_PENALTY = os.getenv("VALIDATION_ALLOW_SIDEWAYS_SCORE_PENALTY", "true").lower() == "true"

LIVE_NEWS_BLOCK = os.getenv("LIVE_NEWS_BLOCK", "true").lower() == "true"
LIVE_NEWS_REVERSE = os.getenv("LIVE_NEWS_REVERSE", "false").lower() == "true"
LIVE_REQUIRE_SWEEP = os.getenv("LIVE_REQUIRE_SWEEP", "true").lower() == "true"
LIVE_REQUIRE_PAIR_REGIME_MATCH = os.getenv("LIVE_REQUIRE_PAIR_REGIME_MATCH", "true").lower() == "true"
LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY = os.getenv("LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY", "false").lower() == "true"

# ===== STRUCTURE ENGINE V3 =====
STRUCTURE_SWING_LOOKBACK = int(os.getenv("STRUCTURE_SWING_LOOKBACK", "14"))
STRUCTURE_FVG_LOOKBACK = int(os.getenv("STRUCTURE_FVG_LOOKBACK", "8"))
STRUCTURE_RECLAIM_TOLERANCE = float(os.getenv("STRUCTURE_RECLAIM_TOLERANCE", "0.0018"))
STRUCTURE_MIN_BODY_RATIO = float(os.getenv("STRUCTURE_MIN_BODY_RATIO", "0.14"))
STRUCTURE_RECENT_WINDOW = int(os.getenv("STRUCTURE_RECENT_WINDOW", "3"))
STRUCTURE_ZONE_TOLERANCE = float(os.getenv("STRUCTURE_ZONE_TOLERANCE", "0.0018"))
STRUCTURE_STRONG_SCORE_BONUS = int(os.getenv("STRUCTURE_STRONG_SCORE_BONUS", "6"))
STRUCTURE_MEDIUM_SCORE_PENALTY = int(os.getenv("STRUCTURE_MEDIUM_SCORE_PENALTY", "2"))

# ===== EXECUTION / NOTIONAL QUALITY =====
TOP_MIN_TRADE_NOTIONAL = float(os.getenv("TOP_MIN_TRADE_NOTIONAL", "150"))
MID_MIN_TRADE_NOTIONAL = float(os.getenv("MID_MIN_TRADE_NOTIONAL", "120"))
LOW_MIN_TRADE_NOTIONAL = float(os.getenv("LOW_MIN_TRADE_NOTIONAL", "100"))
DEFAULT_MIN_TRADE_NOTIONAL = float(os.getenv("DEFAULT_MIN_TRADE_NOTIONAL", "120"))

# ===== PAIR PRIORITY ENGINE =====
# Tier sekarang diambil dari config.py agar universe scan dan tiering tidak saling
# bertentangan. Kalau config lama belum punya variabel ini, fallback lama tetap aman.
TOP_PAIRS = globals().get("TOP_PAIRS", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"])
MID_PAIRS = globals().get("MID_PAIRS", ["ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "BCHUSDT", "DOGEUSDT", "TRXUSDT", "ATOMUSDT", "TONUSDT"])
VALIDATION_ONLY = globals().get("VALIDATION_ONLY", [])
REMOVE_FROM_CORE = globals().get("REMOVE_FROM_CORE", [])

# PAIRS dari config tetap jadi source of truth universe scan.
# REMOVE_FROM_CORE diproteksi ulang di sini bila config masih membawa pair tersebut.
PAIRS = [p for p in PAIRS if p not in REMOVE_FROM_CORE]
LOW_PAIRS = [p for p in PAIRS if p not in TOP_PAIRS and p not in MID_PAIRS]

TOP_PAIR_LIMIT = int(os.getenv("TOP_PAIR_LIMIT", "3" if VALIDATION_MODE else "2"))
MID_PAIR_LIMIT = int(os.getenv("MID_PAIR_LIMIT", "2" if VALIDATION_MODE else "1"))
LOW_PAIR_LIMIT = int(os.getenv("LOW_PAIR_LIMIT", "1" if VALIDATION_MODE else "0"))

ACCOUNTS = [
    {
        "name": "MAIN",
        "api_key": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "risk": 0.003,
        "compound": True,
        "withdraw_threshold": 50,   # $ profit
        "withdraw_ratio": 0.3       # 30% ditarik
    },
    {
        "name": "SECOND",
        "api_key": os.getenv("BINANCE_API_KEY_2"),
        "secret": os.getenv("BINANCE_SECRET_2"),
        "risk": 0.005,
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
from ws_feed import (
    start_ws,
    get_live_candle,
    get_live_mark,
    get_live_age,
    get_ws_status,
    count_stale_symbols,
    restart_ws,
    is_ws_running,
)

# ================= INIT =================
app = FastAPI(title="Montra Backend", version="1.0")

@app.get("/health/live")
def health_live():
    return {"status": "ok", "mode": MONTRA_MODE}

@app.get("/health/ready")
def health_ready():
    return {
        "status": "ready",
        "mode": MONTRA_MODE,
        "binance": binance is not None,
        "openai": client is not None,
        "accounts": len(CLIENTS),
    }

@app.get("/debug/bootstrap/ai-memory")
def get_ai_memory_bootstrap():
    return ai_memory

@app.get("/debug/bootstrap/accounts")
def get_accounts_bootstrap():
    return {"accounts": []}

@app.get("/debug/bootstrap/positions")
def get_positions_bootstrap():
    try:
        return {"positions": build_live_position_rows()[:10]}
    except Exception:
        return {"positions": []}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 OPENAI CLIENT
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

BINANCE_RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))
BINANCE_TIME_SYNC_INTERVAL = int(os.getenv("BINANCE_TIME_SYNC_INTERVAL", "900"))
BINANCE_MAX_TIME_RETRIES = int(os.getenv("BINANCE_MAX_TIME_RETRIES", "1"))
BINANCE_RATE_LIMIT_RETRIES = int(os.getenv("BINANCE_RATE_LIMIT_RETRIES", "1"))
POSITION_CACHE_TTL = float(os.getenv("POSITION_CACHE_TTL", "8"))
POSITION_MONITOR_INTERVAL = float(os.getenv("POSITION_MONITOR_INTERVAL", "15"))
TRAILING_LOOP_INTERVAL = float(os.getenv("TRAILING_LOOP_INTERVAL", "10"))
POSITION_RATE_LIMIT_SLEEP = float(os.getenv("POSITION_RATE_LIMIT_SLEEP", "20"))
MARKET_KLINES_CACHE_TTL_15M = float(os.getenv("MARKET_KLINES_CACHE_TTL_15M", "20"))
MARKET_KLINES_CACHE_TTL_1H = float(os.getenv("MARKET_KLINES_CACHE_TTL_1H", "120"))
MARKET_KLINES_CACHE_TTL_4H = float(os.getenv("MARKET_KLINES_CACHE_TTL_4H", "300"))
WS_DEGRADED_MODE_ALLOW = os.getenv("WS_DEGRADED_MODE_ALLOW", "true").lower() == "true"
WS_DEGRADED_GRACE_SECONDS = float(os.getenv("WS_DEGRADED_GRACE_SECONDS", "120"))
WS_FULL_STALE_BLOCK_SECONDS = float(os.getenv("WS_FULL_STALE_BLOCK_SECONDS", "600"))
MAX_TRADE_HISTORY = int(os.getenv("MAX_TRADE_HISTORY", "1000"))
CLOSE_REALIZED_LOOKBACK_MINUTES = int(os.getenv("CLOSE_REALIZED_LOOKBACK_MINUTES", "180"))

LAST_MAIN_POSITIONS = []
LAST_MAIN_POSITIONS_TS = 0.0
LAST_MAIN_POSITIONS_ERROR = None
LAST_MAIN_POSITIONS_ERROR_TS = 0.0
POSITIONS_CACHE_LOCK = threading.Lock()
LAST_MAIN_OPEN_ORDERS = []
LAST_MAIN_OPEN_ORDERS_TS = 0.0
OPEN_ORDERS_CACHE_LOCK = threading.Lock()

LAST_ACCOUNTS_SUMMARY = []
LAST_ACCOUNTS_SUMMARY_TS = 0.0
ACCOUNTS_CACHE_LOCK = threading.Lock()

MARKET_KLINES_CACHE = {}
MARKET_KLINES_CACHE_LOCK = threading.Lock()
LAST_WS_GOOD_TS = 0.0


def is_rate_limit_error(exc):
    msg = str(exc)
    return "-1003" in msg or "Too many requests" in msg

def get_cached_main_positions(max_age=None):
    if max_age is None:
        max_age = POSITION_CACHE_TTL
    with POSITIONS_CACHE_LOCK:
        age = time.time() - LAST_MAIN_POSITIONS_TS
        if LAST_MAIN_POSITIONS_TS and age <= max_age:
            return [dict(p) for p in LAST_MAIN_POSITIONS]
    return None

def set_cached_main_positions(positions, error=None):
    global LAST_MAIN_POSITIONS, LAST_MAIN_POSITIONS_TS, LAST_MAIN_POSITIONS_ERROR, LAST_MAIN_POSITIONS_ERROR_TS
    with POSITIONS_CACHE_LOCK:
        LAST_MAIN_POSITIONS = [dict(p) for p in (positions or [])]
        LAST_MAIN_POSITIONS_TS = time.time()
        LAST_MAIN_POSITIONS_ERROR = error
        LAST_MAIN_POSITIONS_ERROR_TS = time.time() if error else 0.0


def invalidate_main_positions_cache():
    global LAST_MAIN_POSITIONS_TS
    with POSITIONS_CACHE_LOCK:
        LAST_MAIN_POSITIONS_TS = 0.0


def fetch_main_positions(force=False, max_age=None, label="MAIN"):
    if binance is None:
        return []

    cached = None if force else get_cached_main_positions(max_age=max_age)
    if cached is not None:
        return cached

    try:
        positions = signed_call(binance, binance.futures_position_information, label=label)
        set_cached_main_positions(positions)
        return positions
    except Exception as e:
        if is_rate_limit_error(e):
            cached = get_cached_main_positions(max_age=60)
            if cached is not None:
                print(f"⚠️ {label} using cached positions after rate limit")
                return cached
        raise


def get_cached_main_open_orders(max_age=None):
    if max_age is None:
        max_age = POSITION_CACHE_TTL
    with OPEN_ORDERS_CACHE_LOCK:
        age = time.time() - LAST_MAIN_OPEN_ORDERS_TS
        if LAST_MAIN_OPEN_ORDERS_TS and age <= max_age:
            return [dict(o) for o in LAST_MAIN_OPEN_ORDERS]
    return None


def set_cached_main_open_orders(orders):
    global LAST_MAIN_OPEN_ORDERS, LAST_MAIN_OPEN_ORDERS_TS
    with OPEN_ORDERS_CACHE_LOCK:
        LAST_MAIN_OPEN_ORDERS = [dict(o) for o in (orders or [])]
        LAST_MAIN_OPEN_ORDERS_TS = time.time()


def invalidate_main_open_orders_cache():
    global LAST_MAIN_OPEN_ORDERS_TS
    with OPEN_ORDERS_CACHE_LOCK:
        LAST_MAIN_OPEN_ORDERS_TS = 0.0


def fetch_main_open_orders(force=False, max_age=None, label="MAIN"):
    if binance is None:
        return []

    cached = None if force else get_cached_main_open_orders(max_age=max_age)
    if cached is not None:
        return cached

    try:
        orders = signed_call(binance, binance.futures_get_open_orders, label=label)
        set_cached_main_open_orders(orders)
        return orders
    except Exception as e:
        if is_rate_limit_error(e):
            cached = get_cached_main_open_orders(max_age=60)
            if cached is not None:
                print(f"⚠️ {label} using cached open orders after rate limit")
                return cached
        raise


def get_cached_accounts_summary(max_age=30):
    with ACCOUNTS_CACHE_LOCK:
        if LAST_ACCOUNTS_SUMMARY_TS and (time.time() - LAST_ACCOUNTS_SUMMARY_TS) <= max_age:
            return [dict(r) for r in LAST_ACCOUNTS_SUMMARY]
    return None


def set_cached_accounts_summary(rows):
    global LAST_ACCOUNTS_SUMMARY, LAST_ACCOUNTS_SUMMARY_TS
    with ACCOUNTS_CACHE_LOCK:
        LAST_ACCOUNTS_SUMMARY = [dict(r) for r in (rows or [])]
        LAST_ACCOUNTS_SUMMARY_TS = time.time()


def get_market_cache_ttl(interval: str) -> float:
    if interval == "15m":
        return MARKET_KLINES_CACHE_TTL_15M
    if interval == "1h":
        return MARKET_KLINES_CACHE_TTL_1H
    if interval == "4h":
        return MARKET_KLINES_CACHE_TTL_4H
    return max(MARKET_KLINES_CACHE_TTL_15M, 20.0)


def fetch_futures_klines_cached(symbol, interval="15m", limit=100, max_age=None):
    if binance is None:
        return []
    if max_age is None:
        max_age = get_market_cache_ttl(interval)

    key = (symbol, interval, int(limit))
    now = time.time()
    with MARKET_KLINES_CACHE_LOCK:
        cached = MARKET_KLINES_CACHE.get(key)
        if cached and (now - cached.get("ts", 0.0)) <= max_age:
            return cached.get("data", [])

    try:
        data = binance.futures_klines(symbol=symbol, interval=interval, limit=limit)
        with MARKET_KLINES_CACHE_LOCK:
            MARKET_KLINES_CACHE[key] = {"ts": now, "data": data}
        return data
    except Exception as e:
        if is_rate_limit_error(e):
            with MARKET_KLINES_CACHE_LOCK:
                cached = MARKET_KLINES_CACHE.get(key)
                if cached:
                    print(f"⚠️ MARKET CACHE fallback {symbol} {interval} after rate limit")
                    return cached.get("data", [])
        raise


def build_exit_lookup(open_orders):
    rows = {}
    for o in open_orders or []:
        symbol = o.get("symbol")
        if not symbol:
            continue
        stop_price = float(o.get("stopPrice", 0) or 0)
        if stop_price <= 0:
            continue
        row = rows.setdefault(symbol, {"sl": None, "tp": None})
        order_type = o.get("type")
        if order_type == "STOP_MARKET":
            row["sl"] = stop_price
        elif order_type == "TAKE_PROFIT_MARKET":
            row["tp"] = stop_price
    return rows


def build_live_position_rows(positions=None, open_orders=None):
    if positions is None:
        positions = fetch_main_positions(force=False, max_age=POSITION_CACHE_TTL, label="MAIN")
    if open_orders is None:
        open_orders = fetch_main_open_orders(force=False, max_age=POSITION_CACHE_TTL, label="MAIN")

    exit_lookup = build_exit_lookup(open_orders)
    rows = []

    for p in positions or []:
        amt = float(p.get("positionAmt", 0) or 0)
        if abs(amt) <= 0:
            continue

        symbol = p.get("symbol")
        entry = float(p.get("entryPrice", 0) or 0)
        mark = float(p.get("markPrice", 0) or 0)
        unrealized = float(p.get("unRealizedProfit", 0) or 0)
        leverage = float(p.get("leverage", 0) or 0)
        side = "BUY" if amt > 0 else "SELL"

        exit_row = exit_lookup.get(symbol, {})
        sl = exit_row.get("sl")
        tp = exit_row.get("tp")

        rr = None
        if entry and sl and tp and abs(entry - sl) > 1e-9:
            rr = round(abs(tp - entry) / abs(entry - sl), 2)

        sl_ok = sl is not None and float(sl or 0) > 0
        tp_ok = tp is not None and float(tp or 0) > 0

        rows.append({
            "symbol": symbol,
            "type": side,
            "entry": entry,
            "mark": mark,
            "sl": sl,
            "tp": tp,
            "rr": rr,
            "size": abs(amt),
            "position_amt": amt,
            "unrealized": unrealized,
            "leverage": leverage,
            "locked": symbol in GLOBAL_SYMBOL_LOCK,
            "has_snapshot": symbol in TRADE_SNAPSHOTS,
            "protective_resolved": bool(sl_ok and tp_ok),
            "sl_resolved": bool(sl_ok),
            "tp_resolved": bool(tp_ok),
            "account": "MAIN",
        })

    rows.sort(key=lambda x: abs(float(x.get("unrealized", 0))), reverse=True)
    return rows

def mark_client_runtime(client_obj, label):
    if client_obj is None:
        return None
    try:
        client_obj._montra_label = label
        client_obj._last_time_sync = 0
    except Exception:
        pass
    return client_obj

def get_client_label(client_obj, fallback="BINANCE"):
    return getattr(client_obj, "_montra_label", fallback)

def sync_binance_time(client_obj, label=None, force=False):
    if client_obj is None:
        return False

    label = label or get_client_label(client_obj)
    now = time.time()
    last_sync = getattr(client_obj, "_last_time_sync", 0)

    if not force and last_sync and (now - last_sync) < BINANCE_TIME_SYNC_INTERVAL:
        return True

    try:
        server_time = client_obj.get_server_time()["serverTime"]
        local_time = int(time.time() * 1000)
        offset = int(server_time - local_time)
        client_obj.timestamp_offset = offset
        client_obj._last_time_sync = now
        print(f"🕒 {label} timestamp_offset synced: {offset} ms")
        return True
    except Exception as e:
        print(f"❌ {label} sync_binance_time error:", e)
        return False

def signed_call(client_obj, fn, *args, label=None, recv_window=None, retry_on_time_error=True, **kwargs):
    if client_obj is None:
        raise RuntimeError("binance client not ready")

    label = label or get_client_label(client_obj)
    if recv_window is None:
        recv_window = BINANCE_RECV_WINDOW

    if recv_window and "recvWindow" not in kwargs:
        kwargs["recvWindow"] = recv_window

    sync_binance_time(client_obj, label=label, force=False)

    time_attempts = 1 + max(0, int(BINANCE_MAX_TIME_RETRIES if retry_on_time_error else 0))
    rate_attempts = 1 + max(0, int(BINANCE_RATE_LIMIT_RETRIES))
    total_attempts = max(time_attempts, rate_attempts)
    last_error = None

    for attempt in range(1, total_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            msg = str(e)
            time_error = ("-1021" in msg) or ("outside of the recvWindow" in msg)
            rate_error = is_rate_limit_error(e)

            if time_error and attempt < time_attempts:
                print(f"⚠️ {label} signed_call time drift detected (attempt {attempt}/{time_attempts})")
                sync_binance_time(client_obj, label=label, force=True)
                time.sleep(0.25)
                continue

            if rate_error and attempt < rate_attempts:
                sleep_for = min(POSITION_RATE_LIMIT_SLEEP, 8 + (attempt * 4))
                print(f"⚠️ {label} signed_call rate limited, retrying in {sleep_for:.1f}s")
                time.sleep(sleep_for)
                continue

            raise

    raise last_error

binance = None
if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_SECRET"):
    binance = mark_client_runtime(Client(
        os.getenv("BINANCE_API_KEY"),
        os.getenv("BINANCE_SECRET")
    ), "MAIN")
    sync_binance_time(binance, "MAIN", force=True)

CLIENTS = []
for acc in ACCOUNTS:
    if acc["api_key"] and acc["secret"]:
        acc_client = mark_client_runtime(Client(acc["api_key"], acc["secret"]), acc["name"])
        sync_binance_time(acc_client, acc["name"], force=True)
        CLIENTS.append({
            "name": acc["name"],
            "client": acc_client,
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

# === DEBUG CANDIDATE LIVE ===
candidate_list_live = []
selected_symbols_live = []
selected_rows_live = []
skip_reasons_live = []
MAX_SKIP_REASONS = 300
EXECUTION_DECISIONS = []
MAX_EXECUTION_DECISIONS = 500

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
TELEGRAM_LAST_UPDATE_ID = None

def add_order_audit(event_type, symbol, detail=None):
    global ORDER_AUDIT_LOG

    if detail is None:
        detail = {}

    row = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event": event_type,
        "symbol": symbol,
        "detail": detail,
    }

    ORDER_AUDIT_LOG.append(row)

    if len(ORDER_AUDIT_LOG) > MAX_AUDIT_LOG:
        ORDER_AUDIT_LOG = ORDER_AUDIT_LOG[-MAX_AUDIT_LOG:]

    print(f"🧾 AUDIT {event_type} {symbol} {detail}")
    save_runtime_state()

def save_trade_snapshot(symbol, snapshot):
    TRADE_SNAPSHOTS[symbol] = snapshot
    save_runtime_state()

def move_snapshot_to_replay(symbol, close_info):
    snap = TRADE_SNAPSHOTS.pop(symbol, None)
    if not snap:
        return

    row = {
        "symbol": symbol,
        "opened_at": snap.get("opened_at"),
        "closed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot": snap,
        "close_info": close_info,
    }

    TRADE_REPLAY_LOG.append(row)

    if len(TRADE_REPLAY_LOG) > MAX_REPLAY_LOG:
        del TRADE_REPLAY_LOG[:-MAX_REPLAY_LOG]

    save_runtime_state()

def build_runtime_state():
    cooldowns = {}
    now = time.time()

    for sym, ts in SYMBOL_COOLDOWN.items():
        left = COOLDOWN_SECONDS - (now - ts)
        if left > 0:
            cooldowns[sym] = ts

    return {
        "kill_switch": KILL_SWITCH,
        "start_equity": START_EQUITY,
        "daily_start_equity": DAILY_START_EQUITY,
        "last_day": LAST_DAY,
        "daily_loss": daily_loss,
        "consecutive_loss": consecutive_loss,
        "current_risk": current_risk,
        "cooldowns": cooldowns,
        "locked_symbols": sorted(list(GLOBAL_SYMBOL_LOCK)),
        "trade_snapshots": TRADE_SNAPSHOTS,
        "trade_replay_log": TRADE_REPLAY_LOG[-MAX_REPLAY_LOG:],
        "trade_history": trade_history[-MAX_TRADE_HISTORY:],
        "last_position_state": last_position_state,
        "position_entry_score": position_entry_score,
        "portfolio_alloc": portfolio_alloc,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

def save_runtime_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(build_runtime_state(), f, indent=2)
    except Exception as e:
        print("save_runtime_state error:", e)

def load_runtime_state():
    global KILL_SWITCH, START_EQUITY, DAILY_START_EQUITY, LAST_DAY
    global daily_loss, consecutive_loss, current_risk, SYMBOL_COOLDOWN, GLOBAL_SYMBOL_LOCK
    global TRADE_SNAPSHOTS, TRADE_REPLAY_LOG, trade_history, last_position_state, position_entry_score, portfolio_alloc

    if not os.path.exists(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        KILL_SWITCH = bool(data.get("kill_switch", False))
        START_EQUITY = data.get("start_equity")
        DAILY_START_EQUITY = data.get("daily_start_equity")
        LAST_DAY = data.get("last_day")
        daily_loss = float(data.get("daily_loss", 0))
        consecutive_loss = int(data.get("consecutive_loss", 0))
        current_risk = float(data.get("current_risk", BASE_RISK))

        cooldowns = data.get("cooldowns", {})
        if isinstance(cooldowns, dict):
            SYMBOL_COOLDOWN.update(cooldowns)

        locked_symbols = data.get("locked_symbols", [])
        if isinstance(locked_symbols, list):
            for sym in locked_symbols:
                GLOBAL_SYMBOL_LOCK.add(sym)

        snapshots = data.get("trade_snapshots", {})
        if isinstance(snapshots, dict):
            TRADE_SNAPSHOTS.update(snapshots)

        replay_log = data.get("trade_replay_log", [])
        if isinstance(replay_log, list):
            TRADE_REPLAY_LOG = replay_log[-MAX_REPLAY_LOG:]

        saved_history = data.get("trade_history", [])
        if isinstance(saved_history, list):
            trade_history = saved_history[-MAX_TRADE_HISTORY:]

        saved_last_position_state = data.get("last_position_state", {})
        if isinstance(saved_last_position_state, dict):
            last_position_state = saved_last_position_state

        saved_position_entry_score = data.get("position_entry_score", {})
        if isinstance(saved_position_entry_score, dict):
            position_entry_score.update(saved_position_entry_score)

        saved_portfolio_alloc = data.get("portfolio_alloc", {})
        if isinstance(saved_portfolio_alloc, dict):
            portfolio_alloc.update(saved_portfolio_alloc)

        print("✅ Runtime state loaded")

    except Exception as e:
        print("load_runtime_state error:", e)

def clean_url(url):
    if not url:
        return None
    url = url.strip()
    if url.startswith("FIREBASE_URL="):
        url = url.split("=", 1)[1].strip()
    return url.rstrip("/")

def firebase_ready():
    return bool(FIREBASE_URL and FIREBASE_URL.startswith("http"))
    
def get_session_utc():
    h = time.gmtime().tm_hour
    if 7 <= h < 13:
        return "LONDON"
    if 13 <= h < 22:
        return "NEWYORK"
    if 0 <= h < 7:
        return "ASIA"
    return "OFF"

def active_rr_min():
    return VALIDATION_RR_MIN if VALIDATION_MODE else LIVE_RR_MIN

def active_vol_min():
    return VALIDATION_VOL_MIN if VALIDATION_MODE else LIVE_VOL_MIN

def active_vol_max():
    return VALIDATION_VOL_MAX if VALIDATION_MODE else LIVE_VOL_MAX

def session_allowed(session):
    if VALIDATION_MODE and VALIDATION_SESSION_ALLOW_ASIA:
        return session in ("ASIA", "LONDON", "NEWYORK")
    return session in ("LONDON", "NEWYORK")

def active_news_block():
    return VALIDATION_NEWS_BLOCK if VALIDATION_MODE else LIVE_NEWS_BLOCK

def active_require_sweep():
    return VALIDATION_REQUIRE_SWEEP if VALIDATION_MODE else LIVE_REQUIRE_SWEEP

def active_require_pair_regime_match():
    return VALIDATION_REQUIRE_PAIR_REGIME_MATCH if VALIDATION_MODE else LIVE_REQUIRE_PAIR_REGIME_MATCH

def active_allow_sideways_score_penalty():
    return VALIDATION_ALLOW_SIDEWAYS_SCORE_PENALTY if VALIDATION_MODE else LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY

def active_target_rr():
    return VALIDATION_TARGET_RR if VALIDATION_MODE else max(LIVE_TARGET_RR, LIVE_RR_MIN)

def get_pair_tier(symbol):
    if symbol in TOP_PAIRS:
        return "TOP"
    if symbol in MID_PAIRS:
        return "MID"
    return "LOW"

def tier_limits():
    return {
        "TOP": TOP_PAIR_LIMIT,
        "MID": MID_PAIR_LIMIT,
        "LOW": LOW_PAIR_LIMIT,
    }

def tier_score_floor(symbol):
    tier = get_pair_tier(symbol)
    if VALIDATION_MODE:
        return MIN_SCORE if tier != "LOW" else max(MIN_SCORE, 50)
    if tier == "TOP":
        return max(MIN_SCORE, 62)
    if tier == "MID":
        return max(MIN_SCORE, 66)
    return 999

def tier_score_bonus(symbol):
    tier = get_pair_tier(symbol)
    if tier == "TOP":
        return 5
    if tier == "MID":
        return 2
    return 0

def detect_recent_fvg(ohlcv, bars=None):
    bars = bars or STRUCTURE_FVG_LOOKBACK
    fvg_up = None
    fvg_down = None

    if len(ohlcv) < 3:
        return {"up": None, "down": None}

    start = max(2, len(ohlcv) - (bars + 2))

    for i in range(start, len(ohlcv)):
        c1 = ohlcv[i - 2]
        c3 = ohlcv[i]

        c1_high = float(c1[2])
        c1_low = float(c1[3])
        c3_high = float(c3[2])
        c3_low = float(c3[3])

        if c1_high < c3_low:
            gap = {
                "top": c3_low,
                "bottom": c1_high,
                "index": i,
                "age": len(ohlcv) - 1 - i,
            }
            if fvg_up is None or gap["age"] < fvg_up["age"]:
                fvg_up = gap

        if c1_low > c3_high:
            gap = {
                "top": c1_low,
                "bottom": c3_high,
                "index": i,
                "age": len(ohlcv) - 1 - i,
            }
            if fvg_down is None or gap["age"] < fvg_down["age"]:
                fvg_down = gap

    return {"up": fvg_up, "down": fvg_down}

def analyze_structure_v3(ohlcv, last_price=None):
    min_bars = max(STRUCTURE_SWING_LOOKBACK + STRUCTURE_RECENT_WINDOW, 20)
    if len(ohlcv) < min_bars:
        return {
            "ok": False,
            "reason": "NO_STRUCTURE",
            "grade": "NONE",
            "signal_type": None,
            "fvg_up": False,
            "fvg_down": False,
            "swing_break_up": False,
            "swing_break_down": False,
            "reclaim_up": False,
            "reclaim_down": False,
            "recent_break_up": False,
            "recent_break_down": False,
            "recent_reclaim_up": False,
            "recent_reclaim_down": False,
            "displacement_up": False,
            "displacement_down": False,
            "directional_up": False,
            "directional_down": False,
            "context_high": None,
            "context_low": None,
        }

    highs = [float(c[2]) for c in ohlcv]
    lows = [float(c[3]) for c in ohlcv]
    opens = [float(c[1]) for c in ohlcv]
    closes = [float(c[4]) for c in ohlcv]

    recent_n = max(2, STRUCTURE_RECENT_WINDOW)
    recent_highs = highs[-recent_n:]
    recent_lows = lows[-recent_n:]
    recent_opens = opens[-recent_n:]
    recent_closes = closes[-recent_n:]

    last_open = recent_opens[-1]
    last_close = recent_closes[-1] if last_price is None else float(last_price)
    last_high = recent_highs[-1]
    last_low = recent_lows[-1]

    prev_high = max(highs[-(STRUCTURE_SWING_LOOKBACK + recent_n):-recent_n])
    prev_low = min(lows[-(STRUCTURE_SWING_LOOKBACK + recent_n):-recent_n])

    tol_high = prev_high * STRUCTURE_RECLAIM_TOLERANCE
    tol_low = prev_low * STRUCTURE_RECLAIM_TOLERANCE

    last_range = max(last_high - last_low, 1e-9)
    last_body = abs(last_close - last_open)
    last_body_ratio = last_body / last_range

    recent_ranges = [max(h - l, 1e-9) for h, l in zip(recent_highs, recent_lows)]
    recent_bodies = [abs(c - o) for c, o in zip(recent_closes, recent_opens)]
    recent_body_ratios = [b / r for b, r in zip(recent_bodies, recent_ranges)]
    recent_body_ratio_max = max(recent_body_ratios) if recent_body_ratios else last_body_ratio

    displacement_up = any(
        c > o and (abs(c - o) / max(h - l, 1e-9)) >= STRUCTURE_MIN_BODY_RATIO
        for o, h, l, c in zip(recent_opens, recent_highs, recent_lows, recent_closes)
    )
    displacement_down = any(
        c < o and (abs(c - o) / max(h - l, 1e-9)) >= STRUCTURE_MIN_BODY_RATIO
        for o, h, l, c in zip(recent_opens, recent_highs, recent_lows, recent_closes)
    )

    bullish_count = sum(1 for c, o in zip(recent_closes, recent_opens) if c > o)
    bearish_count = sum(1 for c, o in zip(recent_closes, recent_opens) if c < o)
    directional_up = bullish_count >= max(2, recent_n - 1)
    directional_down = bearish_count >= max(2, recent_n - 1)

    swing_break_up = last_close > (prev_high + tol_high)
    swing_break_down = last_close < (prev_low - tol_low)

    reclaim_up = last_low < (prev_low - tol_low) and last_close > prev_low and last_close > last_open
    reclaim_down = last_high > (prev_high + tol_high) and last_close < prev_high and last_close < last_open

    recent_break_up = max(recent_closes) > (prev_high + tol_high) or (
        max(recent_highs) > (prev_high + tol_high) and last_close >= (prev_high - tol_high * 0.35)
    )
    recent_break_down = min(recent_closes) < (prev_low - tol_low) or (
        min(recent_lows) < (prev_low - tol_low) and last_close <= (prev_low + tol_low * 0.35)
    )

    recent_reclaim_up = min(recent_lows) < (prev_low - tol_low) and max(recent_closes) > prev_low
    recent_reclaim_down = max(recent_highs) > (prev_high + tol_high) and min(recent_closes) < prev_high

    fvg = detect_recent_fvg(ohlcv, bars=max(STRUCTURE_FVG_LOOKBACK, recent_n + 2))
    fvg_up_zone = fvg["up"]
    fvg_down_zone = fvg["down"]
    fvg_up = fvg_up_zone is not None
    fvg_down = fvg_down_zone is not None

    zone_tol = STRUCTURE_ZONE_TOLERANCE
    near_fvg_up = False
    near_fvg_down = False
    if fvg_up_zone:
        band_low = fvg_up_zone["bottom"] * (1 - zone_tol)
        band_high = fvg_up_zone["top"] * (1 + zone_tol)
        near_fvg_up = band_low <= last_close <= band_high or last_close >= fvg_up_zone["bottom"]
    if fvg_down_zone:
        band_low = fvg_down_zone["bottom"] * (1 - zone_tol)
        band_high = fvg_down_zone["top"] * (1 + zone_tol)
        near_fvg_down = band_low <= last_close <= band_high or last_close <= fvg_down_zone["top"]

    strong_buy = (
        (swing_break_up and fvg_up and displacement_up) or
        (reclaim_up and fvg_up and displacement_up)
    )
    strong_sell = (
        (swing_break_down and fvg_down and displacement_down) or
        (reclaim_down and fvg_down and displacement_down)
    )

    medium_buy = (
        (recent_break_up and (fvg_up or near_fvg_up) and (displacement_up or directional_up)) or
        (recent_reclaim_up and (fvg_up or near_fvg_up or displacement_up)) or
        (directional_up and near_fvg_up and recent_body_ratio_max >= max(0.08, STRUCTURE_MIN_BODY_RATIO * 0.75))
    )

    medium_sell = (
        (recent_break_down and (fvg_down or near_fvg_down) and (displacement_down or directional_down)) or
        (recent_reclaim_down and (fvg_down or near_fvg_down or displacement_down)) or
        (directional_down and near_fvg_down and recent_body_ratio_max >= max(0.08, STRUCTURE_MIN_BODY_RATIO * 0.75))
    )

    signal_type = None
    grade = "NONE"
    reason = "NO_STRUCTURE"

    if strong_buy:
        signal_type = "BUY"
        grade = "STRONG"
        reason = "STRUCTURE_STRONG_BUY"
    elif strong_sell:
        signal_type = "SELL"
        grade = "STRONG"
        reason = "STRUCTURE_STRONG_SELL"
    elif medium_buy:
        signal_type = "BUY"
        grade = "MEDIUM"
        reason = "STRUCTURE_MEDIUM_BUY"
    elif medium_sell:
        signal_type = "SELL"
        grade = "MEDIUM"
        reason = "STRUCTURE_MEDIUM_SELL"

    return {
        "ok": signal_type is not None,
        "reason": reason,
        "grade": grade,
        "signal_type": signal_type,
        "fvg_up": fvg_up,
        "fvg_down": fvg_down,
        "fvg_up_zone": fvg_up_zone,
        "fvg_down_zone": fvg_down_zone,
        "near_fvg_up": near_fvg_up,
        "near_fvg_down": near_fvg_down,
        "swing_break_up": swing_break_up,
        "swing_break_down": swing_break_down,
        "reclaim_up": reclaim_up,
        "reclaim_down": reclaim_down,
        "recent_break_up": recent_break_up,
        "recent_break_down": recent_break_down,
        "recent_reclaim_up": recent_reclaim_up,
        "recent_reclaim_down": recent_reclaim_down,
        "displacement_up": displacement_up,
        "displacement_down": displacement_down,
        "directional_up": directional_up,
        "directional_down": directional_down,
        "context_high": prev_high,
        "context_low": prev_low,
        "body_ratio": round(last_body_ratio, 4),
        "recent_body_ratio_max": round(recent_body_ratio_max, 4),
    }

def structure_score_adjustment(structure):

    grade = structure.get("grade")
    if grade == "STRONG":
        return STRUCTURE_STRONG_SCORE_BONUS
    if grade == "MEDIUM":
        return -STRUCTURE_MEDIUM_SCORE_PENALTY
    return 0

def add_skip_reason(symbol, reason, extra=None):
    global skip_reasons_live

    row = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "reason": reason,
    }

    if extra:
        row.update(extra)

    skip_reasons_live.append(row)

    if len(skip_reasons_live) > MAX_SKIP_REASONS:
        skip_reasons_live = skip_reasons_live[-MAX_SKIP_REASONS:]


def add_execution_decision(stage, symbol, status, detail=None):
    global EXECUTION_DECISIONS

    row = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stage": stage,
        "symbol": symbol,
        "status": status,
    }

    if detail:
        row["detail"] = detail

    EXECUTION_DECISIONS.append(row)

    if len(EXECUTION_DECISIONS) > MAX_EXECUTION_DECISIONS:
        EXECUTION_DECISIONS = EXECUTION_DECISIONS[-MAX_EXECUTION_DECISIONS:]

ai_memory = {}  # simpan skor tiap simbol
trade_history = []  # journal semua trade
TRADE_SNAPSHOTS = {}
TRADE_REPLAY_LOG = []
MAX_REPLAY_LOG = 500

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
    if binance is None:
        print("⚠️ Exchange cache skipped: binance client not ready")
        return

    try:
        info = binance.futures_exchange_info()
        for s in info["symbols"]:
            symbol = s["symbol"]
            if symbol not in PAIRS:
                continue

            lot = next((f for f in s["filters"] if f["filterType"] == "LOT_SIZE"), None)
            price = next((f for f in s["filters"] if f["filterType"] == "PRICE_FILTER"), None)

            if not lot or not price:
                continue

            EXCHANGE_CACHE[symbol] = {
                "stepSize": float(lot["stepSize"]),
                "minQty": float(lot["minQty"]),
                "tickSize": float(price["tickSize"]),
            }

        print("✅ Exchange cache loaded:", len(EXCHANGE_CACHE))

    except Exception as e:
        print("❌ load_exchange_cache error:", e)

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

def get_min_trade_notional(symbol):
    tier = get_pair_tier(symbol)
    if tier == "TOP":
        return TOP_MIN_TRADE_NOTIONAL
    if tier == "MID":
        return MID_MIN_TRADE_NOTIONAL
    if tier == "LOW":
        return LOW_MIN_TRADE_NOTIONAL
    return DEFAULT_MIN_TRADE_NOTIONAL

def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": msg})

def cancel_existing_orders(symbol, cancel_tp: bool = True, cancel_sl: bool = True):
    if binance is None:
        print("⚠️ cancel skipped: binance client not ready")
        return False
    try:
        orders = signed_call(binance, binance.futures_get_open_orders, symbol=symbol, label="MAIN")
        for o in orders:
            otype = o.get("type")
            should_cancel = False
            if cancel_sl and otype == "STOP_MARKET":
                should_cancel = True
            if cancel_tp and otype == "TAKE_PROFIT_MARKET":
                should_cancel = True
            if should_cancel:
                try:
                    signed_call(binance, binance.futures_cancel_order, symbol=symbol, orderId=o["orderId"], label="MAIN")
                except Exception as e:
                    print("Cancel single order error:", e)
        time.sleep(1.0)
        invalidate_main_open_orders_cache()
        return True
    except Exception as e:
        print("Cancel error:", e)
        return False
    
def place_futures_order(symbol, side, quantity, sl, tp):
    if binance is None:
        return {"error": "binance client not ready"}
    try:
        sl = normalize_price(symbol, sl)
        tp = normalize_price(symbol, tp)
        cancel_existing_orders(symbol)
        time.sleep(1.0)
        order = signed_call(binance, binance.futures_create_order, label="MAIN",
            symbol=symbol,
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=FUTURE_ORDER_TYPE_MARKET,
            quantity=quantity
        )
        time.sleep(0.3)
        signed_call(binance, binance.futures_create_order, label="MAIN",
            symbol=symbol,
            side=SIDE_SELL if side == "BUY" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=sl,
            closePosition=True,
            workingType="MARK_PRICE"
        )
        signed_call(binance, binance.futures_create_order, label="MAIN",
            symbol=symbol,
            side=SIDE_SELL if side == "BUY" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=tp,
            closePosition=True,
            workingType="MARK_PRICE"
        )
        invalidate_main_positions_cache()
        invalidate_main_open_orders_cache()
        return {"status": "FILLED", "order": order}
    except Exception as e:
        return {"error": str(e)}

def update_account_profit(client, name):
    try:
        balance_info = signed_call(client, client.futures_account_balance, label=name)
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
            balance_info = signed_call(c, c.futures_account_balance, label=acc["name"])
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
            balance = float(usdt["balance"]) if usdt else 0
            alloc = min(portfolio_alloc.get(symbol, 0.25), 0.12)
            risk_amount = balance * risk_pct * alloc
            price = float(c.futures_symbol_ticker(symbol=symbol)["price"])
            stop_distance = abs(price - sl)
            if stop_distance == 0:
                results.append({"account": acc["name"], "error": "stop_distance_zero"})
                continue
            qty = risk_amount / stop_distance
            min_notional = get_min_trade_notional(symbol)
            if qty * price < min_notional:
                qty = ceil_to_step(min_notional / price, EXCHANGE_CACHE.get(symbol, {}).get("stepSize", 0.001))
            qty, price = adjust_precision(symbol, qty, price)
            if qty * price < min_notional:
                print(f"❌ SKIP NOTIONAL < {min_notional}", symbol)
                results.append({
                    "account": acc["name"],
                    "error": "notional_below_min",
                    "qty": qty,
                    "price": price,
                    "min_notional": min_notional,
                })
                continue

            sl_price = normalize_price(symbol, sl)
            tp_price = normalize_price(symbol, tp)
            order = signed_call(c, c.futures_create_order, label=acc["name"],
                symbol=symbol,
                side=SIDE_BUY if side == "BUY" else SIDE_SELL,
                type=FUTURE_ORDER_TYPE_MARKET,
                quantity=qty
            )

            close_side = SIDE_SELL if side == "BUY" else SIDE_BUY
            signed_call(c, c.futures_create_order, label=acc["name"],
                symbol=symbol,
                side=close_side,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                stopPrice=sl_price,
                closePosition=True,
                workingType="MARK_PRICE"
            )
            signed_call(c, c.futures_create_order, label=acc["name"],
                symbol=symbol,
                side=close_side,
                type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                stopPrice=tp_price,
                closePosition=True,
                workingType="MARK_PRICE"
            )

            results.append({
                "account": acc["name"],
                "status": "OK",
                "qty": qty,
                "entry_price": price,
                "sl": sl_price,
                "tp": tp_price,
                "order_id": order.get("orderId") if isinstance(order, dict) else None,
            })
            update_account_profit(c, acc["name"])
            check_withdraw(acc, c)
        except Exception as e:
            results.append({"account": acc["name"], "error": str(e)})
    success = any(r.get("status") == "OK" for r in results if isinstance(r, dict))
    if not success:
        add_order_audit("ORDER_MULTI_FAILED", symbol, {"results": results})
        TRADE_SNAPSHOTS.pop(symbol, None)
        set_symbol_cooldown(symbol, reason="multi_order_failed")
    else:
        add_order_audit("ORDER_MULTI_OK", symbol, {"results": results})

    return results

def place_split_tp(symbol, side, quantity, tp1, tp2, tp3):
    side_close = SIDE_SELL if side == "BUY" else SIDE_BUY
    q1 = round(quantity * 0.4, 3)
    q2 = round(quantity * 0.3, 3)
    q3 = round(quantity * 0.3, 3)
    for tp, q in [(tp1, q1), (tp2, q2), (tp3, q3)]:
        signed_call(binance, binance.futures_create_order, label="MAIN",
            symbol=symbol,
            side=side_close,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=tp,
            quantity=q
        )

def update_stop_loss(symbol, side, new_sl):
    if binance is None:
        print("⚠️ SL update skipped: binance client not ready")
        return
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
            cancel_existing_orders(symbol, cancel_tp=False, cancel_sl=True)
            time.sleep(1.0)
            try:
                signed_call(binance, binance.futures_create_order, label="MAIN",
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
def get_daily_loss_pct_now():
    eq = get_total_equity()

    if eq is None or eq <= 0:
        return None

    if DAILY_START_EQUITY is None or DAILY_START_EQUITY <= 0:
        return 0.0

    pct = ((DAILY_START_EQUITY - eq) / DAILY_START_EQUITY) * 100
    return max(0.0, pct)

def get_total_equity():
    if not CLIENTS:
        print("⚠️ get_total_equity: no active clients")
        return None

    total = 0.0
    ok_count = 0

    for acc in CLIENTS:
        try:
            c = acc["client"]
            balance_info = signed_call(c, c.futures_account_balance, label=acc["name"])
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)

            if not usdt:
                print(f"⚠️ get_total_equity: no USDT balance for {acc['name']}")
                continue

            balance = float(usdt["balance"])
            unreal = float(usdt["crossUnPnl"])
            total += (balance + unreal)
            ok_count += 1

        except Exception as e:
            print(f"get_total_equity error {acc['name']}: {e}")

    if ok_count == 0:
        print("⚠️ get_total_equity: all account reads failed")
        return None

    return total

def safety_check():
    global KILL_SWITCH, DAILY_START_EQUITY, LAST_DAY, daily_loss, START_EQUITY

    now_day = time.strftime("%Y-%m-%d")
    eq = get_total_equity()

    if eq is None or eq <= 0:
        print(f"⚠️ safety_check skipped: invalid equity read ({eq})")
        return True

    if START_EQUITY is None or START_EQUITY <= 0:
        START_EQUITY = eq
        print("🧠 START_EQUITY initialized from safety_check:", START_EQUITY)
        save_runtime_state()
        return True

    if DAILY_START_EQUITY is None or DAILY_START_EQUITY <= 0:
        DAILY_START_EQUITY = eq
        print("🧠 DAILY_START_EQUITY initialized from safety_check:", DAILY_START_EQUITY)
        save_runtime_state()
        return True

    if now_day != LAST_DAY:
        DAILY_START_EQUITY = eq
        LAST_DAY = now_day
        daily_loss = 0
        print("🌅 RESET DAILY EQUITY:", eq)
        reset_pairs()
        save_runtime_state()

    dd = ((START_EQUITY - eq) / START_EQUITY) * 100
    if dd < 0:
        dd = 0

    if dd >= MAX_DRAWDOWN_PCT:
        if not KILL_SWITCH:
            KILL_SWITCH = True
            save_runtime_state()
            send_telegram(f"🛑 MAX DD HIT: {dd:.2f}% → BOT STOP")
        return False

    daily_loss_pct = ((DAILY_START_EQUITY - eq) / DAILY_START_EQUITY) * 100
    if daily_loss_pct < 0:
        daily_loss_pct = 0

    if daily_loss_pct >= DAILY_LOSS_PCT:
        if not KILL_SWITCH:
            KILL_SWITCH = True
            save_runtime_state()
            send_telegram(f"🛑 DAILY LOSS HIT: {daily_loss_pct:.2f}% → BOT STOP")
        return False

    return True

def check_telegram_commands():
    global KILL_SWITCH, AUTO_TRADING, TELEGRAM_LAST_UPDATE_ID
    global DAILY_START_EQUITY, daily_loss, LAST_DAY

    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        return

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": 1}

    if TELEGRAM_LAST_UPDATE_ID is not None:
        params["offset"] = TELEGRAM_LAST_UPDATE_ID + 1

    try:
        res = requests.get(url, params=params, timeout=5).json()

        for u in res.get("result", []):
            update_id = u.get("update_id")
            if update_id is not None:
                TELEGRAM_LAST_UPDATE_ID = update_id

            text = (u.get("message", {}) or {}).get("text", "").strip()

            if not text:
                continue

            if text == "/stop":
                if not KILL_SWITCH:
                    KILL_SWITCH = True
                    save_runtime_state()
                    send_telegram("🛑 BOT STOPPED via Telegram")
                continue

            if text == "/start":
                daily_loss_pct = get_daily_loss_pct_now()

                if daily_loss_pct is not None and daily_loss_pct >= DAILY_LOSS_PCT:
                    send_telegram(
                        f"⛔ BOT TETAP STOP: daily loss masih {daily_loss_pct:.2f}% "
                        f"(limit {DAILY_LOSS_PCT:.2f}%). Gunakan /resetday jika memang mau reset baseline."
                    )
                    continue

                if KILL_SWITCH:
                    KILL_SWITCH = False
                    save_runtime_state()
                    send_telegram("🚀 BOT RESUMED via Telegram")
                continue

            if text == "/auto_on":
                if not AUTO_TRADING:
                    AUTO_TRADING = True
                    save_runtime_state()
                    send_telegram("🟢 AUTO TRADING ENABLED")
                continue

            if text == "/auto_off":
                if AUTO_TRADING:
                    AUTO_TRADING = False
                    save_runtime_state()
                    send_telegram("🔴 AUTO TRADING DISABLED")
                continue

            if text == "/resetday":
                eq = get_total_equity()
                if eq is not None and eq > 0:
                    DAILY_START_EQUITY = eq
                    daily_loss = 0
                    LAST_DAY = time.strftime("%Y-%m-%d")
                    KILL_SWITCH = False
                    save_runtime_state()
                    send_telegram(f"🔄 DAILY BASELINE RESET ke equity {eq:.4f}")
                else:
                    send_telegram("⚠️ RESETDAY gagal: equity tidak valid")
                continue

    except Exception as e:
        print("telegram command error:", e)

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
    save_runtime_state()
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
def symbol_in_cooldown(symbol):
    ts = SYMBOL_COOLDOWN.get(symbol)
    if not ts:
        return False
    return (time.time() - ts) < COOLDOWN_SECONDS

def get_symbol_cooldown_left(symbol):
    ts = SYMBOL_COOLDOWN.get(symbol)
    if not ts:
        return 0
    left = COOLDOWN_SECONDS - (time.time() - ts)
    return max(0, int(left))

def set_symbol_cooldown(symbol, reason=""):
    SYMBOL_COOLDOWN[symbol] = time.time()
    add_order_audit("COOLDOWN_SET", symbol, {"reason": reason, "seconds": COOLDOWN_SECONDS})
    save_runtime_state()

def clamp_runtime_state():
    global current_risk, daily_loss, consecutive_loss
    try:
        current_risk = float(current_risk)
    except Exception:
        current_risk = float(BASE_RISK)
    current_risk = max(MIN_RISK, min(MAX_RISK, current_risk))
    daily_loss = max(0.0, float(daily_loss or 0.0))
    consecutive_loss = max(0, int(consecutive_loss or 0))

    now = time.time()
    expired = [sym for sym, ts in SYMBOL_COOLDOWN.items() if (now - float(ts)) >= COOLDOWN_SECONDS]
    for sym in expired:
        SYMBOL_COOLDOWN.pop(sym, None)

def get_exchange_open_symbols_strict():
    if binance is None:
        return None
    try:
        positions = signed_call(binance, binance.futures_position_information, label="MAIN")
        return {p["symbol"] for p in positions if float(p.get("positionAmt", 0)) != 0}
    except Exception as e:
        print("reconcile open symbols error:", e)
        return None

def reconcile_runtime_state_with_exchange():
    actual_open = get_exchange_open_symbols_strict()
    if actual_open is None:
        return

    stale_locks = sorted(list(GLOBAL_SYMBOL_LOCK - actual_open))
    stale_snapshots = sorted([sym for sym in TRADE_SNAPSHOTS.keys() if sym not in actual_open])

    if stale_locks:
        print("🧹 Clearing stale locks:", stale_locks)
    if stale_snapshots:
        print("🧹 Clearing stale snapshots:", stale_snapshots)

    GLOBAL_SYMBOL_LOCK.clear()
    GLOBAL_SYMBOL_LOCK.update(actual_open)

    for sym in stale_snapshots:
        close_info = finalize_closed_trade(
            sym,
            fallback_pnl=0.0,
            regime="RECOVERED",
            vol=0.0,
            note="startup_reconcile_no_open_position",
            send_notice=False,
            audit_event="STALE_SNAPSHOT_RECOVERED",
        )
        print(f"🧹 Reconciled stale snapshot: {sym} {close_info}")

    save_runtime_state()

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
    try:
        update_portfolio_allocation()
    except Exception as e:
        print("update_portfolio_allocation after ai memory error:", e)
    save_runtime_state()

def ai_allow_trade(symbol):
    mem = ai_memory.get(symbol)
    if not mem:
        return True

    score = safe_score(mem)
    threshold = 15 if VALIDATION_MODE else 35

    if score < threshold:
        print(f"🧠 AI BLOCK {symbol} score={score} threshold={threshold}")
        return False

    return True

# === HELPER FUNCTIONS ===
def get_ohlcv_cached(symbol, interval="15m"):
    live = get_live_candle(symbol)
    if live and get_live_age(symbol) < 10:
        return live
    return None

def ws_health_snapshot():
    global LAST_WS_GOOD_TS

    if MONTRA_MODE == "api_only":
        return {
            "healthy": True,
            "degraded": False,
            "block": False,
            "reason": "API_ONLY",
            "stale": [],
            "sample_age": {},
            "since_good": 0.0,
        }

    status = get_ws_status()
    sample = {}
    watchlist = PAIRS[:10]
    for sym in PAIRS[:5]:
        sample[sym] = round(get_live_age(sym), 2)

    stale = count_stale_symbols(watchlist, max_age=WS_MAX_AGE)
    now = time.time()

    thread_alive = bool(status.get("thread_alive"))
    socket_running = bool(status.get("running"))
    healthy = thread_alive and socket_running and len(stale) < WS_STALE_THRESHOLD
    if healthy:
        LAST_WS_GOOD_TS = now

    since_good = 0.0 if LAST_WS_GOOD_TS == 0 else max(0.0, now - LAST_WS_GOOD_TS)
    degraded = False
    block = False
    reason = "OK"

    if not thread_alive:
        block = True
        reason = "THREAD_DEAD"
    elif not socket_running:
        block = True
        reason = "SOCKET_DOWN"
    elif len(stale) >= WS_STALE_THRESHOLD:
        if WS_DEGRADED_MODE_ALLOW and LAST_WS_GOOD_TS and since_good <= WS_DEGRADED_GRACE_SECONDS:
            degraded = True
            reason = "STALE_DEGRADED"
        else:
            block = True
            reason = "STALE_BLOCK"

    return {
        "healthy": healthy,
        "degraded": degraded,
        "block": block,
        "reason": reason,
        "stale": stale,
        "sample_age": sample,
        "since_good": round(since_good, 2),
    }


def ws_data_healthy():
    snap = ws_health_snapshot()
    return not snap["block"]

def ws_auto_heal():
    global LAST_WS_HEAL

    if MONTRA_MODE == "api_only":
        return

    now = time.time()
    if now - LAST_WS_HEAL < WS_RESTART_COOLDOWN:
        return

    status = get_ws_status()
    stale = count_stale_symbols(PAIRS[:10], max_age=WS_MAX_AGE)

    need_restart = False

    if not status.get("thread_alive"):
        print("❌ WS watchdog: thread dead")
        need_restart = True
    elif not status.get("running"):
        print("❌ WS watchdog: socket down")
        need_restart = True
    elif len(stale) >= WS_STALE_THRESHOLD:
        print(f"❌ WS watchdog: stale symbols = {stale}")
        need_restart = True

    if need_restart:
        LAST_WS_HEAL = now
        restart_ws(PAIRS, interval="15m")
    
def _get_trend(symbol):
    try:
        klines = fetch_futures_klines_cached(symbol, interval="1h", limit=50)
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
        klines = fetch_futures_klines_cached(symbol, interval="1h", limit=2)
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

def btc_alignment(symbol, signal_trend):
    btc_trend = _get_trend("BTCUSDT")
    pair_tier = get_pair_tier(symbol)

    if btc_trend == signal_trend:
        return {"ok": True, "penalty": 0, "reason": "ALIGNED"}

    if pair_tier == "TOP":
        return {"ok": True, "penalty": 6, "reason": f"TOP_COUNTER_BTC_{btc_trend}"}

    if pair_tier == "MID" and VALIDATION_MODE:
        return {"ok": True, "penalty": 10, "reason": f"MID_COUNTER_BTC_{btc_trend}"}

    return {"ok": False, "penalty": 99, "reason": f"BTC_BLOCK_{btc_trend}"}

def get_regime_tf(symbol, interval):
    try:
        klines = fetch_futures_klines_cached(symbol, interval=interval, limit=50)
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
        klines = fetch_futures_klines_cached(symbol, interval="15m", limit=20)
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
    total = 0.0

    default_score = 50 if VALIDATION_MODE else 35

    for sym in PAIRS:
        mem = ai_memory.get(sym)

        if isinstance(mem, dict):
            score = mem.get("score", default_score)
        elif mem is not None:
            try:
                score = float(mem)
            except:
                score = default_score
        else:
            score = default_score

        score = max(float(score), 1.0)
        scores[sym] = score
        total += score

    if total <= 0:
        even_weight = round(1 / max(len(PAIRS), 1), 6)
        portfolio_alloc = {sym: even_weight for sym in PAIRS}
        print("📊 PORTFOLIO fallback-even:", portfolio_alloc)
        save_portfolio()
        return

    portfolio_alloc = {sym: (scores[sym] / total) for sym in scores}

    top_rows = sorted(portfolio_alloc.items(), key=lambda x: x[1], reverse=True)[:5]
    print("📊 PORTFOLIO TOP:", [(sym, round(w, 4)) for sym, w in top_rows])
    save_portfolio()

def get_open_positions():
    try:
        positions = fetch_main_positions(force=False, max_age=POSITION_CACHE_TTL, label="MAIN")
        return [p for p in positions if float(p["positionAmt"]) != 0]
    except Exception as e:
        print("Error get_open_positions:", e)
        return []

# ⭐ NEW: centralized decision
def should_execute_trade(signal):
    score = float(signal.get("score", 0) or 0)
    symbol = signal.get("symbol")
    side = signal.get("type")
    rr = float(signal.get("rr", 0) or 0)
    pair_regime = signal.get("pair_regime")
    sweep_high = bool(signal.get("sweep_high", False))
    sweep_low = bool(signal.get("sweep_low", False))

    if not symbol or side not in ("BUY", "SELL"):
        return False, "INVALID_SIGNAL"

    if KILL_SWITCH:
        return False, "KILL_SWITCH"

    if not AUTO_TRADING:
        return False, "AUTO_OFF"

    if not safety_check():
        return False, "SAFETY_BLOCK"

    if symbol in disabled_pairs:
        return False, "DISABLED_PAIR"

    if symbol in EXECUTION_IN_PROGRESS:
        return False, "EXECUTION_IN_PROGRESS"

    if symbol in GLOBAL_SYMBOL_LOCK:
        return False, "SYMBOL_LOCKED"

    if symbol_in_cooldown(symbol):
        return False, f"COOLDOWN_{get_symbol_cooldown_left(symbol)}s"

    if not ai_allow_trade(symbol):
        return False, "AI_BLOCK"

    min_score_needed = tier_score_floor(symbol)
    if score < min_score_needed:
        return False, f"LOW_SCORE_{min_score_needed}"

    if rr and rr < active_rr_min():
        return False, f"LOW_RR_{active_rr_min()}"

    if active_require_sweep():
        if side == "BUY" and not sweep_low:
            return False, "NO_SWEEP_LOW"
        if side == "SELL" and not sweep_high:
            return False, "NO_SWEEP_HIGH"

    if active_require_pair_regime_match() and pair_regime:
        if pair_regime == "SIDEWAYS":
            return False, "PAIR_REGIME_SIDEWAYS"
        if pair_regime == "BULL" and side != "BUY":
            return False, "PAIR_REGIME_BULL_MISMATCH"
        if pair_regime == "BEAR" and side != "SELL":
            return False, "PAIR_REGIME_BEAR_MISMATCH"

    positions = get_open_positions()

    if len(positions) >= MAX_OPEN_TRADES:
        return False, "MAX_POSITION"

    if any(p["symbol"] == symbol for p in positions):
        return False, "POSITION_ALREADY_OPEN"

    strategy = get_strategy(symbol)
    if strategy == "DEFENSIVE" and score < max(75, min_score_needed):
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

def resolve_closed_trade_pnl(symbol, fallback_pnl=0.0):
    if binance is None:
        return float(fallback_pnl or 0.0)
    try:
        trades = signed_call(binance, binance.futures_account_trades, symbol=symbol, label="MAIN")
        now_ms = int(time.time() * 1000)
        window_ms = max(1, CLOSE_REALIZED_LOOKBACK_MINUTES) * 60 * 1000
        realized = []
        for t in trades[-50:]:
            rpnl = float(t.get("realizedPnl", 0) or 0)
            tms = int(t.get("time", 0) or 0)
            if abs(rpnl) <= 0:
                continue
            if tms and (now_ms - tms) <= window_ms:
                realized.append(rpnl)
        if realized:
            return float(sum(realized))
    except Exception as e:
        print(f"resolve_closed_trade_pnl error {symbol}: {e}")
    return float(fallback_pnl or 0.0)


def finalize_closed_trade(
    symbol,
    fallback_pnl=0.0,
    regime=None,
    vol=None,
    note=None,
    send_notice=True,
    audit_event="POSITION_CLOSED",
):
    pnl = resolve_closed_trade_pnl(symbol, fallback_pnl)
    if pnl > 0:
        result = "WIN"
    elif pnl < 0:
        result = "LOSS"
    else:
        result = "UNKNOWN"

    entry_score = position_entry_score.pop(symbol, 50)
    used_regime = regime if regime is not None else (last_regime if last_regime else "UNKNOWN")
    used_vol = vol if vol is not None else (last_vol if last_vol else 0.0)

    close_info = {
        "result": result,
        "pnl": pnl,
        "regime": used_regime,
        "vol": used_vol,
        "entry_score": entry_score,
    }
    if note:
        close_info["note"] = note

    if result in ("WIN", "LOSS"):
        update_pair_stats(symbol, result, pnl)
        update_risk(result, pnl)
        update_ai_memory(symbol, result)
        update_rl_weights(result, entry_score)

        trade_history.append({
            "symbol": symbol,
            "result": result,
            "pnl": pnl,
            "regime": used_regime,
            "vol": used_vol,
            "score": entry_score,
            "note": note,
        })
        if len(trade_history) > MAX_TRADE_HISTORY:
            del trade_history[:-MAX_TRADE_HISTORY]
        print(f"📝 Journal updated: {symbol} {result}")
    else:
        print(f"⚠️ Closed trade unresolved: {symbol} PnL=0.00; memory/journal not updated as loss")

    add_order_audit(audit_event, symbol, close_info)
    move_snapshot_to_replay(symbol, close_info)

    GLOBAL_SYMBOL_LOCK.discard(symbol)
    EXECUTION_IN_PROGRESS.discard(symbol)
    if result in ("WIN", "LOSS"):
        set_symbol_cooldown(symbol, reason=f"position_closed_{result.lower()}")

    if send_notice and result in ("WIN", "LOSS"):
        send_telegram(f"✅ Trade closed: {symbol} {result} PnL=${pnl:.2f}")

    return close_info


def monitor_positions_for_memory_update():
    global last_position_state, last_regime, last_vol
    while True:
        try:
            if binance is None:
                time.sleep(POSITION_MONITOR_INTERVAL)
                continue
            try:
                current_regime = get_multi_tf_regime("BTCUSDT")
                current_vol = get_volatility("BTCUSDT")
                last_regime = current_regime
                last_vol = current_vol
            except:
                pass

            positions = fetch_main_positions(force=False, max_age=POSITION_MONITOR_INTERVAL, label="MAIN")
            current_state = {}
            for p in positions:
                amt = float(p["positionAmt"])
                if amt != 0:
                    symbol = p["symbol"]
                    GLOBAL_SYMBOL_LOCK.add(symbol)                    
                    side = "BUY" if amt > 0 else "SELL"
                    current_state[symbol] = {
                        "side": side,
                        "size": abs(amt),
                        "entry": float(p["entryPrice"]),
                        "unrealized": float(p["unRealizedProfit"]),
                        "leverage": float(p.get("leverage", 0) or 0)
                    }

            for symbol, last in last_position_state.items():
                if symbol not in current_state:
                    close_info = finalize_closed_trade(
                        symbol,
                        fallback_pnl=last.get("unrealized", 0.0),
                        regime=last_regime if last_regime else "UNKNOWN",
                        vol=last_vol if last_vol else 0.0,
                        send_notice=True,
                        audit_event="POSITION_CLOSED",
                    )
                    print(f"📊 Position closed: {symbol} {close_info}")

            # Snapshot safety: if runtime state contains a trade snapshot but the
            # exchange no longer has that symbol open, finalize it even after a
            # restart or monitor gap.
            for symbol in list(TRADE_SNAPSHOTS.keys()):
                if symbol not in current_state:
                    close_info = finalize_closed_trade(
                        symbol,
                        fallback_pnl=0.0,
                        regime=last_regime if last_regime else "UNKNOWN",
                        vol=last_vol if last_vol else 0.0,
                        note="snapshot_missing_from_exchange",
                        send_notice=True,
                        audit_event="SNAPSHOT_CLOSED_RECOVERED",
                    )
                    print(f"🧩 Snapshot close recovered: {symbol} {close_info}")

            last_position_state = current_state
            save_runtime_state()

        except Exception as e:
            print("Monitor position error:", e)
            if is_rate_limit_error(e):
                time.sleep(POSITION_RATE_LIMIT_SLEEP)
            else:
                time.sleep(POSITION_MONITOR_INTERVAL)
            continue

        time.sleep(POSITION_MONITOR_INTERVAL)

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
        data = fetch_futures_klines_cached(symbol, interval=timeframe, limit=limit)
        return {"symbol": symbol, "timeframe": timeframe, "limit": limit, "data": data}
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
        if binance is None:
            return {"error": "binance client not ready"}
        symbol = payload.get("symbol")
        side = payload.get("type")
        if symbol in EXECUTION_IN_PROGRESS:
            return {"error": "execution in progress"}

        if symbol in GLOBAL_SYMBOL_LOCK:
            return {"error": "symbol locked"}

        if symbol_in_cooldown(symbol):
            return {"error": f"symbol cooldown {get_symbol_cooldown_left(symbol)}s"}

        EXECUTION_IN_PROGRESS.add(symbol)
        GLOBAL_SYMBOL_LOCK.add(symbol)
        
        save_trade_snapshot(symbol, {
            "opened_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "manual_trade",
            "signal": {
                "symbol": symbol,
                "type": side,
            },
            "score": None,
            "side": side,
            "sl": float(payload.get("sl")),
            "tp": float(payload.get("tp")),
            "entry": float(payload.get("entry")),
            "risk_percent": float(payload.get("risk", 1)),
        })

        entry = float(payload.get("entry"))
        sl = float(payload.get("sl"))
        tp = float(payload.get("tp"))
        risk_percent = max(0.1, min(float(payload.get("risk", 1)), 2.0))
        balance_info = signed_call(binance, binance.futures_account_balance, label="MAIN")
        usdt_balance = next((b for b in balance_info if b["asset"] == "USDT"), None)
        balance = float(usdt_balance["balance"]) if usdt_balance else 0
        risk_amount = balance * (risk_percent / 100)
        stop_distance = abs(entry - sl)
        if stop_distance <= 0:
            return {"error": "invalid_stop_distance"}
        quantity = round(risk_amount / stop_distance, 3)
        quantity, _ = adjust_precision(symbol, quantity, entry)
        min_notional = get_min_trade_notional(symbol)
        if quantity * entry < min_notional:
            quantity = ceil_to_step(min_notional / entry, EXCHANGE_CACHE.get(symbol, {}).get("stepSize", 0.001))
            quantity, _ = adjust_precision(symbol, quantity, entry)
        if quantity <= 0:
            return {"error": "quantity_below_min"}
        if quantity * entry < min_notional:
            return {"error": "notional_below_min", "min_notional": min_notional}
        result = place_futures_order(symbol, side, quantity, sl, tp)
        send_telegram(f"""
🚀 TRADE EXECUTED
{symbol} {side}
Qty: {quantity}
SL: {sl}
TP: {tp}
""")
        add_order_audit("MANUAL_TRADE_SENT", symbol, {
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "risk_percent": risk_percent,
            "result": result,
        })

        if isinstance(result, dict) and result.get("error"):
            TRADE_SNAPSHOTS.pop(symbol, None)
            set_symbol_cooldown(symbol, reason="manual_trade_error")
            GLOBAL_SYMBOL_LOCK.discard(symbol)
        return result

    except Exception as e:
        add_order_audit("MANUAL_TRADE_ERROR", payload.get("symbol", "UNKNOWN"), {"error": str(e)})
        if payload.get("symbol"):
            set_symbol_cooldown(payload.get("symbol"), reason="manual_trade_exception")
            GLOBAL_SYMBOL_LOCK.discard(payload.get("symbol"))
        return {"error": str(e)}

    finally:
        if payload.get("symbol"):
            EXECUTION_IN_PROGRESS.discard(payload.get("symbol"))

@app.get("/positions")
def get_positions():
    try:
        if binance is None:
            return {"positions": []}
        positions = signed_call(binance, binance.futures_position_information, label="MAIN")
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

@app.get("/audit/orders")
def audit_orders(limit: int = Query(default=50, ge=1, le=500)):
    return {
        "count": min(limit, len(ORDER_AUDIT_LOG)),
        "rows": ORDER_AUDIT_LOG[-limit:]
    }

@app.get("/health/live")
def health_live():
    return {"status": "ok", "mode": MONTRA_MODE}

@app.get("/health/ready")
def health_ready():
    return {
        "status": "ready",
        "mode": MONTRA_MODE,
        "binance": binance is not None,
        "openai": client is not None,
        "accounts": len(CLIENTS),
    }

@app.get("/health/pairs")
def health_pairs():
    return {
        "scan_pairs": PAIRS,
        "top_pairs": TOP_PAIRS,
        "mid_pairs": MID_PAIRS,
        "low_pairs": LOW_PAIRS,
        "validation_only": VALIDATION_ONLY,
        "remove_from_core": REMOVE_FROM_CORE,
        "limits": tier_limits(),
    }

@app.get("/health/validation")
def health_validation():
    return {
        "validation_mode": VALIDATION_MODE,
        "min_score": MIN_SCORE,
        "rr_min": active_rr_min(),
        "vol_min": active_vol_min(),
        "vol_max": active_vol_max(),
        "allow_asia_session": VALIDATION_SESSION_ALLOW_ASIA,
        "news_block": VALIDATION_NEWS_BLOCK,
        "require_sweep": VALIDATION_REQUIRE_SWEEP,
        "require_pair_regime_match": VALIDATION_REQUIRE_PAIR_REGIME_MATCH,
    }

@app.get("/health/ws")
def health_ws():
    sample = {}
    for sym in PAIRS[:5]:
        sample[sym] = round(get_live_age(sym), 2)

    stale = count_stale_symbols(PAIRS[:10], max_age=WS_MAX_AGE)
    status = get_ws_status()

    return {
        "mode": MONTRA_MODE,
        "sample_age": sample,
        "ws_expected": MONTRA_MODE != "api_only",
        "ws_running": status["running"],
        "thread_alive": status["thread_alive"],
        "restart_count": status["restart_count"],
        "last_error": status["last_error"],
        "stale_symbols": stale,
        "healthy": len(stale) < WS_STALE_THRESHOLD and status["thread_alive"],
    }

@app.get("/health/state")
def health_state():
    return build_runtime_state()

@app.get("/health/equity")
def health_equity():
    eq = get_total_equity()
    return {
        "equity_now": eq,
        "start_equity": START_EQUITY,
        "daily_start_equity": DAILY_START_EQUITY,
        "clients": len(CLIENTS),
        "kill_switch": KILL_SWITCH,
    }

@app.post("/health/state/reset")
def health_state_reset():
    global KILL_SWITCH, START_EQUITY, DAILY_START_EQUITY, LAST_DAY
    global daily_loss, consecutive_loss, current_risk
    global SYMBOL_COOLDOWN, GLOBAL_SYMBOL_LOCK, EXECUTION_IN_PROGRESS

    KILL_SWITCH = False
    START_EQUITY = None
    DAILY_START_EQUITY = None
    LAST_DAY = None
    daily_loss = 0
    consecutive_loss = 0
    current_risk = BASE_RISK
    SYMBOL_COOLDOWN = {}
    GLOBAL_SYMBOL_LOCK = set()
    EXECUTION_IN_PROGRESS = set()

    save_runtime_state()
    return {"status": "reset_ok"}

@app.get("/health/locks")
def health_locks():
    cooldowns = {}
    for sym in list(SYMBOL_COOLDOWN.keys()):
        left = get_symbol_cooldown_left(sym)
        if left > 0:
            cooldowns[sym] = left

    return {
        "symbol_lock_count": len(GLOBAL_SYMBOL_LOCK),
        "execution_in_progress_count": len(EXECUTION_IN_PROGRESS),
        "locked_symbols": sorted(list(GLOBAL_SYMBOL_LOCK)),
        "executing_symbols": sorted(list(EXECUTION_IN_PROGRESS)),
        "cooldowns": cooldowns,
    }

@app.post("/health/ws/restart")
def health_ws_restart():
    try:
        restart_ws(PAIRS, interval="15m")
        return {"status": "restarted"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/health/bot")
def health_bot():
    return {
        "mode": MONTRA_MODE,
        "auto_mode": AUTO_MODE,
        "auto_trading": AUTO_TRADING,
        "profile": MONTRA_PROFILE,
        "validation_mode": VALIDATION_MODE,
        "kill_switch": KILL_SWITCH,
        "max_open_trades": MAX_OPEN_TRADES,
        "symbol_lock_count": len(GLOBAL_SYMBOL_LOCK),
        "active_accounts": len(CLIENTS),
    }

@app.get("/replay/open")
def replay_open():
    return {
        "count": len(TRADE_SNAPSHOTS),
        "rows": TRADE_SNAPSHOTS
    }

@app.get("/replay/history")
def replay_history(limit: int = Query(default=50, ge=1, le=500)):
    return {
        "count": min(limit, len(TRADE_REPLAY_LOG)),
        "rows": TRADE_REPLAY_LOG[-limit:]
    }

@app.get("/analytics/summary")
def analytics_summary():
    total = len(trade_history)
    wins = sum(1 for t in trade_history if t.get("result") == "WIN")
    losses = sum(1 for t in trade_history if t.get("result") == "LOSS")
    pnl_total = sum(float(t.get("pnl", 0)) for t in trade_history)

    winrate = (wins / total * 100) if total > 0 else 0.0

    best = None
    worst = None

    if trade_history:
        best = max(trade_history, key=lambda x: float(x.get("pnl", 0)))
        worst = min(trade_history, key=lambda x: float(x.get("pnl", 0)))

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "winrate_pct": round(winrate, 2),
        "pnl_total": round(pnl_total, 4),
        "best_trade": best,
        "worst_trade": worst,
        "open_snapshots": len(TRADE_SNAPSHOTS),
        "replay_log_size": len(TRADE_REPLAY_LOG),
    }

@app.get("/analytics/by-symbol")
def analytics_by_symbol():
    rows = {}

    for t in trade_history:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in rows:
            rows[sym] = {
                "symbol": sym,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "pnl": 0.0,
            }

        rows[sym]["trades"] += 1
        if t.get("result") == "WIN":
            rows[sym]["wins"] += 1
        else:
            rows[sym]["losses"] += 1
        rows[sym]["pnl"] += float(t.get("pnl", 0))

    for sym in rows:
        total = rows[sym]["trades"]
        rows[sym]["winrate_pct"] = round((rows[sym]["wins"] / total * 100) if total > 0 else 0.0, 2)
        rows[sym]["pnl"] = round(rows[sym]["pnl"], 4)

    return {"rows": list(rows.values())}

@app.get("/analytics/by-regime")
def analytics_by_regime():
    rows = {}

    for t in trade_history:
        regime = t.get("regime", "UNKNOWN")
        if regime not in rows:
            rows[regime] = {
                "regime": regime,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "pnl": 0.0,
            }

        rows[regime]["trades"] += 1
        if t.get("result") == "WIN":
            rows[regime]["wins"] += 1
        else:
            rows[regime]["losses"] += 1
        rows[regime]["pnl"] += float(t.get("pnl", 0))

    for regime in rows:
        total = rows[regime]["trades"]
        rows[regime]["winrate_pct"] = round((rows[regime]["wins"] / total * 100) if total > 0 else 0.0, 2)
        rows[regime]["pnl"] = round(rows[regime]["pnl"], 4)

    return {"rows": list(rows.values())}

@app.get("/debug/ws-detail")
def debug_ws_detail():
    status = get_ws_status()
    gate = ws_health_snapshot()
    return {
        "running": status.get("running"),
        "thread_alive": status.get("thread_alive"),
        "app_alive": status.get("app_alive"),
        "restart_count": status.get("restart_count"),
        "last_error": status.get("last_error"),

        "message_count": status.get("message_count"),
        "last_message_age": status.get("last_message_age"),
        "last_stream": status.get("last_stream"),
        "last_event": status.get("last_event"),
        "subscribed_count": status.get("subscribed_count"),
        "subscribed_sample": status.get("subscribed_sample"),

        "healthy": gate["healthy"],
        "degraded": gate["degraded"],
        "block": gate["block"],
        "reason": gate["reason"],
        "stale": gate["stale"],
        "sample_age": gate["sample_age"],
        "since_good": gate["since_good"],
    }


@app.get("/debug/pair-tiers")
def debug_pair_tiers():
    rows = []
    for sym in PAIRS:
        rows.append({
            "symbol": sym,
            "tier": get_pair_tier(sym),
            "bonus": tier_score_bonus(sym),
        })
    return {"rows": rows}

@app.get("/debug/candidates")
def debug_candidates():
    rows = sorted(candidate_list_live, key=lambda x: x.get("score", 0), reverse=True)
    return {
        "count": len(rows),
        "rows": rows[:20]
    }

@app.get("/debug/selected")
def debug_selected():
    return {
        "count": len(selected_rows_live),
        "rows": selected_rows_live
    }

@app.get("/debug/skip-reasons")
def debug_skip_reasons(limit: int = Query(default=100, ge=1, le=300)):
    rows = skip_reasons_live[-limit:]

    summary = {}
    for row in rows:
        reason = row["reason"]
        summary[reason] = summary.get(reason, 0) + 1

    summary_rows = [
        {"reason": reason, "count": count}
        for reason, count in sorted(summary.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "count": len(rows),
        "summary": summary_rows,
        "rows": rows
    }


@app.get("/debug/portfolio")
def debug_portfolio():
    rows = []
    for sym in PAIRS:
        mem = ai_memory.get(sym)
        rows.append({
            "symbol": sym,
            "tier": get_pair_tier(sym),
            "weight": round(float(portfolio_alloc.get(sym, 0.0)), 6),
            "has_memory": mem is not None,
            "memory_score": round(safe_score(mem) if mem is not None else (50 if VALIDATION_MODE else 35), 2),
        })

    rows.sort(key=lambda x: x["weight"], reverse=True)
    return {
        "count": len(rows),
        "rows": rows,
        "total_weight": round(sum(r["weight"] for r in rows), 6),
    }


@app.get("/debug/execution-decisions")
def debug_execution_decisions(limit: int = Query(default=100, ge=1, le=500)):
    rows = EXECUTION_DECISIONS[-limit:]
    return {
        "count": len(rows),
        "rows": rows,
    }

@app.get("/debug/decision-board")
def debug_decision_board():
    candidate_rows = sorted(candidate_list_live, key=lambda x: x.get("score", 0), reverse=True)

    skip_rows = skip_reasons_live[-100:]
    skip_summary = {}
    for row in skip_rows:
        reason = row["reason"]
        skip_summary[reason] = skip_summary.get(reason, 0) + 1

    skip_summary_rows = [
        {"reason": reason, "count": count}
        for reason, count in sorted(skip_summary.items(), key=lambda x: x[1], reverse=True)
    ]

    ws_status = get_ws_status()
    ws_gate = ws_health_snapshot()

    portfolio_rows = sorted(
        [{"symbol": sym, "weight": round(float(portfolio_alloc.get(sym, 0.0)), 6)} for sym in PAIRS],
        key=lambda x: x["weight"],
        reverse=True,
    )[:10]

    try:
        live_rows = build_live_position_rows()
    except Exception as e:
        live_rows = []
        add_execution_decision("decision_board_positions", "_SYSTEM_", "WARN", {"error": str(e)})

    return {
        "mode": MONTRA_MODE,
        "validation_mode": VALIDATION_MODE,
        "kill_switch": KILL_SWITCH,
        "auto_mode": AUTO_MODE,
        "auto_trading": AUTO_TRADING,

        "ws": {
            "running": ws_status["running"],
            "thread_alive": ws_status["thread_alive"],
            "restart_count": ws_status["restart_count"],
            "last_error": ws_status["last_error"],
            "sample_age": ws_gate["sample_age"],
            "healthy": ws_gate["healthy"],
            "degraded": ws_gate["degraded"],
            "block": ws_gate["block"],
            "reason": ws_gate["reason"],
            "stale": ws_gate["stale"],
            "since_good": ws_gate["since_good"],
        },

        "risk": {
            "start_equity": START_EQUITY,
            "daily_start_equity": DAILY_START_EQUITY,
            "daily_loss": daily_loss,
            "current_risk": current_risk,
            "max_open_trades": MAX_OPEN_TRADES,
        },

        "locks": {
            "symbol_lock_count": len(GLOBAL_SYMBOL_LOCK),
            "execution_in_progress_count": len(EXECUTION_IN_PROGRESS),
            "locked_symbols": sorted(list(GLOBAL_SYMBOL_LOCK)),
            "executing_symbols": sorted(list(EXECUTION_IN_PROGRESS)),
        },

        "portfolio": {
            "rows": portfolio_rows
        },

        "candidates": {
            "count": len(candidate_rows),
            "rows": candidate_rows[:20]
        },

        "selected": {
            "count": len(selected_rows_live),
            "rows": selected_rows_live
        },

        "live_positions": {
            "count": len(live_rows),
            "rows": live_rows[:10],
        },

        "skip_reasons": {
            "count": len(skip_rows),
            "summary": skip_summary_rows[:20],
            "rows": skip_rows[-20:]
        },

        "execution_decisions": {
            "count": len(EXECUTION_DECISIONS),
            "rows": EXECUTION_DECISIONS[-20:],
        },

        "analytics": {
            "total_trades": len(trade_history),
            "open_snapshots": len(TRADE_SNAPSHOTS),
            "replay_log_size": len(TRADE_REPLAY_LOG),
        }
    }

@app.get("/position-detail/{symbol}")
def position_detail(symbol: str):
    if binance is None:
        return {"position": None, "trades": []}    
    try:
        positions = signed_call(binance, binance.futures_position_information, symbol=symbol, label="MAIN")
        trades = signed_call(binance, binance.futures_account_trades, symbol=symbol, label="MAIN")
        pos = next((p for p in positions if float(p["positionAmt"]) != 0), None)
        open_orders = signed_call(binance, binance.futures_get_open_orders, symbol=symbol, label="MAIN")
        exits = build_exit_lookup(open_orders).get(symbol, {})
        return {"position": pos, "trades": trades[-50:], "sl": exits.get("sl"), "tp": exits.get("tp")}
    except Exception as e:
        return {"error": str(e)}

@app.get("/positions")
def get_positions():
    try:
        rows = build_live_position_rows()
        return {"count": len(rows), "rows": rows}
    except Exception as e:
        return {"count": 0, "rows": [], "error": str(e)}


@app.post("/positions/{symbol}/protect")
def protect_position(symbol: str, payload: dict = Body(...)):
    """
    Emergency/manual exchange-level protection resolver.

    Payload:
    {
        "side": "BUY" | "SELL",  # optional; auto-derived from open position if omitted
        "sl": 450.0,
        "tp": 470.0
    }
    """
    if binance is None:
        return {"status": "rejected", "reason": "binance client not ready"}

    symbol = symbol.upper().strip()
    sl_raw = payload.get("sl")
    tp_raw = payload.get("tp")
    side_raw = payload.get("side")

    if sl_raw is None or tp_raw is None:
        return {"status": "rejected", "reason": "sl and tp required"}

    try:
        sl = float(sl_raw)
        tp = float(tp_raw)
    except Exception:
        return {"status": "rejected", "reason": "sl and tp must be numeric"}

    if sl <= 0 or tp <= 0:
        return {"status": "rejected", "reason": "sl and tp must be > 0"}

    try:
        positions = signed_call(binance, binance.futures_position_information, symbol=symbol, label="MAIN")
        pos = next((p for p in positions if abs(float(p.get("positionAmt", 0) or 0)) > 0), None)
        if not pos:
            return {"status": "rejected", "reason": "no open position for symbol"}

        amt = float(pos.get("positionAmt", 0) or 0)
        entry = float(pos.get("entryPrice", 0) or 0)
        mark = float(pos.get("markPrice", 0) or 0)
        side = str(side_raw or ("BUY" if amt > 0 else "SELL")).upper()

        if side not in ("BUY", "SELL"):
            return {"status": "rejected", "reason": "side must be BUY or SELL"}

        ref_price = mark if mark > 0 else entry
        if side == "BUY":
            if sl >= ref_price:
                return {"status": "rejected", "reason": "BUY protection invalid: SL must be below mark/entry"}
            if tp <= ref_price:
                return {"status": "rejected", "reason": "BUY protection invalid: TP must be above mark/entry"}
            close_side = SIDE_SELL
        else:
            if sl <= ref_price:
                return {"status": "rejected", "reason": "SELL protection invalid: SL must be above mark/entry"}
            if tp >= ref_price:
                return {"status": "rejected", "reason": "SELL protection invalid: TP must be below mark/entry"}
            close_side = SIDE_BUY

        sl_price = normalize_price(symbol, sl)
        tp_price = normalize_price(symbol, tp)

        cancel_ok = cancel_existing_orders(symbol, cancel_tp=True, cancel_sl=True)
        if not cancel_ok:
            return {"status": "rejected", "reason": "failed to cancel existing protective orders"}

        sl_order = signed_call(
            binance,
            binance.futures_create_order,
            label="MAIN",
            symbol=symbol,
            side=close_side,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=sl_price,
            closePosition=True,
            workingType="MARK_PRICE",
        )

        tp_order = signed_call(
            binance,
            binance.futures_create_order,
            label="MAIN",
            symbol=symbol,
            side=close_side,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=tp_price,
            closePosition=True,
            workingType="MARK_PRICE",
        )

        invalidate_main_positions_cache()
        invalidate_main_open_orders_cache()

        detail = {
            "side": side,
            "entry": entry,
            "mark": mark,
            "sl": sl_price,
            "tp": tp_price,
            "position_amt": amt,
        }
        add_order_audit("MANUAL_PROTECT_OK", symbol, detail)

        return {
            "status": "OK",
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "mark": mark,
            "sl": sl_price,
            "tp": tp_price,
            "orders": {
                "sl": sl_order,
                "tp": tp_order,
            },
        }

    except Exception as e:
        err = str(e)
        add_order_audit("MANUAL_PROTECT_ERROR", symbol, {"error": err})
        return {"status": "error", "error": err}


@app.get("/accounts")
def get_accounts():
    data = []
    had_error = False
    for acc in CLIENTS:
        try:
            c = acc["client"]
            balance_info = signed_call(c, c.futures_account_balance, label=acc["name"])
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
            balance = float((usdt or {}).get("balance", 0) or 0)
            if c is binance:
                positions = fetch_main_positions(force=False, max_age=POSITION_CACHE_TTL, label=acc["name"])
            else:
                positions = signed_call(c, c.futures_position_information, label=acc["name"])
            active = [p for p in positions if float(p.get("positionAmt", 0) or 0) != 0]
            unrealized = sum(float(p.get("unRealizedProfit", 0) or 0) for p in active)
            equity = balance + unrealized
            data.append({
                "name": acc["name"],
                "balance": balance,
                "equity": equity,
                "unrealized": unrealized,
                "positions": len(active)
            })
        except Exception as e:
            had_error = True
            data.append({"name": acc["name"], "error": str(e)})

    if data and not had_error:
        set_cached_accounts_summary(data)
        return {"accounts": data}

    cached = get_cached_accounts_summary(max_age=45)
    if cached is not None:
        return {"accounts": cached, "cached": True, "warning": "accounts summary using cached snapshot"}

    return {"accounts": data}

@app.post("/kill-switch")
def kill_switch(payload: dict = Body(...)):
    global KILL_SWITCH
    state = payload.get("state", True)
    KILL_SWITCH = state
    save_runtime_state()
    return {"kill_switch": KILL_SWITCH}

@app.get("/ai-memory")
def get_ai_memory():
    return ai_memory

# ⭐ NEW: signal receiver endpoint
@app.post("/signal")
def receive_signal(signal: dict):
    global LAST_SIGNAL

    LAST_SIGNAL = signal
    symbol = signal.get("symbol")

    if not symbol:
        return {"status": "rejected", "reason": "NO_SYMBOL"}

    ok, reason = should_execute_trade(signal)
    if not ok:
        add_order_audit("SIGNAL_REJECTED", symbol, {"reason": reason, "signal": signal})
        return {"status": "rejected", "reason": reason}

    if symbol in EXECUTION_IN_PROGRESS:
        add_order_audit("SIGNAL_REJECTED", symbol, {"reason": "EXECUTION_IN_PROGRESS", "signal": signal})
        return {"status": "rejected", "reason": "EXECUTION_IN_PROGRESS"}

    EXECUTION_IN_PROGRESS.add(symbol)
    GLOBAL_SYMBOL_LOCK.add(symbol)

    snapshot = {
        "opened_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "signal_endpoint",
        "signal": signal,
        "score": signal.get("score", 0),
        "side": signal.get("type"),
        "sl": signal.get("sl"),
        "tp": signal.get("tp"),
        "entry": signal.get("entry"),
        "regime": None,
        "vol": None,
        "news_bias": None,
    }

    save_trade_snapshot(symbol, snapshot)
    add_order_audit("SIGNAL_ACCEPTED", symbol, {"signal": signal})

    def execute():
        try:
            result = place_order_multi(
                signal["symbol"],
                signal["type"],
                signal["sl"],
                signal["tp"]
            )

            position_entry_score[signal["symbol"]] = signal.get("score", 0)

            add_order_audit("ORDER_SENT", symbol, {
                "type": signal.get("type"),
                "score": signal.get("score", 0),
                "sl": signal.get("sl"),
                "tp": signal.get("tp"),
                "result": result,
            })

            send_telegram(
                f"🚀 SIGNAL TRADE\n"
                f"{signal['symbol']} {signal['type']}\n"
                f"Score: {signal.get('score', 0)}"
            )

        except Exception as e:
            add_order_audit("ORDER_ERROR", symbol, {"error": str(e)})
            set_symbol_cooldown(symbol, reason="order_error")
            GLOBAL_SYMBOL_LOCK.discard(symbol)

        finally:
            EXECUTION_IN_PROGRESS.discard(symbol)

    threading.Thread(target=execute, daemon=True).start()
    return {"status": "accepted", "reason": "EXECUTING"}
    
def smart_trailing():
    while True:
        try:
            if binance is None:
                time.sleep(TRAILING_LOOP_INTERVAL)
                continue
            positions = fetch_main_positions(force=False, max_age=TRAILING_LOOP_INTERVAL, label="MAIN")
            for p in positions:
                amt = float(p["positionAmt"])
                if amt == 0:
                    continue
                symbol = p["symbol"]
                entry = float(p["entryPrice"])
                price = float(p.get("markPrice", p.get("entryPrice", 0)) or 0)
                if entry <= 0 or price <= 0:
                    continue
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
            time.sleep(TRAILING_LOOP_INTERVAL)
        except Exception as e:
            print("Trailing error:", e)
            if is_rate_limit_error(e):
                time.sleep(POSITION_RATE_LIMIT_SLEEP)
            else:
                time.sleep(TRAILING_LOOP_INTERVAL)

def apply_news_bias(signal_type, news_reverse):
    if news_reverse:
        return "SELL" if signal_type == "BUY" else "BUY"
    return signal_type

def auto_trader():
    global candidate_list_live, selected_symbols_live, selected_rows_live, skip_reasons_live
    while True:
        try:
            check_telegram_commands()

            if KILL_SWITCH:
                print("🛑 KILL SWITCH ACTIVE")
                time.sleep(5)
                continue

            if not AUTO_MODE:
                time.sleep(SCAN_INTERVAL)
                continue

            if not AUTO_TRADING:
                print("⏸️ AUTO TRADING DISABLED")
                time.sleep(SCAN_INTERVAL)
                continue

            ws_auto_heal()

            ws_gate = ws_health_snapshot()
            if ws_gate["block"]:
                candidate_list_live = []
                selected_symbols_live = []
                selected_rows_live = []
                skip_reasons_live = [{
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": "_SYSTEM_",
                    "reason": "WS_DATA_NOT_HEALTHY",
                    "detail": ws_gate,
                }]
                add_execution_decision("ws_gate", "_SYSTEM_", "BLOCK", ws_gate)
                print(f"⏸️ Skip trade: WS data not healthy ({ws_gate['reason']})")
                time.sleep(5)
                continue
            if not safety_check():
                time.sleep(10)
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
            news_reverse = (news_impact == "HIGH" and not VALIDATION_MODE and LIVE_NEWS_REVERSE and not active_news_block())

            if news_impact == "HIGH":
                if active_news_block():
                    print("📰 HIGH IMPACT NEWS → BLOCK")
                    time.sleep(SCAN_INTERVAL)
                    continue
                elif news_reverse:
                    print("📰 HIGH IMPACT NEWS → reverse enabled")
                else:
                    print("📰 HIGH IMPACT NEWS → score penalty only")

            if vol < active_vol_min():
                print(f"⏸️ Skip: low volatility ({vol:.4f})")
                time.sleep(SCAN_INTERVAL)
                continue

            if vol > active_vol_max():
                print(f"⚠️ Skip: high volatility ({vol:.4f})")
                time.sleep(SCAN_INTERVAL)
                continue

            session = get_session_utc()
            if not session_allowed(session):
                print(f"⏸️ Skip: off session ({session})")
                time.sleep(SCAN_INTERVAL)
                continue

            candidate_list_live = []
            selected_symbols_live = []
            selected_rows_live = []
            skip_reasons_live = []

            pairs = PAIRS.copy()

            pairs = PAIRS.copy()
            scores_map = {}
            candidate_map = {"TOP": [], "MID": [], "LOW": []}

            # --- Kumpulkan skor untuk semua pair ---
            for symbol in pairs:
                try:
                    if symbol in disabled_pairs:
                        add_skip_reason(symbol, "DISABLED_PAIR")
                        continue

                    if not check_pair_health(symbol):
                        add_skip_reason(symbol, "PAIR_HEALTH_FAIL")
                        continue

                    if not ai_allow_trade(symbol):
                        add_skip_reason(symbol, "AI_BLOCK")
                        continue

                    ohlcv = fetch_futures_klines_cached(symbol, interval="15m", limit=100)
                    
                    live = get_live_candle(symbol)
                    if live and get_live_age(symbol) < 10:
                        last_price = live["close"]
                    else:
                        last_price = float(ohlcv[-1][4])

                    # === STRUCTURE LOGIC V2 ===
                    highs = [float(c[2]) for c in ohlcv]
                    lows = [float(c[3]) for c in ohlcv]

                    structure = analyze_structure_v3(ohlcv, last_price=last_price)
                    if not structure["ok"]:
                        add_skip_reason(symbol, structure["reason"])
                        continue

                    signal_type = structure["signal_type"]
                    structure_grade = structure["grade"]
                    fvg_up = structure["fvg_up"]
                    fvg_down = structure["fvg_down"]

                    # === FILTER FAKE MOVE (liquidity sweep) ===
                    last_candle = ohlcv[-1]
                    prev_candle = ohlcv[-2]

                    wick_up = float(last_candle[2]) - max(float(last_candle[1]), float(last_candle[4]))
                    wick_down = min(float(last_candle[1]), float(last_candle[4])) - float(last_candle[3])

                    if wick_up > wick_down * 2 and signal_type == "BUY":
                        add_skip_reason(symbol, "FAKE_MOVE_WICK_UP")
                        continue
                    if wick_down > wick_up * 2 and signal_type == "SELL":
                        add_skip_reason(symbol, "FAKE_MOVE_WICK_DOWN")
                        continue

                    # === LIQUIDITY SWEEP CHECK ===
                    recent_high = max(highs[-11:-1])
                    recent_low = min(lows[-11:-1])

                    sweep_high = highs[-1] > recent_high
                    sweep_low = lows[-1] < recent_low

                    if active_require_sweep():
                        if signal_type == "BUY" and not sweep_low:
                            add_skip_reason(symbol, "NO_SWEEP_LOW")
                            continue
                        if signal_type == "SELL" and not sweep_high:
                            add_skip_reason(symbol, "NO_SWEEP_HIGH")
                            continue

                    # === BUY RUMOR / SELL NEWS ===
                    # [!] LOGIC FIX: Posisi dipindah ke sini agar SL dan TP dihitung dengan arah yang sudah di-reverse
                    # news impact dipakai lewat apply_news_bias() saja

                    # === ENTRY, SL, TP ===
                    ob_candle = ohlcv[-4]

                    final_side = apply_news_bias(signal_type, news_reverse)
                    
                    pair_regime = get_multi_tf_regime(symbol)

                    if not active_require_pair_regime_match():
                        if pair_regime == "SIDEWAYS" and active_allow_sideways_score_penalty():
                            pass
                    else:
                        if pair_regime == "SIDEWAYS":
                            add_skip_reason(symbol, "PAIR_REGIME_SIDEWAYS")
                            continue
                        if pair_regime == "BULL" and final_side != "BUY":
                            add_skip_reason(symbol, "PAIR_REGIME_BULL_MISMATCH")
                            continue
                        if pair_regime == "BEAR" and final_side != "SELL":
                            add_skip_reason(symbol, "PAIR_REGIME_BEAR_MISMATCH")
                            continue
                    
                    rr_target = active_target_rr()
                    if final_side == "BUY":
                        sl = float(ob_candle[3])  # low OB
                        tp = last_price + (last_price - sl) * rr_target
                    else:
                        sl = float(ob_candle[2])  # high OB
                        tp = last_price - (sl - last_price) * rr_target
                        
                    rr = abs(tp - last_price) / max(abs(last_price - sl), 1e-9)
                    if rr < active_rr_min():
                        add_skip_reason(symbol, "LOW_RR", {
                            "rr": round(rr, 2),
                            "min_rr": active_rr_min()
                        })
                        continue
                    
                    signal = {
                        "symbol": symbol,
                        "type": final_side,
                        "entry": last_price,
                        "sl": sl,
                        "tp": tp,
                        "score": 85 if structure_grade == "STRONG" else 72,
                        "structure_grade": structure_grade,
                    }

                    score = meta_score(symbol, signal, regime, vol)
                    
                    ml_prob = ml_predict(build_ml_features(
                        symbol, final_side, regime, vol, news_reverse, fvg_up, fvg_down, sweep_high, sweep_low
                    ))
                    score = round((score * 0.8) + (ml_prob * 100 * 0.2))
                    score += structure_score_adjustment(structure)
                                                          
                    if news_impact == "HIGH":
                        score -= 2 if VALIDATION_MODE else 6

                    # === SMC BOOST ===
                    if fvg_up or fvg_down:
                        score += 5
                    if sweep_high or sweep_low:
                        score += 5
                    if structure.get("reclaim_up") or structure.get("reclaim_down"):
                        score += 3

                    # === NEWS FACTOR ===
                    if news_impact == "HIGH":
                        score -= 4 if VALIDATION_MODE else 10
                    elif news_impact == "NORMAL":
                        score += 6 if VALIDATION_MODE else 8

                    score += tier_score_bonus(symbol)

                    if pair_regime == "SIDEWAYS" and active_allow_sideways_score_penalty():
                        score -= 4

                    score = max(0, min(score, 100))
                    scores_map[symbol] = score
                    tier = get_pair_tier(symbol)

                    row = {
                        "symbol": symbol,
                        "tier": tier,
                        "score": score,
                        "side": final_side,
                        "type": final_side,
                        "entry": round(float(last_price), 8),
                        "sl": round(float(sl), 8),
                        "tp": round(float(tp), 8),
                        "rr": round(rr, 2),
                        "pair_regime": pair_regime,
                        "regime": pair_regime,
                        "news_impact": news_impact,
                        "session": session,
                        "structure_grade": structure_grade,
                    }

                    candidate_map[tier].append(row)
                    candidate_list_live.append(row)
                    
                    if VALIDATION_MODE:
                        print(f"🧪 CANDIDATE {symbol} tier={get_pair_tier(symbol)} side={final_side} score={score} rr={rr:.2f} regime={pair_regime} news={news_impact} session={session} vol={vol:.4f}")

                except Exception as e:
                    print(f"Scoring error {symbol}: {e}")

            # --- Eksekusi trade dengan decision engine ---
            selected_symbols = set()
            candidate_symbols = set()
            candidate_rank_map = {}
            selected_row_map = {}

            for tier_name, limit in tier_limits().items():
                rows = sorted(candidate_map[tier_name], key=lambda x: x["score"], reverse=True)
                for idx, row in enumerate(rows, start=1):
                    sym = row["symbol"]
                    candidate_symbols.add(sym)
                    candidate_rank_map[sym] = {
                        "tier": tier_name,
                        "rank": idx,
                        "score": round(float(row.get("score", 0)), 2),
                        "rr": round(float(row.get("rr", 0)), 2),
                        "limit": limit,
                    }
                    if idx <= limit:
                        selected_symbols.add(sym)
                        selected_row_map[sym] = {
                            **row,
                            "rank": idx,
                            "limit": limit,
                            "portfolio_weight": round(float(portfolio_alloc.get(sym, 0.0)), 6),
                        }

            selected_symbols_live = sorted(list(selected_symbols))
            selected_rows_live = sorted(
                list(selected_row_map.values()),
                key=lambda x: x.get("score", 0),
                reverse=True,
            )

            if VALIDATION_MODE:
                print("🎯 SELECTED SYMBOLS:", selected_symbols_live)

            for row in selected_rows_live:
                sym = row["symbol"]
                add_execution_decision("shortlist", sym, "PASS", {
                    "weight": round(float(portfolio_alloc.get(sym, 0.0)), 6),
                    "tier": get_pair_tier(sym),
                })
            
            for symbol in pairs:
                try:
                    if symbol not in selected_symbols:
                        if symbol in candidate_symbols:
                            shortlist_meta = candidate_rank_map.get(symbol, {})
                            add_skip_reason(symbol, "NOT_IN_SHORTLIST", shortlist_meta)
                            add_execution_decision("shortlist", symbol, "BLOCK", shortlist_meta)
                        continue
                    if not check_pair_health(symbol):
                        add_skip_reason(symbol, "PAIR_HEALTH_FAIL_EXEC")
                        continue
                    if not ai_allow_trade(symbol):
                        add_skip_reason(symbol, "AI_BLOCK_EXEC")
                        continue

                    w = portfolio_alloc.get(symbol, 0)
                    if w <= 0:
                        add_skip_reason(symbol, "ZERO_PORTFOLIO_WEIGHT")
                        add_execution_decision("portfolio", symbol, "BLOCK", {"weight": round(float(w), 6)})
                        continue

                    ohlcv = fetch_futures_klines_cached(symbol, interval="15m", limit=100)
                    
                    live = get_live_candle(symbol)
                    if live and get_live_age(symbol) < 10:
                        last_price = live["close"]
                    else:
                        last_price = float(ohlcv[-1][4])

                    # === STRUCTURE LOGIC V2 ===
                    highs = [float(c[2]) for c in ohlcv]
                    lows = [float(c[3]) for c in ohlcv]

                    structure = analyze_structure_v3(ohlcv, last_price=last_price)
                    if not structure["ok"]:
                        add_skip_reason(symbol, structure["reason"])
                        continue

                    signal_type = structure["signal_type"]
                    structure_grade = structure["grade"]
                    fvg_up = structure["fvg_up"]
                    fvg_down = structure["fvg_down"]

                    # === FILTER FAKE MOVE (liquidity sweep) ===
                    last_candle = ohlcv[-1]
                    prev_candle = ohlcv[-2]

                    wick_up = float(last_candle[2]) - max(float(last_candle[1]), float(last_candle[4]))
                    wick_down = min(float(last_candle[1]), float(last_candle[4])) - float(last_candle[3])

                    if wick_up > wick_down * 2 and signal_type == "BUY":
                        add_skip_reason(symbol, "FAKE_MOVE_WICK_UP")
                        continue
                    if wick_down > wick_up * 2 and signal_type == "SELL":
                        add_skip_reason(symbol, "FAKE_MOVE_WICK_DOWN")
                        continue

                    # === LIQUIDITY SWEEP CHECK ===
                    recent_high = max(highs[-11:-1])
                    recent_low = min(lows[-11:-1])

                    sweep_high = highs[-1] > recent_high
                    sweep_low = lows[-1] < recent_low

                    if active_require_sweep():
                        if signal_type == "BUY" and not sweep_low:
                            add_skip_reason(symbol, "NO_SWEEP_LOW")
                            continue
                        if signal_type == "SELL" and not sweep_high:
                            add_skip_reason(symbol, "NO_SWEEP_HIGH")
                            continue

                    # === BUY RUMOR / SELL NEWS ===
                    # [!] LOGIC FIX: Posisi dipindah ke sini agar SL dan TP dihitung dengan arah yang sudah di-reverse
                    # news impact dipakai lewat apply_news_bias() saja, jangan reversal dua kali

                    # === ENTRY, SL, TP ===
                    ob_candle = ohlcv[-4]

                    final_side = apply_news_bias(signal_type, news_reverse)
                    
                    pair_regime = get_multi_tf_regime(symbol)

                    if active_require_pair_regime_match():
                        if pair_regime == "SIDEWAYS":
                            continue
                        if pair_regime == "BULL" and final_side != "BUY":
                            continue
                        if pair_regime == "BEAR" and final_side != "SELL":
                            continue
                    
                    rr_target = active_target_rr()
                    if final_side == "BUY":
                        sl = float(ob_candle[3])  # low OB
                        tp = last_price + (last_price - sl) * rr_target
                    else:
                        sl = float(ob_candle[2])  # high OB
                        tp = last_price - (sl - last_price) * rr_target
                        
                    rr = abs(tp - last_price) / max(abs(last_price - sl), 1e-9)
                    if rr < active_rr_min():
                        continue
                    
                    signal = {
                        "symbol": symbol,
                        "type": final_side,
                        "entry": last_price,
                        "sl": sl,
                        "tp": tp,
                        "score": scores_map.get(symbol, 0),
                        "pair_regime": pair_regime,
                        "sweep_high": sweep_high,
                        "sweep_low": sweep_low,
                        "rr": round(rr, 2),
                        "structure_grade": structure_grade,
                    }

                    min_score_needed = tier_score_floor(symbol)
                    if signal["score"] < min_score_needed:
                        add_skip_reason(symbol, "LOW_SCORE_FINAL_LOCK", {
                            "score": round(float(signal["score"]), 2),
                            "min_score": min_score_needed,
                        })
                        add_execution_decision("score_floor", symbol, "BLOCK", {
                            "score": round(float(signal["score"]), 2),
                            "min_score": min_score_needed,
                        })
                        continue

                    ml_prob = ml_predict(build_ml_features(
                        symbol, final_side, regime, vol, news_reverse, fvg_up, fvg_down, sweep_high, sweep_low
                    ))
                    score = round((scores_map.get(symbol, 0) * 0.8) + (ml_prob * 100 * 0.2))
                    signal["score"] = score
                    
                    ok, reason = should_execute_trade(signal)
                    add_execution_decision("should_execute_trade", symbol, "PASS" if ok else "BLOCK", {
                        "reason": reason,
                        "score": round(float(signal["score"]), 2),
                        "rr": round(rr, 2),
                        "weight": round(float(w), 6),
                    })
                    if not ok:
                        add_skip_reason(symbol, reason, {
                            "score": signal["score"],
                            "rr": round(rr, 2)
                        })
                        if VALIDATION_MODE:
                            print(f"🧪 SKIP {symbol} - {reason} score={signal['score']} rr={rr:.2f}")
                        else:
                            print(f"❌ SKIP {symbol} - {reason}")
                        continue

                    if regime == "SIDEWAYS":
                        add_skip_reason(symbol, "GLOBAL_REGIME_SIDEWAYS")
                        print(f"⏸️ Skip {symbol}: market SIDEWAYS")
                        continue
                    if regime == "BULL" and signal["type"] != "BUY":
                        add_skip_reason(symbol, "GLOBAL_REGIME_BULL_MISMATCH")
                        print(f"⏸️ Skip {symbol}: BULL market but signal SELL")
                        continue
                    if regime == "BEAR" and signal["type"] != "SELL":
                        add_skip_reason(symbol, "GLOBAL_REGIME_BEAR_MISMATCH")
                        print(f"⏸️ Skip {symbol}: BEAR market but signal BUY")
                        continue

                    signal_trend = "BULLISH" if signal["type"] == "BUY" else "BEARISH"
                    btc_align = btc_alignment(symbol, signal_trend)

                    if not btc_align["ok"]:
                        add_skip_reason(symbol, btc_align["reason"])
                        add_execution_decision("btc_alignment", symbol, "BLOCK", btc_align)
                        print(f"🧠 BTC BLOCK {symbol} - {btc_align['reason']}")
                        continue

                    add_execution_decision("btc_alignment", symbol, "PASS", btc_align)

                    signal["score"] = max(0, signal["score"] - btc_align["penalty"])

                    btc_strength = _get_strength("BTCUSDT")
                    alt_strength = _get_strength(symbol)

                    divergence_limit = 30.0 if get_pair_tier(symbol) == "TOP" else 20.0

                    if abs(btc_strength - alt_strength) > divergence_limit:
                        add_skip_reason(symbol, "STRENGTH_DIVERGENCE", {
                            "btc_strength": round(btc_strength, 2),
                            "alt_strength": round(alt_strength, 2),
                            "limit": divergence_limit
                        })
                        add_execution_decision("strength_divergence", symbol, "BLOCK", {
                            "btc_strength": round(btc_strength, 2),
                            "alt_strength": round(alt_strength, 2),
                            "limit": divergence_limit,
                        })
                        print(f"🧠 Strength divergence block: BTC {btc_strength:.2f}% vs {symbol} {alt_strength:.2f}% limit={divergence_limit}")
                        continue

                    add_execution_decision("strength_divergence", symbol, "PASS", {
                        "btc_strength": round(btc_strength, 2),
                        "alt_strength": round(alt_strength, 2),
                        "limit": divergence_limit,
                    })

                    positions = get_open_positions()
                    if len(positions) >= MAX_OPEN_TRADES:
                        print(f"❌ SKIP {symbol} - MAX_POSITION")
                        continue
                    if any(p["symbol"] == symbol for p in positions):
                        continue
                    
                    if symbol in GLOBAL_SYMBOL_LOCK:
                        print(f"🔒 SKIP {symbol} already open")
                        continue

                    dynamic_risk = get_dynamic_risk(regime, vol)
                    balance_info = signed_call(binance, binance.futures_account_balance, label="MAIN")
                    usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
                    balance = float(usdt["balance"]) if usdt else 0
                    risk_amount = balance * dynamic_risk * w

                    stop_distance = abs(signal["entry"] - signal["sl"])
                    qty = round(risk_amount / stop_distance, 3)

                    save_trade_snapshot(symbol, {
                        "opened_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source": "auto_trader",
                        "signal": signal,
                        "score": signal["score"],
                        "side": signal["type"],
                        "sl": signal["sl"],
                        "tp": signal["tp"],
                        "entry": signal["entry"],
                        "regime": regime,
                        "pair_regime": pair_regime,
                        "pair_tier": get_pair_tier(symbol),
                        "vol": vol,
                        "news_impact": news_impact,
                        "news_reverse": news_reverse,
                        "portfolio_weight": w,
                        "btc_strength": btc_strength,
                        "alt_strength": alt_strength,
                        "fvg_up": fvg_up,
                        "fvg_down": fvg_down,
                        "sweep_high": sweep_high,
                        "sweep_low": sweep_low,
                    })

                    add_execution_decision("order_attempt", symbol, "PASS", {
                        "side": signal["type"],
                        "score": round(float(signal["score"]), 2),
                        "weight": round(float(w), 6),
                        "entry": round(float(signal["entry"]), 8),
                        "sl": round(float(signal["sl"]), 8),
                        "tp": round(float(signal["tp"]), 8),
                    })

                    result = place_order_multi(
                        symbol=symbol,
                        side=signal["type"],
                        sl=signal["sl"],
                        tp=signal["tp"]
                    )

                    add_execution_decision("order_result", symbol, "PASS" if not any(isinstance(r, dict) and r.get("error") for r in (result or [])) else "BLOCK", {
                        "result": result,
                    })
                    
                    GLOBAL_SYMBOL_LOCK.add(symbol)

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
    load_runtime_state()
    clamp_runtime_state()

    if MONTRA_MODE == "api_only":
        print("⚠️ API ONLY mode → no WS, no bot, no trader")
        return

    load_exchange_cache()
    try:
        update_portfolio_allocation()
    except Exception as e:
        print("startup portfolio allocation error:", e)
    start_ws(PAIRS, interval="15m")

    try:
        for p in get_open_positions():
            sym = p["symbol"]
            GLOBAL_SYMBOL_LOCK.add(sym)
        reconcile_runtime_state_with_exchange()
        if GLOBAL_SYMBOL_LOCK:
            print("🔒 Recovered symbol locks:", sorted(list(GLOBAL_SYMBOL_LOCK)))
    except Exception as e:
        print("recover open positions error:", e)

    if not AUTO_MODE:
        print("⚠️ AUTO_MODE OFF → WS on, trader not started")
        return

    eq = get_total_equity()

    if eq is None or eq <= 0:
        print(f"⚠️ startup equity invalid: {eq}, skip baseline init")
    else:
        if START_EQUITY is None or START_EQUITY <= 0:
            START_EQUITY = eq

        if DAILY_START_EQUITY is None or DAILY_START_EQUITY <= 0:
            DAILY_START_EQUITY = eq

        if LAST_DAY is None:
            LAST_DAY = time.strftime("%Y-%m-%d")

        print("🧠 START EQUITY:", START_EQUITY)
        print("🧠 DAILY START EQUITY:", DAILY_START_EQUITY)

        save_runtime_state()

    threading.Thread(target=smart_trailing, daemon=True).start()
    threading.Thread(target=monitor_positions_for_memory_update, daemon=True).start()
    threading.Thread(target=start_bot, daemon=True).start()

@app.on_event("startup")
def on_startup():
    start_background_tasks()