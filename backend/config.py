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
# MONTRA PAIR UNIVERSE V4
# =========================
TOP_PAIRS = [
    "BTCUSDT",    # King liquidity
    "ETHUSDT",    # ETH dominance play
    "SOLUSDT",    # Best intraday volatility
    "BNBUSDT",    # Tight spread, reliable
    "XRPUSDT",    # High volume momentum
    "DOGEUSDT",   # Volume besar, meski sentiment-driven
]

MID_PAIRS = [
    "HYPEUSDT",      # Breakout behavior terbaik di mid
    "SUIUSDT",       # Aktif sesi Asia
    "LINKUSDT",      # DeFi blue chip, sweep clean
    "AVAXUSDT",      # Solid intraday
    "WIFUSDT",       # Meme volume justified
    "NEARUSDT",      # L1 momentum clean
    "ARBUSDT",       # L2 structure reliable
    "AAVEUSDT",      # FVG behavior konsisten
    "1000PEPEUSDT",  # Volume ada, wajib vol filter ketat
    "ADAUSDT",       # Bersyarat — pantau, drop jika sideways
    "LTCUSDT",       # Bersyarat — legacy, drop jika volume turun
    "TRXUSDT",       # Turun dari TOP, monitor di MID dulu
    "TONUSDT",       # Bersyarat — block jika off-hours volume tipis
    "WLDUSDT",       # Opsional swap bila TRX/TON underperform
]

VALIDATION_ONLY = [
    "TAOUSDT", "ETCUSDT", "FILUSDT", "QNTUSDT", "XMRUSDT", "ZECUSDT"
]

REMOVE_FROM_CORE = [
    "BCHUSDT", "XLMUSDT", "ATOMUSDT",
    "XAUUSDT", "XAGUSDT", "DASHUSDT", "ZENUSDT", "ENJUSDT", "MANAUSDT"
]

INCLUDE_VALIDATION_ONLY = os.getenv("MONTRA_INCLUDE_VALIDATION_ONLY", "false").lower() == "true"
PAIRS = TOP_PAIRS + MID_PAIRS
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
MIN_STOP_DISTANCE_PCT = float(os.getenv("MIN_STOP_DISTANCE_PCT", "0.0015"))
MIN_TP_DISTANCE_PCT = float(os.getenv("MIN_TP_DISTANCE_PCT", "0.0030"))
FEE_BUFFER_RR = float(os.getenv("FEE_BUFFER_RR", "0.15"))
STRICT_PROTECTION = os.getenv("STRICT_PROTECTION", "true").lower() == "true"
PROTECTION_ORDER_MODE = (os.getenv("PROTECTION_ORDER_MODE", "REDUCE_ONLY") or "REDUCE_ONLY").strip().upper()
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "M")

# Dynamic spread gate. Per-pair override format: SPREAD_THRESHOLD_BTCUSDT=0.0006
SPREAD_THRESHOLD_TOP = float(os.getenv("SPREAD_THRESHOLD_TOP", "0.0008"))
SPREAD_THRESHOLD_MID = float(os.getenv("SPREAD_THRESHOLD_MID", "0.0015"))
SPREAD_WARN_MULTIPLIER = float(os.getenv("SPREAD_WARN_MULTIPLIER", "0.8"))
SPREAD_CACHE_TTL = float(os.getenv("SPREAD_CACHE_TTL", "5"))
SPREAD_ORDER_BOOK_LIMIT = int(os.getenv("SPREAD_ORDER_BOOK_LIMIT", "5"))

# Live gate defaults.
LIVE_RR_MIN = float(os.getenv("LIVE_RR_MIN", "2.0"))
LIVE_TARGET_RR = float(os.getenv("LIVE_TARGET_RR", "2.5"))
LIVE_VOL_MIN = float(os.getenv("LIVE_VOL_MIN", "0.0015"))
LIVE_VOL_MAX = float(os.getenv("LIVE_VOL_MAX", "0.03"))
LIVE_REQUIRE_SWEEP = os.getenv("LIVE_REQUIRE_SWEEP", "true").lower() == "true"
LIVE_REQUIRE_PAIR_REGIME_MATCH = os.getenv("LIVE_REQUIRE_PAIR_REGIME_MATCH", "true").lower() == "true"
LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY = os.getenv("LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY", "false").lower() == "true"

# Backend pacing / cache.
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))
SCAN_INTERVAL_TOP = int(os.getenv("SCAN_INTERVAL_TOP", "30"))
SCAN_INTERVAL_MID = int(os.getenv("SCAN_INTERVAL_MID", "60"))
POSITION_CACHE_TTL = float(os.getenv("POSITION_CACHE_TTL", "30"))
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
