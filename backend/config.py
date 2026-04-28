import os

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FIREBASE_URL = os.getenv("FIREBASE_URL")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", 5))  # USD
MAX_CONSECUTIVE_LOSS = int(os.getenv("MAX_CONSECUTIVE_LOSS", 3))
BASE_RISK = float(os.getenv("BASE_RISK", 1))  # % per trade
MIN_RISK = 0.3
MAX_RISK = 2

# =========================
# MONTRA PAIR UNIVERSE V5.3 — 3 active groups
# =========================
TOP_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
]

MID_PAIRS = [
    "LINKUSDT", "AVAXUSDT", "NEARUSDT", "ARBUSDT", "AAVEUSDT",
    "ADAUSDT", "LTCUSDT", "TRXUSDT", "TONUSDT", "WLDUSDT",
]

MID_AGGRESSIVE_PAIRS = [
    "HYPEUSDT", "SUIUSDT", "WIFUSDT", "1000PEPEUSDT",
]

VALIDATION_ONLY = [
    "TAOUSDT", "ETCUSDT", "FILUSDT", "QNTUSDT", "XMRUSDT", "ZECUSDT",
    "BCHUSDT", "XLMUSDT", "ATOMUSDT",
]

REMOVE_FROM_CORE = [
    "BCHUSDT", "XLMUSDT", "ATOMUSDT",
    "XAUUSDT", "XAGUSDT", "DASHUSDT", "ZENUSDT", "ENJUSDT", "MANAUSDT",
]

INCLUDE_VALIDATION_ONLY = os.getenv("MONTRA_INCLUDE_VALIDATION_ONLY", "false").lower() == "true"
PAIRS = TOP_PAIRS + MID_PAIRS + MID_AGGRESSIVE_PAIRS
if INCLUDE_VALIDATION_ONLY:
    PAIRS += VALIDATION_ONLY
PAIRS = [p for p in list(dict.fromkeys(PAIRS)) if p not in REMOVE_FROM_CORE]

MONTRA_MODE = os.getenv("MONTRA_MODE", "api_only")
AUTO_MODE = os.getenv("AUTO_MODE", "false").lower() == "true"
AUTO_TRADING = os.getenv("AUTO_TRADING", "false").lower() == "true"
MONTRA_PROFILE = os.getenv("MONTRA_PROFILE", "final_lock")
STATE_FILE = os.getenv("STATE_FILE", "runtime_state.json")

BINANCE_FSTREAM_WS_URL = os.getenv("BINANCE_FSTREAM_WS_URL", "wss://fstream.binance.com/market/stream")

# Request pacing / retry guard. Aliases supported for user-friendly env names.
BINANCE_RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))
BINANCE_TIME_SYNC_INTERVAL = int(os.getenv("BINANCE_TIME_SYNC_INTERVAL", "900"))
BINANCE_MAX_TIME_RETRIES = int(os.getenv("BINANCE_MAX_TIME_RETRIES", os.getenv("MAX_TIME_RETRIES", "3")))
BINANCE_RATE_LIMIT_RETRIES = int(os.getenv("BINANCE_RATE_LIMIT_RETRIES", os.getenv("RATE_LIMIT_RETRIES", "3")))
SIGNED_CALL_MIN_INTERVAL = float(os.getenv("SIGNED_CALL_MIN_INTERVAL", "0.15"))

# Circuit breaker / REST fallback safety.
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", os.getenv("MAX_CONSECUTIVE_ERRORS", "10")))
CIRCUIT_BREAKER_PAUSE = float(os.getenv("CIRCUIT_BREAKER_PAUSE", "60"))
WS_FALLBACK_POLL_INTERVAL = float(os.getenv("WS_FALLBACK_POLL_INTERVAL", "5"))

