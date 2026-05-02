import os
import time
import threading
import requests
import base64
import json
from dotenv import load_dotenv
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP

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
KILL_SWITCH_DEFAULT = (os.getenv("KILL_SWITCH", os.getenv("MONTRA_KILL_SWITCH", "false")) or "false").strip().lower() in ("1", "true", "yes", "on")

# ===== PROFILE / HARDENING =====
MONTRA_PROFILE = os.getenv("MONTRA_PROFILE", "final_lock").lower()
VALIDATION_MODE = os.getenv(
    "VALIDATION_MODE",
    "true" if MONTRA_PROFILE in ("validation", "sample_hunt") else "false"
).lower() == "true"

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10" if VALIDATION_MODE else "30"))
SCAN_INTERVAL_TOP = int(os.getenv("SCAN_INTERVAL_TOP", "30"))
SCAN_INTERVAL_MID = int(os.getenv("SCAN_INTERVAL_MID", "45"))
SCAN_INTERVAL_MID_AGGRESSIVE = int(os.getenv("SCAN_INTERVAL_MID_AGGRESSIVE", os.getenv("SCAN_INTERVAL_MID", "45")))
MIN_SCORE = int(os.getenv("MIN_SCORE", "85" if VALIDATION_MODE else "85"))

# safety core tetap dijaga, tapi live-safe lebih ketat
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "2" if VALIDATION_MODE else "3"))
# Atomic trade-slot reservation prevents multiple entries from racing past MAX_OPEN_TRADES
# while Binance position/order state is still propagating.
ENTRY_SLOT_TTL_SECONDS = float(os.getenv("ENTRY_SLOT_TTL_SECONDS", "180"))
MAX_OPEN_TRADES_FORCE_REFRESH = os.getenv("MAX_OPEN_TRADES_FORCE_REFRESH", "true").lower() == "true"
GLOBAL_SYMBOL_LOCK = set()
SYMBOL_COOLDOWN = {}
ORDER_AUDIT_LOG = []
EXECUTION_IN_PROGRESS = set()
EXECUTION_SLOT_LOCK = threading.RLock()
RESERVED_TRADE_SLOTS = {}
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "180" if VALIDATION_MODE else "360"))
MAX_AUDIT_LOG = 500

# websocket safety
WS_MAX_AGE = int(os.getenv("WS_MAX_AGE", "20"))
WS_STALE_THRESHOLD = int(os.getenv("WS_STALE_THRESHOLD", "5"))
WS_RESTART_COOLDOWN = int(os.getenv("WS_RESTART_COOLDOWN", "300"))
LAST_WS_HEAL = 0

STATE_FILE = os.getenv("STATE_FILE", "runtime_state.json")

# ===== VALIDATION / LIVE GATES =====
VALIDATION_RR_MIN = float(os.getenv("VALIDATION_RR_MIN", "1.8"))
LIVE_RR_MIN = float(os.getenv("LIVE_RR_MIN", "2.5"))
VALIDATION_TARGET_RR = float(os.getenv("VALIDATION_TARGET_RR", "2.0"))
LIVE_TARGET_RR = float(os.getenv("LIVE_TARGET_RR", "3.5"))

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

# ===== EXECUTION QUALITY / ORDER HARDENING =====
# Guardrail live agar RR tidak "valid di angka" tetapi terlalu mepet untuk fee/spread/wick.
MIN_STOP_DISTANCE_PCT = float(os.getenv("MIN_STOP_DISTANCE_PCT", "0.0025"))  # 0.25%
MIN_TP_DISTANCE_PCT = float(os.getenv("MIN_TP_DISTANCE_PCT", "0.0050"))      # 0.50%
FEE_BUFFER_RR = float(os.getenv("FEE_BUFFER_RR", "0.15"))                    # haircut RR untuk fee/slippage/noise
STRICT_PROTECTION = os.getenv("STRICT_PROTECTION", "true").lower() == "true"
ORDER_ID_PREFIX = (os.getenv("ORDER_ID_PREFIX", "M") or "M").strip()[:8]
SIGNED_CALL_MIN_INTERVAL = float(os.getenv("SIGNED_CALL_MIN_INTERVAL", "0.15"))
PROTECTION_PLACEMENT_GAP_SECONDS = float(os.getenv("PROTECTION_PLACEMENT_GAP_SECONDS", "0.35"))
PROTECTION_VERIFY_RETRIES = int(os.getenv("PROTECTION_VERIFY_RETRIES", "4"))
PROTECTION_VERIFY_DELAY = float(os.getenv("PROTECTION_VERIFY_DELAY", "0.50"))
PROTECTION_ORDER_MODE = (os.getenv("PROTECTION_ORDER_MODE", "CLOSE_POSITION") or "CLOSE_POSITION").strip().upper()
# Binance USDⓈ-M Futures conditional orders can be returned by the Algo Service
# with algoId/clientAlgoId/algoStatus instead of standard orderId/status fields.
PROTECTION_ACCEPT_ALGO_ID = os.getenv("PROTECTION_ACCEPT_ALGO_ID", "true").lower() == "true"
PROTECTION_VERIFY_CONDITIONAL_ORDERS = os.getenv("PROTECTION_VERIFY_CONDITIONAL_ORDERS", "true").lower() == "true"
PROTECTION_VERIFY_PLACEMENT_FALLBACK = os.getenv("PROTECTION_VERIFY_PLACEMENT_FALLBACK", "true").lower() == "true"
PROTECTION_RECENT_PLACEMENT_TTL = float(os.getenv("PROTECTION_RECENT_PLACEMENT_TTL", "90"))
PROTECTION_ENTRY_CONFIRM_RETRIES = int(os.getenv("PROTECTION_ENTRY_CONFIRM_RETRIES", "6"))
PROTECTION_ENTRY_CONFIRM_DELAY = float(os.getenv("PROTECTION_ENTRY_CONFIRM_DELAY", "0.50"))
EMERGENCY_CLOSE_VERIFY_RETRIES = int(os.getenv("EMERGENCY_CLOSE_VERIFY_RETRIES", "6"))
EMERGENCY_CLOSE_VERIFY_DELAY = float(os.getenv("EMERGENCY_CLOSE_VERIFY_DELAY", "0.50"))

# Controlled entry guard. Use a marketable LIMIT with a small tier-based cap
# to avoid bad fills/slippage. SL/TP and emergency close remain market/conditional.
ENTRY_ORDER_TYPE = (os.getenv("ENTRY_ORDER_TYPE", "LIMIT") or "LIMIT").strip().upper()
ENTRY_LIMIT_TTL_SECONDS = float(os.getenv("ENTRY_LIMIT_TTL_SECONDS", "30"))
ENTRY_LIMIT_POLL_INTERVAL = float(os.getenv("ENTRY_LIMIT_POLL_INTERVAL", "0.50"))
ENTRY_LIMIT_MAX_REPRICE = int(os.getenv("ENTRY_LIMIT_MAX_REPRICE", "1"))
ENTRY_MARKET_FALLBACK = os.getenv("ENTRY_MARKET_FALLBACK", "false").lower() == "true"
ENTRY_LIMIT_OFFSET_TOP = float(os.getenv("ENTRY_LIMIT_OFFSET_TOP", "0.0001"))
ENTRY_LIMIT_OFFSET_MID = float(os.getenv("ENTRY_LIMIT_OFFSET_MID", "0.0002"))
ENTRY_LIMIT_OFFSET_MID_AGGRESSIVE = float(os.getenv("ENTRY_LIMIT_OFFSET_MID_AGGRESSIVE", "0.0004"))
ENTRY_LIMIT_OFFSET_DEFAULT = float(os.getenv("ENTRY_LIMIT_OFFSET_DEFAULT", "0.0004"))
ENTRY_LIMIT_TIME_IN_FORCE = (os.getenv("ENTRY_LIMIT_TIME_IN_FORCE", "GTC") or "GTC").strip().upper()

# Group leverage policy. Set on execution only and cached per symbol/account.
ENABLE_AUTO_LEVERAGE = os.getenv("ENABLE_AUTO_LEVERAGE", "true").lower() == "true"
TOP_LEVERAGE = int(os.getenv("TOP_LEVERAGE", "20"))
MID_LEVERAGE = int(os.getenv("MID_LEVERAGE", "10"))
MID_AGGRESSIVE_LEVERAGE = int(os.getenv("MID_AGGRESSIVE_LEVERAGE", "5"))
LEVERAGE_SET_CACHE = set()

# Price precision guard. Binance futures can expose tickSize that is finer than
# effective order/display precision for some contracts. Use the stricter/coarser
# pricePrecision step when available, unless disabled via env. Per-pair override:
# PRICE_TICK_SIZE_SUIUSDT=0.0001
PRICE_PRECISION_USE_PRICE_PRECISION = os.getenv("PRICE_PRECISION_USE_PRICE_PRECISION", "true").lower() == "true"
PRICE_PRECISION_FAIL_ON_MISSING = os.getenv("PRICE_PRECISION_FAIL_ON_MISSING", "true").lower() == "true"

# Close source audit diagnostics. Used when a position disappears from Binance so we can
# distinguish exchange SL/TP, bot market close, manual/app close, or unknown close.
CLOSE_AUDIT_ENABLED = os.getenv("CLOSE_AUDIT_ENABLED", "true").lower() == "true"
CLOSE_AUDIT_LOOKBACK_MINUTES = int(os.getenv("CLOSE_AUDIT_LOOKBACK_MINUTES", "60"))
CLOSE_AUDIT_FETCH_ORDERS = os.getenv("CLOSE_AUDIT_FETCH_ORDERS", "true").lower() == "true"
CLOSE_AUDIT_TRADE_LIMIT = int(os.getenv("CLOSE_AUDIT_TRADE_LIMIT", "80"))
CLOSE_AUDIT_ORDER_LIMIT = int(os.getenv("CLOSE_AUDIT_ORDER_LIMIT", "80"))


# ===== CIRCUIT BREAKER / SPREAD GATE =====
CONSECUTIVE_ERRORS = 0
CIRCUIT_BREAKER_UNTIL = 0.0
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", os.getenv("MAX_CONSECUTIVE_ERRORS", "10")))
CIRCUIT_BREAKER_PAUSE = float(os.getenv("CIRCUIT_BREAKER_PAUSE", "60"))
WS_FALLBACK_POLL_INTERVAL = float(os.getenv("WS_FALLBACK_POLL_INTERVAL", "5"))
SPREAD_THRESHOLD_TOP = float(os.getenv("SPREAD_THRESHOLD_TOP", "0.0008"))
SPREAD_THRESHOLD_MID = float(os.getenv("SPREAD_THRESHOLD_MID", "0.0012"))
SPREAD_THRESHOLD_MID_AGGRESSIVE = float(os.getenv("SPREAD_THRESHOLD_MID_AGGRESSIVE", "0.0015"))
SPREAD_WARN_MULTIPLIER = float(os.getenv("SPREAD_WARN_MULTIPLIER", "0.8"))
SPREAD_CACHE_TTL = float(os.getenv("SPREAD_CACHE_TTL", "5"))
SPREAD_ORDER_BOOK_LIMIT = int(os.getenv("SPREAD_ORDER_BOOK_LIMIT", "5"))

SWEEP_REQUIRE_RECLAIM = os.getenv("SWEEP_REQUIRE_RECLAIM", "true").lower() == "true"

TELEGRAM_ALERTS_ENABLED = os.getenv("TELEGRAM_ALERTS_ENABLED", "true").lower() == "true"
TELEGRAM_ALERT_COOLDOWN_SECONDS = float(os.getenv("TELEGRAM_ALERT_COOLDOWN_SECONDS", "300"))
TELEGRAM_BLOCKED_ALERT_MINUTES = float(os.getenv("TELEGRAM_BLOCKED_ALERT_MINUTES", "5"))
TELEGRAM_SCAN_STALE_ALERT_SECONDS = float(os.getenv("TELEGRAM_SCAN_STALE_ALERT_SECONDS", "90"))
TELEGRAM_WS_BLOCK_ALERT_SECONDS = float(os.getenv("TELEGRAM_WS_BLOCK_ALERT_SECONDS", "60"))
TELEGRAM_UNPROTECTED_ALERT_SECONDS = float(os.getenv("TELEGRAM_UNPROTECTED_ALERT_SECONDS", "45"))
# Prevent false WS-stale Telegram alerts during boot while the websocket has
# connected but has not received its first market payload yet.
TELEGRAM_WS_STARTUP_GRACE_SECONDS = float(os.getenv("TELEGRAM_WS_STARTUP_GRACE_SECONDS", "120"))
# If true, WS alerts are sent only when the backend WS health gate is actually
# blocking, not merely when last_message_age is temporarily high.
TELEGRAM_REQUIRE_WS_BLOCK = os.getenv("TELEGRAM_REQUIRE_WS_BLOCK", "true").lower() == "true"
TELEGRAM_SEND_RECOVERY_ALERT = os.getenv("TELEGRAM_SEND_RECOVERY_ALERT", "true").lower() == "true"
# Telegram alerts must be based on current WS/execution state, not old audit rows.
TELEGRAM_ALERT_CURRENT_ONLY = os.getenv("TELEGRAM_ALERT_CURRENT_ONLY", "true").lower() == "true"
TELEGRAM_CLEAR_RESOLVED_KEYS = os.getenv("TELEGRAM_CLEAR_RESOLVED_KEYS", "true").lower() == "true"
TELEGRAM_CANDIDATE_ALERT_ENABLED = os.getenv("TELEGRAM_CANDIDATE_ALERT_ENABLED", "true").lower() == "true"
TELEGRAM_CANDIDATE_MIN_SCORE = float(os.getenv("TELEGRAM_CANDIDATE_MIN_SCORE", "87"))
TELEGRAM_CANDIDATE_ALERT_COOLDOWN_SECONDS = float(os.getenv("TELEGRAM_CANDIDATE_ALERT_COOLDOWN_SECONDS", "900"))
TELEGRAM_CANDIDATE_ALERT_TOP_N = int(os.getenv("TELEGRAM_CANDIDATE_ALERT_TOP_N", "3"))
TELEGRAM_ENTRY_ALERT_SIMPLE = os.getenv("TELEGRAM_ENTRY_ALERT_SIMPLE", "true").lower() == "true"

# === MONTRA: NEWS_ENGINE_CONSTANTS START ===
NEWS_ENGINE_ENABLED = os.getenv("NEWS_ENGINE_ENABLED", "true").lower() == "true"
NEWS_ENGINE_PROVIDER = (os.getenv("NEWS_ENGINE_PROVIDER", "fmp") or "fmp").strip().lower()
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
NEWS_CRYPTO_AUGMENT_ENABLED = os.getenv("NEWS_CRYPTO_AUGMENT_ENABLED", "false").lower() == "true"
NEWS_REFRESH_INTERVAL = int(os.getenv("NEWS_REFRESH_INTERVAL", "1800"))
NEWS_FETCH_TIMEOUT = float(os.getenv("NEWS_FETCH_TIMEOUT", "4"))
NEWS_MANUAL_FALLBACK_PATH = os.getenv("NEWS_MANUAL_FALLBACK_PATH", "news_calendar_manual.json")

NEWS_PRE_EVENT_BLOCK_MIN = int(os.getenv("NEWS_PRE_EVENT_BLOCK_MIN", "30"))
NEWS_EVENT_WINDOW_MIN = int(os.getenv("NEWS_EVENT_WINDOW_MIN", "15"))
NEWS_POST_EVENT_PENALTY_MIN = int(os.getenv("NEWS_POST_EVENT_PENALTY_MIN", "30"))
NEWS_TIER2_PRE_BLOCK_MIN = int(os.getenv("NEWS_TIER2_PRE_BLOCK_MIN", "15"))
NEWS_TIER2_POST_PENALTY_MIN = int(os.getenv("NEWS_TIER2_POST_PENALTY_MIN", "15"))

NEWS_TIER1_HARD_BLOCK = os.getenv("NEWS_TIER1_HARD_BLOCK", "true").lower() == "true"
NEWS_TIER2_HARD_BLOCK = os.getenv("NEWS_TIER2_HARD_BLOCK", "true").lower() == "true"
NEWS_TIER1_POST_PENALTY = int(os.getenv("NEWS_TIER1_POST_PENALTY", "8"))
NEWS_TIER2_POST_PENALTY = int(os.getenv("NEWS_TIER2_POST_PENALTY", "4"))
NEWS_TIER1_TELEGRAM_ALERT = os.getenv("NEWS_TIER1_TELEGRAM_ALERT", "true").lower() == "true"

NEWS_TIER1_KEYWORDS = (
    "consumer price index", "core cpi", "cpi y/y", "cpi yoy",
    "non-farm payrolls", "non farm payrolls", "nonfarm payrolls", "nfp",
    "unemployment rate",
    "fomc statement", "fomc economic projections", "fomc press conference",
    "fomc minutes", "interest rate decision",
    "fed chair", "powell speech", "powell speaks", "fed chair speaks",
    "ecb interest rate", "ecb press conference", "ecb monetary policy",
    "boj policy rate", "bank of japan policy rate",
    "gdp advance", "gdp growth rate", "gdp q",
    "ppi y/y", "ppi yoy", "producer price index",
    "sec etf", "spot etf decision",
)

NEWS_TIER2_KEYWORDS = (
    "retail sales", "ism manufacturing", "ism services", "ism non-manufacturing",
    "jolts", "core pce", "pce price index",
    "initial jobless claims", "continuing jobless claims",
    "trade balance", "boe interest rate", "bank of england rate",
    "china manufacturing pmi", "china services pmi",
    "german zew", "german ifo",
)

NEWS_TIER3_KEYWORDS = (
    "housing starts", "building permits", "consumer confidence",
    "michigan sentiment", "philly fed", "empire state",
)

NEWS_SCOPE_GLOBAL_KEYWORDS = (
    "fomc", "non-farm", "nfp", "cpi", "core cpi", "powell", "fed chair",
    "interest rate decision", "ppi", "unemployment rate",
)

NEWS_SCOPE_EU_KEYWORDS = ("ecb", "boe", "bank of england")
NEWS_SCOPE_ASIA_KEYWORDS = ("boj", "bank of japan", "china manufacturing", "china services")
NEWS_SCOPE_BTC_KEYWORDS = ("sec etf", "spot etf", "bitcoin etf", "ethereum etf")

INSTITUTIONAL_NEWS_CACHE = {
    "last_refresh_ts": 0,
    "next_refresh_ts": 0,
    "events": [],
    "source": None,
    "fetch_error": None,
    "fetch_attempts": 0,
}
INSTITUTIONAL_NEWS_LOCK = threading.RLock()
# === MONTRA: NEWS_ENGINE_CONSTANTS END ===

# === MONTRA: ANTI_TRAP_CONSTANTS START ===
ANTI_TRAP_MODE = (os.getenv("ANTI_TRAP_MODE", "enforce") or "enforce").strip().lower()

ANTI_TRAP_EQHL_ENABLED = os.getenv("ANTI_TRAP_EQHL_ENABLED", "true").lower() == "true"
ANTI_TRAP_EQHL_TOLERANCE = float(os.getenv("ANTI_TRAP_EQHL_TOLERANCE", "0.0005"))
ANTI_TRAP_EQHL_LOOKBACK = int(os.getenv("ANTI_TRAP_EQHL_LOOKBACK", "20"))
ANTI_TRAP_EQHL_SWEEP_LOOKBACK = int(os.getenv("ANTI_TRAP_EQHL_SWEEP_LOOKBACK", "5"))
ANTI_TRAP_EQHL_SWING_LEFT = int(os.getenv("ANTI_TRAP_EQHL_SWING_LEFT", "2"))
ANTI_TRAP_EQHL_SWING_RIGHT = int(os.getenv("ANTI_TRAP_EQHL_SWING_RIGHT", "2"))
ANTI_TRAP_EQHL_BONUS = int(os.getenv("ANTI_TRAP_EQHL_BONUS", "5"))

ANTI_TRAP_WICK_ENABLED = os.getenv("ANTI_TRAP_WICK_ENABLED", "true").lower() == "true"
ANTI_TRAP_WICK_RATIO_MAX = float(os.getenv("ANTI_TRAP_WICK_RATIO_MAX", "1.8"))
ANTI_TRAP_WICK_REQUIRE_BOS = os.getenv("ANTI_TRAP_WICK_REQUIRE_BOS", "true").lower() == "true"
ANTI_TRAP_BOS_LOOKBACK = int(os.getenv("ANTI_TRAP_BOS_LOOKBACK", "5"))
ANTI_TRAP_WICK_BONUS = int(os.getenv("ANTI_TRAP_WICK_BONUS", "4"))

ANTI_TRAP_SESSION_MAP_ENABLED = os.getenv("ANTI_TRAP_SESSION_MAP_ENABLED", "true").lower() == "true"
ANTI_TRAP_SESSION_TP_BONUS = int(os.getenv("ANTI_TRAP_SESSION_TP_BONUS", "6"))
ANTI_TRAP_SESSION_TP_PENALTY = int(os.getenv("ANTI_TRAP_SESSION_TP_PENALTY", "5"))
ANTI_TRAP_SESSION_OVERSHOOT_THRESHOLD = float(os.getenv("ANTI_TRAP_SESSION_OVERSHOOT_THRESHOLD", "0.005"))
ANTI_TRAP_SESSION_TTL_MIN = int(os.getenv("ANTI_TRAP_SESSION_TTL_MIN", "60"))

ANTI_TRAP_CLUSTER_ENABLED = os.getenv("ANTI_TRAP_CLUSTER_ENABLED", "true").lower() == "true"
ANTI_TRAP_CLUSTER_LOOKBACK = int(os.getenv("ANTI_TRAP_CLUSTER_LOOKBACK", "80"))
ANTI_TRAP_CLUSTER_Z_THRESHOLD = float(os.getenv("ANTI_TRAP_CLUSTER_Z_THRESHOLD", "1.5"))
ANTI_TRAP_CLUSTER_TOLERANCE = float(os.getenv("ANTI_TRAP_CLUSTER_TOLERANCE", "0.001"))
ANTI_TRAP_CLUSTER_BONUS = int(os.getenv("ANTI_TRAP_CLUSTER_BONUS", "5"))

SESSION_LIQUIDITY_CACHE = {}
# === MONTRA: ANTI_TRAP_CONSTANTS END ===

# ===== STRUCTURE ENGINE V3 =====
STRUCTURE_SWING_LOOKBACK = int(os.getenv("STRUCTURE_SWING_LOOKBACK", "14"))
STRUCTURE_FVG_LOOKBACK = int(os.getenv("STRUCTURE_FVG_LOOKBACK", "8"))
STRUCTURE_RECLAIM_TOLERANCE = float(os.getenv("STRUCTURE_RECLAIM_TOLERANCE", "0.0018"))
STRUCTURE_MIN_BODY_RATIO = float(os.getenv("STRUCTURE_MIN_BODY_RATIO", "0.35"))
STRUCTURE_RECENT_WINDOW = int(os.getenv("STRUCTURE_RECENT_WINDOW", "3"))
STRUCTURE_ZONE_TOLERANCE = float(os.getenv("STRUCTURE_ZONE_TOLERANCE", "0.0012"))
STRUCTURE_STRONG_SCORE_BONUS = int(os.getenv("STRUCTURE_STRONG_SCORE_BONUS", "6"))
STRUCTURE_MEDIUM_SCORE_PENALTY = int(os.getenv("STRUCTURE_MEDIUM_SCORE_PENALTY", "2"))

# ===== PRECISION EXECUTION ENGINE =====
SMART_OB_LOOKBACK = int(os.getenv("SMART_OB_LOOKBACK", "14"))
SMART_OB_EXCLUDE_RECENT_CANDLES = int(os.getenv("SMART_OB_EXCLUDE_RECENT_CANDLES", "1"))
SMART_SL_ATR_PERIOD = int(os.getenv("SMART_SL_ATR_PERIOD", "14"))
SMART_SL_ATR_BUFFER_MULT = float(os.getenv("SMART_SL_ATR_BUFFER_MULT", "0.22"))
SMART_TP_USE_FVG_MAGNET = os.getenv("SMART_TP_USE_FVG_MAGNET", "true").lower() == "true"
SMART_TP_FVG_MAX_RR_MULT = float(os.getenv("SMART_TP_FVG_MAX_RR_MULT", "1.35"))

# [FIX 4] Redistribusi bobot ML ke Pre dan Meta jika ML mati.
ENABLE_ML = os.getenv("ENABLE_ML", "false").lower() == "true"
if not ENABLE_ML:
    PRE_SCORE_WEIGHT = 0.60
    META_SCORE_WEIGHT = 0.40
    ML_SCORE_WEIGHT = 0.0
else:
    PRE_SCORE_WEIGHT = float(os.getenv("PRE_SCORE_WEIGHT", "0.45"))
    META_SCORE_WEIGHT = float(os.getenv("META_SCORE_WEIGHT", "0.35"))
    ML_SCORE_WEIGHT = float(os.getenv("ML_SCORE_WEIGHT", "0"))

# [FIX 6] Sweep Memory Window dikompresi agar sinyal tidak basi (stale).
SWEEP_LOOKBACK = int(os.getenv("SWEEP_LOOKBACK", "7"))
SWEEP_MEMORY_WINDOW = int(os.getenv("SWEEP_MEMORY_WINDOW", "2"))

# ===== PROFIT MANAGEMENT =====
PARTIAL_TP_ENABLED = os.getenv("PARTIAL_TP_ENABLED", "true").lower() == "true"
PARTIAL_TP_R1_RATIO = float(os.getenv("PARTIAL_TP_R1_RATIO", "0.40"))
SMART_TRAIL_BE_TRIGGER_PCT = float(os.getenv("SMART_TRAIL_BE_TRIGGER_PCT", "0.015"))
SMART_TRAIL_ACTIVE_PCT = float(os.getenv("SMART_TRAIL_ACTIVE_PCT", "0.018"))
SMART_TRAIL_LOCK_RATIO = float(os.getenv("SMART_TRAIL_LOCK_RATIO", "0.70"))
STATE_SAVE_MIN_INTERVAL_SECONDS = float(os.getenv("STATE_SAVE_MIN_INTERVAL_SECONDS", "30"))

# ===== EXECUTION / NOTIONAL QUALITY =====
TOP_MIN_TRADE_NOTIONAL = float(os.getenv("TOP_MIN_TRADE_NOTIONAL", "100"))
MID_MIN_TRADE_NOTIONAL = float(os.getenv("MID_MIN_TRADE_NOTIONAL", "100"))
LOW_MIN_TRADE_NOTIONAL = float(os.getenv("LOW_MIN_TRADE_NOTIONAL", "100"))
MID_AGGRESSIVE_MIN_TRADE_NOTIONAL = float(os.getenv("MID_AGGRESSIVE_MIN_TRADE_NOTIONAL", os.getenv("DEFAULT_MIN_TRADE_NOTIONAL", "100")))
DEFAULT_MIN_TRADE_NOTIONAL = float(os.getenv("DEFAULT_MIN_TRADE_NOTIONAL", "100"))
USE_DEFAULT_MIN_NOTIONAL_FOR_ALL = os.getenv("USE_DEFAULT_MIN_NOTIONAL_FOR_ALL", "true").lower() == "true"

