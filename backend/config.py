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