# Execution quality gate.
MIN_STOP_DISTANCE_PCT = float(os.getenv("MIN_STOP_DISTANCE_PCT", "0.0025"))
MIN_TP_DISTANCE_PCT = float(os.getenv("MIN_TP_DISTANCE_PCT", "0.0050"))
FEE_BUFFER_RR = float(os.getenv("FEE_BUFFER_RR", "0.15"))
STRICT_PROTECTION = os.getenv("STRICT_PROTECTION", "true").lower() == "true"
PROTECTION_ORDER_MODE = (os.getenv("PROTECTION_ORDER_MODE", "CLOSE_POSITION") or "CLOSE_POSITION").strip().upper()
PROTECTION_ACCEPT_ALGO_ID = os.getenv("PROTECTION_ACCEPT_ALGO_ID", "true").lower() == "true"
PROTECTION_VERIFY_CONDITIONAL_ORDERS = os.getenv("PROTECTION_VERIFY_CONDITIONAL_ORDERS", "true").lower() == "true"
PROTECTION_VERIFY_PLACEMENT_FALLBACK = os.getenv("PROTECTION_VERIFY_PLACEMENT_FALLBACK", "true").lower() == "true"
PROTECTION_RECENT_PLACEMENT_TTL = float(os.getenv("PROTECTION_RECENT_PLACEMENT_TTL", "90"))
PROTECTION_ENTRY_CONFIRM_RETRIES = int(os.getenv("PROTECTION_ENTRY_CONFIRM_RETRIES", "6"))
PROTECTION_ENTRY_CONFIRM_DELAY = float(os.getenv("PROTECTION_ENTRY_CONFIRM_DELAY", "0.50"))
EMERGENCY_CLOSE_VERIFY_RETRIES = int(os.getenv("EMERGENCY_CLOSE_VERIFY_RETRIES", "6"))
EMERGENCY_CLOSE_VERIFY_DELAY = float(os.getenv("EMERGENCY_CLOSE_VERIFY_DELAY", "0.50"))
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "M")

# Price precision guard. Per-pair override format: PRICE_TICK_SIZE_SUIUSDT=0.0001
PRICE_PRECISION_USE_PRICE_PRECISION = os.getenv("PRICE_PRECISION_USE_PRICE_PRECISION", "true").lower() == "true"
PRICE_PRECISION_FAIL_ON_MISSING = os.getenv("PRICE_PRECISION_FAIL_ON_MISSING", "true").lower() == "true"

# Dynamic spread gate. Per-pair override format: SPREAD_THRESHOLD_BTCUSDT=0.0006
SPREAD_THRESHOLD_TOP = float(os.getenv("SPREAD_THRESHOLD_TOP", "0.0008"))
SPREAD_THRESHOLD_MID = float(os.getenv("SPREAD_THRESHOLD_MID", "0.0012"))
SPREAD_THRESHOLD_MID_AGGRESSIVE = float(os.getenv("SPREAD_THRESHOLD_MID_AGGRESSIVE", "0.0015"))
SPREAD_WARN_MULTIPLIER = float(os.getenv("SPREAD_WARN_MULTIPLIER", "0.8"))
SPREAD_CACHE_TTL = float(os.getenv("SPREAD_CACHE_TTL", "5"))
SPREAD_ORDER_BOOK_LIMIT = int(os.getenv("SPREAD_ORDER_BOOK_LIMIT", "5"))

# Live gate defaults.
LIVE_RR_MIN = float(os.getenv("LIVE_RR_MIN", "2.5"))
LIVE_TARGET_RR = float(os.getenv("LIVE_TARGET_RR", "3.5"))
LIVE_VOL_MIN = float(os.getenv("LIVE_VOL_MIN", "0.0015"))
LIVE_VOL_MAX = float(os.getenv("LIVE_VOL_MAX", "0.03"))
LIVE_REQUIRE_SWEEP = os.getenv("LIVE_REQUIRE_SWEEP", "true").lower() == "true"
LIVE_REQUIRE_PAIR_REGIME_MATCH = os.getenv("LIVE_REQUIRE_PAIR_REGIME_MATCH", "true").lower() == "true"
LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY = os.getenv("LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY", "false").lower() == "true"

