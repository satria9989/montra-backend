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
# MONTRA PAIR UNIVERSE (recommended)
# =========================
# Core live universe: hanya pair yang lebih cocok untuk final-lock intraday
TOP_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "DOGEUSDT", "TRXUSDT"
]

MID_PAIRS = [
    "HYPEUSDT", "SUIUSDT", "ADAUSDT", "LINKUSDT",
    "BCHUSDT", "XLMUSDT", "LTCUSDT", "AVAXUSDT",
    "TONUSDT", "ATOMUSDT", "1000PEPEUSDT"
]

# Pair yang boleh dipantau / diuji di fase validation,
# tapi jangan dijadikan core live dulu sampai ada bukti journal
VALIDATION_ONLY = [
    "TAOUSDT", "AAVEUSDT", "ETCUSDT", "FILUSDT",
    "QNTUSDT", "XMRUSDT", "ZECUSDT"
]

# Pair yang disarankan keluar dari core MONTRA sekarang
REMOVE_FROM_CORE = [
    "XAUUSDT", "XAGUSDT", "DASHUSDT",
    "ZENUSDT", "ENJUSDT", "MANAUSDT"
]

# PAIRS = universe yang benar-benar dipakai backend untuk scan.
# Kalau mau validation ikut scan VALIDATION_ONLY, nyalakan env MONTRA_INCLUDE_VALIDATION_ONLY=true
INCLUDE_VALIDATION_ONLY = os.getenv("MONTRA_INCLUDE_VALIDATION_ONLY", "false").lower() == "true"

PAIRS = TOP_PAIRS + MID_PAIRS
if INCLUDE_VALIDATION_ONLY:
    PAIRS += VALIDATION_ONLY

# Deduplicate sambil mempertahankan urutan
PAIRS = list(dict.fromkeys(PAIRS))

MONTRA_MODE = os.getenv("MONTRA_MODE", "api_only")


# =========================
# MONTRA EXECUTION / LIVE HARDENING DEFAULTS
# =========================
# Main.py tetap membaca env langsung, tapi config ini menjadi single reference
# agar Render/local .env mudah disinkronkan.
AUTO_MODE = os.getenv("AUTO_MODE", "false").lower() == "true"
AUTO_TRADING = os.getenv("AUTO_TRADING", "false").lower() == "true"
MONTRA_PROFILE = os.getenv("MONTRA_PROFILE", "final_lock")
STATE_FILE = os.getenv("STATE_FILE", "runtime_state.json")

# Binance WS endpoint sengaja dibuat env-driven agar perubahan endpoint Binance
# cukup diperbaiki dari Render env tanpa patch kode.
BINANCE_FSTREAM_WS_URL = os.getenv(
    "BINANCE_FSTREAM_WS_URL",
    "wss://fstream.binance.com/market/stream"
)

# Request pacing / rate-limit guard.
BINANCE_RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))
BINANCE_TIME_SYNC_INTERVAL = int(os.getenv("BINANCE_TIME_SYNC_INTERVAL", "900"))
BINANCE_MAX_TIME_RETRIES = int(os.getenv("BINANCE_MAX_TIME_RETRIES", "1"))
BINANCE_RATE_LIMIT_RETRIES = int(os.getenv("BINANCE_RATE_LIMIT_RETRIES", "1"))
SIGNED_CALL_MIN_INTERVAL = float(os.getenv("SIGNED_CALL_MIN_INTERVAL", "0.12"))

# Execution quality gate.
MIN_STOP_DISTANCE_PCT = float(os.getenv("MIN_STOP_DISTANCE_PCT", "0.0015"))
MIN_TP_DISTANCE_PCT = float(os.getenv("MIN_TP_DISTANCE_PCT", "0.0030"))
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.0008"))
FEE_BUFFER_RR = float(os.getenv("FEE_BUFFER_RR", "0.15"))
STRICT_PROTECTION = os.getenv("STRICT_PROTECTION", "true").lower() == "true"
ORDER_ID_PREFIX = os.getenv("ORDER_ID_PREFIX", "M")

# Live gate defaults.
LIVE_RR_MIN = float(os.getenv("LIVE_RR_MIN", "3.0"))
LIVE_TARGET_RR = float(os.getenv("LIVE_TARGET_RR", "3.0"))
LIVE_VOL_MIN = float(os.getenv("LIVE_VOL_MIN", "0.0015"))
LIVE_VOL_MAX = float(os.getenv("LIVE_VOL_MAX", "0.03"))
LIVE_REQUIRE_SWEEP = os.getenv("LIVE_REQUIRE_SWEEP", "true").lower() == "true"
LIVE_REQUIRE_PAIR_REGIME_MATCH = os.getenv("LIVE_REQUIRE_PAIR_REGIME_MATCH", "true").lower() == "true"
LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY = os.getenv("LIVE_ALLOW_SIDEWAYS_SCORE_PENALTY", "false").lower() == "true"

# Backend pacing / cache.
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))
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
WS_DEGRADED_MODE_ALLOW = os.getenv("WS_DEGRADED_MODE_ALLOW", "false").lower() == "true"
WS_DEGRADED_GRACE_SECONDS = float(os.getenv("WS_DEGRADED_GRACE_SECONDS", "0"))
WS_FULL_STALE_BLOCK_SECONDS = float(os.getenv("WS_FULL_STALE_BLOCK_SECONDS", "600"))