# ===== PAIR PRIORITY ENGINE =====
# Tier sekarang diambil dari config.py agar universe scan dan tiering tidak saling
# bertentangan. Kalau config lama belum punya variabel ini, fallback lama tetap aman.
TOP_PAIRS = globals().get("TOP_PAIRS", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"])
MID_PAIRS = globals().get("MID_PAIRS", ["LINKUSDT", "AVAXUSDT", "NEARUSDT", "ARBUSDT", "AAVEUSDT", "ADAUSDT", "LTCUSDT", "TRXUSDT", "TONUSDT", "WLDUSDT"])
MID_AGGRESSIVE_PAIRS = globals().get("MID_AGGRESSIVE_PAIRS", ["HYPEUSDT", "SUIUSDT", "WIFUSDT", "1000PEPEUSDT"])
VALIDATION_ONLY = globals().get("VALIDATION_ONLY", [])
REMOVE_FROM_CORE = globals().get("REMOVE_FROM_CORE", [])

# PAIRS dari config tetap jadi source of truth universe scan.
# REMOVE_FROM_CORE diproteksi ulang di sini bila config masih membawa pair tersebut.
PAIRS = [p for p in PAIRS if p not in REMOVE_FROM_CORE]
LOW_PAIRS = [p for p in PAIRS if p not in TOP_PAIRS and p not in MID_PAIRS and p not in MID_AGGRESSIVE_PAIRS]

TOP_PAIR_LIMIT = int(os.getenv("TOP_PAIR_LIMIT", "3" if VALIDATION_MODE else "2"))
MID_PAIR_LIMIT = int(os.getenv("MID_PAIR_LIMIT", "2" if VALIDATION_MODE else "1"))
MID_AGGRESSIVE_PAIR_LIMIT = int(os.getenv("MID_AGGRESSIVE_PAIR_LIMIT", os.getenv("MID_PAIR_LIMIT", "1")))
LOW_PAIR_LIMIT = int(os.getenv("LOW_PAIR_LIMIT", "0"))

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

from fastapi import FastAPI, Query, Body, HTTPException
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
from utils.spread import (
    check_spread_gate,
    get_live_spread,
    get_spread_cache_snapshot,
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
BINANCE_MAX_TIME_RETRIES = int(os.getenv("BINANCE_MAX_TIME_RETRIES", os.getenv("MAX_TIME_RETRIES", "3")))
BINANCE_RATE_LIMIT_RETRIES = int(os.getenv("BINANCE_RATE_LIMIT_RETRIES", os.getenv("RATE_LIMIT_RETRIES", "3")))
POSITION_CACHE_TTL = float(os.getenv("POSITION_CACHE_TTL", "30"))
POSITION_MONITOR_INTERVAL = float(os.getenv("POSITION_MONITOR_INTERVAL", "45"))
TRAILING_LOOP_INTERVAL = float(os.getenv("TRAILING_LOOP_INTERVAL", "30"))
POSITION_RATE_LIMIT_SLEEP = float(os.getenv("POSITION_RATE_LIMIT_SLEEP", "20"))
MARKET_KLINES_CACHE_TTL_15M = float(os.getenv("MARKET_KLINES_CACHE_TTL_15M", "60"))
MARKET_KLINES_CACHE_TTL_1H = float(os.getenv("MARKET_KLINES_CACHE_TTL_1H", "180"))
MARKET_KLINES_CACHE_TTL_4H = float(os.getenv("MARKET_KLINES_CACHE_TTL_4H", "600"))
WS_DEGRADED_MODE_ALLOW = os.getenv("WS_DEGRADED_MODE_ALLOW", "true").lower() == "true"
WS_DEGRADED_GRACE_SECONDS = float(os.getenv("WS_DEGRADED_GRACE_SECONDS", "15"))
WS_FULL_STALE_BLOCK_SECONDS = float(os.getenv("WS_FULL_STALE_BLOCK_SECONDS", "600"))
MAX_TRADE_HISTORY = int(os.getenv("MAX_TRADE_HISTORY", "1000"))
CLOSE_REALIZED_LOOKBACK_MINUTES = int(os.getenv("CLOSE_REALIZED_LOOKBACK_MINUTES", "720"))

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

SIGNED_CALL_LOCK = threading.Lock()
LAST_SIGNED_CALL_TS = 0.0


def circuit_breaker_active():
    return time.time() < CIRCUIT_BREAKER_UNTIL


def circuit_breaker_remaining():
    return max(0.0, CIRCUIT_BREAKER_UNTIL - time.time())


def record_runtime_error(stage="runtime", error=None):
    global CONSECUTIVE_ERRORS, CIRCUIT_BREAKER_UNTIL
    CONSECUTIVE_ERRORS += 1
    detail = {
        "stage": stage,
        "error": str(error) if error is not None else None,
        "consecutive_errors": CONSECUTIVE_ERRORS,
        "threshold": CIRCUIT_BREAKER_THRESHOLD,
    }
    if CONSECUTIVE_ERRORS >= CIRCUIT_BREAKER_THRESHOLD:
        CIRCUIT_BREAKER_UNTIL = time.time() + CIRCUIT_BREAKER_PAUSE
        detail["pause_seconds"] = CIRCUIT_BREAKER_PAUSE
        try:
            add_execution_decision("circuit_breaker", "_SYSTEM_", "BLOCK", detail)
        except Exception:
            pass
        print(f"🧯 CIRCUIT BREAKER PAUSE {CIRCUIT_BREAKER_PAUSE}s after {CONSECUTIVE_ERRORS} errors")
    return detail


def reset_runtime_errors():
    global CONSECUTIVE_ERRORS
    if CONSECUTIVE_ERRORS:
        CONSECUTIVE_ERRORS = 0


def signed_backoff_sleep(attempt, rate_error=False, time_error=False):
    base = 0.5 if time_error else 1.0
    if rate_error:
        base = 2.0
    sleep_for = min(POSITION_RATE_LIMIT_SLEEP, base * (2 ** max(0, attempt - 1)))
    sleep_for += min(0.25, 0.03 * attempt)
    time.sleep(sleep_for)
    return sleep_for


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


def _protection_order_ref(order):
    """Return (ref_type, ref_id) for standard or Algo Service conditional orders."""
    if not isinstance(order, dict):
        return (None, None)
    order_id = order.get("orderId") or order.get("order_id")
    if order_id not in (None, ""):
        return ("orderId", order_id)
    algo_id = order.get("algoId") or order.get("algo_id")
    if PROTECTION_ACCEPT_ALGO_ID and algo_id not in (None, ""):
        return ("algoId", algo_id)
    client_algo_id = order.get("clientAlgoId") or order.get("client_algo_id")
    if PROTECTION_ACCEPT_ALGO_ID and client_algo_id:
        return ("clientAlgoId", client_algo_id)
    return (None, None)


def _protection_order_status(order):
    if not isinstance(order, dict):
        return None
    return order.get("status") or order.get("algoStatus") or order.get("orderStatus")


def _protection_order_type(order):
    if not isinstance(order, dict):
        return None
    return order.get("type") or order.get("orderType") or order.get("origType")


def _protection_stop_price(order):
    if not isinstance(order, dict):
        return 0.0
    return _safe_float(order.get("stopPrice") or order.get("triggerPrice") or order.get("activatePrice"), 0.0)


def _is_active_protection_status(status):
    if status is None:
        return True
    return str(status).upper() not in ("CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "FILLED", "TRIGGERED", "FINISHED")


def _annotate_protection_response(order, leg=None):
    """Normalize Binance standard/algo response so internal logs remain stable."""
    if not isinstance(order, dict):
        return order
    ref_type, ref_id = _protection_order_ref(order)
    if ref_id is not None:
        order.setdefault("_montra_ref_type", ref_type)
        order.setdefault("_montra_ref_id", ref_id)
        # Compatibility for existing logs/return payloads only. Do not use this
        # as a standard cancel id when _montra_ref_type is algoId/clientAlgoId.
        if "orderId" not in order and ref_type == "algoId":
            order["orderId"] = ref_id
    if leg:
        order.setdefault("_montra_leg", leg)
    return order


def _remember_protection_order(symbol, leg, order):
    if not isinstance(order, dict):
        return
    leg = str(leg or "").upper()
    if leg not in ("SL", "TP"):
        return
    ref_type, ref_id = _protection_order_ref(order)
    if not ref_id:
        return
    row = {
        "ts": time.time(),
        "leg": leg,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "order": dict(order),
        "status": _protection_order_status(order),
        "order_type": _protection_order_type(order),
        "stop_price": _protection_stop_price(order),
    }
    RECENT_PROTECTION_ORDERS.setdefault(symbol, {})[leg] = row


def _recent_protection_verify(symbol):
    rows = RECENT_PROTECTION_ORDERS.get(symbol) or {}
    now = time.time()
    result = {"sl": None, "tp": None, "sl_ref": None, "tp_ref": None, "rows": []}
    for leg, key in (("SL", "sl"), ("TP", "tp")):
        row = rows.get(leg)
        if not row:
            continue
        age = now - float(row.get("ts") or 0)
        order = row.get("order") or {}
        status = row.get("status") or _protection_order_status(order)
        if age <= PROTECTION_RECENT_PLACEMENT_TTL and _is_active_protection_status(status):
            result[key] = row.get("stop_price") or _protection_stop_price(order)
            result[f"{key}_ref"] = {"type": row.get("ref_type"), "id": row.get("ref_id"), "status": status, "age": round(age, 2)}
            result["rows"].append(row)
    return result


def build_exit_lookup(open_orders):
    rows = {}
    for o in open_orders or []:
        symbol = o.get("symbol")
        if not symbol:
            continue
        status = _protection_order_status(o)
        if not _is_active_protection_status(status):
            continue
        stop_price = _protection_stop_price(o)
        if stop_price <= 0:
            continue
        row = rows.setdefault(symbol, {"sl": None, "tp": None, "sl_ref": None, "tp_ref": None})
        order_type = str(_protection_order_type(o) or "").upper()
        ref_type, ref_id = _protection_order_ref(o)
        ref = {"type": ref_type, "id": ref_id, "status": status}
        if order_type == "STOP_MARKET":
            row["sl"] = stop_price
            row["sl_ref"] = ref
        elif order_type == "TAKE_PROFIT_MARKET":
            row["tp"] = stop_price
            row["tp_ref"] = ref
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
    global LAST_SIGNED_CALL_TS
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
            if SIGNED_CALL_MIN_INTERVAL > 0:
                with SIGNED_CALL_LOCK:
                    elapsed = time.time() - LAST_SIGNED_CALL_TS
                    if elapsed < SIGNED_CALL_MIN_INTERVAL:
                        time.sleep(SIGNED_CALL_MIN_INTERVAL - elapsed)
                    LAST_SIGNED_CALL_TS = time.time()
                    result = fn(*args, **kwargs)
                    reset_runtime_errors()
                    return result
            result = fn(*args, **kwargs)
            reset_runtime_errors()
            return result
        except Exception as e:
            last_error = e
            msg = str(e)
            time_error = ("-1021" in msg) or ("outside of the recvWindow" in msg)
            rate_error = is_rate_limit_error(e)

            if time_error and attempt < time_attempts:
                print(f"⚠️ {label} signed_call time drift detected (attempt {attempt}/{time_attempts})")
                sync_binance_time(client_obj, label=label, force=True)
                sleep_for = signed_backoff_sleep(attempt, time_error=True)
                print(f"⏳ {label} time retry backoff {sleep_for:.2f}s")
                continue

            if rate_error and attempt < rate_attempts:
                sleep_for = signed_backoff_sleep(attempt, rate_error=True)
                print(f"⚠️ {label} signed_call rate limited, retrying in {sleep_for:.1f}s")
                continue

            record_runtime_error("signed_call", e)
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
KILL_SWITCH = bool(globals().get("KILL_SWITCH_DEFAULT", False))

START_EQUITY = None
MAX_DRAWDOWN_PCT = 10   # stop kalau -10%

DAILY_START_EQUITY = None
DAILY_LOSS_PCT = 3      # stop kalau -3% harian

LAST_DAY = None

# ===== PERFORMANCE TRACKING =====
daily_loss = 0
consecutive_loss = 0
current_risk = float(os.getenv("BASE_RISK", str(BASE_RISK)))
MIN_RISK = float(os.getenv("MIN_RISK", str(globals().get("MIN_RISK", 0.003))))
MAX_RISK = float(os.getenv("MAX_RISK", str(globals().get("MAX_RISK", 0.02))))

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
APP_START_TS = time.time()
EXECUTION_BOOT_GRACE_SECONDS = float(os.getenv("EXECUTION_BOOT_GRACE_SECONDS", "45"))
LAST_SCAN_CYCLE_TS = 0.0
LAST_FINAL_EXECUTION = {
    "status": "STARTING",
    "symbol": None,
    "side": None,
    "reason": "WAITING_FOR_FIRST_SCAN",
    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    "ts": APP_START_TS,
    "stage": "startup",
    "detail": {
        "boot_grace_seconds": EXECUTION_BOOT_GRACE_SECONDS,
    },
}

# Short-lived accepted protection responses keyed by symbol/leg. This prevents
# false emergency-close when Binance accepts STOP_MARKET / TAKE_PROFIT_MARKET
# as Algo Service objects but the open-order query lags or returns via a
# separate conditional endpoint.
RECENT_PROTECTION_ORDERS = {}  # {symbol: {"SL": row, "TP": row}}

TELEGRAM_ALERT_STATE = {
    "last_sent_by_key": {},
    "last_alerts": [],
    "ws_block_active": False,
    "ws_block_reason": None,
    "suppressed_by_key": {},
    "current_state": {
        "ws": "UNKNOWN",
        "scan": "UNKNOWN",
        "execution": "UNKNOWN",
    },
}

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

LAST_STATE_SAVE_TS = 0.0
SAVE_RUNTIME_STATE_DIRTY = False
STATE_SAVE_LOCK = threading.RLock()

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
    save_runtime_state(force=True)

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

    save_runtime_state(force=True)

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

def save_runtime_state(force=False):
    global LAST_STATE_SAVE_TS, SAVE_RUNTIME_STATE_DIRTY

    now = time.time()
    if (
        not force
        and STATE_SAVE_MIN_INTERVAL_SECONDS > 0
        and LAST_STATE_SAVE_TS
        and (now - LAST_STATE_SAVE_TS) < STATE_SAVE_MIN_INTERVAL_SECONDS
    ):
        SAVE_RUNTIME_STATE_DIRTY = True
        return

    try:
        with STATE_SAVE_LOCK:
            tmp_file = f"{STATE_FILE}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(build_runtime_state(), f, indent=2)
            os.replace(tmp_file, STATE_FILE)
            LAST_STATE_SAVE_TS = time.time()
            SAVE_RUNTIME_STATE_DIRTY = False
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
    symbol = str(symbol or "").upper().strip()
    if symbol in TOP_PAIRS:
        return "TOP"
    if symbol in MID_PAIRS:
        return "MID"
    if symbol in MID_AGGRESSIVE_PAIRS:
        return "MID_AGGRESSIVE"
    return "LOW"

def tier_limits():
    return {
        "TOP": TOP_PAIR_LIMIT,
        "MID": MID_PAIR_LIMIT,
        "MID_AGGRESSIVE": MID_AGGRESSIVE_PAIR_LIMIT,
        "LOW": LOW_PAIR_LIMIT,
    }

def tier_score_floor(symbol):
    tier = get_pair_tier(symbol)
    if VALIDATION_MODE:
        return MIN_SCORE if tier != "LOW" else max(MIN_SCORE, 50)
    if tier == "TOP":
        return max(MIN_SCORE, 80)
    if tier == "MID":
        return max(MIN_SCORE, 85)
    if tier == "MID_AGGRESSIVE":
        return max(MIN_SCORE, 85)
    return 999

def tier_score_bonus(symbol):
    tier = get_pair_tier(symbol)
    if tier == "TOP":
        return 5
    if tier == "MID":
        return 2
    if tier == "MID_AGGRESSIVE":
        return 0
    return 0

def get_pair_leverage(symbol):
    tier = get_pair_tier(symbol)
    if tier == "TOP":
        return TOP_LEVERAGE
    if tier == "MID":
        return MID_LEVERAGE
    if tier == "MID_AGGRESSIVE":
        return MID_AGGRESSIVE_LEVERAGE
    return MID_AGGRESSIVE_LEVERAGE

def ensure_symbol_leverage(client_obj, label, symbol):
    if not ENABLE_AUTO_LEVERAGE:
        return {"ok": True, "skipped": True, "reason": "auto_leverage_disabled"}
    symbol = str(symbol or "").upper().strip()
    target = int(get_pair_leverage(symbol))
    key = (label, symbol, target)
    if key in LEVERAGE_SET_CACHE:
        return {"ok": True, "cached": True, "leverage": target, "symbol": symbol}
    try:
        add_order_audit("LEVERAGE_SET_ATTEMPT", symbol, {"account": label, "target_leverage": target, "tier": get_pair_tier(symbol)})
        res = signed_call(client_obj, client_obj.futures_change_leverage, label=label, symbol=symbol, leverage=target)
        LEVERAGE_SET_CACHE.add(key)
        add_order_audit("LEVERAGE_SET_OK", symbol, {"account": label, "target_leverage": target, "response": res})
        return {"ok": True, "leverage": target, "response": res}
    except Exception as exc:
        add_order_audit("LEVERAGE_SET_FAILED", symbol, {"account": label, "target_leverage": target, "error": str(exc)})
        return {"ok": False, "leverage": target, "error": str(exc)}

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

def _candle_open(candle):
    return float(candle[1])

def _candle_high(candle):
    return float(candle[2])

def _candle_low(candle):
    return float(candle[3])

def _candle_close(candle):
    return float(candle[4])

def calculate_atr(ohlcv, period=None):
    period = max(2, int(period or SMART_SL_ATR_PERIOD))
    if len(ohlcv) < 2:
        return 0.0

    start = max(1, len(ohlcv) - period)
    true_ranges = []
    for i in range(start, len(ohlcv)):
        high = _candle_high(ohlcv[i])
        low = _candle_low(ohlcv[i])
        prev_close = _candle_close(ohlcv[i - 1])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    if not true_ranges:
        return 0.0
    return sum(true_ranges) / len(true_ranges)

def find_last_order_block(ohlcv, side, lookback=None):
    side = str(side or "").upper().strip()
    lookback = max(4, int(lookback or SMART_OB_LOOKBACK))
    if len(ohlcv) < 5:
        return None

    exclude = max(1, int(SMART_OB_EXCLUDE_RECENT_CANDLES))
    end = max(1, len(ohlcv) - 1 - exclude)
    start = max(0, end - lookback)

    for idx in range(end, start - 1, -1):
        candle = ohlcv[idx]
        opened = _candle_open(candle)
        high = _candle_high(candle)
        low = _candle_low(candle)
        closed = _candle_close(candle)

        if side == "BUY" and closed < opened:
            return {
                "index": idx,
                "source": "last_bearish_before_break",
                "open": opened,
                "high": high,
                "low": low,
                "close": closed,
                "top": opened,
                "bottom": low,
            }

        if side == "SELL" and closed > opened:
            return {
                "index": idx,
                "source": "last_bullish_before_break",
                "open": opened,
                "high": high,
                "low": low,
                "close": closed,
                "top": high,
                "bottom": opened,
            }

    # [FIX 1] AUDIT INSTITUSI: Tidak ada OB valid = Tidak ada trade. 
    # SL di area acak hanya menjadi likuiditas bagi Market Maker.
    return None

def _directional_fvg_target(side, entry, structure):
    if not structure:
        return None

    side = str(side or "").upper().strip()
    zones = []
    if structure.get("fvg_up_zone"):
        zones.append(("fvg_up_zone", structure.get("fvg_up_zone")))
    if structure.get("fvg_down_zone"):
        zones.append(("fvg_down_zone", structure.get("fvg_down_zone")))

    candidates = []
    for name, zone in zones:
        if not isinstance(zone, dict):
            continue
        top = _safe_float(zone.get("top"), 0.0)
        bottom = _safe_float(zone.get("bottom"), 0.0)
        if top <= 0 or bottom <= 0:
            continue

        if side == "BUY":
            price = max(top, bottom)
            if price > entry:
                candidates.append({"source": name, "price": price, "zone": zone})
        elif side == "SELL":
            price = min(top, bottom)
            if price < entry:
                candidates.append({"source": name, "price": price, "zone": zone})

    if not candidates:
        return None

    if side == "BUY":
        return min(candidates, key=lambda row: row["price"] - entry)
    return min(candidates, key=lambda row: entry - row["price"])

def build_precision_trade_plan(symbol, side, entry, ohlcv, structure=None, rr_target=None):
    side = str(side or "").upper().strip()
    entry = float(entry or 0.0)
    rr_target = float(rr_target or active_target_rr())

    if side not in ("BUY", "SELL") or entry <= 0 or len(ohlcv) < 5:
        return {"ok": False, "reason": "INVALID_TRADE_PLAN_INPUT", "side": side, "entry": entry}

    atr = calculate_atr(ohlcv, SMART_SL_ATR_PERIOD)
    ob = find_last_order_block(ohlcv, side)
    if not ob:
        return {"ok": False, "reason": "ORDER_BLOCK_NOT_FOUND", "side": side, "entry": entry, "atr": atr}

    sl_buffer = max(atr * SMART_SL_ATR_BUFFER_MULT, entry * 0.00005)
    recent = ohlcv[-max(3, min(len(ohlcv), SMART_OB_LOOKBACK)):]
    recent_low = min(_candle_low(c) for c in recent)
    recent_high = max(_candle_high(c) for c in recent)

    if side == "BUY":
        sl = min(float(ob["low"]), recent_low) - sl_buffer
        if sl >= entry:
            sl = recent_low - sl_buffer
        risk = entry - sl
        tp_rr = entry + (risk * rr_target)
    else:
        sl = max(float(ob["high"]), recent_high) + sl_buffer
        if sl <= entry:
            sl = recent_high + sl_buffer
        risk = sl - entry
        tp_rr = entry - (risk * rr_target)

    if risk <= 0:
        return {"ok": False, "reason": "INVALID_RISK_DISTANCE", "side": side, "entry": entry, "sl": sl, "ob": ob, "atr": atr}

    tp = tp_rr
    tp_source = "rr_target"
    fvg_target = _directional_fvg_target(side, entry, structure)
    if SMART_TP_USE_FVG_MAGNET and fvg_target:
        fvg_price = float(fvg_target["price"])
        fvg_rr = abs(fvg_price - entry) / max(risk, 1e-12)
        if fvg_rr >= active_rr_min() and fvg_rr <= max(rr_target * SMART_TP_FVG_MAX_RR_MULT, active_rr_min()):
            tp = fvg_price
            tp_source = fvg_target.get("source", "fvg_magnet")

    rr = abs(tp - entry) / max(risk, 1e-12)
    return {
        "ok": True,
        "reason": "OK",
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "atr": atr,
        "sl_buffer": sl_buffer,
        "ob": ob,
        "tp_source": tp_source,
        "fvg_target": fvg_target,
        "rr_target": rr_target,
    }

def get_fng_context():
    return {
        "value": NEWS_CACHE.get("value"),
        "classification": NEWS_CACHE.get("classification", "NEUTRAL"),
        "impact": NEWS_CACHE.get("impact", "NORMAL"),
        "source": NEWS_CACHE.get("source", "alternative_me_fng"),
    }

def get_fng_score_bias(side, fng_ctx=None):
    side = str(side or "").upper().strip()
    fng_ctx = fng_ctx or get_fng_context()
    classification = str(fng_ctx.get("classification") or "").upper()

    if classification == "EXTREME_FEAR":
        return 8 if side == "BUY" else -5
    if classification == "EXTREME_GREED":
        return 8 if side == "SELL" else -5
    return 0

def composite_pre_score(symbol, side, entry, sl, tp, structure, pair_regime, vol, sweep_high=False, sweep_low=False, fng_ctx=None):
    side = str(side or "").upper().strip()
    structure = structure or {}
    score = 85.0

    grade = structure.get("grade")
    if grade == "STRONG":
        score += 16
    elif grade == "MEDIUM":
        score += 8

    if side == "BUY":
        if structure.get("swing_break_up"):
            score += 5
        if structure.get("reclaim_up") or structure.get("recent_reclaim_up"):
            score += 5
        if structure.get("displacement_up") or structure.get("directional_up"):
            score += 4
        if structure.get("fvg_up") or structure.get("near_fvg_up"):
            score += 5
        if sweep_low:
            score += 6
    elif side == "SELL":
        if structure.get("swing_break_down"):
            score += 5
        if structure.get("reclaim_down") or structure.get("recent_reclaim_down"):
            score += 5
        if structure.get("displacement_down") or structure.get("directional_down"):
            score += 4
        if structure.get("fvg_down") or structure.get("near_fvg_down"):
            score += 5
        if sweep_high:
            score += 6

    rr = abs(float(tp) - float(entry)) / max(abs(float(entry) - float(sl)), 1e-12)
    if rr >= active_target_rr():
        score += 5
    elif rr >= active_rr_min():
        score += 2
    else:
        score -= 12

    stop_ratio = abs(float(entry) - float(sl)) / max(abs(float(entry)), 1e-12)
    if stop_ratio < MIN_STOP_DISTANCE_PCT * 1.15:
        score -= 8
    elif stop_ratio <= 0.02:
        score += 4
    else:
        score -= 4

    if pair_regime == "SIDEWAYS":
        score -= 5
    elif pair_regime == "BULL" and side == "BUY":
        score += 5
    elif pair_regime == "BEAR" and side == "SELL":
        score += 5

    if active_vol_min() <= float(vol or 0.0) <= active_vol_max():
        score += 3

    score += get_fng_score_bias(side, fng_ctx)
    return max(0, min(100, round(score, 2)))

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


def summarize_skip_reasons(rows=None, limit=8):
    summary = {}
    for row in rows or []:
        reason = row.get("reason", "UNKNOWN")
        summary[reason] = summary.get(reason, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(summary.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def detect_sweep_memory(ohlcv, lookback=None, memory_window=None, require_reclaim=None):
    """Detect confirmed liquidity sweep within the last N candles."""
    lookback = int(lookback or SWEEP_LOOKBACK)
    memory_window = max(1, int(memory_window or SWEEP_MEMORY_WINDOW))
    require_reclaim = SWEEP_REQUIRE_RECLAIM if require_reclaim is None else bool(require_reclaim)
    out = {
        "sweep_high": False,
        "sweep_low": False,
        "raw_sweep_high": False,
        "raw_sweep_low": False,
        "high": None,
        "low": None,
        "lookback": lookback,
        "memory_window": memory_window,
        "require_reclaim": require_reclaim,
    }
    if not ohlcv or len(ohlcv) < lookback + 1:
        return out
    n = len(ohlcv)
    start = max(lookback, n - memory_window)
    for idx in range(start, n):
        prev = ohlcv[max(0, idx - lookback):idx]
        if len(prev) < max(3, min(lookback, 3)):
            continue
        prev_high = max(float(c[2]) for c in prev)
        prev_low = min(float(c[3]) for c in prev)
        candle = ohlcv[idx]
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])
        ts = int(float(candle[0])) if len(candle) > 0 else None
        age = n - 1 - idx
        raw_high = high > prev_high
        raw_low = low < prev_low
        reclaim_high = close < prev_high
        reclaim_low = close > prev_low
        if raw_high:
            out["raw_sweep_high"] = True
        if raw_low:
            out["raw_sweep_low"] = True
        if raw_high and (not require_reclaim or reclaim_high):
            out["sweep_high"] = True
            out["high"] = {
                "age_candles": age,
                "level": round(prev_high, 8),
                "wick_price": round(high, 8),
                "close": round(close, 8),
                "reclaimed": reclaim_high,
                "time": ts,
            }
        if raw_low and (not require_reclaim or reclaim_low):
            out["sweep_low"] = True
            out["low"] = {
                "age_candles": age,
                "level": round(prev_low, 8),
                "wick_price": round(low, 8),
                "close": round(close, 8),
                "reclaimed": reclaim_low,
                "time": ts,
            }
    return out


# === MONTRA: ANTI_TRAP_DETECTORS START ===
def _ohlcv_field(candle, idx, default=0.0):
    try:
        return float(candle[idx])
    except Exception:
        return float(default)


def _identify_swing_points(ohlcv, swing_left, swing_right, kind):
    points = []
    n = len(ohlcv)
    if n < swing_left + swing_right + 1:
        return points
    for i in range(swing_left, n - swing_right):
        center = ohlcv[i]
        center_price = _ohlcv_field(center, 2 if kind == "high" else 3)
        is_swing = True
        for j in range(1, swing_left + 1):
            ref = _ohlcv_field(ohlcv[i - j], 2 if kind == "high" else 3)
            if kind == "high" and ref >= center_price:
                is_swing = False; break
            if kind == "low" and ref <= center_price:
                is_swing = False; break
        if not is_swing:
            continue
        for j in range(1, swing_right + 1):
            ref = _ohlcv_field(ohlcv[i + j], 2 if kind == "high" else 3)
            if kind == "high" and ref >= center_price:
                is_swing = False; break
            if kind == "low" and ref <= center_price:
                is_swing = False; break
        if is_swing:
            points.append({"index": i, "price": center_price, "ts": _ohlcv_field(center, 0)})
    return points


def _cluster_swing_points(points, tolerance):
    clusters = []
    used = set()
    for i, p in enumerate(points):
        if i in used:
            continue
        cluster = [p]
        used.add(i)
        for j in range(i + 1, len(points)):
            if j in used:
                continue
            ref_price = p["price"]
            if abs(points[j]["price"] - ref_price) / max(ref_price, 1e-9) <= tolerance:
                if abs(points[j]["index"] - cluster[-1]["index"]) >= 3:
                    cluster.append(points[j])
                    used.add(j)
        if len(cluster) >= 2:
            avg_price = sum(c["price"] for c in cluster) / len(cluster)
            clusters.append({
                "price": avg_price,
                "count": len(cluster),
                "points": cluster,
                "last_index": max(c["index"] for c in cluster),
            })
    return clusters


def _check_cluster_swept(cluster, ohlcv, kind, sweep_lookback):
    n = len(ohlcv)
    last_index = cluster.get("last_index", 0)
    sweep_window_start = max(last_index + 1, n - sweep_lookback)
    cluster_price = cluster["price"]
    swept = False
    swept_at_ts = None
    for i in range(sweep_window_start, n):
        candle = ohlcv[i]
        high = _ohlcv_field(candle, 2)
        low = _ohlcv_field(candle, 3)
        close = _ohlcv_field(candle, 4)
        ts = _ohlcv_field(candle, 0)
        if kind == "high" and high > cluster_price and close < cluster_price:
            swept = True; swept_at_ts = ts
        elif kind == "low" and low < cluster_price and close > cluster_price:
            swept = True; swept_at_ts = ts
        if swept:
            break
    return swept, swept_at_ts


def detect_eqh_eql(ohlcv, lookback=None, swing_left=None, swing_right=None, tolerance=None, sweep_lookback=None):
    lookback = lookback or ANTI_TRAP_EQHL_LOOKBACK
    swing_left = swing_left or ANTI_TRAP_EQHL_SWING_LEFT
    swing_right = swing_right or ANTI_TRAP_EQHL_SWING_RIGHT
    tolerance = tolerance if tolerance is not None else ANTI_TRAP_EQHL_TOLERANCE
    sweep_lookback = sweep_lookback or ANTI_TRAP_EQHL_SWEEP_LOOKBACK

    if not ohlcv or len(ohlcv) < lookback:
        return {"eqh_clusters": [], "eql_clusters": []}

    window = ohlcv[-lookback:]
    high_swings = _identify_swing_points(window, swing_left, swing_right, "high")
    low_swings = _identify_swing_points(window, swing_left, swing_right, "low")
    eqh = _cluster_swing_points(high_swings, tolerance)
    eql = _cluster_swing_points(low_swings, tolerance)
    for c in eqh:
        swept, ts = _check_cluster_swept(c, window, "high", sweep_lookback)
        c["swept"] = swept; c["swept_at_ts"] = ts
    for c in eql:
        swept, ts = _check_cluster_swept(c, window, "low", sweep_lookback)
        c["swept"] = swept; c["swept_at_ts"] = ts
    return {"eqh_clusters": eqh, "eql_clusters": eql}


def compute_candle_wick_metrics(candle):
    o = _ohlcv_field(candle, 1)
    h = _ohlcv_field(candle, 2)
    l = _ohlcv_field(candle, 3)
    c = _ohlcv_field(candle, 4)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    total_range = max(h - l, 1e-9)
    body_safe = max(body, 1e-9)
    return {
        "open": o, "high": h, "low": l, "close": c,
        "body": body, "upper_wick": upper_wick, "lower_wick": lower_wick,
        "total_range": total_range,
        "upper_wick_ratio": upper_wick / body_safe,
        "lower_wick_ratio": lower_wick / body_safe,
        "is_bullish": c > o, "is_bearish": c < o,
    }


def detect_bos(ohlcv, side, lookback=None):
    lookback = lookback or ANTI_TRAP_BOS_LOOKBACK
    if not ohlcv or len(ohlcv) < lookback + 2:
        return False
    last_close = _ohlcv_field(ohlcv[-1], 4)
    window_for_swing = ohlcv[-(lookback + 5):-1]
    if side == "BUY":
        swing_high = max((_ohlcv_field(c, 2) for c in window_for_swing), default=0)
        return last_close > swing_high
    if side == "SELL":
        swing_low = min((_ohlcv_field(c, 3) for c in window_for_swing), default=float("inf"))
        return last_close < swing_low
    return False


def compute_session_liquidity_map(symbol, ohlcv, ttl_min=None):
    ttl_min = ttl_min or ANTI_TRAP_SESSION_TTL_MIN
    cached = SESSION_LIQUIDITY_CACHE.get(symbol)
    now = time.time()
    if cached and (now - cached.get("ts", 0)) < ttl_min * 60:
        return cached

    if not ohlcv or len(ohlcv) < 8:
        empty = {"ts": now, "asia_high": None, "asia_low": None,
                 "london_kz_low": None, "ny_kz_high": None,
                 "prev_day_high": None, "prev_day_low": None}
        SESSION_LIQUIDITY_CACHE[symbol] = empty
        return empty

    asia_highs, asia_lows = [], []
    london_lows = []
    ny_highs = []
    prev_day_highs, prev_day_lows = [], []
    today_str = time.strftime("%Y-%m-%d", time.gmtime(now))
    yesterday_ts = now - 86400
    yesterday_str = time.strftime("%Y-%m-%d", time.gmtime(yesterday_ts))

    for candle in ohlcv:
        ts_ms = _ohlcv_field(candle, 0)
        ts_sec = ts_ms / 1000.0 if ts_ms > 1e12 else ts_ms
        struct = time.gmtime(ts_sec)
        date_str = time.strftime("%Y-%m-%d", struct)
        hour = struct.tm_hour
        h = _ohlcv_field(candle, 2); l = _ohlcv_field(candle, 3)
        if date_str == today_str:
            if 0 <= hour < 8:
                asia_highs.append(h); asia_lows.append(l)
            if 7 <= hour < 9:
                london_lows.append(l)
            if 13 <= hour < 16:
                ny_highs.append(h)
        elif date_str == yesterday_str:
            prev_day_highs.append(h); prev_day_lows.append(l)

    result = {
        "ts": now,
        "asia_high": max(asia_highs) if asia_highs else None,
        "asia_low": min(asia_lows) if asia_lows else None,
        "london_kz_low": min(london_lows) if london_lows else None,
        "ny_kz_high": max(ny_highs) if ny_highs else None,
        "prev_day_high": max(prev_day_highs) if prev_day_highs else None,
        "prev_day_low": min(prev_day_lows) if prev_day_lows else None,
    }
    SESSION_LIQUIDITY_CACHE[symbol] = result
    return result


def detect_liquidation_clusters(ohlcv, lookback=None, z_threshold=None, tolerance=None):
    lookback = lookback or ANTI_TRAP_CLUSTER_LOOKBACK
    z_threshold = z_threshold if z_threshold is not None else ANTI_TRAP_CLUSTER_Z_THRESHOLD
    tolerance = tolerance if tolerance is not None else ANTI_TRAP_CLUSTER_TOLERANCE

    if not ohlcv or len(ohlcv) < lookback:
        return {"high_clusters": [], "low_clusters": []}

    window = ohlcv[-lookback:]
    volumes = [_ohlcv_field(c, 5) for c in window]
    n = len(volumes)
    if n < 10:
        return {"high_clusters": [], "low_clusters": []}
    mean_vol = sum(volumes) / n
    var_vol = sum((v - mean_vol) ** 2 for v in volumes) / n
    std_vol = var_vol ** 0.5 if var_vol > 0 else 1.0

    high_pivots, low_pivots = [], []
    for i in range(2, n - 2):
        candle = window[i]
        h = _ohlcv_field(candle, 2); l = _ohlcv_field(candle, 3)
        v = volumes[i]; z = (v - mean_vol) / max(std_vol, 1e-9)
        if z < z_threshold:
            continue
        is_high_pivot = (h > _ohlcv_field(window[i - 1], 2) and h > _ohlcv_field(window[i + 1], 2))
        is_low_pivot = (l < _ohlcv_field(window[i - 1], 3) and l < _ohlcv_field(window[i + 1], 3))
        if is_high_pivot:
            high_pivots.append({"index": i, "price": h, "z": z})
        if is_low_pivot:
            low_pivots.append({"index": i, "price": l, "z": z})

    def _cluster_pivots(pivots):
        clusters = []
        used = set()
        for i, p in enumerate(pivots):
            if i in used:
                continue
            group = [p]; used.add(i)
            for j in range(i + 1, len(pivots)):
                if j in used:
                    continue
                if abs(pivots[j]["price"] - p["price"]) / max(p["price"], 1e-9) <= tolerance:
                    group.append(pivots[j]); used.add(j)
            avg = sum(g["price"] for g in group) / len(group)
            zmax = max(g["z"] for g in group)
            clusters.append({"price": avg, "z_max": zmax, "candle_count": len(group)})
        return clusters

    return {"high_clusters": _cluster_pivots(high_pivots), "low_clusters": _cluster_pivots(low_pivots)}
# === MONTRA: ANTI_TRAP_DETECTORS END ===


# === MONTRA: ANTI_TRAP_EVALUATORS START ===
def evaluate_eqhl_gate(symbol, side, signal, ohlcv):
    if not ANTI_TRAP_EQHL_ENABLED:
        return True, "DISABLED", 0, {}
    detail = detect_eqh_eql(ohlcv)
    eqh = detail.get("eqh_clusters", [])
    eql = detail.get("eql_clusters", [])
    bonus = 0
    decision = "ALLOW"; reason = "OK"

    if side == "BUY":
        for c in eqh:
            if c.get("swept"):
                decision = "BLOCK"
                reason = "EQHL_BUY_TRAP_AFTER_EQH_SWEEP"
                break
        if decision == "ALLOW":
            tp = float(signal.get("tp") or 0)
            for c in eqh:
                if not c.get("swept") and tp > 0:
                    if abs(tp - c["price"]) / max(c["price"], 1e-9) < 0.003:
                        bonus = ANTI_TRAP_EQHL_BONUS
                        reason = "TP_TARGETS_EQH_LIQUIDITY"
                        break
    elif side == "SELL":
        for c in eql:
            if c.get("swept"):
                decision = "BLOCK"
                reason = "EQHL_SELL_TRAP_AFTER_EQL_SWEEP"
                break
        if decision == "ALLOW":
            tp = float(signal.get("tp") or 0)
            for c in eql:
                if not c.get("swept") and tp > 0:
                    if abs(tp - c["price"]) / max(c["price"], 1e-9) < 0.003:
                        bonus = ANTI_TRAP_EQHL_BONUS
                        reason = "TP_TARGETS_EQL_LIQUIDITY"
                        break

    allow = decision != "BLOCK"
    return allow, reason, bonus, {"detail": detail, "decision": decision, "reason": reason, "bonus": bonus}


def evaluate_wick_gate(symbol, side, ohlcv):
    if not ANTI_TRAP_WICK_ENABLED:
        return True, "DISABLED", 0, {}
    if not ohlcv or len(ohlcv) < 3:
        return True, "INSUFFICIENT_DATA", 0, {}
    last_metrics = compute_candle_wick_metrics(ohlcv[-1])
    bos = detect_bos(ohlcv, side)
    bonus = 0
    decision = "ALLOW"; reason = "OK"

    if side == "BUY":
        if last_metrics["upper_wick_ratio"] > ANTI_TRAP_WICK_RATIO_MAX:
            if ANTI_TRAP_WICK_REQUIRE_BOS and not bos:
                decision = "BLOCK"
                reason = "WICK_AGAINST_BUY_NO_BOS"
        if last_metrics["lower_wick_ratio"] > ANTI_TRAP_WICK_RATIO_MAX and last_metrics["is_bullish"]:
            bonus = ANTI_TRAP_WICK_BONUS
            reason = "LOWER_WICK_RECLAIM_SUPPORTS_BUY" if decision == "ALLOW" else reason
    elif side == "SELL":
        if last_metrics["lower_wick_ratio"] > ANTI_TRAP_WICK_RATIO_MAX:
            if ANTI_TRAP_WICK_REQUIRE_BOS and not bos:
                decision = "BLOCK"
                reason = "WICK_AGAINST_SELL_NO_BOS"
        if last_metrics["upper_wick_ratio"] > ANTI_TRAP_WICK_RATIO_MAX and last_metrics["is_bearish"]:
            bonus = ANTI_TRAP_WICK_BONUS
            reason = "UPPER_WICK_RECLAIM_SUPPORTS_SELL" if decision == "ALLOW" else reason

    allow = decision != "BLOCK"
    return allow, reason, bonus, {
        "metrics": last_metrics, "bos": bos,
        "decision": decision, "reason": reason, "bonus": bonus,
    }


def evaluate_session_alignment(side, entry, tp, liquidity_map):
    if not ANTI_TRAP_SESSION_MAP_ENABLED or not liquidity_map:
        return 0, "DISABLED_OR_EMPTY", None

    candidates = []
    if side == "BUY":
        for name in ("ny_kz_high", "asia_high", "prev_day_high"):
            v = liquidity_map.get(name)
            if v and v > entry:
                candidates.append({"name": name, "price": v})
    elif side == "SELL":
        for name in ("london_kz_low", "asia_low", "prev_day_low"):
            v = liquidity_map.get(name)
            if v and v < entry:
                candidates.append({"name": name, "price": v})

    if not candidates or tp <= 0 or entry <= 0:
        return 0, "NO_LIQUIDITY_REFERENCE", None

    if side == "BUY":
        sorted_pools = sorted(candidates, key=lambda x: x["price"])
        nearest = sorted_pools[0]
    else:
        sorted_pools = sorted(candidates, key=lambda x: -x["price"])
        nearest = sorted_pools[0]

    pool_price = nearest["price"]
    risk_reward_distance = abs(tp - entry)
    pool_distance = abs(pool_price - entry)

    if (side == "BUY" and tp >= pool_price - 0.0015 * pool_price) or (side == "SELL" and tp <= pool_price + 0.0015 * pool_price):
        if (side == "BUY" and tp > pool_price * (1 + ANTI_TRAP_SESSION_OVERSHOOT_THRESHOLD)) or \
           (side == "SELL" and tp < pool_price * (1 - ANTI_TRAP_SESSION_OVERSHOOT_THRESHOLD)):
            return -ANTI_TRAP_SESSION_TP_PENALTY, "OVERSHOOT_LIQUIDITY", nearest
        return ANTI_TRAP_SESSION_TP_BONUS, "AT_LIQUIDITY", nearest

    if pool_distance > 0 and risk_reward_distance < 0.4 * pool_distance:
        return 0, "BEFORE_LIQUIDITY", nearest

    return 0, "MISALIGNED", nearest


def evaluate_cluster_alignment(side, entry, tp, clusters):
    if not ANTI_TRAP_CLUSTER_ENABLED or not clusters:
        return 0, False, None
    pool_list = clusters.get("high_clusters", []) if side == "BUY" else clusters.get("low_clusters", [])
    if not pool_list or tp <= 0:
        return 0, False, None
    best = None; best_distance = None
    for c in pool_list:
        cprice = c.get("price", 0)
        if cprice <= 0:
            continue
        if side == "BUY" and cprice <= entry:
            continue
        if side == "SELL" and cprice >= entry:
            continue
        d = abs(tp - cprice) / max(cprice, 1e-9)
        if best is None or d < best_distance:
            best = c; best_distance = d
    if best is None:
        return 0, False, None
    if best_distance is not None and best_distance < 0.003:
        return ANTI_TRAP_CLUSTER_BONUS, True, best
    return 0, False, best


def evaluate_anti_trap_gates(signal, ohlcv, session_map=None):
    side = signal.get("type")
    symbol = signal.get("symbol", "")
    entry = float(signal.get("entry") or 0)
    tp = float(signal.get("tp") or 0)

    eqhl_allow, eqhl_reason, eqhl_bonus, eqhl_detail = evaluate_eqhl_gate(symbol, side, signal, ohlcv)
    wick_allow, wick_reason, wick_bonus, wick_detail = evaluate_wick_gate(symbol, side, ohlcv)
    if session_map is None and symbol:
        session_map = compute_session_liquidity_map(symbol, ohlcv)
    session_mod, session_reason, session_pool = evaluate_session_alignment(side, entry, tp, session_map or {})
    clusters = detect_liquidation_clusters(ohlcv)
    cluster_bonus, cluster_aligned, cluster_pool = evaluate_cluster_alignment(side, entry, tp, clusters)

    score_modifier = (eqhl_bonus or 0) + (wick_bonus or 0) + (session_mod or 0) + (cluster_bonus or 0)

    hard_block = False
    block_reason = None
    if ANTI_TRAP_MODE == "enforce":
        if not eqhl_allow:
            hard_block = True; block_reason = eqhl_reason
        elif not wick_allow:
            hard_block = True; block_reason = wick_reason
    else:
        score_modifier = 0

    return {
        "mode": ANTI_TRAP_MODE,
        "eqhl": {"allow": eqhl_allow, "reason": eqhl_reason, "bonus": eqhl_bonus, "detail": eqhl_detail},
        "wick": {"allow": wick_allow, "reason": wick_reason, "bonus": wick_bonus, "detail": wick_detail},
        "session": {"score_modifier": session_mod, "alignment": session_reason, "pool": session_pool},
        "cluster": {"bonus": cluster_bonus, "aligned": cluster_aligned, "pool": cluster_pool},
        "hard_block": hard_block,
        "block_reason": block_reason,
        "score_modifier": int(score_modifier),
    }
# === MONTRA: ANTI_TRAP_EVALUATORS END ===


def add_execution_decision(stage, symbol, status, detail=None):
    global EXECUTION_DECISIONS

    now = time.time()
    row = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": now,
        "stage": stage,
        "symbol": symbol,
        "status": status,
    }

    if detail:
        row["detail"] = detail

    EXECUTION_DECISIONS.append(row)

    if len(EXECUTION_DECISIONS) > MAX_EXECUTION_DECISIONS:
        EXECUTION_DECISIONS = EXECUTION_DECISIONS[-MAX_EXECUTION_DECISIONS:]

def set_final_execution(status, symbol=None, side=None, reason=None, stage=None, detail=None):
    global LAST_FINAL_EXECUTION
    now = time.time()
    LAST_FINAL_EXECUTION = {
        "status": status,
        "symbol": symbol,
        "side": side,
        "reason": reason,
        "stage": stage,
        "detail": detail or {},
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": now,
    }


def guard_execution_boot_state():
    """Prevent STARTING/BOOT telemetry from staying visible forever."""
    status = LAST_FINAL_EXECUTION.get("status")
    reason = LAST_FINAL_EXECUTION.get("reason")
    boot_elapsed = time.time() - APP_START_TS
    if status in ("STARTING", "IDLE") and reason in ("BOOT", "WAITING_FOR_FIRST_SCAN") and boot_elapsed > EXECUTION_BOOT_GRACE_SECONDS:
        set_final_execution(
            "IDLE",
            reason="WAITING_FOR_SCAN_TELEMETRY",
            stage="execution_boot_guard",
            detail={
                "boot_elapsed_seconds": round(boot_elapsed, 2),
                "boot_grace_seconds": EXECUTION_BOOT_GRACE_SECONDS,
                "last_scan_cycle_ts": LAST_SCAN_CYCLE_TS or None,
            },
        )


def _execution_age(ts):
    try:
        ts = float(ts or 0)
    except Exception:
        ts = 0.0
    if ts <= 0:
        return None
    return round(max(0.0, time.time() - ts), 2)



def _decision_rows_current_only(rows=None):
    """Return execution decisions from the current scan/execution era only.

    Prevents old BLOCK/PASS rows from previous scans from driving the current
    execution summary or Telegram alert source-of-truth.
    """
    rows = rows if rows is not None else EXECUTION_DECISIONS
    if not rows:
        return []

    if not TELEGRAM_ALERT_CURRENT_ONLY:
        return list(rows)

    try:
        final_ts = float((LAST_FINAL_EXECUTION or {}).get("ts") or 0)
    except Exception:
        final_ts = 0.0

    try:
        scan_ts = float(LAST_SCAN_CYCLE_TS or 0)
    except Exception:
        scan_ts = 0.0

    # Use the latest scan cycle as the primary cutoff. Fall back to the most
    # recent final_execution timestamp minus a small tolerance for rows written
    # immediately before set_final_execution().
    cutoff = max(scan_ts, final_ts - 1.0)
    if cutoff <= 0:
        return []

    current = []
    for row in rows:
        try:
            ts = float(row.get("ts") or 0)
        except Exception:
            ts = 0.0
        if ts >= cutoff:
            current.append(row)
    return current

def mark_scan_cycle(status="SCANNING", reason="SCAN_CYCLE_STARTED", pairs=None, detail=None):
    global LAST_SCAN_CYCLE_TS
    LAST_SCAN_CYCLE_TS = time.time()
    payload = {
        "pairs_due": len(pairs or []),
        "scan_interval_top": SCAN_INTERVAL_TOP,
        "scan_interval_mid": SCAN_INTERVAL_MID,
            "scan_interval_mid_aggressive": SCAN_INTERVAL_MID_AGGRESSIVE,
    }
    if detail:
        payload.update(detail)
    set_final_execution(status, reason=reason, stage="scan_cycle", detail=payload)


def set_idle_after_scan(reason, pairs=None, detail=None):
    payload = {
        "pairs_scanned": len(pairs or []),
        "candidate_count": len(candidate_list_live),
        "selected_count": len(selected_rows_live),
        "skip_count": len(skip_reasons_live),
        "last_scan_age": round(time.time() - LAST_SCAN_CYCLE_TS, 2) if LAST_SCAN_CYCLE_TS else None,
    }
    if detail:
        payload.update(detail)
    set_final_execution("IDLE", reason=reason, stage="scan_cycle_done", detail=payload)


def build_final_execution_summary(candidate_rows=None, live_rows=None):
    guard_execution_boot_state()
    candidate_rows = candidate_rows or []
    live_rows = live_rows or []

    primary = None
    source = "none"
    if live_rows:
        primary = live_rows[0]
        source = "live_position"
    elif selected_rows_live:
        primary = selected_rows_live[0]
        source = "selected"
    elif candidate_rows:
        primary = candidate_rows[0]
        source = "candidate"

    active_decisions = _decision_rows_current_only(EXECUTION_DECISIONS)
    last_decision = active_decisions[-1] if active_decisions else None
    symbol = None
    side = None

    if primary:
        symbol = primary.get("symbol")
        side = primary.get("type")
    elif last_decision:
        symbol = last_decision.get("symbol")
    elif LAST_FINAL_EXECUTION.get("symbol"):
        symbol = LAST_FINAL_EXECUTION.get("symbol")
        side = LAST_FINAL_EXECUTION.get("side")

    recent = []
    if symbol:
        recent = [r for r in active_decisions if r.get("symbol") == symbol][-8:]
    elif active_decisions:
        recent = active_decisions[-8:]

    last_for_symbol = recent[-1] if recent else last_decision
    live = next((row for row in live_rows if row.get("symbol") == symbol), None) if symbol else None

    if live:
        if live.get("protective_resolved"):
            status = "LIVE_PROTECTED"
            reason = "SL_TP_RESOLVED"
            protection = "RESOLVED"
        else:
            status = "LIVE_UNPROTECTED"
            reason = "SL_TP_PENDING"
            protection = "PENDING"
    elif not AUTO_TRADING and primary:
        status = "CANDIDATE_AUTO_TRADING_OFF"
        reason = "AUTO_TRADING_FALSE"
        protection = "NONE"
    elif not AUTO_MODE:
        status = "AUTO_MODE_OFF"
        reason = "AUTO_MODE_FALSE"
        protection = "NONE"
    elif last_for_symbol and last_for_symbol.get("status") == "BLOCK":
        status = "BLOCKED"
        reason = last_for_symbol.get("stage")
        protection = "NONE"
    elif last_for_symbol and last_for_symbol.get("stage") == "order_result" and last_for_symbol.get("status") == "PASS":
        status = "ORDER_SENT_WAITING_POSITION"
        reason = "ORDER_RESULT_PASS_NO_LIVE_POSITION_YET"
        protection = "VERIFYING"
    elif primary:
        status = "CANDIDATE_WAITING"
        reason = "NO_FINAL_ORDER_DECISION_YET"
        protection = "NONE"
    else:
        protection = "NONE"
        boot_elapsed = time.time() - APP_START_TS
        last_status = LAST_FINAL_EXECUTION.get("status", "IDLE")
        last_reason = LAST_FINAL_EXECUTION.get("reason", "NO_SIGNAL")

        if KILL_SWITCH:
            status = "KILL_SWITCH_ON"
            reason = "KILL_SWITCH_TRUE"
        elif not AUTO_MODE:
            status = "AUTO_MODE_OFF"
            reason = "AUTO_MODE_FALSE"
        elif not AUTO_TRADING:
            status = "AUTO_TRADING_OFF"
            reason = "AUTO_TRADING_FALSE"
        elif circuit_breaker_active():
            status = "CIRCUIT_BREAKER_PAUSED"
            reason = f"CIRCUIT_BREAKER_{int(circuit_breaker_remaining())}s"
        elif last_status in ("STARTING", "IDLE") and last_reason in ("BOOT", "WAITING_FOR_FIRST_SCAN") and boot_elapsed > EXECUTION_BOOT_GRACE_SECONDS:
            status = "IDLE"
            reason = "WAITING_FOR_SCAN_TELEMETRY"
        else:
            status = last_status
            reason = last_reason or "NO_SIGNAL"

    status_source = last_for_symbol if last_for_symbol else LAST_FINAL_EXECUTION
    since_ts = status_source.get("ts") if isinstance(status_source, dict) else None
    since = status_source.get("time") if isinstance(status_source, dict) else None
    last_scan_age = _execution_age(LAST_SCAN_CYCLE_TS) if LAST_SCAN_CYCLE_TS else None

    return {
        "status": status,
        "reason": reason,
        "symbol": symbol,
        "side": side,
        "source": source,
        "candidate": bool(primary and source in ("candidate", "selected")),
        "live_position": bool(live),
        "protection": protection,
        "last_stage": last_for_symbol.get("stage") if last_for_symbol else LAST_FINAL_EXECUTION.get("stage"),
        "last_status": last_for_symbol.get("status") if last_for_symbol else LAST_FINAL_EXECUTION.get("status"),
        "last_detail": last_for_symbol.get("detail") if last_for_symbol else LAST_FINAL_EXECUTION.get("detail", {}),
        "recent_decisions": recent[-5:],
        "since": since,
        "since_ts": since_ts,
        "age_seconds": _execution_age(since_ts),
        "app_uptime_seconds": round(time.time() - APP_START_TS, 2),
        "boot_grace_seconds": EXECUTION_BOOT_GRACE_SECONDS,
        "last_scan_since": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(LAST_SCAN_CYCLE_TS)) if LAST_SCAN_CYCLE_TS else None,
        "last_scan_age_seconds": last_scan_age,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


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
NEWS_CACHE = {"last_check": 0, "impact": "NORMAL", "value": None, "classification": "NEUTRAL", "source": "alternative_me_fng"}

def get_market_news():
    global NEWS_CACHE

    # FNG is sentiment context, not a hard news blocker.
    if time.time() - NEWS_CACHE.get("last_check", 0) < 300:
        return NEWS_CACHE.get("impact", "NORMAL")

    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=5).json()
        value = int(res["data"][0]["value"])

        if value < 25:
            classification = "EXTREME_FEAR"
            impact = "FNG_EXTREME_FEAR"
        elif value > 75:
            classification = "EXTREME_GREED"
            impact = "FNG_EXTREME_GREED"
        else:
            classification = "NEUTRAL"
            impact = "NORMAL"

        NEWS_CACHE = {
            "last_check": time.time(),
            "impact": impact,
            "value": value,
            "classification": classification,
            "source": "alternative_me_fng",
        }

        return impact

    except Exception as exc:
        NEWS_CACHE = {
            **NEWS_CACHE,
            "last_check": time.time(),
            "impact": "NORMAL",
            "classification": "NEUTRAL",
            "error": str(exc),
        }
        return "NORMAL"


# === MONTRA: NEWS_ENGINE_PROVIDERS START ===
def _fetch_economic_calendar_fmp(api_key=None, timeout=None):
    if not api_key:
        raise ValueError("fmp_api_key_missing_or_empty_env")
    timeout = timeout or NEWS_FETCH_TIMEOUT
    from_dt = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3600))
    to_dt = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400))
    url = (
        "https://financialmodelingprep.com/api/v3/economic_calendar"
        f"?from={from_dt}&to={to_dt}&apikey={api_key}"
    )
    try:
        resp = requests.get(url, timeout=timeout)
    except Exception as exc:
        raise ValueError(f"fmp_network_error: {exc}")
    if resp.status_code != 200:
        body_snippet = (resp.text or "")[:300].replace("\n", " ")
        if resp.status_code == 401:
            raise ValueError(f"fmp_unauthorized_check_api_key: {body_snippet}")
        if resp.status_code == 403:
            raise ValueError(f"fmp_forbidden_tier_or_endpoint_restricted: {body_snippet}")
        if resp.status_code == 429:
            raise ValueError(f"fmp_rate_limit_exceeded: {body_snippet}")
        raise ValueError(f"fmp_http_{resp.status_code}: {body_snippet}")
    try:
        data = resp.json()
    except Exception as exc:
        body_snippet = (resp.text or "")[:300].replace("\n", " ")
        raise ValueError(f"fmp_json_decode_error: {exc} body={body_snippet}")
    if isinstance(data, dict) and ("Error Message" in data or "error" in data):
        raise ValueError(f"fmp_api_error: {str(data)[:300]}")
    if not isinstance(data, list):
        raise ValueError(f"fmp_unexpected_response_type: {type(data).__name__}")
    return data


