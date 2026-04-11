import ccxt
from typing import List, Dict, Any


exchange = ccxt.binance(
    {
        "enableRateLimit": True,
        "timeout": 30000,
        "options": {
            "defaultType": "future",
        },
    }
)


def _ensure_markets() -> None:
    if not exchange.markets:
        exchange.load_markets()


def normalize_symbol(symbol: str) -> str:
    """
    Convert:
    BTCUSDT -> BTC/USDT
    ETHUSDT -> ETH/USDT
    BTC/USDT -> BTC/USDT
    """
    symbol = symbol.upper().strip()

    if "/" in symbol:
        return symbol

    if symbol.endswith("USDT"):
        base = symbol[:-4]
        return f"{base}/USDT"

    return symbol


def get_ticker(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    _ensure_markets()

    sym = normalize_symbol(symbol)
    ticker = exchange.fetch_ticker(sym)

    return {
        "symbol": symbol,
        "normalized_symbol": sym,
        "last": ticker.get("last"),
        "high": ticker.get("high"),
        "low": ticker.get("low"),
        "open": ticker.get("open"),
        "close": ticker.get("close"),
        "volume": ticker.get("baseVolume"),
        "timestamp": ticker.get("timestamp"),
        "datetime": ticker.get("datetime"),
    }


def get_ohlcv(
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    _ensure_markets()

    sym = normalize_symbol(symbol)
    candles = exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)

    return [
        {
            "time": int(c[0]),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        }
        for c in candles
    ]


def get_multi_tickers(symbols: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for s in symbols:
        try:
            results.append(get_ticker(s))
        except Exception as e:
            results.append(
                {
                    "symbol": s,
                    "error": str(e),
                }
            )

    return results