# Backend pacing / cache.
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))
SCAN_INTERVAL_TOP = int(os.getenv("SCAN_INTERVAL_TOP", "30"))
SCAN_INTERVAL_MID = int(os.getenv("SCAN_INTERVAL_MID", "45"))
SCAN_INTERVAL_MID_AGGRESSIVE = int(os.getenv("SCAN_INTERVAL_MID_AGGRESSIVE", os.getenv("SCAN_INTERVAL_MID", "45")))
POSITION_CACHE_TTL = float(os.getenv("POSITION_CACHE_TTL", "30"))
# Atomic risk-slot gate for MAX_OPEN_TRADES. Keep MAX_OPEN_TRADES=2 if desired;
# this guard prevents fast sequential entries from outrunning Binance position propagation.
ENTRY_SLOT_TTL_SECONDS = float(os.getenv("ENTRY_SLOT_TTL_SECONDS", "180"))
MAX_OPEN_TRADES_FORCE_REFRESH = os.getenv("MAX_OPEN_TRADES_FORCE_REFRESH", "true").lower() == "true"
POSITION_MONITOR_INTERVAL = float(os.getenv("POSITION_MONITOR_INTERVAL", "45"))
TRAILING_LOOP_INTERVAL = float(os.getenv("TRAILING_LOOP_INTERVAL", "30"))
MARKET_KLINES_CACHE_TTL_15M = float(os.getenv("MARKET_KLINES_CACHE_TTL_15M", "60"))
MARKET_KLINES_CACHE_TTL_1H = float(os.getenv("MARKET_KLINES_CACHE_TTL_1H", "180"))
MARKET_KLINES_CACHE_TTL_4H = float(os.getenv("MARKET_KLINES_CACHE_TTL_4H", "600"))

# Websocket health gate.
WS_MAX_AGE = int(os.getenv("WS_MAX_AGE", "20"))
WS_STALE_THRESHOLD = int(os.getenv("WS_STALE_THRESHOLD", "5"))
WS_RESTART_COOLDOWN = int(os.getenv("WS_RESTART_COOLDOWN", "300"))
WS_DEGRADED_MODE_ALLOW = os.getenv("WS_DEGRADED_MODE_ALLOW", "true").lower() == "true"
WS_DEGRADED_GRACE_SECONDS = float(os.getenv("WS_DEGRADED_GRACE_SECONDS", "15"))
WS_FULL_STALE_BLOCK_SECONDS = float(os.getenv("WS_FULL_STALE_BLOCK_SECONDS", "600"))

# Sweep memory: keep a confirmed reclaim sweep valid for a few candles.
SWEEP_LOOKBACK = int(os.getenv("SWEEP_LOOKBACK", "10"))
SWEEP_MEMORY_WINDOW = int(os.getenv("SWEEP_MEMORY_WINDOW", "5"))
SWEEP_REQUIRE_RECLAIM = os.getenv("SWEEP_REQUIRE_RECLAIM", "true").lower() == "true"

# Telegram runtime alerting.
TELEGRAM_ALERTS_ENABLED = os.getenv("TELEGRAM_ALERTS_ENABLED", "true").lower() == "true"
TELEGRAM_ALERT_COOLDOWN_SECONDS = float(os.getenv("TELEGRAM_ALERT_COOLDOWN_SECONDS", "300"))
TELEGRAM_BLOCKED_ALERT_MINUTES = float(os.getenv("TELEGRAM_BLOCKED_ALERT_MINUTES", "5"))
TELEGRAM_SCAN_STALE_ALERT_SECONDS = float(os.getenv("TELEGRAM_SCAN_STALE_ALERT_SECONDS", "90"))
TELEGRAM_WS_BLOCK_ALERT_SECONDS = float(os.getenv("TELEGRAM_WS_BLOCK_ALERT_SECONDS", "60"))
TELEGRAM_UNPROTECTED_ALERT_SECONDS = float(os.getenv("TELEGRAM_UNPROTECTED_ALERT_SECONDS", "45"))
TELEGRAM_WS_STARTUP_GRACE_SECONDS = float(os.getenv("TELEGRAM_WS_STARTUP_GRACE_SECONDS", "120"))
TELEGRAM_REQUIRE_WS_BLOCK = os.getenv("TELEGRAM_REQUIRE_WS_BLOCK", "true").lower() == "true"
TELEGRAM_SEND_RECOVERY_ALERT = os.getenv("TELEGRAM_SEND_RECOVERY_ALERT", "true").lower() == "true"
TELEGRAM_ALERT_CURRENT_ONLY = os.getenv("TELEGRAM_ALERT_CURRENT_ONLY", "true").lower() == "true"
TELEGRAM_CLEAR_RESOLVED_KEYS = os.getenv("TELEGRAM_CLEAR_RESOLVED_KEYS", "true").lower() == "true"