def _fetch_economic_calendar_tradingeconomics(timeout=None):
    raise ValueError("tradingeconomics_guest_endpoint_deprecated_410_gone")


def _load_economic_calendar_manual_fallback():
    path = NEWS_MANUAL_FALLBACK_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        events = payload.get("events", [])
        if not isinstance(events, list):
            return []
        return events
    except FileNotFoundError:
        return []
    except Exception as exc:
        print(f"manual fallback load error: {exc}")
        return []


def _parse_event_timestamp(raw):
    if not raw:
        return 0
    try:
        if isinstance(raw, (int, float)):
            return int(raw if raw < 1e12 else raw / 1000)
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "T" in s:
            from datetime import datetime
            dt = datetime.fromisoformat(s)
            return int(dt.timestamp())
        from datetime import datetime
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except Exception:
        return 0


def _normalize_calendar_event(raw_event, source):
    title = (
        raw_event.get("event")
        or raw_event.get("Event")
        or raw_event.get("title")
        or ""
    )
    country = (
        raw_event.get("country")
        or raw_event.get("Country")
        or raw_event.get("CountryCode")
        or ""
    ).upper()
    currency = (
        raw_event.get("currency")
        or raw_event.get("Currency")
        or ""
    ).upper()
    raw_impact = (
        raw_event.get("impact")
        or raw_event.get("Importance")
        or raw_event.get("importance")
        or ""
    )
    if isinstance(raw_impact, (int, float)):
        raw_impact = {1: "Low", 2: "Medium", 3: "High"}.get(int(raw_impact), "Low")
    raw_impact = str(raw_impact).capitalize()

    date_field = (
        raw_event.get("date")
        or raw_event.get("Date")
        or raw_event.get("datetime")
        or raw_event.get("dateUtc")
    )
    ts = _parse_event_timestamp(date_field)
    if ts == 0:
        return None

    tier, category, scope = classify_news_impact(title, country, raw_impact)

    return {
        "id": f"{source}_{ts}_{title.replace(' ', '_')[:32]}",
        "ts_utc": ts,
        "date_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "country": country,
        "currency": currency,
        "title": title,
        "raw_impact": raw_impact,
        "tier": tier,
        "category": category,
        "scope": scope,
        "previous": raw_event.get("previous") or raw_event.get("Previous"),
        "estimate": raw_event.get("estimate") or raw_event.get("Forecast") or raw_event.get("forecast"),
        "actual": raw_event.get("actual") or raw_event.get("Actual"),
        "source": source,
    }
# === MONTRA: NEWS_ENGINE_PROVIDERS END ===


