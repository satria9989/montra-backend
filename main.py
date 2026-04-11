import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

from data import get_ticker, get_ohlcv, get_multi_tickers

# ================= INIT =================
app = FastAPI(title="Montra Backend", version="1.0")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 OPENAI CLIENT
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ================= BASIC =================
@app.get("/")
def root():
    return {"status": "MONTRA backend running 🚀"}

@app.get("/")
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