# Controlled limit entry to avoid bad fills/slippage. SL/TP and emergency close stay market/conditional.
ENTRY_ORDER_TYPE = (os.getenv("ENTRY_ORDER_TYPE", "LIMIT") or "LIMIT").strip().upper()
ENTRY_LIMIT_TTL_SECONDS = float(os.getenv("ENTRY_LIMIT_TTL_SECONDS", "15"))
ENTRY_LIMIT_POLL_INTERVAL = float(os.getenv("ENTRY_LIMIT_POLL_INTERVAL", "0.50"))
ENTRY_LIMIT_MAX_REPRICE = int(os.getenv("ENTRY_LIMIT_MAX_REPRICE", "2"))
ENTRY_MARKET_FALLBACK = os.getenv("ENTRY_MARKET_FALLBACK", "false").lower() == "true"
ENTRY_LIMIT_OFFSET_TOP = float(os.getenv("ENTRY_LIMIT_OFFSET_TOP", "0.0001"))
ENTRY_LIMIT_OFFSET_MID = float(os.getenv("ENTRY_LIMIT_OFFSET_MID", "0.0002"))
ENTRY_LIMIT_OFFSET_MID_AGGRESSIVE = float(os.getenv("ENTRY_LIMIT_OFFSET_MID_AGGRESSIVE", "0.0004"))
ENTRY_LIMIT_OFFSET_DEFAULT = float(os.getenv("ENTRY_LIMIT_OFFSET_DEFAULT", "0.0004"))
ENTRY_LIMIT_TIME_IN_FORCE = (os.getenv("ENTRY_LIMIT_TIME_IN_FORCE", "GTC") or "GTC").strip().upper()


# Group leverage defaults. Applied at execution time only, with per-symbol cache.
ENABLE_AUTO_LEVERAGE = os.getenv("ENABLE_AUTO_LEVERAGE", "true").lower() == "true"
TOP_LEVERAGE = int(os.getenv("TOP_LEVERAGE", "20"))
MID_LEVERAGE = int(os.getenv("MID_LEVERAGE", "10"))
MID_AGGRESSIVE_LEVERAGE = int(os.getenv("MID_AGGRESSIVE_LEVERAGE", "5"))

# v5.3 grouping controls
MID_AGGRESSIVE_PAIR_LIMIT = int(os.getenv("MID_AGGRESSIVE_PAIR_LIMIT", os.getenv("MID_PAIR_LIMIT", "1")))
USE_DEFAULT_MIN_NOTIONAL_FOR_ALL = os.getenv("USE_DEFAULT_MIN_NOTIONAL_FOR_ALL", "true").lower() == "true"

# Close source audit diagnostics. Adds close_source, close trades, and matching order info
# when a position disappears from the exchange.
CLOSE_AUDIT_ENABLED = os.getenv("CLOSE_AUDIT_ENABLED", "true").lower() == "true"
CLOSE_AUDIT_LOOKBACK_MINUTES = int(os.getenv("CLOSE_AUDIT_LOOKBACK_MINUTES", "60"))
CLOSE_AUDIT_FETCH_ORDERS = os.getenv("CLOSE_AUDIT_FETCH_ORDERS", "true").lower() == "true"
CLOSE_AUDIT_TRADE_LIMIT = int(os.getenv("CLOSE_AUDIT_TRADE_LIMIT", "80"))
CLOSE_AUDIT_ORDER_LIMIT = int(os.getenv("CLOSE_AUDIT_ORDER_LIMIT", "80"))