# === MONTRA: NEWS_ENGINE_CORE START ===
def classify_news_impact(event_title, country, raw_impact):
    title_low = (event_title or "").lower()
    country_up = (country or "").upper()

    is_us_or_global = country_up in ("US", "USD", "UNITED STATES", "EUR", "EU", "EMU", "EUROPEAN MONETARY UNION", "")
    is_eu = country_up in ("EU", "EUR", "EMU", "DE", "GERMANY", "FR", "FRANCE", "EUROPEAN MONETARY UNION")
    is_asia = country_up in ("JP", "JPY", "JAPAN", "CN", "CNY", "CHINA")

    tier_1 = any(kw in title_low for kw in NEWS_TIER1_KEYWORDS)
    tier_2 = any(kw in title_low for kw in NEWS_TIER2_KEYWORDS)
    tier_3 = any(kw in title_low for kw in NEWS_TIER3_KEYWORDS)

    raw_high = str(raw_impact or "").lower() == "high"
    raw_med = str(raw_impact or "").lower() == "medium"

    if tier_1 and (is_us_or_global or is_eu or is_asia):
        tier = "TIER_1_RED"
    elif tier_2 and (is_us_or_global or is_eu or is_asia):
        tier = "TIER_2_ORANGE"
    elif raw_high and (is_us_or_global or is_eu):
        tier = "TIER_2_ORANGE"
    elif tier_3 or raw_med:
        tier = "TIER_3_YELLOW"
    else:
        tier = "TIER_NONE"

    if any(k in title_low for k in ("cpi", "ppi", "core pce", "pce price")):
        category = "INFLATION"
    elif any(k in title_low for k in ("payrolls", "unemployment", "jobless", "jolts", "employment")):
        category = "EMPLOYMENT"
    elif any(k in title_low for k in ("interest rate", "fomc", "ecb", "boj", "boe", "fed chair", "powell")):
        category = "RATE"
    elif "gdp" in title_low:
        category = "GDP"
    elif any(k in title_low for k in ("etf", "sec ", "halving")):
        category = "CRYPTO_SPECIFIC"
    else:
        category = "OTHER"

    if any(k in title_low for k in NEWS_SCOPE_BTC_KEYWORDS):
        scope = "BTC_HEAVY"
    elif any(k in title_low for k in NEWS_SCOPE_GLOBAL_KEYWORDS) and is_us_or_global:
        scope = "GLOBAL_CRYPTO"
    elif any(k in title_low for k in NEWS_SCOPE_EU_KEYWORDS) or is_eu:
        scope = "EU_LIMITED"
    elif any(k in title_low for k in NEWS_SCOPE_ASIA_KEYWORDS) or is_asia:
        scope = "ASIA_LIMITED"
    else:
        scope = "NONE"

    return tier, category, scope


def refresh_institutional_news_cache(force=False):
    global INSTITUTIONAL_NEWS_CACHE
    if not NEWS_ENGINE_ENABLED:
        return INSTITUTIONAL_NEWS_CACHE

    now = time.time()
    with INSTITUTIONAL_NEWS_LOCK:
        if not force and now < INSTITUTIONAL_NEWS_CACHE.get("next_refresh_ts", 0):
            return INSTITUTIONAL_NEWS_CACHE

        raw_events = []
        used_source = None
        fetch_error = None
        provider_errors = {}

        provider_order = [NEWS_ENGINE_PROVIDER, "tradingeconomics", "manual"]
        seen = set()
        provider_chain = []
        for p in provider_order:
            if p not in seen:
                provider_chain.append(p)
                seen.add(p)

        for provider in provider_chain:
            try:
                if provider == "fmp":
                    raw_events = _fetch_economic_calendar_fmp(api_key=FMP_API_KEY)
                    used_source = "fmp"
                    break
                elif provider == "tradingeconomics":
                    raw_events = _fetch_economic_calendar_tradingeconomics()
                    used_source = "tradingeconomics"
                    break
                elif provider == "manual":
                    raw_events = _load_economic_calendar_manual_fallback()
                    used_source = "manual_fallback"
                    if raw_events:
                        break
            except Exception as exc:
                err_msg = str(exc)
                provider_errors[provider] = err_msg
                fetch_error = f"{provider}: {err_msg}"
                continue

        if not raw_events:
            INSTITUTIONAL_NEWS_CACHE["fetch_attempts"] = INSTITUTIONAL_NEWS_CACHE.get("fetch_attempts", 0) + 1
            INSTITUTIONAL_NEWS_CACHE["fetch_error"] = fetch_error or "no_events"
            INSTITUTIONAL_NEWS_CACHE["provider_errors"] = provider_errors
            INSTITUTIONAL_NEWS_CACHE["next_refresh_ts"] = now + NEWS_REFRESH_INTERVAL
            print(f"📰 NEWS REFRESH FAILED provider_errors={provider_errors}")
            return INSTITUTIONAL_NEWS_CACHE

        normalized = []
        for raw in raw_events:
            try:
                norm = _normalize_calendar_event(raw, used_source or "unknown")
                if norm and norm["ts_utc"] > 0:
                    normalized.append(norm)
            except Exception:
                continue

        cutoff_low = now - 3600
        cutoff_high = now + 86400
        filtered = [e for e in normalized if cutoff_low <= e["ts_utc"] <= cutoff_high]
        filtered.sort(key=lambda e: e["ts_utc"])

        INSTITUTIONAL_NEWS_CACHE = {
            "last_refresh_ts": now,
            "next_refresh_ts": now + NEWS_REFRESH_INTERVAL,
            "events": filtered,
            "source": used_source,
            "fetch_error": None,
            "fetch_attempts": 0,
            "provider_errors": provider_errors,
        }
        print(f"📰 NEWS REFRESH ok source={used_source} events={len(filtered)}")
    return INSTITUTIONAL_NEWS_CACHE


def get_event_phase(event, now_ts=None):
    now_ts = now_ts or time.time()
    ts = event.get("ts_utc", 0)
    if ts <= 0:
        return "CLEAR"
    diff_min = (now_ts - ts) / 60.0
    tier = event.get("tier", "TIER_NONE")

    if tier == "TIER_1_RED":
        if -NEWS_PRE_EVENT_BLOCK_MIN <= diff_min < 0:
            return "PRE"
        if 0 <= diff_min < NEWS_EVENT_WINDOW_MIN:
            return "EVENT"
        if NEWS_EVENT_WINDOW_MIN <= diff_min < NEWS_EVENT_WINDOW_MIN + NEWS_POST_EVENT_PENALTY_MIN:
            return "POST"
        return "CLEAR"

    if tier == "TIER_2_ORANGE":
        if -NEWS_TIER2_PRE_BLOCK_MIN <= diff_min < 0:
            return "PRE"
        if 0 <= diff_min < NEWS_EVENT_WINDOW_MIN:
            return "EVENT"
        if NEWS_EVENT_WINDOW_MIN <= diff_min < NEWS_EVENT_WINDOW_MIN + NEWS_TIER2_POST_PENALTY_MIN:
            return "POST"
        return "CLEAR"

    return "CLEAR"


def news_applies_to_symbol(event, symbol):
    scope = event.get("scope", "NONE")
    sym_up = (symbol or "").upper()

    if scope == "GLOBAL_CRYPTO":
        return True, 1.0
    if scope == "BTC_HEAVY":
        if sym_up in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            return True, 1.0
        return True, 0.5
    if scope == "EU_LIMITED":
        return True, 0.5
    if scope == "ASIA_LIMITED":
        if sym_up in ("HYPEUSDT", "WIFUSDT", "1000PEPEUSDT", "SUIUSDT"):
            return True, 1.0
        return True, 0.25
    return False, 0.0


def get_institutional_news_state(symbol="_SYSTEM_", now_ts=None):
    now_ts = now_ts or time.time()
    if not NEWS_ENGINE_ENABLED:
        return {
            "active_event": None, "phase": "CLEAR", "tier": "TIER_NONE",
            "scope": "NONE", "block_decision": False, "score_penalty": 0,
            "minutes_to_event": None, "minutes_since_event": None,
            "applies_to_symbol": False, "severity_modifier": 0.0,
            "source": "disabled", "cache_age_seconds": 0,
        }

    refresh_institutional_news_cache()

    events = INSTITUTIONAL_NEWS_CACHE.get("events", []) or []
    candidate = None
    candidate_phase = "CLEAR"
    candidate_applies = False
    candidate_severity = 0.0

    for ev in events:
        phase = get_event_phase(ev, now_ts)
        if phase == "CLEAR":
            continue
        applies, severity = news_applies_to_symbol(ev, symbol)
        if not applies:
            continue
        rank = {"PRE": 3, "EVENT": 4, "POST": 1}.get(phase, 0)
        cand_rank = {"PRE": 3, "EVENT": 4, "POST": 1}.get(candidate_phase, 0)
        if candidate is None or rank > cand_rank:
            candidate = ev
            candidate_phase = phase
            candidate_applies = applies
            candidate_severity = severity

    if candidate is None:
        return {
            "active_event": None, "phase": "CLEAR", "tier": "TIER_NONE",
            "scope": "NONE", "block_decision": False, "score_penalty": 0,
            "minutes_to_event": None, "minutes_since_event": None,
            "applies_to_symbol": False, "severity_modifier": 0.0,
            "source": INSTITUTIONAL_NEWS_CACHE.get("source") or "empty",
            "cache_age_seconds": int(now_ts - INSTITUTIONAL_NEWS_CACHE.get("last_refresh_ts", now_ts)),
        }

    tier = candidate.get("tier", "TIER_NONE")
    block = False
    penalty = 0
    if candidate_phase in ("PRE", "EVENT"):
        if tier == "TIER_1_RED" and NEWS_TIER1_HARD_BLOCK:
            block = True
        elif tier == "TIER_2_ORANGE" and NEWS_TIER2_HARD_BLOCK:
            block = True
    elif candidate_phase == "POST":
        if tier == "TIER_1_RED":
            penalty = NEWS_TIER1_POST_PENALTY
        elif tier == "TIER_2_ORANGE":
            penalty = NEWS_TIER2_POST_PENALTY

    if candidate_severity < 1.0:
        if candidate_severity < 0.5 and block:
            block = False
            penalty = max(penalty, NEWS_TIER2_POST_PENALTY)

    diff_sec = candidate.get("ts_utc", 0) - now_ts
    if diff_sec > 0:
        minutes_to_event = int(diff_sec / 60)
        minutes_since_event = None
    else:
        minutes_to_event = None
        minutes_since_event = int(-diff_sec / 60)

    return {
        "active_event": candidate, "phase": candidate_phase,
        "tier": tier, "scope": candidate.get("scope", "NONE"),
        "block_decision": block, "score_penalty": penalty,
        "minutes_to_event": minutes_to_event,
        "minutes_since_event": minutes_since_event,
        "applies_to_symbol": candidate_applies,
        "severity_modifier": candidate_severity,
        "source": INSTITUTIONAL_NEWS_CACHE.get("source") or "empty",
        "cache_age_seconds": int(now_ts - INSTITUTIONAL_NEWS_CACHE.get("last_refresh_ts", now_ts)),
    }
# === MONTRA: NEWS_ENGINE_CORE END ===


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

def _symbol_env_key(symbol):
    return str(symbol or "").upper().replace("/", "").replace("-", "").replace(" ", "")


def _decimal_or_none(value):
    try:
        d = Decimal(str(value))
        if d > 0:
            return d
    except Exception:
        return None
    return None


def _precision_step(price_precision):
    try:
        pp = int(price_precision)
        if pp < 0:
            return None
        return Decimal("1").scaleb(-pp)
    except Exception:
        return None


def get_price_tick_detail(symbol):
    """Return effective tick step for entry/SL/TP.

    Source order:
    1) PRICE_TICK_SIZE_<SYMBOL> env override
    2) EXCHANGE_CACHE PRICE_FILTER tickSize
    3) EXCHANGE_CACHE pricePrecision fallback

    With PRICE_PRECISION_USE_PRICE_PRECISION=true, MONTRA uses the coarser of
    tickSize and pricePrecision step. This prevents candidates like SUIUSDT
    TP=0.91835 when effective precision is 4 decimals -> 0.9184.
    """
    sym = _symbol_env_key(symbol)
    f = EXCHANGE_CACHE.get(sym) or {}
    override = os.getenv(f"PRICE_TICK_SIZE_{sym}") or os.getenv(f"TICK_SIZE_{sym}")

    tick_source = "missing"
    tick = None
    if override:
        tick = _decimal_or_none(override)
        tick_source = "env_override"
    if tick is None:
        tick = _decimal_or_none(f.get("tickSizeText") or f.get("tickSize"))
        tick_source = "exchange_tickSize" if tick is not None else "missing"

    precision_step = _precision_step(f.get("pricePrecision"))
    if PRICE_PRECISION_USE_PRICE_PRECISION and precision_step is not None and precision_step > 0:
        if tick is None or precision_step > tick:
            tick = precision_step
            tick_source = "pricePrecision"
        else:
            tick_source = tick_source + "+pricePrecision_checked"

    if tick is None or tick <= 0:
        return {
            "ok": False,
            "reason": "missing_tick_size",
            "tick": None,
            "tickSize": None,
            "tick_text": None,
            "source": tick_source,
            "exchange": f,
            "pricePrecision": f.get("pricePrecision"),
        }

    tick_text = format(tick, "f")
    return {
        "ok": True,
        "reason": "OK",
        "tick": tick,
        "tickSize": float(tick),
        "tick_text": tick_text,
        "source": tick_source,
        "pricePrecision": f.get("pricePrecision"),
        "exchange_tickSize": f.get("tickSize"),
        "exchange_tickSizeText": f.get("tickSizeText"),
    }


def floor_to_step(value, step):
    d = Decimal(str(value))
    s = Decimal(str(step))
    if s <= 0:
        return float(d)
    return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)

def ceil_to_step(value, step):
    d = Decimal(str(value))
    s = Decimal(str(step))
    if s <= 0:
        return float(d)
    return float((d / s).to_integral_value(rounding=ROUND_UP) * s)

def _round_decimal_to_step(value, step, rounding=ROUND_DOWN):
    d = Decimal(str(value))
    s = Decimal(str(step))
    if s <= 0:
        return d
    return (d / s).to_integral_value(rounding=rounding) * s

def _format_decimal_to_step(value, step):
    """Return Binance-safe decimal string using the exact step/tick precision.

    Avoid passing raw Python floats like 98.74000000000002 as stopPrice.
    """
    d = Decimal(str(value))
    s = Decimal(str(step))
    if s <= 0:
        return format(d.normalize(), "f")
    q = s.normalize()
    return format(d.quantize(q), "f")

def normalize_price(symbol, price):
    tick_detail = get_price_tick_detail(symbol)
    if not tick_detail.get("ok"):
        return price
    return float(_round_decimal_to_step(price, tick_detail["tick"], rounding=ROUND_HALF_UP))


def normalize_protective_price_detail(symbol, price, side, leg):
    """Round SL/TP using EXCHANGE_CACHE tickSize and return float + safe string.

    No extra Binance API call is made here. If tickSize is missing, the caller
    gets tick_missing=True so entry can be blocked before creating an unprotected position.
    """
    tick_detail = get_price_tick_detail(symbol)
    tick = tick_detail.get("tick")
    raw = Decimal(str(price or 0))
    side = str(side or "").upper()
    leg = str(leg or "").upper()
    if raw <= 0:
        return {"ok": False, "reason": "invalid_price", "raw": float(raw), "value": float(raw), "text": str(raw), "tickSize": tick_detail.get("tickSize"), "tick_source": tick_detail.get("source")}
    if not tick_detail.get("ok"):
        return {"ok": False, "reason": tick_detail.get("reason", "missing_tick_size"), "raw": float(raw), "value": float(raw), "text": format(raw, "f"), "tickSize": tick_detail.get("tickSize"), "tick_source": tick_detail.get("source")}

    # MONTRA v4.9.4: entry, SL and TP must be tick-clean before quality
    # checks, candidate exposure and order placement. Use Decimal HALF_UP so
    # SUIUSDT 0.91835 at 0.0001 tick becomes 0.9184.
    rounding = ROUND_HALF_UP

    rounded = _round_decimal_to_step(raw, tick, rounding=rounding)
    return {
        "ok": True,
        "reason": "OK",
        "raw": float(raw),
        "value": float(rounded),
        "text": _format_decimal_to_step(rounded, tick),
        "tickSize": float(tick),
        "tick_text": tick_detail.get("tick_text"),
        "tick_source": tick_detail.get("source"),
        "pricePrecision": tick_detail.get("pricePrecision"),
        "rounding": "HALF_UP",
        "leg": leg,
    }

def normalize_protective_price(symbol, price, side, leg):
    return normalize_protective_price_detail(symbol, price, side, leg).get("value", float(price or 0))

def normalize_entry_price_detail(symbol, price):
    tick_detail = get_price_tick_detail(symbol)
    tick = tick_detail.get("tick")
    raw = Decimal(str(price or 0))
    if raw <= 0:
        return {"ok": False, "reason": "invalid_entry", "raw": float(raw), "value": float(raw), "text": str(raw), "tickSize": tick_detail.get("tickSize"), "tick_source": tick_detail.get("source")}
    if not tick_detail.get("ok"):
        return {"ok": False, "reason": tick_detail.get("reason", "missing_tick_size"), "raw": float(raw), "value": float(raw), "text": format(raw, "f"), "tickSize": tick_detail.get("tickSize"), "tick_source": tick_detail.get("source")}
    rounded = _round_decimal_to_step(raw, tick, rounding=ROUND_HALF_UP)
    return {
        "ok": True,
        "reason": "OK",
        "raw": float(raw),
        "value": float(rounded),
        "text": _format_decimal_to_step(rounded, tick),
        "tickSize": float(tick),
        "tick_text": tick_detail.get("tick_text"),
        "tick_source": tick_detail.get("source"),
        "pricePrecision": tick_detail.get("pricePrecision"),
        "rounding": "HALF_UP",
        "leg": "ENTRY",
    }

def normalize_signal_execution_prices(signal, reference_price=None):
    symbol = str((signal or {}).get("symbol") or "").upper().strip()
    side = str((signal or {}).get("type") or (signal or {}).get("side") or "").upper().strip()
    raw_entry = _safe_float((signal or {}).get("entry"), 0.0)
    if raw_entry <= 0 and reference_price is not None:
        raw_entry = _safe_float(reference_price, 0.0)
    raw_sl = _safe_float((signal or {}).get("sl"), 0.0)
    raw_tp = _safe_float((signal or {}).get("tp"), 0.0)

    entry_detail = normalize_entry_price_detail(symbol, raw_entry)
    sl_detail = normalize_protective_price_detail(symbol, raw_sl, side, "SL")
    tp_detail = normalize_protective_price_detail(symbol, raw_tp, side, "TP")

    ok = bool(entry_detail.get("ok") and sl_detail.get("ok") and tp_detail.get("ok"))
    return {
        "ok": ok,
        "symbol": symbol,
        "side": side,
        "entry": entry_detail.get("value", raw_entry),
        "sl": sl_detail.get("value", raw_sl),
        "tp": tp_detail.get("value", raw_tp),
        "entry_text": entry_detail.get("text"),
        "sl_text": sl_detail.get("text"),
        "tp_text": tp_detail.get("text"),
        "details": {"entry": entry_detail, "sl": sl_detail, "tp": tp_detail},
    }

def apply_clean_prices_to_signal(signal, reference_price=None):
    clean = normalize_signal_execution_prices(signal, reference_price=reference_price)
    if clean.get("ok"):
        signal["entry"] = clean["entry"]
        signal["sl"] = clean["sl"]
        signal["tp"] = clean["tp"]
        signal["entry_text"] = clean.get("entry_text")
        signal["sl_text"] = clean.get("sl_text")
        signal["tp_text"] = clean.get("tp_text")
        signal["price_precision"] = clean.get("details")
        signal["rr"] = round(abs(clean["tp"] - clean["entry"]) / max(abs(clean["entry"] - clean["sl"]), 1e-12), 2)
    return signal

def normalize_quantity_detail(symbol, qty):
    f = EXCHANGE_CACHE.get(symbol) or {}
    step = f.get("stepSize")
    raw = Decimal(str(qty or 0))
    if raw <= 0:
        return {"ok": False, "reason": "invalid_qty", "raw": float(raw), "value": float(raw), "text": str(raw), "stepSize": step}
    if not step or float(step) <= 0:
        return {"ok": False, "reason": "missing_step_size", "raw": float(raw), "value": float(raw), "text": format(raw, "f"), "stepSize": step}
    rounded = _round_decimal_to_step(raw, step, rounding=ROUND_DOWN)
    return {"ok": True, "reason": "OK", "raw": float(raw), "value": float(rounded), "text": _format_decimal_to_step(rounded, step), "stepSize": float(step)}

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
                "stepSizeText": str(lot["stepSize"]),
                "minQty": float(lot["minQty"]),
                "minQtyText": str(lot["minQty"]),
                "tickSize": float(price["tickSize"]),
                "tickSizeText": str(price["tickSize"]),
                "pricePrecision": s.get("pricePrecision"),
                "quantityPrecision": s.get("quantityPrecision"),
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
    tick_detail = get_price_tick_detail(symbol)
    tick = tick_detail.get("tickSize") or f["tickSize"]

    qty = floor_to_step(qty, step)
    if qty < min_qty:
        qty = min_qty
    qty = floor_to_step(qty, step)

    price = float(_round_decimal_to_step(price, tick, rounding=ROUND_HALF_UP))
    return qty, price

def get_min_trade_notional(symbol):
    # v5.3 default: all active groups use DEFAULT_MIN_TRADE_NOTIONAL=100
    # unless USE_DEFAULT_MIN_NOTIONAL_FOR_ALL=false is explicitly set.
    if USE_DEFAULT_MIN_NOTIONAL_FOR_ALL:
        return DEFAULT_MIN_TRADE_NOTIONAL
    tier = get_pair_tier(symbol)
    if tier == "TOP":
        return TOP_MIN_TRADE_NOTIONAL
    if tier == "MID":
        return MID_MIN_TRADE_NOTIONAL
    if tier == "MID_AGGRESSIVE":
        return MID_AGGRESSIVE_MIN_TRADE_NOTIONAL
    return LOW_MIN_TRADE_NOTIONAL

def _safe_float(value, default=0.0):
    try:
        num = float(value)
        if num == num and abs(num) != float("inf"):
            return num
    except Exception:
        pass
    return default


def build_order_client_id(symbol, side, purpose):
    prefix = ORDER_ID_PREFIX or "M"
    clean_symbol = str(symbol or "NA").upper().replace("/", "")[:12]
    side_code = "B" if str(side).upper() == "BUY" else "S"
    purpose_code = str(purpose or "O").upper()[:3]
    millis = int(time.time() * 1000) % 10_000_000_000
    return f"{prefix}_{clean_symbol}_{side_code}_{purpose_code}_{millis}"[:36]


def evaluate_signal_execution_quality(signal, reference_price=None):
    symbol = signal.get("symbol")
    side = str(signal.get("type") or signal.get("side") or "").upper()

    clean = normalize_signal_execution_prices(signal, reference_price=reference_price)
    entry = _safe_float(clean.get("entry"), 0.0)
    sl = _safe_float(clean.get("sl"), 0.0)
    tp = _safe_float(clean.get("tp"), 0.0)

    # Mutate the signal intentionally so downstream placement, decision-board,
    # Telegram and quality metrics use the exact tick-clean prices.
    if clean.get("ok"):
        signal["entry"] = entry
        signal["sl"] = sl
        signal["tp"] = tp
        signal["entry_text"] = clean.get("entry_text")
        signal["sl_text"] = clean.get("sl_text")
        signal["tp_text"] = clean.get("tp_text")
        signal["price_precision"] = clean.get("details")

    detail = {
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "entry_text": clean.get("entry_text"),
        "sl_text": clean.get("sl_text"),
        "tp_text": clean.get("tp_text"),
        "price_precision": clean.get("details"),
        "min_stop_distance_pct": MIN_STOP_DISTANCE_PCT,
        "min_tp_distance_pct": MIN_TP_DISTANCE_PCT,
        "fee_buffer_rr": FEE_BUFFER_RR,
    }

    if not clean.get("ok"):
        detail["reason"] = "precision_normalization_failed"
        return False, "PRICE_PRECISION_INVALID", detail

    if not symbol or side not in ("BUY", "SELL") or entry <= 0 or sl <= 0 or tp <= 0:
        detail["reason"] = "missing_symbol_side_or_prices"
        return False, "INVALID_EXECUTION_PRICES", detail

    if side == "BUY":
        if not (sl < entry < tp):
            detail["reason"] = "buy_direction_invalid"
            return False, "INVALID_BUY_PRICE_ORDER", detail
    else:
        if not (tp < entry < sl):
            detail["reason"] = "sell_direction_invalid"
            return False, "INVALID_SELL_PRICE_ORDER", detail

    stop_pct = abs(entry - sl) / max(entry, 1e-12)
    tp_pct = abs(tp - entry) / max(entry, 1e-12)
    raw_rr = abs(tp - entry) / max(abs(entry - sl), 1e-12)
    effective_rr = raw_rr - FEE_BUFFER_RR

    spread_pct = signal.get("spread_pct")
    if spread_pct is not None:
        spread_pct = _safe_float(spread_pct, 0.0)
    detail.update({
        "stop_distance_pct": round(stop_pct, 6),
        "tp_distance_pct": round(tp_pct, 6),
        "raw_rr": round(raw_rr, 4),
        "effective_rr": round(effective_rr, 4),
        "spread_pct": spread_pct,
    })

    if stop_pct < MIN_STOP_DISTANCE_PCT:
        return False, "STOP_DISTANCE_TOO_TIGHT", detail

    if tp_pct < MIN_TP_DISTANCE_PCT:
        return False, "TP_DISTANCE_TOO_TIGHT", detail

    if effective_rr < active_rr_min():
        return False, "EFFECTIVE_RR_TOO_LOW", detail

    return True, "OK", detail


def fetch_conditional_open_orders_for_client(client_obj, label, symbol):
    """Fetch Binance Algo Service conditional open orders when python-binance supports it."""
    if not PROTECTION_VERIFY_CONDITIONAL_ORDERS or client_obj is None:
        return []
    try:
        orders = signed_call(
            client_obj,
            client_obj.futures_get_open_orders,
            symbol=symbol,
            conditional=True,
            label=label,
        )
        return orders or []
    except TypeError as exc:
        add_order_audit("CONDITIONAL_OPEN_ORDERS_UNSUPPORTED", symbol, {"account": label, "error": str(exc)})
        return []
    except Exception as exc:
        add_order_audit("CONDITIONAL_OPEN_ORDERS_ERROR", symbol, {"account": label, "error": str(exc)})
        return []


def cancel_conditional_order_for_client(client_obj, label, symbol, order):
    ref_type, ref_id = _protection_order_ref(order)
    if not ref_id:
        return False
    params = {"symbol": symbol, "conditional": True}
    if ref_type == "algoId":
        params["algoId"] = ref_id
    elif ref_type == "clientAlgoId":
        params["clientAlgoId"] = ref_id
    else:
        # Standard orders are cancelled by the normal cancel path.
        return False
    try:
        signed_call(client_obj, client_obj.futures_cancel_order, label=label, **params)
        add_order_audit("CANCEL_CONDITIONAL_PROTECTION_OK", symbol, {"account": label, "ref_type": ref_type, "ref_id": ref_id})
        return True
    except Exception as exc:
        add_order_audit("CANCEL_CONDITIONAL_PROTECTION_ERROR", symbol, {"account": label, "ref_type": ref_type, "ref_id": ref_id, "error": str(exc)})
        return False


def cancel_protective_orders_for_client(client_obj, label, symbol, cancel_tp=True, cancel_sl=True):
    if client_obj is None:
        return False
    ok = True
    try:
        # Standard active orders.
        orders = signed_call(client_obj, client_obj.futures_get_open_orders, symbol=symbol, label=label)
        for o in orders or []:
            otype = str(_protection_order_type(o) or "").upper()
            should_cancel = (cancel_sl and otype == "STOP_MARKET") or (cancel_tp and otype == "TAKE_PROFIT_MARKET")
            if not should_cancel:
                continue
            try:
                signed_call(client_obj, client_obj.futures_cancel_order, symbol=symbol, orderId=o["orderId"], label=label)
                add_order_audit("CANCEL_STANDARD_PROTECTION_OK", symbol, {"account": label, "orderId": o.get("orderId"), "type": otype})
            except Exception as exc:
                ok = False
                add_order_audit("CANCEL_STANDARD_PROTECTION_ERROR", symbol, {"account": label, "orderId": o.get("orderId"), "type": otype, "error": str(exc)})

        # Conditional Algo Service orders. Binance migrated STOP_MARKET / TP_MARKET
        # conditional orders to algo order objects, so they must be queried and
        # cancelled with conditional=True + algoId/clientAlgoId.
        algo_orders = fetch_conditional_open_orders_for_client(client_obj, label, symbol)
        for o in algo_orders or []:
            otype = str(_protection_order_type(o) or "").upper()
            should_cancel = (cancel_sl and otype == "STOP_MARKET") or (cancel_tp and otype == "TAKE_PROFIT_MARKET")
            if not should_cancel:
                continue
            if not cancel_conditional_order_for_client(client_obj, label, symbol, o):
                ok = False

        RECENT_PROTECTION_ORDERS.pop(symbol, None)
        if client_obj is binance:
            invalidate_main_open_orders_cache()
        return ok
    except Exception as exc:
        print(f"Cancel protective orders error {label} {symbol}:", exc)
        add_order_audit("CANCEL_PROTECTIVE_ORDERS_ERROR", symbol, {"account": label, "error": str(exc)})
        return False


def verify_protective_orders_for_client(client_obj, label, symbol):
    try:
        standard_orders = signed_call(client_obj, client_obj.futures_get_open_orders, symbol=symbol, label=label) or []
        algo_orders = fetch_conditional_open_orders_for_client(client_obj, label, symbol)
        combined = list(standard_orders or []) + list(algo_orders or [])
        exits = build_exit_lookup(combined).get(symbol, {})
        recent = _recent_protection_verify(symbol) if PROTECTION_VERIFY_PLACEMENT_FALLBACK else {"rows": []}

        sl = exits.get("sl") or recent.get("sl")
        tp = exits.get("tp") or recent.get("tp")
        sl_ok = _safe_float(sl, 0.0) > 0
        tp_ok = _safe_float(tp, 0.0) > 0
        source = "open_orders"
        if (not exits.get("sl") or not exits.get("tp")) and sl_ok and tp_ok:
            source = "recent_algo_placement_fallback"
            add_order_audit("PROTECTION_VERIFY_RECENT_PLACEMENT_FALLBACK", symbol, {
                "account": label,
                "sl_ref": recent.get("sl_ref"),
                "tp_ref": recent.get("tp_ref"),
                "standard_open_order_count": len(standard_orders or []),
                "conditional_open_order_count": len(algo_orders or []),
            })

        return {
            "ok": bool(sl_ok and tp_ok),
            "sl_resolved": bool(sl_ok),
            "tp_resolved": bool(tp_ok),
            "sl": sl,
            "tp": tp,
            "sl_ref": exits.get("sl_ref") or recent.get("sl_ref"),
            "tp_ref": exits.get("tp_ref") or recent.get("tp_ref"),
            "open_order_count": len(combined or []),
            "standard_open_order_count": len(standard_orders or []),
            "conditional_open_order_count": len(algo_orders or []),
            "source": source,
        }
    except Exception as exc:
        return {"ok": False, "sl_resolved": False, "tp_resolved": False, "error": str(exc)}


def verify_protective_orders_with_retry(client_obj, label, symbol, attempts=None, delay=None):
    attempts = max(1, int(attempts if attempts is not None else PROTECTION_VERIFY_RETRIES))
    delay = float(delay if delay is not None else PROTECTION_VERIFY_DELAY)
    last = None
    for attempt in range(1, attempts + 1):
        result = verify_protective_orders_for_client(client_obj, label, symbol)
        result["attempt"] = attempt
        result["attempts"] = attempts
        last = result
        if result.get("ok"):
            add_order_audit("PROTECTION_VERIFY_OK", symbol, {"account": label, "attempt": attempt, "verify": result})
            return result
        if attempt < attempts:
            add_order_audit("PROTECTION_VERIFY_RETRY", symbol, {"account": label, "attempt": attempt, "verify": result, "sleep": delay})
            time.sleep(delay)
    add_order_audit("PROTECTION_VERIFY_FINAL_FAILED", symbol, {"account": label, "verify": last})
    return last or {"ok": False, "sl_resolved": False, "tp_resolved": False, "attempts": attempts}


def get_position_amt_for_client(client_obj, label, symbol):
    """Return current futures position amount from Binance, bypassing app caches."""
    try:
        positions = signed_call(client_obj, client_obj.futures_position_information, symbol=symbol, label=label)
        for pos in positions or []:
            if str(pos.get("symbol", "")).upper() == str(symbol).upper():
                return _safe_float(pos.get("positionAmt"), 0.0)
    except Exception as exc:
        add_order_audit("POSITION_FETCH_ERROR", symbol, {"account": label, "error": str(exc)})
    return 0.0


def wait_for_position_for_client(client_obj, label, symbol, side, min_qty=0.0, attempts=None, delay=None):
    """Wait until the market entry is reflected as an open position."""
    attempts = max(1, int(attempts if attempts is not None else PROTECTION_ENTRY_CONFIRM_RETRIES))
    delay = float(delay if delay is not None else PROTECTION_ENTRY_CONFIRM_DELAY)
    side = str(side or "").upper()
    min_qty = abs(_safe_float(min_qty, 0.0))
    last_amt = 0.0

    for attempt in range(1, attempts + 1):
        amt = get_position_amt_for_client(client_obj, label, symbol)
        last_amt = amt
        ok = (side == "BUY" and amt > 0) or (side == "SELL" and amt < 0)
        if ok and abs(amt) >= max(min_qty * 0.25, 1e-12):
            detail = {"account": label, "side": side, "position_amt": amt, "qty": abs(amt), "attempt": attempt, "attempts": attempts}
            add_order_audit("ENTRY_POSITION_CONFIRMED", symbol, detail)
            return {"ok": True, **detail}
        if attempt < attempts:
            add_order_audit("ENTRY_POSITION_WAIT", symbol, {
                "account": label, "side": side, "position_amt": amt, "attempt": attempt, "attempts": attempts, "sleep": delay,
            })
            time.sleep(delay)

    detail = {"account": label, "side": side, "position_amt": last_amt, "qty": abs(last_amt), "attempts": attempts}
    add_order_audit("ENTRY_POSITION_NOT_CONFIRMED", symbol, detail)
    return {"ok": False, **detail}


def wait_for_position_closed_for_client(client_obj, label, symbol, attempts=None, delay=None):
    attempts = max(1, int(attempts if attempts is not None else EMERGENCY_CLOSE_VERIFY_RETRIES))
    delay = float(delay if delay is not None else EMERGENCY_CLOSE_VERIFY_DELAY)
    step = _safe_float((EXCHANGE_CACHE.get(symbol) or {}).get("stepSize"), 0.0)
    tolerance = max(step * 0.5, 1e-12)
    last_amt = 0.0

    for attempt in range(1, attempts + 1):
        amt = get_position_amt_for_client(client_obj, label, symbol)
        last_amt = amt
        if abs(amt) <= tolerance:
            detail = {"account": label, "position_amt": amt, "attempt": attempt, "attempts": attempts}
            add_order_audit("EMERGENCY_CLOSE_CONFIRMED", symbol, detail)
            return {"ok": True, **detail}
        if attempt < attempts:
            add_order_audit("EMERGENCY_CLOSE_WAIT", symbol, {
                "account": label, "position_amt": amt, "attempt": attempt, "attempts": attempts, "sleep": delay,
            })
            time.sleep(delay)

    detail = {"account": label, "position_amt": last_amt, "attempts": attempts}
    add_order_audit("EMERGENCY_CLOSE_NOT_CONFIRMED", symbol, detail)
    return {"ok": False, **detail}


def emergency_close_position_for_client(client_obj, label, symbol, side, qty, reason="protection_failed"):
    try:
        live_amt = get_position_amt_for_client(client_obj, label, symbol)
        if abs(live_amt) > 0:
            close_side = SIDE_SELL if live_amt > 0 else SIDE_BUY
            close_qty_raw = abs(live_amt)
        else:
            close_side = SIDE_SELL if str(side).upper() == "BUY" else SIDE_BUY
            close_qty_raw = abs(float(qty or 0))

        close_qty_detail = normalize_quantity_detail(symbol, close_qty_raw)
        if not close_qty_detail.get("ok"):
            add_order_audit("EMERGENCY_CLOSE_QTY_INVALID", symbol, {
                "account": label, "raw_qty": close_qty_raw, "detail": close_qty_detail, "reason": reason,
            })
            return {"status": "rejected", "reason": "close_qty_invalid", "detail": close_qty_detail}

        close_qty = close_qty_detail["value"]
        close_qty_text = close_qty_detail["text"]
        if close_qty <= 0:
            return {"status": "rejected", "reason": "close_qty_zero"}

        client_order_id = build_order_client_id(symbol, side, "CLS")
        add_order_audit("EMERGENCY_CLOSE_ATTEMPT", symbol, {
            "account": label, "side": close_side, "qty": close_qty, "qty_text": close_qty_text,
            "live_position_amt": live_amt, "reason": reason, "clientOrderId": client_order_id,
        })

        order = signed_call(
            client_obj,
            client_obj.futures_create_order,
            label=label,
            symbol=symbol,
            side=close_side,
            type=FUTURE_ORDER_TYPE_MARKET,
            quantity=close_qty_text,
            reduceOnly=True,
            newClientOrderId=client_order_id,
        )
        if client_obj is binance:
            invalidate_main_positions_cache()
            invalidate_main_open_orders_cache()

        add_order_audit("EMERGENCY_CLOSE_SENT", symbol, {
            "account": label, "qty": close_qty, "qty_text": close_qty_text, "reason": reason,
            "order_id": order.get("orderId") if isinstance(order, dict) else None,
            "status": order.get("status") if isinstance(order, dict) else None,
        })
        close_verify = wait_for_position_closed_for_client(client_obj, label, symbol)
        return {"status": "OK" if close_verify.get("ok") else "SENT_NOT_CONFIRMED", "order": order, "verify_close": close_verify}
    except Exception as exc:
        add_order_audit("EMERGENCY_CLOSE_ERROR", symbol, {"account": label, "error": str(exc), "reason": reason})
        return {"status": "error", "error": str(exc)}


def place_protective_order_for_client(client_obj, label, symbol, leg, order_type, close_side, stop_price_text, qty_text, client_order_id, force_quantity=False):
    """Place one protective order and accept both standard orderId and Algo Service algoId responses."""
    leg = str(leg or "").upper()
    params = {
        "symbol": symbol,
        "side": close_side,
        "type": order_type,
        "stopPrice": stop_price_text,
        "workingType": "MARK_PRICE",
        "newClientOrderId": client_order_id,
    }
    if PROTECTION_ORDER_MODE == "CLOSE_POSITION" and not force_quantity:
        params["closePosition"] = True
    else:
        params["quantity"] = qty_text
        params["reduceOnly"] = True

    add_order_audit(f"PLACE_{leg}_ATTEMPT", symbol, {
        "account": label,
        "clientOrderId": client_order_id,
        "protection_order_mode": PROTECTION_ORDER_MODE,
        "force_quantity": bool(force_quantity),
        "params": {k: v for k, v in params.items() if k != "newClientOrderId"},
    })

    try:
        order = signed_call(client_obj, client_obj.futures_create_order, label=label, **params)
        if isinstance(order, dict):
            order = _annotate_protection_response(order, leg=leg)
        ref_type, ref_id = _protection_order_ref(order)
        status = _protection_order_status(order)
        if not ref_id:
            raise RuntimeError(f"{leg} order accepted without orderId/algoId: {order}")
        if not _is_active_protection_status(status):
            raise RuntimeError(f"{leg} order returned inactive status {status}: {order}")

        _remember_protection_order(symbol, leg, order)
        add_order_audit(f"PLACE_{leg}_OK", symbol, {
            "account": label,
            "ref_type": ref_type,
            "ref_id": ref_id,
            "order_id": order.get("orderId") if isinstance(order, dict) else None,
            "algo_id": order.get("algoId") if isinstance(order, dict) else None,
            "clientAlgoId": order.get("clientAlgoId") if isinstance(order, dict) else None,
            "clientOrderId": client_order_id,
            "stopPrice": stop_price_text,
            "triggerPrice": order.get("triggerPrice") if isinstance(order, dict) else None,
            "status": status,
            "type": _protection_order_type(order),
            "closePosition": order.get("closePosition") if isinstance(order, dict) else None,
            "reduceOnly": order.get("reduceOnly") if isinstance(order, dict) else None,
            "protection_order_mode": PROTECTION_ORDER_MODE,
            "force_quantity": bool(force_quantity),
        })
        if client_obj is binance:
            invalidate_main_open_orders_cache()
        return order
    except Exception as exc:
        add_order_audit(f"PLACE_{leg}_FAILED", symbol, {
            "account": label,
            "error": str(exc),
            "stopPrice": stop_price_text,
            "clientOrderId": client_order_id,
            "protection_order_mode": PROTECTION_ORDER_MODE,
            "force_quantity": bool(force_quantity),
            "params": {k: v for k, v in params.items() if k != "newClientOrderId"},
        })
        raise



def build_partial_tp_plan(symbol, side, entry_price, sl_price, full_tp_price, qty):
    if not PARTIAL_TP_ENABLED:
        return {"enabled": False, "reason": "partial_tp_disabled"}

    side = str(side or "").upper().strip()
    entry_price = float(entry_price or 0.0)
    sl_price = float(sl_price or 0.0)
    full_tp_price = float(full_tp_price or 0.0)
    qty = float(qty or 0.0)

    if side not in ("BUY", "SELL") or entry_price <= 0 or sl_price <= 0 or full_tp_price <= 0 or qty <= 0:
        return {"enabled": False, "reason": "partial_tp_invalid_input"}

    risk = abs(entry_price - sl_price)
    if risk <= 0:
        return {"enabled": False, "reason": "partial_tp_zero_risk"}

    tp1 = entry_price + risk if side == "BUY" else entry_price - risk
    if side == "BUY" and not (entry_price < tp1 < full_tp_price):
        return {"enabled": False, "reason": "partial_tp1_not_between_entry_and_tp"}
    if side == "SELL" and not (full_tp_price < tp1 < entry_price):
        return {"enabled": False, "reason": "partial_tp1_not_between_entry_and_tp"}

    ratio = max(0.05, min(0.80, float(PARTIAL_TP_R1_RATIO)))
    q1_detail = normalize_quantity_detail(symbol, qty * ratio)
    if not q1_detail.get("ok") or q1_detail.get("value", 0) <= 0:
        return {"enabled": False, "reason": "partial_tp_q1_invalid", "q1_detail": q1_detail}

    q1 = float(q1_detail["value"])
    q2_detail = normalize_quantity_detail(symbol, max(qty - q1, 0.0))
    if not q2_detail.get("ok") or q2_detail.get("value", 0) <= 0:
        return {"enabled": False, "reason": "partial_tp_q2_invalid", "q1_detail": q1_detail, "q2_detail": q2_detail}

    tp1_detail = normalize_protective_price_detail(symbol, tp1, side, "TP1")
    tp2_detail = normalize_protective_price_detail(symbol, full_tp_price, side, "TP2")
    if not tp1_detail.get("ok") or not tp2_detail.get("ok"):
        return {
            "enabled": False,
            "reason": "partial_tp_price_invalid",
            "tp1_detail": tp1_detail,
            "tp2_detail": tp2_detail,
        }

    return {
        "enabled": True,
        "ratio": ratio,
        "tp1": tp1_detail,
        "tp2": tp2_detail,
        "q1": q1_detail,
        "q2": q2_detail,
    }

def place_partial_tp_orders_for_client(client_obj, label, symbol, side, close_side, entry_price, sl_price, full_tp_price, qty):
    plan = build_partial_tp_plan(symbol, side, entry_price, sl_price, full_tp_price, qty)
    if not plan.get("enabled"):
        add_order_audit("PARTIAL_TP_SKIPPED", symbol, {"account": label, "plan": plan})
        return [], plan

    orders = []
    legs = [
        ("TP1", plan["tp1"]["text"], plan["q1"]["text"]),
        ("TP2", plan["tp2"]["text"], plan["q2"]["text"]),
    ]
    for leg, stop_price_text, qty_text in legs:
        client_id = build_order_client_id(symbol, side, leg)
        order = place_protective_order_for_client(
            client_obj,
            label,
            symbol,
            leg,
            FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            close_side,
            stop_price_text,
            qty_text,
            client_id,
            force_quantity=True,
        )
        orders.append(order)
        time.sleep(max(0.0, PROTECTION_PLACEMENT_GAP_SECONDS))

    add_order_audit("PARTIAL_TP_PLACED", symbol, {"account": label, "plan": plan, "orders": orders})
    return orders, plan


def get_entry_limit_offset(symbol):
    symbol = str(symbol or "").upper().strip()
    override = os.getenv(f"ENTRY_LIMIT_OFFSET_{symbol}")
    if override is not None:
        try:
            return float(override)
        except Exception:
            pass
    tier = get_pair_tier(symbol)
    if tier == "TOP":
        return ENTRY_LIMIT_OFFSET_TOP
    if tier == "MID":
        return ENTRY_LIMIT_OFFSET_MID
    if tier == "MID_AGGRESSIVE":
        return ENTRY_LIMIT_OFFSET_MID_AGGRESSIVE
    return ENTRY_LIMIT_OFFSET_DEFAULT

def build_entry_limit_plan(client_obj, label, symbol, side, force=False):
    """Build a marketable limit-entry plan from live orderbook.

    BUY caps price near best ask; SELL caps price near best bid. This prevents
    unexpected slippage while still allowing immediate fill when liquidity is present.
    """
    symbol = str(symbol or "").upper().strip()
    side = str(side or "").upper().strip()
    tier = get_pair_tier(symbol)
    offset = get_entry_limit_offset(symbol)
    spread = get_live_spread(client_obj, symbol, tier, force=force)
    best_bid = _safe_float(spread.get("best_bid"), 0.0)
    best_ask = _safe_float(spread.get("best_ask"), 0.0)

    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return {
            "ok": False,
            "reason": "ENTRY_ORDERBOOK_UNAVAILABLE",
            "symbol": symbol,
            "side": side,
            "tier": tier,
            "spread": spread,
            "offset": offset,
        }

    if side == "BUY":
        raw_price = best_ask * (1.0 + offset)
        anchor = "best_ask"
    elif side == "SELL":
        raw_price = best_bid * (1.0 - offset)
        anchor = "best_bid"
    else:
        return {"ok": False, "reason": "INVALID_SIDE", "symbol": symbol, "side": side}

    price_detail = normalize_entry_price_detail(symbol, raw_price)
    if not price_detail.get("ok"):
        return {
            "ok": False,
            "reason": "ENTRY_LIMIT_PRICE_INVALID",
            "symbol": symbol,
            "side": side,
            "tier": tier,
            "spread": spread,
            "offset": offset,
            "price_detail": price_detail,
        }

    return {
        "ok": True,
        "reason": "OK",
        "symbol": symbol,
        "side": side,
        "tier": tier,
        "offset": offset,
        "anchor": anchor,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": spread.get("spread_pct"),
        "limit_price": price_detail.get("value"),
        "limit_price_text": price_detail.get("text"),
        "price_detail": price_detail,
        "spread": spread,
        "time_in_force": ENTRY_LIMIT_TIME_IN_FORCE,
        "ttl_seconds": ENTRY_LIMIT_TTL_SECONDS,
    }


def get_entry_reference_price_for_quality(client_obj, label, symbol, side):
    """Return the price used for quality/qty calculation before entry.

    For LIMIT entries, use the same tick-clean capped limit price that will be
    used in placement. For MARKET entries, use current ticker as before.
    """
    if ENTRY_ORDER_TYPE == "LIMIT":
        plan = build_entry_limit_plan(client_obj, label, symbol, side, force=False)
        if plan.get("ok"):
            return float(plan["limit_price"]), plan
        return None, plan

    try:
        ticker_price = float(client_obj.futures_symbol_ticker(symbol=symbol)["price"])
        detail = normalize_entry_price_detail(symbol, ticker_price)
        if detail.get("ok"):
            ticker_price = float(detail.get("value"))
        return ticker_price, {"ok": True, "reason": "MARKET_REFERENCE", "entry_order_type": ENTRY_ORDER_TYPE, "price_detail": detail}
    except Exception as exc:
        return None, {"ok": False, "reason": "TICKER_REFERENCE_ERROR", "error": str(exc)}


def _fetch_entry_order_status(client_obj, label, symbol, order=None, client_order_id=None):
    try:
        params = {"symbol": symbol}
        if isinstance(order, dict) and order.get("orderId"):
            params["orderId"] = order.get("orderId")
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            return {"ok": False, "reason": "missing_order_reference"}
        data = signed_call(client_obj, client_obj.futures_get_order, label=label, **params)
        return {"ok": True, "order": data, "status": str((data or {}).get("status") or "UNKNOWN").upper()}
    except Exception as exc:
        return {"ok": False, "reason": "fetch_order_status_error", "error": str(exc)}


def _cancel_entry_limit_order(client_obj, label, symbol, order=None, client_order_id=None, reason="ttl_expired"):
    try:
        params = {"symbol": symbol}
        if isinstance(order, dict) and order.get("orderId"):
            params["orderId"] = order.get("orderId")
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            return {"ok": False, "reason": "missing_order_reference"}
        result = signed_call(client_obj, client_obj.futures_cancel_order, label=label, **params)
        add_order_audit("ENTRY_LIMIT_CANCEL_SENT", symbol, {
            "account": label,
            "reason": reason,
            "order_id": result.get("orderId") if isinstance(result, dict) else None,
            "clientOrderId": client_order_id,
            "status": result.get("status") if isinstance(result, dict) else None,
        })
        return {"ok": True, "order": result}
    except Exception as exc:
        add_order_audit("ENTRY_LIMIT_CANCEL_ERROR", symbol, {"account": label, "reason": reason, "error": str(exc), "clientOrderId": client_order_id})
        return {"ok": False, "error": str(exc)}


def wait_for_limit_entry_fill(client_obj, label, symbol, side, order, client_order_id, qty, ttl_seconds=None, poll_interval=None):
    ttl_seconds = float(ENTRY_LIMIT_TTL_SECONDS if ttl_seconds is None else ttl_seconds)
    poll_interval = float(ENTRY_LIMIT_POLL_INTERVAL if poll_interval is None else poll_interval)
    deadline = time.time() + max(0.5, ttl_seconds)
    last_status = None
    last_order = None

    while time.time() <= deadline:
        status_row = _fetch_entry_order_status(client_obj, label, symbol, order=order, client_order_id=client_order_id)
        if status_row.get("ok"):
            last_status = status_row.get("status")
            last_order = status_row.get("order")
            executed = _safe_float((last_order or {}).get("executedQty"), 0.0)
            add_order_audit("ENTRY_LIMIT_STATUS", symbol, {
                "account": label,
                "clientOrderId": client_order_id,
                "status": last_status,
                "executedQty": executed,
            })
            if last_status == "FILLED" or executed > 0:
                # Position is the source of truth; partial fills are protected by actual live qty.
                fill = wait_for_position_for_client(client_obj, label, symbol, side, min_qty=max(executed, 0.0), attempts=2, delay=0.25)
                if fill.get("ok"):
                    fill["order_status"] = last_status
                    fill["executedQty"] = executed
                    return fill
            if last_status in ("CANCELED", "EXPIRED", "REJECTED"):
                break
        else:
            add_order_audit("ENTRY_LIMIT_STATUS_ERROR", symbol, {"account": label, "clientOrderId": client_order_id, "status": status_row})
        time.sleep(max(0.1, poll_interval))

    cancel_result = _cancel_entry_limit_order(client_obj, label, symbol, order=order, client_order_id=client_order_id, reason="entry_limit_not_filled")
    # After cancel, check once more in case a partial fill landed just before cancel.
    fill = wait_for_position_for_client(client_obj, label, symbol, side, min_qty=0.0, attempts=2, delay=0.25)
    if fill.get("ok"):
        fill["order_status"] = last_status
        fill["cancel_result"] = cancel_result
        return fill
    return {
        "ok": False,
        "reason": "entry_limit_not_filled",
        "last_status": last_status,
        "last_order": last_order,
        "cancel_result": cancel_result,
    }


def place_market_entry_for_client(client_obj, label, symbol, side, qty_text, entry_client_id):
    add_order_audit("ENTRY_PLACE_ATTEMPT", symbol, {
        "account": label,
        "entry_order_type": "MARKET",
        "side": side,
        "qty_text": qty_text,
        "clientOrderId": entry_client_id,
    })
    order = signed_call(
        client_obj,
        client_obj.futures_create_order,
        label=label,
        symbol=symbol,
        side=SIDE_BUY if side == "BUY" else SIDE_SELL,
        type=FUTURE_ORDER_TYPE_MARKET,
        quantity=qty_text,
        newClientOrderId=entry_client_id,
    )
    add_order_audit("ENTRY_PLACE_OK", symbol, {
        "account": label,
        "entry_order_type": "MARKET",
        "order_id": order.get("orderId") if isinstance(order, dict) else None,
        "clientOrderId": entry_client_id,
        "status": order.get("status") if isinstance(order, dict) else None,
        "executedQty": order.get("executedQty") if isinstance(order, dict) else None,
    })
    fill = wait_for_position_for_client(client_obj, label, symbol, side, min_qty=float(qty_text or 0))
    return order, fill, {"entry_order_type": "MARKET"}


def place_controlled_entry_for_client(client_obj, label, symbol, side, qty_text):
    entry_type = ENTRY_ORDER_TYPE
    if entry_type not in ("LIMIT", "MARKET"):
        entry_type = "LIMIT"

    if entry_type == "MARKET":
        cid = build_order_client_id(symbol, side, "ENT")
        return place_market_entry_for_client(client_obj, label, symbol, side, qty_text, cid)

    attempts = 1 + max(0, int(ENTRY_LIMIT_MAX_REPRICE))
    last_detail = None
    for attempt in range(1, attempts + 1):
        plan = build_entry_limit_plan(client_obj, label, symbol, side, force=(attempt > 1))
        last_detail = plan
        if not plan.get("ok"):
            add_order_audit("ENTRY_LIMIT_PLAN_FAILED", symbol, {"account": label, "attempt": attempt, "attempts": attempts, "plan": plan})
            break

        cid = build_order_client_id(symbol, side, f"L{attempt}")
        params = {
            "symbol": symbol,
            "side": SIDE_BUY if side == "BUY" else SIDE_SELL,
            "type": "LIMIT",
            "timeInForce": ENTRY_LIMIT_TIME_IN_FORCE,
            "quantity": qty_text,
            "price": plan["limit_price_text"],
            "newClientOrderId": cid,
        }
        add_order_audit("ENTRY_LIMIT_PLAN", symbol, {"account": label, "attempt": attempt, "attempts": attempts, "plan": plan})
        add_order_audit("ENTRY_LIMIT_PLACE_ATTEMPT", symbol, {"account": label, "attempt": attempt, "params": {k: v for k, v in params.items() if k != "newClientOrderId"}, "clientOrderId": cid})
        try:
            order = signed_call(client_obj, client_obj.futures_create_order, label=label, **params)
            add_order_audit("ENTRY_LIMIT_PLACE_OK", symbol, {
                "account": label,
                "attempt": attempt,
                "order_id": order.get("orderId") if isinstance(order, dict) else None,
                "clientOrderId": cid,
                "status": order.get("status") if isinstance(order, dict) else None,
                "price": plan.get("limit_price_text"),
            })
            fill = wait_for_limit_entry_fill(client_obj, label, symbol, side, order, cid, qty_text)
            if fill.get("ok"):
                return order, fill, {"entry_order_type": "LIMIT", "entry_limit_plan": plan, "attempt": attempt, "attempts": attempts}
            add_order_audit("ENTRY_LIMIT_NOT_FILLED", symbol, {"account": label, "attempt": attempt, "attempts": attempts, "fill": fill, "plan": plan})
        except Exception as exc:
            add_order_audit("ENTRY_LIMIT_PLACE_FAILED", symbol, {"account": label, "attempt": attempt, "attempts": attempts, "error": str(exc), "plan": plan})
            last_detail = {"ok": False, "reason": "ENTRY_LIMIT_PLACE_FAILED", "error": str(exc), "plan": plan}

    if ENTRY_MARKET_FALLBACK:
        add_order_audit("ENTRY_MARKET_FALLBACK", symbol, {"account": label, "last_detail": last_detail})
        cid = build_order_client_id(symbol, side, "ENT")
        return place_market_entry_for_client(client_obj, label, symbol, side, qty_text, cid)

    return None, {"ok": False, "reason": "entry_limit_not_filled", "detail": last_detail, "attempts": attempts}, {"entry_order_type": "LIMIT", "entry_limit_detail": last_detail}

def place_order_for_client(client_obj, label, symbol, side, qty, sl, tp, entry_price=None):
    if client_obj is None:
        return {"account": label, "error": "binance client not ready"}

    symbol = str(symbol or "").upper().strip()
    side = str(side or "").upper().strip()
    if side not in ("BUY", "SELL"):
        return {"account": label, "error": "invalid_side"}

    qty_detail = normalize_quantity_detail(symbol, qty)
    sl_detail = normalize_protective_price_detail(symbol, sl, side, "SL")
    tp_detail = normalize_protective_price_detail(symbol, tp, side, "TP")

    precision_detail = {
        "account": label,
        "symbol": symbol,
        "side": side,
        "qty": qty_detail,
        "sl": sl_detail,
        "tp": tp_detail,
        "exchange_cache": EXCHANGE_CACHE.get(symbol),
        "protection_order_mode": PROTECTION_ORDER_MODE,
    }

    if not qty_detail.get("ok") or not sl_detail.get("ok") or not tp_detail.get("ok"):
        add_order_audit("PROTECTION_PRECISION_INVALID", symbol, precision_detail)
        return {"account": label, "error": "precision_invalid", "precision": precision_detail}

    qty = qty_detail["value"]
    qty_text = qty_detail["text"]
    sl_price = sl_detail["value"]
    tp_price = tp_detail["value"]
    sl_text = sl_detail["text"]
    tp_text = tp_detail["text"]
    close_side = SIDE_SELL if side == "BUY" else SIDE_BUY

    add_order_audit("PROTECTION_PRICE_NORMALIZED", symbol, {
        "account": label,
        "side": side,
        "raw_qty": float(qty_detail.get("raw", qty)),
        "qty": qty,
        "qty_text": qty_text,
        "raw_sl": float(sl),
        "raw_tp": float(tp),
        "sl": sl_price,
        "tp": tp_price,
        "sl_text": sl_text,
        "tp_text": tp_text,
        "tickSize": sl_detail.get("tickSize"),
        "stepSize": qty_detail.get("stepSize"),
        "rounding": {"sl": sl_detail.get("rounding"), "tp": tp_detail.get("rounding")},
        "protection_order_mode": PROTECTION_ORDER_MODE,
    })

    if not cancel_protective_orders_for_client(client_obj, label, symbol, cancel_tp=True, cancel_sl=True):
        add_order_audit("CANCEL_PROTECTIVE_FAILED", symbol, {"account": label})
        return {"account": label, "error": "cancel_protective_failed"}

    entry_order = None
    sl_order = None
    tp_order = None
    tp_orders = []
    partial_tp_plan = {"enabled": False, "reason": "not_attempted"}
    entry_fill = None
    entry_detail = None
    protect_qty = qty
    protect_qty_text = qty_text

    try:
        entry_order, entry_fill, entry_detail = place_controlled_entry_for_client(client_obj, label, symbol, side, qty_text)
        if client_obj is binance:
            invalidate_main_positions_cache()
            invalidate_main_open_orders_cache()

        if not entry_fill.get("ok"):
            # LIMIT entries that do not fill are skipped, not emergency-closed.
            # MARKET fallback/market entries still use strict close verification if a position might exist.
            close_result = None
            if entry_order and (entry_detail or {}).get("entry_order_type") == "MARKET":
                close_result = emergency_close_position_for_client(client_obj, label, symbol, side, qty, reason="entry_position_not_confirmed")
            cancel_protective_orders_for_client(client_obj, label, symbol, cancel_tp=True, cancel_sl=True)
            return {
                "account": label,
                "status": "ENTRY_NOT_FILLED",
                "error": entry_fill.get("reason") or "entry_not_filled",
                "qty": qty,
                "qty_text": qty_text,
                "entry_fill": entry_fill,
                "entry_detail": entry_detail,
                "close_result": close_result,
                "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
                "entry_order_type": (entry_detail or {}).get("entry_order_type"),
                "protection_order_mode": PROTECTION_ORDER_MODE,
            }

        live_qty_detail = normalize_quantity_detail(symbol, entry_fill.get("qty") or qty)
        if live_qty_detail.get("ok"):
            protect_qty = live_qty_detail["value"]
            protect_qty_text = live_qty_detail["text"]

        time.sleep(max(0.0, PROTECTION_PLACEMENT_GAP_SECONDS))

        sl_client_id = build_order_client_id(symbol, side, "SL")
        try:
            sl_order = place_protective_order_for_client(
                client_obj, label, symbol, "SL", FUTURE_ORDER_TYPE_STOP_MARKET,
                close_side, sl_text, protect_qty_text, sl_client_id
            )
        except Exception as sl_exc:
            close_result = emergency_close_position_for_client(client_obj, label, symbol, side, protect_qty, reason="place_sl_failed")
            cancel_protective_orders_for_client(client_obj, label, symbol, cancel_tp=True, cancel_sl=True)
            return {
                "account": label,
                "status": "CLOSED_PROTECTION_PLACE_FAILED",
                "error": "place_sl_failed",
                "error_detail": str(sl_exc),
                "qty": protect_qty,
                "qty_text": protect_qty_text,
                "sl": sl_price,
                "tp": tp_price,
                "sl_text": sl_text,
                "tp_text": tp_text,
                "entry_fill": entry_fill,
                "close_result": close_result,
                "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
                "sl_order_id": None,
                "tp_order_id": None,
                "protection_order_mode": PROTECTION_ORDER_MODE,
            }

        time.sleep(max(0.0, PROTECTION_PLACEMENT_GAP_SECONDS))

        tp_entry_price = float(entry_price or entry_fill.get("entry_price") or entry_fill.get("avgPrice") or entry_fill.get("price") or 0.0)
        if tp_entry_price <= 0:
            tp_entry_price = float(entry_detail.get("entry_limit_plan", {}).get("limit_price") or entry_detail.get("entry_reference_price") or 0.0) if isinstance(entry_detail, dict) else 0.0
        if tp_entry_price <= 0:
            tp_entry_price = float((float(sl_price) + float(tp_price)) / 2.0)

        try:
            if PARTIAL_TP_ENABLED:
                tp_orders, partial_tp_plan = place_partial_tp_orders_for_client(
                    client_obj, label, symbol, side, close_side, tp_entry_price, sl_price, tp_price, protect_qty
                )
                if tp_orders:
                    tp_order = {"partial": True, "orders": tp_orders, "plan": partial_tp_plan}
                else:
                    tp_client_id = build_order_client_id(symbol, side, "TP")
                    tp_order = place_protective_order_for_client(
                        client_obj, label, symbol, "TP", FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                        close_side, tp_text, protect_qty_text, tp_client_id
                    )
            else:
                tp_client_id = build_order_client_id(symbol, side, "TP")
                tp_order = place_protective_order_for_client(
                    client_obj, label, symbol, "TP", FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                    close_side, tp_text, protect_qty_text, tp_client_id
                )
        except Exception as tp_exc:
            close_result = emergency_close_position_for_client(client_obj, label, symbol, side, protect_qty, reason="place_tp_failed")
            cancel_protective_orders_for_client(client_obj, label, symbol, cancel_tp=True, cancel_sl=True)
            return {
                "account": label,
                "status": "CLOSED_PROTECTION_PLACE_FAILED",
                "error": "place_tp_failed",
                "error_detail": str(tp_exc),
                "qty": protect_qty,
                "qty_text": protect_qty_text,
                "sl": sl_price,
                "tp": tp_price,
                "sl_text": sl_text,
                "tp_text": tp_text,
                "entry_fill": entry_fill,
                "close_result": close_result,
                "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
                "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
                "tp_order_id": None,
                "partial_tp_plan": partial_tp_plan,
                "protection_order_mode": PROTECTION_ORDER_MODE,
            }

        verify = verify_protective_orders_with_retry(client_obj, label, symbol)
        if client_obj is binance:
            invalidate_main_positions_cache()
            invalidate_main_open_orders_cache()

        if not verify.get("ok"):
            detail = {
                "account": label,
                "symbol": symbol,
                "side": side,
                "qty": protect_qty,
                "qty_text": protect_qty_text,
                "sl": sl_price,
                "tp": tp_price,
                "sl_text": sl_text,
                "tp_text": tp_text,
                "verify": verify,
                "entry_fill": entry_fill,
                "entry_order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
                "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
                "tp_order_id": tp_order.get("orderId") if isinstance(tp_order, dict) else None,
                "sl_order_status": sl_order.get("status") if isinstance(sl_order, dict) else None,
                "tp_order_status": tp_order.get("status") if isinstance(tp_order, dict) else None,
                "protection_order_mode": PROTECTION_ORDER_MODE,
            }
            add_order_audit("PROTECTION_VERIFY_FAILED", symbol, detail)
            if STRICT_PROTECTION:
                close_result = emergency_close_position_for_client(client_obj, label, symbol, side, protect_qty, reason="protection_verify_failed")
                cancel_protective_orders_for_client(client_obj, label, symbol, cancel_tp=True, cancel_sl=True)
                return {
                    "account": label,
                    "status": "CLOSED_UNPROTECTED",
                    "error": "protection_verify_failed",
                    "qty": protect_qty,
                    "qty_text": protect_qty_text,
                    "sl": sl_price,
                    "tp": tp_price,
                    "sl_text": sl_text,
                    "tp_text": tp_text,
                    "verify": verify,
                    "entry_fill": entry_fill,
                    "close_result": close_result,
                    "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
                    "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
                    "tp_order_id": tp_order.get("orderId") if isinstance(tp_order, dict) else None,
                    "protection_order_mode": PROTECTION_ORDER_MODE,
                }

            return {
                "account": label,
                "status": "UNPROTECTED",
                "error": "protection_verify_failed",
                "qty": protect_qty,
                "qty_text": protect_qty_text,
                "sl": sl_price,
                "tp": tp_price,
                "sl_text": sl_text,
                "tp_text": tp_text,
                "verify": verify,
                "entry_fill": entry_fill,
                "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
                "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
                "tp_order_id": tp_order.get("orderId") if isinstance(tp_order, dict) else None,
                "protection_order_mode": PROTECTION_ORDER_MODE,
            }

        add_order_audit("PROTECTION_RESOLVED", symbol, {
            "account": label,
            "side": side,
            "qty": protect_qty,
            "qty_text": protect_qty_text,
            "sl": sl_price,
            "tp": tp_price,
            "sl_text": sl_text,
            "tp_text": tp_text,
            "verify": verify,
            "entry_fill": entry_fill,
            "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
            "tp_order_id": tp_order.get("orderId") if isinstance(tp_order, dict) else None,
            "tp_order_ids": [o.get("orderId") for o in tp_orders if isinstance(o, dict)],
            "partial_tp_plan": partial_tp_plan,
            "protection_order_mode": PROTECTION_ORDER_MODE,
        })

        return {
            "account": label,
            "status": "OK",
            "qty": protect_qty,
            "qty_text": protect_qty_text,
            "sl": sl_price,
            "tp": tp_price,
            "sl_text": sl_text,
            "tp_text": tp_text,
            "protective_resolved": True,
            "verify": verify,
            "entry_fill": entry_fill,
            "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
            "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
            "tp_order_id": tp_order.get("orderId") if isinstance(tp_order, dict) else None,
            "tp_order_ids": [o.get("orderId") for o in tp_orders if isinstance(o, dict)],
            "partial_tp_plan": partial_tp_plan,
            "protection_order_mode": PROTECTION_ORDER_MODE,
        }

    except Exception as exc:
        err = str(exc)
        add_order_audit("ORDER_PROTECTION_ERROR", symbol, {
            "account": label,
            "error": err,
            "entry_order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
            "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
            "tp_order_id": tp_order.get("orderId") if isinstance(tp_order, dict) else None,
            "sl": sl_price,
            "tp": tp_price,
            "sl_text": sl_text,
            "tp_text": tp_text,
            "qty_text": qty_text,
            "entry_fill": entry_fill,
            "protection_order_mode": PROTECTION_ORDER_MODE,
        })
        if entry_order and STRICT_PROTECTION:
            close_result = emergency_close_position_for_client(client_obj, label, symbol, side, qty, reason="protection_create_error")
            cancel_protective_orders_for_client(client_obj, label, symbol, cancel_tp=True, cancel_sl=True)
            return {
                "account": label,
                "status": "CLOSED_AFTER_ERROR",
                "error": err,
                "close_result": close_result,
                "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None,
                "sl_order_id": sl_order.get("orderId") if isinstance(sl_order, dict) else None,
                "tp_order_id": tp_order.get("orderId") if isinstance(tp_order, dict) else None,
                "protection_order_mode": PROTECTION_ORDER_MODE,
            }
        return {"account": label, "error": err, "order_id": entry_order.get("orderId") if isinstance(entry_order, dict) else None}


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
    symbol = str(symbol or "").upper().strip()
    slot_ok, slot_reason, slot_detail = reserve_trade_slot(symbol, side=side, reason="place_order_multi", allow_existing=True)
    if not slot_ok:
        detail = {"reason": slot_reason, "risk_slots": slot_detail}
        add_order_audit("ORDER_REJECTED_RISK_SLOT", symbol, detail)
        set_final_execution("BLOCKED", symbol=symbol, side=side, reason=slot_reason, stage="risk_slot_gate", detail=detail)
        return [{"account": "MAIN", "status": "REJECTED", "error": slot_reason, "risk_slots": slot_detail}]

    results = []
    for acc in CLIENTS:
        label = acc["name"]
        try:
            c = acc["client"]
            base_risk = acc["risk"]
            profit = ACCOUNT_PROFIT.get(label, 0)
            if acc.get("compound") and profit > 0:
                risk_pct = base_risk + (profit / 1000)
            else:
                risk_pct = base_risk

            balance_info = signed_call(c, c.futures_account_balance, label=label)
            usdt = next((b for b in balance_info if b["asset"] == "USDT"), None)
            balance = float(usdt["balance"]) if usdt else 0
            alloc = min(portfolio_alloc.get(symbol, 0.25), 0.12)

            price, entry_reference_detail = get_entry_reference_price_for_quality(c, label, symbol, side)
            if price is None or price <= 0:
                results.append({
                    "account": label,
                    "error": "entry_reference_unavailable",
                    "entry_reference": entry_reference_detail,
                })
                continue

            exec_signal = apply_clean_prices_to_signal({
                "symbol": symbol,
                "type": side,
                "entry": price,
                "sl": sl,
                "tp": tp,
                "rr": abs(float(tp) - price) / max(abs(price - float(sl)), 1e-12),
            }, reference_price=price)
            price = float(exec_signal.get("entry", price))
            sl = float(exec_signal.get("sl", sl))
            tp = float(exec_signal.get("tp", tp))

            quality_ok, quality_reason, quality_detail = evaluate_signal_execution_quality(exec_signal, reference_price=price)
            if isinstance(quality_detail, dict):
                quality_detail["entry_reference"] = entry_reference_detail
                quality_detail["entry_order_type"] = ENTRY_ORDER_TYPE
            if not quality_ok:
                results.append({
                    "account": label,
                    "error": quality_reason,
                    "quality": quality_detail,
                })
                continue

            risk_amount = balance * risk_pct * alloc
            stop_distance = abs(price - float(sl))
            if stop_distance <= 0:
                results.append({"account": label, "error": "stop_distance_zero"})
                continue

            qty = risk_amount / stop_distance
            min_notional = get_min_trade_notional(symbol)
            if qty * price < min_notional:
                qty = ceil_to_step(min_notional / price, EXCHANGE_CACHE.get(symbol, {}).get("stepSize", 0.001))

            qty, price = adjust_precision(symbol, qty, price)

            if qty * price < min_notional:
                print(f"❌ SKIP NOTIONAL < {min_notional}", symbol)
                results.append({
                    "account": label,
                    "error": "notional_below_min",
                    "qty": qty,
                    "price": price,
                    "min_notional": min_notional,
                })
                continue

            leverage_result = ensure_symbol_leverage(c, label, symbol)
            if not leverage_result.get("ok"):
                results.append({
                    "account": label,
                    "error": "leverage_set_failed",
                    "leverage": leverage_result,
                })
                continue

            result = place_order_for_client(c, label, symbol, side, qty, sl, tp, entry_price=price)
            result["entry_price"] = price
            result["leverage"] = leverage_result
            result["min_notional"] = min_notional
            result["quality"] = quality_detail
            results.append(result)

            if result.get("status") == "OK":
                update_account_profit(c, label)
                check_withdraw(acc, c)

        except Exception as e:
            results.append({"account": label, "error": str(e)})

    success = any(r.get("status") == "OK" for r in results if isinstance(r, dict))
    if not success:
        set_final_execution("ORDER_FAILED", symbol=symbol, side=side, reason="NO_ACCOUNT_FILLED", stage="order_result", detail={"results": results})
        add_order_audit("ORDER_MULTI_FAILED", symbol, {"results": results})
        TRADE_SNAPSHOTS.pop(symbol, None)
        set_symbol_cooldown(symbol, reason="multi_order_failed")
        release_trade_slot(symbol, reason="order_failed", unlock=True)
    else:
        set_final_execution("ORDER_OK_PROTECTED", symbol=symbol, side=side, reason="PROTECTED_ORDER_OK", stage="order_result", detail={"results": results})
        add_order_audit("ORDER_MULTI_OK", symbol, {"results": results})
        release_trade_slot(symbol, reason="order_ok_protected", unlock=False)

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



# ================= TELEGRAM ALERT SOURCE-OF-TRUTH HELPERS (v4.9.2) =================
def send_telegram(msg: str):
    """Send a plain Telegram message. Safe no-op when token/chat id are absent."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": str(msg)}, timeout=8)
        return bool(resp.ok)
    except Exception as exc:
        print("telegram send error:", exc)
        return False


def telegram_available():
    return bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def _telegram_clear_alert_key(key: str) -> None:
    try:
        TELEGRAM_ALERT_STATE.setdefault("last_sent_by_key", {}).pop(key, None)
        TELEGRAM_ALERT_STATE.setdefault("suppressed_by_key", {}).pop(key, None)
    except Exception:
        pass


def _telegram_clear_alert_prefix(prefix: str) -> None:
    try:
        sent = TELEGRAM_ALERT_STATE.setdefault("last_sent_by_key", {})
        suppressed = TELEGRAM_ALERT_STATE.setdefault("suppressed_by_key", {})
        for key in list(sent.keys()):
            if str(key).startswith(prefix):
                sent.pop(key, None)
        for key in list(suppressed.keys()):
            if str(key).startswith(prefix):
                suppressed.pop(key, None)
    except Exception:
        pass


def _telegram_mark_suppressed(key: str, reason: str, detail=None) -> None:
    try:
        TELEGRAM_ALERT_STATE.setdefault("suppressed_by_key", {})[key] = {
            "reason": reason,
            "detail": detail or {},
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ts": time.time(),
        }
    except Exception:
        pass


def _telegram_record_alert(key, msg, sent):
    now = time.time()
    TELEGRAM_ALERT_STATE.setdefault("last_sent_by_key", {})[key] = now
    TELEGRAM_ALERT_STATE.setdefault("last_alerts", []).append({
        "key": key,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": now,
        "sent": bool(sent),
        "message": str(msg)[:500],
    })
    TELEGRAM_ALERT_STATE["last_alerts"] = TELEGRAM_ALERT_STATE.get("last_alerts", [])[-25:]


def send_telegram_alert(key, msg, force=False, cooldown_seconds=None):
    if not TELEGRAM_ALERTS_ENABLED or not telegram_available():
        return False
    now = time.time()
    cooldown = TELEGRAM_ALERT_COOLDOWN_SECONDS if cooldown_seconds is None else float(cooldown_seconds)
    last = float(TELEGRAM_ALERT_STATE.setdefault("last_sent_by_key", {}).get(key, 0) or 0)
    if not force and last and (now - last) < cooldown:
        return False
    sent = send_telegram(msg)
    _telegram_record_alert(key, msg, sent)
    return sent



def _tg_float(value, default=0.0):
    try:
        num = float(value)
        return num if num == num else default
    except Exception:
        return default


def _tg_price(value, digits=6):
    num = _tg_float(value, None)
    if num is None or num <= 0:
        return "-"
    if abs(num) >= 100:
        return f"{num:.2f}"
    if abs(num) >= 1:
        return f"{num:.4f}"
    return f"{num:.6f}".rstrip("0").rstrip(".")


def _tg_score(value):
    num = _tg_float(value, 0.0)
    return f"{num:.0f}" if abs(num - round(num)) < 0.05 else f"{num:.1f}"


def _tg_rr(signal):
    rr = signal.get("rr") if isinstance(signal, dict) else None
    try:
        rr_num = float(rr)
        if rr_num > 0:
            return rr_num
    except Exception:
        pass
    try:
        entry = float(signal.get("entry"))
        sl = float(signal.get("sl"))
        tp = float(signal.get("tp"))
        return abs(tp - entry) / max(abs(entry - sl), 1e-9)
    except Exception:
        return 0.0


def build_candidate_telegram_message(signal):
    symbol = str(signal.get("symbol") or "-").upper()
    side = str(signal.get("type") or signal.get("side") or "-").upper()
    score = _tg_score(signal.get("score"))
    rr = _tg_rr(signal)
    tier = str(signal.get("tier") or signal.get("pair_tier") or get_pair_tier(symbol) or "-").upper()
    regime = str(signal.get("pair_regime") or signal.get("regime") or "-").upper()
    grade = str(signal.get("structure_grade") or signal.get("setupTag") or "-").upper()
    sweep = "SWEEP" if signal.get("sweep_high") or signal.get("sweep_low") or signal.get("sweep_memory") else "NO SWEEP"
    tp_source = str(signal.get("tp_source") or "RR").upper()
    return (
        f"🎯 MONTRA Candidate {score}\n"
        f"{symbol} {side} | RR {rr:.2f} | {tier}\n"
        f"Entry {_tg_price(signal.get('entry'))} | SL {_tg_price(signal.get('sl'))} | TP {_tg_price(signal.get('tp'))}\n"
        f"Setup {grade} | {regime} | {sweep} | TP {tp_source}"
    )


def maybe_send_candidate_alerts(rows):
    if not TELEGRAM_CANDIDATE_ALERT_ENABLED or not TELEGRAM_ALERTS_ENABLED or not telegram_available():
        return 0
    if not rows:
        return 0
    try:
        top_n = max(1, int(TELEGRAM_CANDIDATE_ALERT_TOP_N))
        min_score = float(TELEGRAM_CANDIDATE_MIN_SCORE)
    except Exception:
        top_n = 3
        min_score = 87.0

    eligible = []
    for row in rows:
        try:
            if float(row.get("score", 0) or 0) >= min_score:
                eligible.append(row)
        except Exception:
            continue
    eligible = sorted(eligible, key=lambda x: float(x.get("score", 0) or 0), reverse=True)[:top_n]

    sent_count = 0
    for row in eligible:
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        side = str(row.get("type") or row.get("side") or "-").upper()
        key = f"candidate:{symbol}:{side}"
        if send_telegram_alert(
            key,
            build_candidate_telegram_message(row),
            cooldown_seconds=TELEGRAM_CANDIDATE_ALERT_COOLDOWN_SECONDS,
        ):
            sent_count += 1
    if sent_count:
        TELEGRAM_ALERT_STATE.setdefault("current_state", {})["candidate_alerts_sent"] = sent_count
    return sent_count


def _best_order_result(result):
    if isinstance(result, dict):
        return result if result.get("status") == "OK" else result
    if isinstance(result, list):
        for row in result:
            if isinstance(row, dict) and row.get("status") == "OK":
                return row
        for row in result:
            if isinstance(row, dict):
                return row
    return {}


def build_simple_entry_telegram_message(signal, result=None, weight=None, order_ok=True):
    symbol = str(signal.get("symbol") or "-").upper()
    side = str(signal.get("type") or signal.get("side") or "-").upper()
    score = _tg_score(signal.get("score", 0))
    rr = _tg_rr(signal)
    row = _best_order_result(result or {})
    qty = row.get("qty_text") or row.get("qty") or row.get("executedQty") or "-"
    lev_obj = row.get("leverage") if isinstance(row, dict) else None
    lev = None
    if isinstance(lev_obj, dict):
        lev = lev_obj.get("leverage")
    elif lev_obj not in (None, ""):
        lev = lev_obj
    lev_txt = f" | Lev {lev}x" if lev not in (None, "") else ""
    protected = "Protected" if order_ok and (row.get("protective_resolved") or row.get("status") == "OK") else ("Failed" if not order_ok else "Protection pending")
    partial = ""
    if PARTIAL_TP_ENABLED:
        partial = f"\nPartial {PARTIAL_TP_R1_RATIO * 100:.0f}% @ R1"
    prefix = "✅ MONTRA ENTRY" if order_ok else "❌ MONTRA ENTRY FAILED"
    return (
        f"{prefix}\n"
        f"{symbol} {side} | Score {score} | RR {rr:.2f}\n"
        f"Entry {_tg_price(signal.get('entry'))} | SL {_tg_price(signal.get('sl'))} | TP {_tg_price(signal.get('tp'))}\n"
        f"Qty {qty}{lev_txt} | {protected}"
        f"{partial}"
    )


def send_auto_entry_telegram(signal, result=None, weight=None, order_ok=True):
    if not TELEGRAM_ENTRY_ALERT_SIMPLE:
        symbol = str(signal.get("symbol") or "UNKNOWN").upper()
        side = str(signal.get("type") or signal.get("side") or "-").upper()
        return send_telegram(f"🤖 MULTI AUTO TRADE\n{symbol} {side}\nScore: {float(signal.get('score', 0) or 0):.1f}\n{result}")
    key_status = "ok" if order_ok else "failed"
    symbol = str(signal.get("symbol") or "UNKNOWN").upper()
    side = str(signal.get("type") or signal.get("side") or "-").upper()
    return send_telegram_alert(
        f"entry:{key_status}:{symbol}:{side}",
        build_simple_entry_telegram_message(signal, result=result, weight=weight, order_ok=order_ok),
        force=bool(order_ok),
    )

def build_telegram_alert_status():
    now = time.time()
    last_sent = TELEGRAM_ALERT_STATE.get("last_sent_by_key", {})
    return {
        "enabled": TELEGRAM_ALERTS_ENABLED,
        "available": telegram_available(),
        "cooldown_seconds": TELEGRAM_ALERT_COOLDOWN_SECONDS,
        "blocked_alert_minutes": TELEGRAM_BLOCKED_ALERT_MINUTES,
        "scan_stale_alert_seconds": TELEGRAM_SCAN_STALE_ALERT_SECONDS,
        "ws_block_alert_seconds": TELEGRAM_WS_BLOCK_ALERT_SECONDS,
        "unprotected_alert_seconds": TELEGRAM_UNPROTECTED_ALERT_SECONDS,
        "ws_startup_grace_seconds": TELEGRAM_WS_STARTUP_GRACE_SECONDS,
        "require_ws_block": TELEGRAM_REQUIRE_WS_BLOCK,
        "send_recovery_alert": TELEGRAM_SEND_RECOVERY_ALERT,
        "current_only": TELEGRAM_ALERT_CURRENT_ONLY,
        "clear_resolved_keys": TELEGRAM_CLEAR_RESOLVED_KEYS,
        "candidate_alert_enabled": TELEGRAM_CANDIDATE_ALERT_ENABLED,
        "candidate_min_score": TELEGRAM_CANDIDATE_MIN_SCORE,
        "candidate_cooldown_seconds": TELEGRAM_CANDIDATE_ALERT_COOLDOWN_SECONDS,
        "candidate_top_n": TELEGRAM_CANDIDATE_ALERT_TOP_N,
        "entry_alert_simple": TELEGRAM_ENTRY_ALERT_SIMPLE,
        "ws_block_active": bool(TELEGRAM_ALERT_STATE.get("ws_block_active", False)),
        "ws_block_reason": TELEGRAM_ALERT_STATE.get("ws_block_reason"),
        "app_uptime_seconds": round(now - APP_START_TS, 2),
        "current_state": TELEGRAM_ALERT_STATE.get("current_state", {}),
        "suppressed_by_key": TELEGRAM_ALERT_STATE.get("suppressed_by_key", {}),
        "last_sent_ago_by_key": {k: round(now - float(v), 2) for k, v in last_sent.items()},
        "last_alerts": TELEGRAM_ALERT_STATE.get("last_alerts", [])[-10:],
    }


def check_runtime_telegram_alerts():
    """Telegram alerts bound only to current runtime state."""
    if not TELEGRAM_ALERTS_ENABLED or not AUTO_MODE:
        return

    now = time.time()
    try:
        live_rows = build_live_position_rows()[:10]
    except Exception:
        live_rows = []

    candidate_rows = sorted(candidate_list_live, key=lambda x: x.get("score", 0), reverse=True)
    summary = build_final_execution_summary(candidate_rows, live_rows)
    status = str(summary.get("status") or "UNKNOWN")
    reason = str(summary.get("reason") or "UNKNOWN")
    age = float(summary.get("age_seconds") or 0)
    symbol = summary.get("symbol") or "_SYSTEM_"
    last_stage = summary.get("last_stage") or "-"
    last_scan_age = summary.get("last_scan_age_seconds")

    TELEGRAM_ALERT_STATE.setdefault("current_state", {})["execution"] = status

    current_final_status = str((LAST_FINAL_EXECUTION or {}).get("status") or "")
    current_final_ts = float((LAST_FINAL_EXECUTION or {}).get("ts") or 0)
    current_summary_ts = float(summary.get("since_ts") or 0)
    is_current_block = (
        status == "BLOCKED"
        and current_final_status == "BLOCKED"
        and current_summary_ts >= max(0.0, current_final_ts - 1.0)
    )

    if is_current_block and age >= TELEGRAM_BLOCKED_ALERT_MINUTES * 60:
        send_telegram_alert(
            f"blocked:{symbol}:{reason}",
            f"⚠️ MONTRA BLOCKED > {TELEGRAM_BLOCKED_ALERT_MINUTES:.0f}m\nSymbol: {symbol}\nReason: {reason}\nAge: {age:.0f}s\nStage: {last_stage}"
        )
    else:
        _telegram_clear_alert_prefix("blocked:")
        if status == "BLOCKED" and not is_current_block:
            _telegram_mark_suppressed("blocked", "stale_or_resolved_block", {
                "status": status,
                "reason": reason,
                "current_final_status": current_final_status,
                "summary_ts": current_summary_ts,
                "final_ts": current_final_ts,
            })

    if status == "LIVE_UNPROTECTED" and age >= TELEGRAM_UNPROTECTED_ALERT_SECONDS:
        send_telegram_alert(
            f"unprotected:{symbol}",
            f"🚨 MONTRA LIVE POSITION UNPROTECTED\nSymbol: {symbol}\nAge: {age:.0f}s\nAction: verify SL/TP immediately."
        )
    elif status != "LIVE_UNPROTECTED":
        _telegram_clear_alert_prefix("unprotected:")

    if AUTO_TRADING and LAST_SCAN_CYCLE_TS <= 0:
        boot_age = now - APP_START_TS
        if boot_age > (EXECUTION_BOOT_GRACE_SECONDS + TELEGRAM_SCAN_STALE_ALERT_SECONDS):
            TELEGRAM_ALERT_STATE.setdefault("current_state", {})["scan"] = "NEVER_STARTED"
            send_telegram_alert("scan_never_started", f"⚠️ MONTRA scan telemetry belum mulai\nUptime: {boot_age:.0f}s")
        else:
            TELEGRAM_ALERT_STATE.setdefault("current_state", {})["scan"] = "BOOT_GRACE"
            _telegram_clear_alert_key("scan_never_started")
            _telegram_clear_alert_key("scan_stale")
    elif AUTO_TRADING and LAST_SCAN_CYCLE_TS > 0:
        scan_age = float(last_scan_age if last_scan_age is not None else (now - LAST_SCAN_CYCLE_TS))
        stale_limit = max(TELEGRAM_SCAN_STALE_ALERT_SECONDS, max(SCAN_INTERVAL_MID, SCAN_INTERVAL_MID_AGGRESSIVE) * 2)
        if scan_age > stale_limit:
            TELEGRAM_ALERT_STATE.setdefault("current_state", {})["scan"] = "STALE"
            send_telegram_alert("scan_stale", f"⚠️ MONTRA scan stale\nLast scan age: {scan_age:.0f}s\nLimit: {stale_limit:.0f}s")
        else:
            TELEGRAM_ALERT_STATE.setdefault("current_state", {})["scan"] = "OK"
            _telegram_clear_alert_key("scan_never_started")
            _telegram_clear_alert_key("scan_stale")

    ws_status = get_ws_status()
    ws_gate = ws_health_snapshot()
    ws_age = float(ws_status.get("last_message_age") or 9999)
    uptime = now - APP_START_TS
    ws_block_reason = str(ws_gate.get("reason") or "UNKNOWN")
    ws_gate_blocking = bool(ws_gate.get("block")) and ws_block_reason in ("STALE_BLOCK", "SOCKET_DOWN", "THREAD_DEAD")

    if uptime < TELEGRAM_WS_STARTUP_GRACE_SECONDS:
        TELEGRAM_ALERT_STATE.setdefault("current_state", {})["ws"] = "STARTUP_GRACE"
        _telegram_mark_suppressed("ws_stale", "startup_grace", {"uptime": round(uptime, 2), "age": ws_age})
    elif ws_gate_blocking:
        TELEGRAM_ALERT_STATE.setdefault("current_state", {})["ws"] = "BLOCKING"
        TELEGRAM_ALERT_STATE["ws_block_active"] = True
        TELEGRAM_ALERT_STATE["ws_block_reason"] = ws_block_reason
        send_telegram_alert("ws_stale", f"⚠️ MONTRA WS stale/blocking\nReason: {ws_block_reason}\nLast message age: {ws_age:.1f}s\nRestart count: {ws_status.get('restart_count')}")
    else:
        TELEGRAM_ALERT_STATE.setdefault("current_state", {})["ws"] = "OK"
        _telegram_clear_alert_key("ws_stale")
        if TELEGRAM_SEND_RECOVERY_ALERT and TELEGRAM_ALERT_STATE.get("ws_block_active"):
            TELEGRAM_ALERT_STATE["ws_block_active"] = False
            prev_reason = TELEGRAM_ALERT_STATE.get("ws_block_reason") or "UNKNOWN"
            TELEGRAM_ALERT_STATE["ws_block_reason"] = None
            send_telegram_alert("ws_recovered", f"✅ MONTRA WS recovered\nPrevious reason: {prev_reason}\nCurrent reason: {ws_block_reason}\nLast message age: {ws_age:.2f}s", force=True)

    if circuit_breaker_active():
        send_telegram_alert("circuit_breaker", f"🧯 MONTRA circuit breaker active\nRemaining: {circuit_breaker_remaining():.0f}s\nErrors: {CONSECUTIVE_ERRORS}/{CIRCUIT_BREAKER_THRESHOLD}")
    else:
        _telegram_clear_alert_key("circuit_breaker")


# Compatibility alias for old callers. Use the newer cancel_protective_orders_for_client under the hood.
def cancel_existing_orders(symbol, cancel_tp: bool = True, cancel_sl: bool = True):
    if binance is None:
        print("⚠️ cancel skipped: binance client not ready")
        return False
    return cancel_protective_orders_for_client(binance, "MAIN", symbol, cancel_tp=cancel_tp, cancel_sl=cancel_sl)

# ================= END TELEGRAM ALERT SOURCE-OF-TRUTH HELPERS =================

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

    # [FIX 7] Hardcode Maximum Daily Loss Institusi: $5 USD Flat.
    MAX_DAILY_LOSS_USD = 5.0 

    now_day = time.strftime("%Y-%m-%d")
    eq = get_total_equity()

    if eq is None or eq <= 0:
        print(f"⚠️ safety_check skipped: invalid equity read ({eq})")
        return True

    if START_EQUITY is None or START_EQUITY <= 0:
        START_EQUITY = eq
        save_runtime_state()
        return True

    if DAILY_START_EQUITY is None or DAILY_START_EQUITY <= 0:
        DAILY_START_EQUITY = eq
        save_runtime_state()
        return True

    if now_day != LAST_DAY:
        DAILY_START_EQUITY = eq
        LAST_DAY = now_day
        daily_loss = 0
        print("🌅 RESET DAILY EQUITY:", eq)
        reset_pairs()
        save_runtime_state()

    # Hitung total PnL Mengambang (Unrealized)
    total_unrealized = sum(ACCOUNT_PROFIT.values()) if ACCOUNT_PROFIT else 0.0
    
    # Total loss harian (Realized loss yang sudah di-cache + PnL mengambang yang negatif)
    current_unrealized_loss = abs(total_unrealized) if total_unrealized < 0 else 0.0
    total_daily_exposure = daily_loss + current_unrealized_loss

    if total_daily_exposure >= MAX_DAILY_LOSS_USD:
        if not KILL_SWITCH:
            KILL_SWITCH = True
            save_runtime_state()
            send_telegram(f"🛑 CIRCUIT BREAKER HIT: Loss + Unrealized (${total_daily_exposure:.2f}) melebihi limit harian (${MAX_DAILY_LOSS_USD}). Bot di-lock.")
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

WS_FALLBACK_PRICE_CACHE = {}
WS_FALLBACK_PRICE_TS = {}


def get_live_or_fallback_price(symbol, ohlcv_last=None):
    """Prefer WS mark/candle. If WS is stale, poll REST ticker with per-symbol TTL."""
    symbol = str(symbol or "").upper()
    mark = get_live_mark(symbol)
    if mark and get_live_age(symbol) < WS_MAX_AGE:
        return float(mark.get("price")), "ws_mark"

    live = get_live_candle(symbol)
    if live and get_live_age(symbol) < WS_MAX_AGE:
        return float(live.get("close")), "ws_candle"

    now = time.time()
    last_ts = WS_FALLBACK_PRICE_TS.get(symbol, 0.0)
    if symbol in WS_FALLBACK_PRICE_CACHE and (now - last_ts) < WS_FALLBACK_POLL_INTERVAL:
        return float(WS_FALLBACK_PRICE_CACHE[symbol]), "rest_fallback_cache"

    if binance is not None:
        try:
            price = float(binance.futures_symbol_ticker(symbol=symbol)["price"])
            WS_FALLBACK_PRICE_CACHE[symbol] = price
            WS_FALLBACK_PRICE_TS[symbol] = now
            add_execution_decision("ws_fallback_price", symbol, "WARN", {
                "price": price,
                "interval": WS_FALLBACK_POLL_INTERVAL,
                "ws_age": round(get_live_age(symbol), 2),
            })
            return price, "rest_fallback"
        except Exception as exc:
            record_runtime_error("ws_fallback_price", exc)

    if ohlcv_last is not None:
        return float(ohlcv_last[4]), "ohlcv_close"
    return 0.0, "unavailable"

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

def get_open_positions(force=False):
    """Return live open positions. Use force=True for pre-entry risk gates."""
    try:
        positions = fetch_main_positions(
            force=bool(force),
            max_age=0 if force else POSITION_CACHE_TTL,
            label="MAIN",
        )
        return [p for p in positions if abs(float(p.get("positionAmt", 0) or 0)) > 0]
    except Exception as e:
        print("Error get_open_positions:", e)
        return []


def _cleanup_reserved_trade_slots(now=None):
    now = time.time() if now is None else float(now)
    expired = []
    with EXECUTION_SLOT_LOCK:
        for sym, row in list(RESERVED_TRADE_SLOTS.items()):
            ts = float(row.get("ts", 0) or 0)
            if ts <= 0 or (now - ts) > ENTRY_SLOT_TTL_SECONDS:
                expired.append(sym)
        for sym in expired:
            RESERVED_TRADE_SLOTS.pop(sym, None)
            EXECUTION_IN_PROGRESS.discard(sym)
    return expired


def get_risk_slot_snapshot(symbol=None, force=True):
    """Source-of-truth slot count = forced Binance positions + in-flight reservations."""
    symbol = str(symbol or "").upper().strip() or None
    now = time.time()
    open_positions = get_open_positions(force=bool(force and MAX_OPEN_TRADES_FORCE_REFRESH))
    open_symbols = sorted({p.get("symbol") for p in open_positions if p.get("symbol")})

    with EXECUTION_SLOT_LOCK:
        _cleanup_reserved_trade_slots(now)
        reserved_rows = {sym: dict(row) for sym, row in RESERVED_TRADE_SLOTS.items()}

    reserved_symbols = sorted([sym for sym in reserved_rows.keys() if sym not in set(open_symbols)])
    used_slots = len(open_symbols) + len(reserved_symbols)
    available_slots = max(0, MAX_OPEN_TRADES - used_slots)
    return {
        "max_open_trades": MAX_OPEN_TRADES,
        "open_count": len(open_symbols),
        "reserved_count": len(reserved_symbols),
        "used_slots": used_slots,
        "available_slots": available_slots,
        "open_symbols": open_symbols,
        "reserved_symbols": reserved_symbols,
        "reserved_rows": reserved_rows,
        "symbol": symbol,
        "force_refresh": bool(force and MAX_OPEN_TRADES_FORCE_REFRESH),
        "ts": now,
    }


def can_open_new_trade(symbol, force=True):
    symbol = str(symbol or "").upper().strip()
    snap = get_risk_slot_snapshot(symbol=symbol, force=force)
    if symbol in snap["open_symbols"]:
        return False, "POSITION_ALREADY_OPEN", snap
    if symbol in snap["reserved_symbols"]:
        return False, "RISK_SLOT_RESERVED", snap
    if snap["used_slots"] >= MAX_OPEN_TRADES:
        return False, "MAX_POSITION", snap
    return True, "OK", snap


def reserve_trade_slot(symbol, side=None, reason="entry", allow_existing=False):
    symbol = str(symbol or "").upper().strip()
    if not symbol:
        return False, "NO_SYMBOL", {}
    with EXECUTION_SLOT_LOCK:
        if symbol in RESERVED_TRADE_SLOTS:
            if allow_existing:
                return True, "ALREADY_RESERVED", get_risk_slot_snapshot(symbol=symbol, force=True)
            return False, "RISK_SLOT_RESERVED", get_risk_slot_snapshot(symbol=symbol, force=True)
        if symbol in EXECUTION_IN_PROGRESS and not allow_existing:
            return False, "EXECUTION_IN_PROGRESS", get_risk_slot_snapshot(symbol=symbol, force=True)

        ok, reason2, snap = can_open_new_trade(symbol, force=True)
        if not ok:
            return False, reason2, snap

        row = {
            "symbol": symbol,
            "side": side,
            "reason": reason,
            "ts": time.time(),
            "expires_at": time.time() + ENTRY_SLOT_TTL_SECONDS,
        }
        RESERVED_TRADE_SLOTS[symbol] = row
        EXECUTION_IN_PROGRESS.add(symbol)
        GLOBAL_SYMBOL_LOCK.add(symbol)
        snap = get_risk_slot_snapshot(symbol=symbol, force=True)
        snap["reservation"] = row

    add_order_audit("RISK_SLOT_RESERVED", symbol, {
        "side": side,
        "reason": reason,
        "slot": {k: snap.get(k) for k in ("max_open_trades", "open_count", "reserved_count", "used_slots", "available_slots", "open_symbols", "reserved_symbols")},
    })
    return True, "RESERVED", snap


def release_trade_slot(symbol, reason="done", unlock=False):
    symbol = str(symbol or "").upper().strip()
    if not symbol:
        return
    with EXECUTION_SLOT_LOCK:
        RESERVED_TRADE_SLOTS.pop(symbol, None)
        EXECUTION_IN_PROGRESS.discard(symbol)
        if unlock:
            GLOBAL_SYMBOL_LOCK.discard(symbol)
    try:
        add_order_audit("RISK_SLOT_RELEASED", symbol, {"reason": reason, "unlock": bool(unlock)})
    except Exception:
        pass


# ⭐ NEW: centralized decision
def pre_entry_spread_gate(symbol):
    tier = get_pair_tier(symbol)
    ok, reason, detail = check_spread_gate(binance, symbol, tier)
    if reason == "SPREAD_WARN":
        add_execution_decision("spread_gate", symbol, "WARN", detail)
        print(f"⚠️ SPREAD WARN {symbol}: {detail.get('spread_pct'):.6f} threshold={detail.get('threshold_pct')}")
        return True, reason, detail
    add_execution_decision("spread_gate", symbol, "PASS" if ok else "BLOCK", detail)
    return ok, reason, detail


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

    if circuit_breaker_active():
        return False, f"CIRCUIT_BREAKER_{int(circuit_breaker_remaining())}s"

    if not AUTO_TRADING:
        return False, "AUTO_OFF"

    if not safety_check():
        return False, "SAFETY_BLOCK"

    # === MONTRA: NEWS_GATE_HOOK_SHOULD_EXECUTE START ===
    news_state = get_institutional_news_state(symbol)
    signal["news_state"] = news_state
    if news_state.get("applies_to_symbol") and news_state.get("block_decision"):
        ev_phase = news_state.get("phase", "UNKNOWN")
        ev_tier = news_state.get("tier", "UNKNOWN")
        return False, f"NEWS_GATE_{ev_tier}_{ev_phase}"
    news_score_penalty = int(news_state.get("score_penalty", 0) or 0)
    if news_score_penalty > 0:
        adjusted_score = float(signal.get("score", 0) or 0) - news_score_penalty
        if adjusted_score < tier_score_floor(symbol):
            return False, f"NEWS_POST_PENALTY_BELOW_FLOOR_{int(adjusted_score)}"
    # === MONTRA: NEWS_GATE_HOOK_SHOULD_EXECUTE END ===

    # [FIX 3] 4H Regime Hard Gate per pair. Institusi tidak entry melawan impulse 4H.
    regime_4h = get_regime_tf(symbol, "4h")
    if regime_4h == "SIDEWAYS":
        return False, "4H_REGIME_SIDEWAYS"
        
    if regime_4h == "BULL" and side != "BUY":
        return False, f"4H_REGIME_BULL_MISMATCH (Signal: {side})"
        
    if regime_4h == "BEAR" and side != "SELL":
        return False, f"4H_REGIME_BEAR_MISMATCH (Signal: {side})"
       
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

    quality_ok, quality_reason, quality_detail = evaluate_signal_execution_quality(signal)
    signal["execution_quality"] = quality_detail
    if not quality_ok:
        return False, quality_reason

    spread_ok, spread_reason, spread_detail = pre_entry_spread_gate(symbol)
    signal["spread_gate"] = spread_detail
    if not spread_ok:
        return False, spread_reason

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

    slot_ok, slot_reason, slot_detail = can_open_new_trade(symbol, force=True)
    signal["risk_slots"] = slot_detail
    if not slot_ok:
        return False, slot_reason

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



def _parse_montra_time_ms(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            val = float(value)
            return int(val if val > 1e12 else val * 1000)
        text = str(value).strip()
        return int(time.mktime(time.strptime(text[:19], "%Y-%m-%d %H:%M:%S")) * 1000)
    except Exception:
        return None


def _safe_trade_row(row):
    if not isinstance(row, dict):
        return {}
    return {
        "time": int(row.get("time", 0) or 0),
        "side": row.get("side"),
        "price": _safe_float(row.get("price"), 0.0),
        "qty": _safe_float(row.get("qty"), 0.0),
        "quoteQty": _safe_float(row.get("quoteQty"), 0.0),
        "realizedPnl": _safe_float(row.get("realizedPnl"), 0.0),
        "commission": _safe_float(row.get("commission"), 0.0),
        "commissionAsset": row.get("commissionAsset"),
        "orderId": row.get("orderId"),
        "buyer": row.get("buyer"),
        "maker": row.get("maker"),
        "positionSide": row.get("positionSide"),
    }


def _safe_order_row(row):
    if not isinstance(row, dict):
        return {}
    return {
        "orderId": row.get("orderId"),
        "clientOrderId": row.get("clientOrderId"),
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "type": row.get("type") or row.get("origType") or row.get("orderType"),
        "origType": row.get("origType"),
        "status": row.get("status") or row.get("algoStatus") or row.get("orderStatus"),
        "price": row.get("price"),
        "avgPrice": row.get("avgPrice"),
        "stopPrice": row.get("stopPrice") or row.get("triggerPrice"),
        "origQty": row.get("origQty") or row.get("quantity"),
        "executedQty": row.get("executedQty"),
        "reduceOnly": row.get("reduceOnly"),
        "closePosition": row.get("closePosition"),
        "updateTime": row.get("updateTime"),
        "time": row.get("time"),
        "workingType": row.get("workingType"),
    }


def _infer_close_source(symbol, snapshot, close_trades, matching_orders):
    signal = (snapshot or {}).get("signal", {}) if isinstance(snapshot, dict) else {}
    side = str((snapshot or {}).get("side") or signal.get("type") or "").upper()
    sl = _safe_float((snapshot or {}).get("sl") or signal.get("sl"), 0.0)
    tp = _safe_float((snapshot or {}).get("tp") or signal.get("tp"), 0.0)
    order_types = {str(o.get("type") or o.get("origType") or "").upper() for o in matching_orders or []}
    reduce_market = any(
        str(o.get("type") or o.get("origType") or "").upper() == "MARKET" and bool(o.get("reduceOnly"))
        for o in matching_orders or []
    )
    if "STOP_MARKET" in order_types:
        return "EXCHANGE_SL_TRIGGERED"
    if "TAKE_PROFIT_MARKET" in order_types:
        return "EXCHANGE_TP_TRIGGERED"
    if reduce_market:
        return "MARKET_REDUCE_CLOSE"
    close_price = _safe_float((close_trades[-1] or {}).get("price"), 0.0) if close_trades else 0.0
    if close_price > 0:
        if sl and abs(close_price - sl) / max(sl, 1e-12) < 0.0015:
            return "PRICE_NEAR_SL"
        if tp and abs(close_price - tp) / max(tp, 1e-12) < 0.0015:
            return "PRICE_NEAR_TP"
    if close_trades:
        return "UNKNOWN_CLOSE_WITH_TRADE"
    return "NO_RECENT_CLOSE_TRADE_FOUND"


def build_position_close_diagnostic(symbol, snapshot=None, last_state=None):
    if not CLOSE_AUDIT_ENABLED or binance is None:
        return {"enabled": bool(CLOSE_AUDIT_ENABLED), "source": "disabled_or_no_client"}
    snapshot = snapshot or {}
    signal = snapshot.get("signal", {}) if isinstance(snapshot, dict) else {}
    side = str(snapshot.get("side") or signal.get("type") or (last_state or {}).get("side") or "").upper()
    close_side = "BUY" if side == "SELL" else "SELL" if side == "BUY" else None
    opened_ms = _parse_montra_time_ms(snapshot.get("opened_at") or signal.get("opened_at"))
    now_ms = int(time.time() * 1000)
    lookback_ms = max(1, int(CLOSE_AUDIT_LOOKBACK_MINUTES)) * 60 * 1000
    start_ms = max(opened_ms or 0, now_ms - lookback_ms)
    diag = {
        "symbol": symbol,
        "side": side or None,
        "expected_close_side": close_side,
        "opened_ms": opened_ms,
        "start_ms": start_ms,
        "lookback_minutes": CLOSE_AUDIT_LOOKBACK_MINUTES,
        "last_state": last_state or {},
        "snapshot_entry": snapshot.get("entry") or signal.get("entry"),
        "snapshot_sl": snapshot.get("sl") or signal.get("sl"),
        "snapshot_tp": snapshot.get("tp") or signal.get("tp"),
    }
    close_rows = []
    close_order_ids = []
    try:
        trades = signed_call(binance, binance.futures_account_trades, symbol=symbol, label="MAIN") or []
        rows = [_safe_trade_row(t) for t in trades[-max(10, CLOSE_AUDIT_TRADE_LIMIT):]]
        recent_rows = [r for r in rows if int(r.get("time") or 0) >= start_ms]
        side_rows = [r for r in recent_rows if str(r.get("side") or "").upper() == close_side] if close_side else recent_rows
        realized_rows = [r for r in recent_rows if abs(_safe_float(r.get("realizedPnl"), 0.0)) > 0]
        close_rows = (realized_rows or side_rows)[-10:]
        close_order_ids = sorted({r.get("orderId") for r in close_rows if r.get("orderId") is not None})
        diag.update({
            "recent_trade_count": len(recent_rows),
            "close_trade_count": len(close_rows),
            "close_order_ids": close_order_ids,
            "close_trades": close_rows,
            "realized_pnl_from_close_rows": round(sum(_safe_float(r.get("realizedPnl"), 0.0) for r in close_rows), 8),
        })
    except Exception as exc:
        diag["trades_error"] = str(exc)
    matching_orders = []
    if CLOSE_AUDIT_FETCH_ORDERS:
        try:
            all_orders_fn = getattr(binance, "futures_get_all_orders", None)
            if all_orders_fn:
                all_orders = signed_call(binance, all_orders_fn, symbol=symbol, limit=max(10, CLOSE_AUDIT_ORDER_LIMIT), label="MAIN") or []
                for o in all_orders:
                    if isinstance(o, dict) and o.get("orderId") in close_order_ids:
                        matching_orders.append(_safe_order_row(o))
                diag["matching_orders"] = matching_orders
                diag["matching_order_count"] = len(matching_orders)
            else:
                diag["orders_error"] = "futures_get_all_orders unavailable"
        except Exception as exc:
            diag["orders_error"] = str(exc)
    diag["inferred_close_source"] = _infer_close_source(symbol, snapshot, close_rows, matching_orders)
    return diag

def finalize_closed_trade(
    symbol,
    fallback_pnl=0.0,
    regime=None,
    vol=None,
    note=None,
    send_notice=True,
    audit_event="POSITION_CLOSED",
    last_state=None,
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

    snapshot_for_close = TRADE_SNAPSHOTS.get(symbol, {})
    close_audit = build_position_close_diagnostic(symbol, snapshot=snapshot_for_close, last_state=last_state)
    close_info["close_audit"] = close_audit
    add_order_audit("POSITION_CLOSE_DIAGNOSTIC", symbol, close_audit)

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

    release_trade_slot(symbol, reason="position_closed", unlock=True)
    GLOBAL_SYMBOL_LOCK.discard(symbol)
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
                        last_state=last,
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
        "mid_aggressive_pairs": MID_AGGRESSIVE_PAIRS,
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

def clean_signal_row_for_output(row):
    try:
        clean_row = dict(row or {})
        apply_clean_prices_to_signal(clean_row)
        return clean_row
    except Exception:
        return dict(row or {})


@app.get("/debug/candidates")
def debug_candidates():
    rows = [clean_signal_row_for_output(r) for r in sorted(candidate_list_live, key=lambda x: x.get("score", 0), reverse=True)]
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

@app.get("/debug/execution-summary")
def debug_execution_summary():
    try:
        candidate_rows = sorted(candidate_list_live, key=lambda x: x.get("score", 0), reverse=True)
        live_rows = build_live_position_rows()
    except Exception:
        candidate_rows = sorted(candidate_list_live, key=lambda x: x.get("score", 0), reverse=True)
        live_rows = []
    return build_final_execution_summary(candidate_rows, live_rows)


@app.get("/debug/sweep-memory/{symbol}")
def debug_sweep_memory(symbol: str, timeframe: str = Query(default="15m"), limit: int = Query(default=80, ge=20, le=300)):
    try:
        data = fetch_futures_klines_cached(symbol.upper(), interval=timeframe, limit=limit)
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "sweep": detect_sweep_memory(data),
        }
    except Exception as e:
        return {"symbol": symbol.upper(), "error": str(e)}


@app.get("/debug/price-precision/{symbol}")
def debug_price_precision(symbol: str):
    sym = symbol.upper()
    tick = get_price_tick_detail(sym)
    return {
        "symbol": sym,
        "effective_tick_ok": tick.get("ok"),
        "effective_tick": tick.get("tick_text"),
        "tick_source": tick.get("source"),
        "pricePrecision": tick.get("pricePrecision"),
        "exchange_tickSize": tick.get("exchange_tickSize"),
        "exchange_tickSizeText": tick.get("exchange_tickSizeText"),
        "price_precision_use_price_precision": PRICE_PRECISION_USE_PRICE_PRECISION,
        "env_override": os.getenv(f"PRICE_TICK_SIZE_{sym}") or os.getenv(f"TICK_SIZE_{sym}"),
        "example_0_91835": normalize_protective_price_detail(sym, 0.91835, "SELL", "TP"),
    }


@app.get("/debug/exchange-filter/{symbol}")
def debug_exchange_filter(symbol: str):
    sym = str(symbol or "").upper().strip()
    row = EXCHANGE_CACHE.get(sym)
    return {
        "symbol": sym,
        "found": bool(row),
        "filter": row,
        "source": "EXCHANGE_CACHE",
        "note": "Used for qty stepSize and protective SL/TP tickSize; no extra Binance API call.",
    }


@app.get("/debug/telegram-alerts")
def debug_telegram_alerts():
    return build_telegram_alert_status()


@app.get("/debug/spread")
def debug_spread_all(force: bool = Query(default=False)):
    rows = []
    for sym in PAIRS:
        tier = get_pair_tier(sym)
        if force:
            rows.append(get_live_spread(binance, sym, tier, force=True))
        else:
            cached = get_spread_cache_snapshot().get(sym)
            rows.append(cached if cached else get_live_spread(binance, sym, tier, force=False))
    return {
        "count": len(rows),
        "rows": rows,
        "thresholds": {
            "TOP": SPREAD_THRESHOLD_TOP,
            "MID": SPREAD_THRESHOLD_MID,
            "MID_AGGRESSIVE": SPREAD_THRESHOLD_MID_AGGRESSIVE,
            "warn_multiplier": SPREAD_WARN_MULTIPLIER,
            "cache_ttl": SPREAD_CACHE_TTL,
        }
    }


@app.get("/debug/spread/{symbol}")
def debug_spread_symbol(symbol: str, force: bool = Query(default=True)):
    sym = str(symbol or "").upper()
    tier = get_pair_tier(sym)
    return get_live_spread(binance, sym, tier, force=force)


# === MONTRA: NEWS_ENGINE_DEBUG_ENDPOINTS START ===
@app.get("/debug/news_state")
def debug_news_state(symbol: str = Query(default="BTCUSDT")):
    return get_institutional_news_state(symbol=symbol)


@app.get("/debug/news_calendar")
def debug_news_calendar(limit: int = Query(default=20, ge=1, le=200)):
    refresh_institutional_news_cache()
    events = INSTITUTIONAL_NEWS_CACHE.get("events", []) or []
    sliced = events[:limit]
    return {
        "source": INSTITUTIONAL_NEWS_CACHE.get("source"),
        "last_refresh_ts": INSTITUTIONAL_NEWS_CACHE.get("last_refresh_ts"),
        "next_refresh_ts": INSTITUTIONAL_NEWS_CACHE.get("next_refresh_ts"),
        "fetch_error": INSTITUTIONAL_NEWS_CACHE.get("fetch_error"),
        "provider_errors": INSTITUTIONAL_NEWS_CACHE.get("provider_errors", {}),
        "fetch_attempts": INSTITUTIONAL_NEWS_CACHE.get("fetch_attempts", 0),
        "fmp_api_key_present": bool(FMP_API_KEY),
        "fmp_api_key_length": len(FMP_API_KEY) if FMP_API_KEY else 0,
        "news_engine_enabled": NEWS_ENGINE_ENABLED,
        "news_engine_provider": NEWS_ENGINE_PROVIDER,
        "event_count_total": len(events),
        "events": sliced,
    }
# === MONTRA: NEWS_ENGINE_DEBUG_ENDPOINTS END ===


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
            "running": ws_status.get("running"),
            "thread_alive": ws_status.get("thread_alive"),
            "app_alive": ws_status.get("app_alive"),
            "restart_count": ws_status.get("restart_count"),
            "last_error": ws_status.get("last_error"),
            "message_count": ws_status.get("message_count"),
            "last_message_age": ws_status.get("last_message_age"),
            "last_stream": ws_status.get("last_stream"),
            "last_event": ws_status.get("last_event"),
            "subscribed_count": ws_status.get("subscribed_count"),
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

        "risk_slots": get_risk_slot_snapshot(force=False),

        "locks": {
            "symbol_lock_count": len(GLOBAL_SYMBOL_LOCK),
            "execution_in_progress_count": len(EXECUTION_IN_PROGRESS),
            "reserved_slot_count": len(RESERVED_TRADE_SLOTS),
            "locked_symbols": sorted(list(GLOBAL_SYMBOL_LOCK)),
            "executing_symbols": sorted(list(EXECUTION_IN_PROGRESS)),
            "reserved_symbols": sorted(list(RESERVED_TRADE_SLOTS.keys())),
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

        "final_execution": build_final_execution_summary(candidate_rows, live_rows),

        "circuit_breaker": {
            "active": circuit_breaker_active(),
            "remaining": round(circuit_breaker_remaining(), 2),
            "consecutive_errors": CONSECUTIVE_ERRORS,
            "threshold": CIRCUIT_BREAKER_THRESHOLD,
            "pause": CIRCUIT_BREAKER_PAUSE,
        },

        "spread": {
            "threshold_top": SPREAD_THRESHOLD_TOP,
            "threshold_mid": SPREAD_THRESHOLD_MID,
            "threshold_mid_aggressive": SPREAD_THRESHOLD_MID_AGGRESSIVE,
            "cache_ttl": SPREAD_CACHE_TTL,
        },

        "telegram_alerts": build_telegram_alert_status(),

        "sweep_memory": {
            "lookback": SWEEP_LOOKBACK,
            "window": SWEEP_MEMORY_WINDOW,
            "require_reclaim": SWEEP_REQUIRE_RECLAIM,
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


@app.get("/debug/close-audit/{symbol}")
def debug_close_audit(symbol: str, limit: int = Query(default=20, ge=1, le=100)):
    symbol = symbol.upper().strip()
    audit_rows = [r for r in ORDER_AUDIT_LOG if r.get("symbol") == symbol and "CLOSE" in str(r.get("event", ""))]
    replay_rows = [r for r in TRADE_REPLAY_LOG if r.get("symbol") == symbol]
    snapshot = TRADE_SNAPSHOTS.get(symbol, {})
    live_diag = build_position_close_diagnostic(symbol, snapshot=snapshot, last_state=last_position_state.get(symbol)) if snapshot else None
    return {
        "symbol": symbol,
        "audit_count": len(audit_rows),
        "audit_rows": audit_rows[-limit:],
        "replay_count": len(replay_rows),
        "replay_rows": replay_rows[-limit:],
        "live_diagnostic": live_diag,
    }


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

def _parse_runtime_bool(value, field_name="state"):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    raise HTTPException(status_code=400, detail=f"{field_name} must be true/false or on/off")


def _kill_switch_payload(source="api"):
    return {
        "kill_switch": bool(KILL_SWITCH),
        "kill_switch_default": bool(globals().get("KILL_SWITCH_DEFAULT", False)),
        "auto_mode": bool(AUTO_MODE),
        "auto_trading": bool(AUTO_TRADING),
        "source": source,
        "note": "kill_switch_on_blocks_new_entries_only; it_does_not_market_close_existing_positions",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/kill-switch")
def get_kill_switch():
    return _kill_switch_payload(source="read")


@app.post("/kill-switch")
def kill_switch(payload: dict = Body(...)):
    global KILL_SWITCH
    if not isinstance(payload, dict) or "state" not in payload:
        raise HTTPException(status_code=400, detail="state is required: true/false or on/off")

    next_state = _parse_runtime_bool(payload.get("state"), "state")
    source = str(payload.get("source") or "api")[:32]
    note = str(payload.get("note") or "")[:160]
    previous_state = bool(KILL_SWITCH)
    KILL_SWITCH = next_state

    detail = {
        "previous_state": previous_state,
        "next_state": bool(KILL_SWITCH),
        "source": source,
        "note": note,
        "auto_mode": bool(AUTO_MODE),
        "auto_trading": bool(AUTO_TRADING),
    }
    try:
        add_execution_decision("manual_kill_switch", "_SYSTEM_", "ON" if KILL_SWITCH else "OFF", detail)
        set_final_execution(
            "KILL_SWITCH_ON" if KILL_SWITCH else "KILL_SWITCH_OFF",
            reason="MANUAL_KILL_SWITCH_ON" if KILL_SWITCH else "MANUAL_KILL_SWITCH_OFF",
            stage="manual_control",
            detail=detail,
        )
    except Exception as e:
        print("manual kill switch telemetry error:", e)

    save_runtime_state(force=True)
    return _kill_switch_payload(source=source)

@app.get("/ai-memory")
def get_ai_memory(active_only: bool = Query(default=False), include_meta: bool = Query(default=False)):
    active_symbols = set(PAIRS)

    if active_only:
        data = {sym: ai_memory.get(sym) for sym in PAIRS if sym in ai_memory}
    else:
        data = ai_memory

    if not include_meta:
        return data

    stale_symbols = sorted([sym for sym in ai_memory.keys() if sym not in active_symbols])
    return {
        "data": data,
        "active_symbols": PAIRS,
        "stale_symbols": stale_symbols,
        "stale_count": len(stale_symbols),
    }


@app.get("/debug/cooldowns")
def debug_cooldowns():
    now = time.time()
    rows = []
    for sym, ts in sorted(SYMBOL_COOLDOWN.items()):
        left = max(0, int(COOLDOWN_SECONDS - (now - float(ts))))
        rows.append({
            "symbol": sym,
            "left_seconds": left,
            "started_at": float(ts),
            "active": left > 0,
        })
    return {
        "scope": "per_symbol",
        "cooldown_seconds": COOLDOWN_SECONDS,
        "count": len(rows),
        "rows": rows,
    }

@app.get("/debug/risk-slots")
def debug_risk_slots():
    return get_risk_slot_snapshot(force=True)


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

            order_ok = any(isinstance(r, dict) and r.get("status") == "OK" for r in (result or []))
            send_auto_entry_telegram(signal, result=result, order_ok=order_ok)

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
                tick = EXCHANGE_CACHE.get(symbol, {}).get("tickSize", 0.0)
                favorable_move = (price - entry) if side == "BUY" else (entry - price)
                if favorable_move <= 0:
                    continue

                move_pct = favorable_move / max(entry, 1e-12)
                new_sl = None

                if move_pct >= SMART_TRAIL_ACTIVE_PCT:
                    locked_move = favorable_move * SMART_TRAIL_LOCK_RATIO
                    new_sl = entry + locked_move if side == "BUY" else entry - locked_move
                elif move_pct >= SMART_TRAIL_BE_TRIGGER_PCT:
                    new_sl = entry

                if new_sl is None:
                    continue

                improves = (
                    current_sl is None
                    or (side == "BUY" and new_sl > current_sl + max(tick, 1e-12))
                    or (side == "SELL" and new_sl < current_sl - max(tick, 1e-12))
                )
                if improves:
                    update_stop_loss(symbol, side, new_sl)
            time.sleep(TRAILING_LOOP_INTERVAL)
        except Exception as e:
            print("Trailing error:", e)
            if is_rate_limit_error(e):
                time.sleep(POSITION_RATE_LIMIT_SLEEP)
            else:
                time.sleep(TRAILING_LOOP_INTERVAL)

LAST_SCAN_BY_TIER = {"TOP": 0.0, "MID": 0.0, "MID_AGGRESSIVE": 0.0}


def get_due_scan_pairs():
    now = time.time()
    due = []
    if now - LAST_SCAN_BY_TIER.get("TOP", 0.0) >= SCAN_INTERVAL_TOP:
        due.extend([p for p in TOP_PAIRS if p in PAIRS])
        LAST_SCAN_BY_TIER["TOP"] = now
    if now - LAST_SCAN_BY_TIER.get("MID", 0.0) >= SCAN_INTERVAL_MID:
        due.extend([p for p in MID_PAIRS if p in PAIRS])
        LAST_SCAN_BY_TIER["MID"] = now
    if now - LAST_SCAN_BY_TIER.get("MID_AGGRESSIVE", 0.0) >= SCAN_INTERVAL_MID_AGGRESSIVE:
        due.extend([p for p in MID_AGGRESSIVE_PAIRS if p in PAIRS])
        LAST_SCAN_BY_TIER["MID_AGGRESSIVE"] = now
    return list(dict.fromkeys(due))

def apply_news_bias(signal_type, news_reverse):
    if news_reverse:
        return "SELL" if signal_type == "BUY" else "BUY"
    return signal_type

def auto_trader():
    global candidate_list_live, selected_symbols_live, selected_rows_live, skip_reasons_live
    while True:
        try:
            check_telegram_commands()
            # Alert monitor is throttled internally; safe to call each loop.
            try:
                check_runtime_telegram_alerts()
            except Exception as alert_error:
                print("telegram alert monitor error:", alert_error)

            if KILL_SWITCH:
                set_final_execution("KILL_SWITCH_ON", reason="KILL_SWITCH_TRUE_SCAN_ONLY", stage="safety_gate", detail={"scan_only": True, "entry_blocked": True})
                print("🛑 KILL SWITCH ACTIVE → scan only, entry blocked")

            if not AUTO_MODE:
                set_final_execution("AUTO_MODE_OFF", reason="AUTO_MODE_FALSE", stage="mode_gate")
                time.sleep(SCAN_INTERVAL)
                continue

            if not AUTO_TRADING:
                set_final_execution("AUTO_TRADING_OFF", reason="AUTO_TRADING_FALSE", stage="mode_gate")
                print("⏸️ AUTO TRADING DISABLED")
                time.sleep(SCAN_INTERVAL)
                continue

            if circuit_breaker_active():
                remaining = circuit_breaker_remaining()
                detail = {"remaining": round(remaining, 2), "consecutive_errors": CONSECUTIVE_ERRORS}
                add_execution_decision("circuit_breaker", "_SYSTEM_", "BLOCK", detail)
                set_final_execution("CIRCUIT_BREAKER_PAUSED", reason=f"CIRCUIT_BREAKER_{int(remaining)}s", stage="circuit_breaker", detail=detail)
                time.sleep(min(remaining, 5) or 1)
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
                set_final_execution("BLOCKED", reason="WS_DATA_NOT_HEALTHY", stage="ws_gate", detail=ws_gate)
                print(f"⏸️ Skip trade: WS data not healthy ({ws_gate['reason']})")
                time.sleep(5)
                continue
            if not safety_check():
                set_final_execution("BLOCKED", reason="SAFETY_CHECK_FAILED", stage="safety_gate")
                time.sleep(10)
                continue
            if daily_loss >= MAX_DAILY_LOSS:
                set_final_execution("BLOCKED", reason="DAILY_LOSS_LIMIT", stage="risk_gate", detail={"daily_loss": daily_loss, "max_daily_loss": MAX_DAILY_LOSS})
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

            # === MONTRA: NEWS_GATE_HOOK_AUTOTRADER START ===
            news_engine_global = get_institutional_news_state(symbol="_SYSTEM_")
            if news_engine_global.get("block_decision") and news_engine_global.get("scope") == "GLOBAL_CRYPTO":
                ev = news_engine_global.get("active_event") or {}
                ev_title = ev.get("title", "UNKNOWN_EVENT")
                ev_phase = news_engine_global.get("phase", "UNKNOWN")
                ev_tier = news_engine_global.get("tier", "UNKNOWN")
                detail = {
                    "tier": ev_tier,
                    "phase": ev_phase,
                    "title": ev_title,
                    "minutes_to_event": news_engine_global.get("minutes_to_event"),
                    "minutes_since_event": news_engine_global.get("minutes_since_event"),
                    "scope": news_engine_global.get("scope"),
                    "source": news_engine_global.get("source"),
                }
                set_final_execution(
                    "BLOCKED",
                    reason=f"NEWS_TIER1_BLOCK_{ev_phase}",
                    stage="news_gate",
                    detail=detail,
                )
                print(f"📰 INSTITUTIONAL NEWS BLOCK tier={ev_tier} phase={ev_phase} title={ev_title[:60]}")
                if NEWS_TIER1_TELEGRAM_ALERT and ev_phase == "PRE" and ev_tier == "TIER_1_RED":
                    try:
                        alert_key = f"news_pre_{ev.get('id', ev_title)[:64]}"
                        alert_msg = (
                            f"📰 NEWS PRE WINDOW\n"
                            f"Event: {ev_title}\n"
                            f"Tier: {ev_tier}\n"
                            f"T-{news_engine_global.get('minutes_to_event')}m\n"
                            f"Source: {news_engine_global.get('source')}"
                        )
                        send_telegram_alert(alert_key, alert_msg)
                    except Exception as alert_exc:
                        print("news telegram alert error:", alert_exc)
                time.sleep(min(SCAN_INTERVAL, 30))
                continue
            # === MONTRA: NEWS_GATE_HOOK_AUTOTRADER END ===

            # === NEWS FILTER ===
            news_impact = get_market_news()
            print(f"📰 NEWS IMPACT: {news_impact}")

            # === NEWS STATE ===
            news_reverse = (news_impact == "HIGH" and not VALIDATION_MODE and LIVE_NEWS_REVERSE and not active_news_block())

            if news_impact == "HIGH":
                if active_news_block():
                    set_final_execution("BLOCKED", reason="HIGH_IMPACT_NEWS", stage="news_gate", detail={"news_impact": news_impact})
                    print("📰 HIGH IMPACT NEWS → BLOCK")
                    time.sleep(SCAN_INTERVAL)
                    continue
                elif news_reverse:
                    print("📰 HIGH IMPACT NEWS → reverse enabled")
                else:
                    print("📰 HIGH IMPACT NEWS → score penalty only")

            if vol < active_vol_min():
                set_final_execution("IDLE", reason="LOW_VOLATILITY", stage="market_gate", detail={"vol": round(vol, 6), "min_vol": active_vol_min()})
                print(f"⏸️ Skip: low volatility ({vol:.4f})")
                time.sleep(SCAN_INTERVAL)
                continue

            if vol > active_vol_max():
                set_final_execution("IDLE", reason="HIGH_VOLATILITY", stage="market_gate", detail={"vol": round(vol, 6), "max_vol": active_vol_max()})
                print(f"⚠️ Skip: high volatility ({vol:.4f})")
                time.sleep(SCAN_INTERVAL)
                continue

            session = get_session_utc()
            if not session_allowed(session):
                set_final_execution("IDLE", reason="OFF_SESSION", stage="session_gate", detail={"session": session})
                print(f"⏸️ Skip: off session ({session})")
                time.sleep(SCAN_INTERVAL)
                continue

            candidate_list_live = []
            selected_symbols_live = []
            selected_rows_live = []
            skip_reasons_live = []

            pairs = get_due_scan_pairs()
            if not pairs:
                set_final_execution("IDLE", reason="WAITING_FOR_TIER_SCAN_INTERVAL", stage="scan_scheduler", detail={
                    "scan_interval_top": SCAN_INTERVAL_TOP,
                    "scan_interval_mid": SCAN_INTERVAL_MID,
            "scan_interval_mid_aggressive": SCAN_INTERVAL_MID_AGGRESSIVE,
                    "last_top_scan_age": round(time.time() - LAST_SCAN_BY_TIER.get("TOP", 0.0), 2) if LAST_SCAN_BY_TIER.get("TOP") else None,
                    "last_mid_scan_age": round(time.time() - LAST_SCAN_BY_TIER.get("MID", 0.0), 2) if LAST_SCAN_BY_TIER.get("MID") else None,
                })
                time.sleep(1)
                continue

            mark_scan_cycle("SCANNING", "SCAN_CYCLE_STARTED", pairs=pairs, detail={"pairs": pairs})

            scores_map = {}
            candidate_map = {tier_name: [] for tier_name in tier_limits().keys()}

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
                    
                    last_price, price_source = get_live_or_fallback_price(symbol, ohlcv[-1])
                    if last_price <= 0:
                        add_skip_reason(symbol, "PRICE_UNAVAILABLE")
                        continue

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

                    # === LIQUIDITY SWEEP CHECK WITH MEMORY ===
                    sweep_ctx = detect_sweep_memory(ohlcv)
                    sweep_high = bool(sweep_ctx.get("sweep_high"))
                    sweep_low = bool(sweep_ctx.get("sweep_low"))

                    if active_require_sweep():
                        if signal_type == "BUY" and not sweep_low:
                            add_skip_reason(symbol, "NO_SWEEP_LOW", {"sweep_memory": sweep_ctx})
                            continue
                        if signal_type == "SELL" and not sweep_high:
                            add_skip_reason(symbol, "NO_SWEEP_HIGH", {"sweep_memory": sweep_ctx})
                            continue

                    # === BUY RUMOR / SELL NEWS ===
                    # [!] LOGIC FIX: Posisi dipindah ke sini agar SL dan TP dihitung dengan arah yang sudah di-reverse
                    # news impact dipakai lewat apply_news_bias() saja

                    # === ENTRY, SL, TP ===
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
                    trade_plan = build_precision_trade_plan(symbol, final_side, last_price, ohlcv, structure, rr_target=rr_target)
                    if not trade_plan.get("ok"):
                        add_skip_reason(symbol, trade_plan.get("reason", "INVALID_TRADE_PLAN"), trade_plan)
                        continue

                    sl = float(trade_plan["sl"])
                    tp = float(trade_plan["tp"])
                    rr = float(trade_plan["rr"])
                    if rr < active_rr_min():
                        add_skip_reason(symbol, "LOW_RR", {
                            "rr": round(rr, 2),
                            "min_rr": active_rr_min(),
                            "trade_plan": trade_plan,
                        })
                        continue

                    fng_ctx = get_fng_context()
                    pre_score = composite_pre_score(
                        symbol, final_side, last_price, sl, tp, structure, pair_regime, vol,
                        sweep_high=sweep_high, sweep_low=sweep_low, fng_ctx=fng_ctx
                    )
                    signal = apply_clean_prices_to_signal({
                        "symbol": symbol,
                        "type": final_side,
                        "entry": last_price,
                        "sl": sl,
                        "tp": tp,
                        "score": pre_score,
                        "sweep_high": sweep_high,
                        "sweep_low": sweep_low,
                        "sweep_memory": sweep_ctx,
                        "structure_grade": structure_grade,
                        "pre_score": pre_score,
                        "fng_value": fng_ctx.get("value"),
                        "fng_classification": fng_ctx.get("classification"),
                        "fng_bias": get_fng_score_bias(final_side, fng_ctx),
                        "sl_source": (trade_plan.get("ob") or {}).get("source"),
                        "sl_buffer": round(float(trade_plan.get("sl_buffer", 0.0)), 8),
                        "atr": round(float(trade_plan.get("atr", 0.0)), 8),
                        "tp_source": trade_plan.get("tp_source"),
                    })
                    last_price = float(signal.get("entry", last_price))
                    sl = float(signal.get("sl", sl))
                    tp = float(signal.get("tp", tp))
                    rr = abs(tp - last_price) / max(abs(last_price - sl), 1e-9)

                    meta = meta_score(symbol, signal, regime, vol)

                    ml_prob = ml_predict(build_ml_features(
                        symbol, final_side, regime, vol, news_reverse, fvg_up, fvg_down, sweep_high, sweep_low
                    ))
                    score = round((pre_score * PRE_SCORE_WEIGHT) + (meta * META_SCORE_WEIGHT) + (ml_prob * 100 * ML_SCORE_WEIGHT))
                    score += structure_score_adjustment(structure)

                    # === SMC BOOST ===
                    if fvg_up or fvg_down:
                        score += 3
                    if sweep_high or sweep_low:
                        score += 3
                    if structure.get("reclaim_up") or structure.get("reclaim_down"):
                        score += 2

                    # FNG sudah masuk pre-score sebagai bias arah, bukan blocker.
                    if news_impact == "NORMAL":
                        score += 4 if VALIDATION_MODE else 5

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
                        "entry": float(signal.get("entry", last_price)),
                        "sl": float(signal.get("sl", sl)),
                        "tp": float(signal.get("tp", tp)),
                        "entry_text": signal.get("entry_text"),
                        "sl_text": signal.get("sl_text"),
                        "tp_text": signal.get("tp_text"),
                        "rr": round(rr, 2),
                        "pair_regime": pair_regime,
                        "regime": pair_regime,
                        "news_impact": news_impact,
                        "session": session,
                        "structure_grade": structure_grade,
                        "pre_score": pre_score,
                        "fng_value": fng_ctx.get("value"),
                        "fng_classification": fng_ctx.get("classification"),
                        "fng_bias": get_fng_score_bias(final_side, fng_ctx),
                        "sl_source": (trade_plan.get("ob") or {}).get("source"),
                        "sl_buffer": round(float(trade_plan.get("sl_buffer", 0.0)), 8),
                        "atr": round(float(trade_plan.get("atr", 0.0)), 8),
                        "tp_source": trade_plan.get("tp_source"),
                    }

                    row = clean_signal_row_for_output(row)
                    candidate_map.setdefault(tier, []).append(row)
                    candidate_list_live.append(row)
                    
                    if VALIDATION_MODE:
                        print(f"🧪 CANDIDATE {symbol} tier={get_pair_tier(symbol)} side={final_side} score={score} rr={rr:.2f} regime={pair_regime} news={news_impact} session={session} vol={vol:.4f}")

                except Exception as e:
                    print(f"Scoring error {symbol}: {e}")

            try:
                maybe_send_candidate_alerts(candidate_list_live)
            except Exception as candidate_alert_error:
                print("candidate telegram alert error:", candidate_alert_error)

            if not candidate_list_live:
                set_idle_after_scan("NO_CANDIDATE_AFTER_SCAN", pairs=pairs, detail={
                    "skip_summary": summarize_skip_reasons(skip_reasons_live),
                })

            # --- Eksekusi trade dengan decision engine ---
            selected_symbols = set()
            candidate_symbols = set()
            candidate_rank_map = {}
            selected_row_map = {}

            for tier_name, limit in tier_limits().items():
                rows = sorted(candidate_map.get(tier_name, []), key=lambda x: x["score"], reverse=True)
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

            if candidate_list_live and not selected_rows_live:
                set_idle_after_scan("NO_SELECTED_AFTER_TIER_LIMITS", pairs=pairs, detail={
                    "candidate_count": len(candidate_list_live),
                    "tier_limits": tier_limits(),
                })
            elif selected_rows_live:
                set_final_execution("CANDIDATE_WAITING", symbol=selected_rows_live[0].get("symbol"), side=selected_rows_live[0].get("type"), reason="SELECTED_FOR_EXECUTION_CHECKS", stage="shortlist", detail={
                    "selected_count": len(selected_rows_live),
                    "top_selected": selected_rows_live[0],
                })

            if VALIDATION_MODE:
                print("🎯 SELECTED SYMBOLS:", selected_symbols_live)

            for row in selected_rows_live:
                sym = row["symbol"]
                add_execution_decision("shortlist", sym, "PASS", {
                    "weight": round(float(portfolio_alloc.get(sym, 0.0)), 6),
                    "tier": get_pair_tier(sym),
                })
            
            order_attempted_this_cycle = False

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
                    
                    last_price, price_source = get_live_or_fallback_price(symbol, ohlcv[-1])
                    if last_price <= 0:
                        add_skip_reason(symbol, "PRICE_UNAVAILABLE")
                        continue

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

                    # === LIQUIDITY SWEEP CHECK WITH MEMORY ===
                    sweep_ctx = detect_sweep_memory(ohlcv)
                    sweep_high = bool(sweep_ctx.get("sweep_high"))
                    sweep_low = bool(sweep_ctx.get("sweep_low"))

                    if active_require_sweep():
                        if signal_type == "BUY" and not sweep_low:
                            add_skip_reason(symbol, "NO_SWEEP_LOW", {"sweep_memory": sweep_ctx})
                            continue
                        if signal_type == "SELL" and not sweep_high:
                            add_skip_reason(symbol, "NO_SWEEP_HIGH", {"sweep_memory": sweep_ctx})
                            continue

                    # === BUY RUMOR / SELL NEWS ===
                    # [!] LOGIC FIX: Posisi dipindah ke sini agar SL dan TP dihitung dengan arah yang sudah di-reverse
                    # news impact dipakai lewat apply_news_bias() saja, jangan reversal dua kali

                    # === ENTRY, SL, TP ===
                    final_side = apply_news_bias(signal_type, news_reverse)

                    pair_regime = get_multi_tf_regime(symbol)

                    if active_require_pair_regime_match():
                        if pair_regime == "SIDEWAYS":
                            add_skip_reason(symbol, "PAIR_REGIME_SIDEWAYS_EXEC")
                            continue
                        if pair_regime == "BULL" and final_side != "BUY":
                            add_skip_reason(symbol, "PAIR_REGIME_BULL_MISMATCH_EXEC")
                            continue
                        if pair_regime == "BEAR" and final_side != "SELL":
                            add_skip_reason(symbol, "PAIR_REGIME_BEAR_MISMATCH_EXEC")
                            continue

                    rr_target = active_target_rr()
                    trade_plan = build_precision_trade_plan(symbol, final_side, last_price, ohlcv, structure, rr_target=rr_target)
                    if not trade_plan.get("ok"):
                        add_skip_reason(symbol, trade_plan.get("reason", "INVALID_TRADE_PLAN_EXEC"), trade_plan)
                        continue

                    sl = float(trade_plan["sl"])
                    tp = float(trade_plan["tp"])
                    rr = float(trade_plan["rr"])
                    if rr < active_rr_min():
                        add_skip_reason(symbol, "LOW_RR_EXEC", {"rr": round(rr, 2), "min_rr": active_rr_min(), "trade_plan": trade_plan})
                        continue

                    fng_ctx = get_fng_context()
                    pre_score = composite_pre_score(
                        symbol, final_side, last_price, sl, tp, structure, pair_regime, vol,
                        sweep_high=sweep_high, sweep_low=sweep_low, fng_ctx=fng_ctx
                    )
                    signal = apply_clean_prices_to_signal({
                        "symbol": symbol,
                        "type": final_side,
                        "entry": last_price,
                        "sl": sl,
                        "tp": tp,
                        "score": scores_map.get(symbol, 0),
                        "pair_regime": pair_regime,
                        "sweep_high": sweep_high,
                        "sweep_low": sweep_low,
                        "sweep_memory": sweep_ctx,
                        "rr": round(rr, 2),
                        "structure_grade": structure_grade,
                        "pre_score": pre_score,
                        "fng_value": fng_ctx.get("value"),
                        "fng_classification": fng_ctx.get("classification"),
                        "fng_bias": get_fng_score_bias(final_side, fng_ctx),
                        "sl_source": (trade_plan.get("ob") or {}).get("source"),
                        "sl_buffer": round(float(trade_plan.get("sl_buffer", 0.0)), 8),
                        "atr": round(float(trade_plan.get("atr", 0.0)), 8),
                        "tp_source": trade_plan.get("tp_source"),
                    })
                    last_price = float(signal.get("entry", last_price))
                    sl = float(signal.get("sl", sl))
                    tp = float(signal.get("tp", tp))
                    rr = abs(tp - last_price) / max(abs(last_price - sl), 1e-9)

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

                    score = max(0, min(100, float(scores_map.get(symbol, signal.get("score", 0)))))
                    signal["score"] = score
                    
                    ok, reason = should_execute_trade(signal)
                    add_execution_decision("should_execute_trade", symbol, "PASS" if ok else "BLOCK", {
                        "reason": reason,
                        "score": round(float(signal["score"]), 2),
                        "rr": round(rr, 2),
                        "weight": round(float(w), 6),
                        "quality": signal.get("execution_quality"),
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

                    slot_ok, slot_reason, slot_detail = can_open_new_trade(symbol, force=True)
                    if not slot_ok:
                        add_skip_reason(symbol, slot_reason, slot_detail)
                        add_execution_decision("risk_slot_gate", symbol, "BLOCK", slot_detail)
                        print(f"❌ SKIP {symbol} - {slot_reason} slots={slot_detail.get('used_slots')}/{slot_detail.get('max_open_trades')}")
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
                        "sweep_memory": sweep_ctx,
                    })

                    order_attempted_this_cycle = True
                    add_execution_decision("order_attempt", symbol, "PASS", {
                        "side": signal["type"],
                        "score": round(float(signal["score"]), 2),
                        "weight": round(float(w), 6),
                        "entry": round(float(signal["entry"]), 8),
                        "sl": round(float(signal["sl"]), 8),
                        "tp": round(float(signal["tp"]), 8),
                        "quality": signal.get("execution_quality"),
                    })
                    set_final_execution("ORDER_ATTEMPT", symbol=symbol, side=signal["type"], reason="SENDING_ORDER", stage="order_attempt", detail={
                        "score": round(float(signal["score"]), 2),
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

                    order_ok = any(isinstance(r, dict) and r.get("status") == "OK" for r in (result or []))
                    add_execution_decision("order_result", symbol, "PASS" if order_ok else "BLOCK", {
                        "result": result,
                    })
                    set_final_execution("ORDER_OK_PROTECTED" if order_ok else "ORDER_FAILED", symbol=symbol, side=signal["type"], reason="ORDER_RESULT_PASS" if order_ok else "ORDER_RESULT_BLOCK", stage="order_result", detail={"result": result})
                    
                    GLOBAL_SYMBOL_LOCK.add(symbol)

                    position_entry_score[symbol] = signal["score"]

                    send_auto_entry_telegram(signal, result=result, weight=w, order_ok=order_ok)
                    print("AUTO EXEC:", result)

                    # [FIX 2] Scale-in otomatis dinonaktifkan. 
                    # Scale-in tanpa gate posisi berisiko double-drawdown.
                    pass

                except Exception as e:
                    print("Pair error:", symbol, e)

            if selected_rows_live and not order_attempted_this_cycle and LAST_FINAL_EXECUTION.get("status") == "CANDIDATE_WAITING":
                set_final_execution("BLOCKED", symbol=selected_rows_live[0].get("symbol"), side=selected_rows_live[0].get("type"), reason="SELECTED_BLOCKED_AFTER_EXEC_CHECKS", stage="scan_cycle_done", detail={
                    "selected_count": len(selected_rows_live),
                    "recent_decisions": EXECUTION_DECISIONS[-5:],
                    "skip_summary": summarize_skip_reasons(skip_reasons_live),
                })
            elif not selected_rows_live and candidate_list_live:
                set_idle_after_scan("NO_SELECTED_AFTER_TIER_LIMITS", pairs=pairs, detail={"candidate_count": len(candidate_list_live)})

        except Exception as e:
            set_final_execution("ERROR", reason="AUTO_LOOP_ERROR", stage="auto_loop", detail={"error": str(e)})
            print("AUTO LOOP ERROR:", e)

        try:
            check_runtime_telegram_alerts()
        except Exception as alert_error:
            print("telegram alert monitor error:", alert_error)

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
        set_final_execution("API_ONLY", reason="MONTRA_MODE_API_ONLY", stage="startup")
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
        set_final_execution("AUTO_MODE_OFF", reason="AUTO_MODE_FALSE", stage="startup")
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

    # === MONTRA: NEWS_ENGINE_BACKGROUND_REFRESH START ===
    if NEWS_ENGINE_ENABLED:
        def _news_refresh_loop():
            while True:
                try:
                    refresh_institutional_news_cache()
                except Exception as exc:
                    print("news refresh loop error:", exc)
                time.sleep(NEWS_REFRESH_INTERVAL)
        threading.Thread(target=_news_refresh_loop, daemon=True).start()
        print("📰 News engine refresh thread started")
    # === MONTRA: NEWS_ENGINE_BACKGROUND_REFRESH END ===

@app.on_event("startup")
def on_startup():
    start_background_tasks()