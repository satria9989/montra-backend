"""MONTRA dynamic spread gate.

Orderbook spread is fetched only when the pre-entry gate asks for it, then
cached for a short TTL so scanner cycles do not hammer Binance.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

_SPREAD_CACHE: Dict[str, Dict[str, Any]] = {}


def _clean_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def get_threshold_for_symbol(symbol: str, tier: str) -> Dict[str, Any]:
    symbol = _clean_symbol(symbol)
    tier = str(tier or "MID").upper()
    pair_override = os.getenv(f"SPREAD_THRESHOLD_{symbol}")
    source = "tier"
    if pair_override is not None:
        try:
            threshold = float(pair_override)
            source = "pair_override"
        except Exception:
            threshold = None
    else:
        threshold = None

    if threshold is None:
        if tier == "TOP":
            threshold = _env_float("SPREAD_THRESHOLD_TOP", 0.0008)
        elif tier == "MID":
            threshold = _env_float("SPREAD_THRESHOLD_MID", 0.0015)
        else:
            # LOW is intentionally not active in MONTRA v4 live universe.
            threshold = None

    warn_multiplier = _env_float("SPREAD_WARN_MULTIPLIER", 0.8)
    warn_at = threshold * warn_multiplier if threshold is not None else None
    return {
        "symbol": symbol,
        "tier": tier,
        "threshold": threshold,
        "warn_at": warn_at,
        "source": source,
    }


def _extract_orderbook(orderbook: Dict[str, Any]) -> Tuple[float, float]:
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []
    if not bids or not asks:
        raise ValueError("empty_orderbook")
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        raise ValueError("invalid_bid_ask")
    return best_bid, best_ask


def get_live_spread(
    client: Any,
    symbol: str,
    tier: str,
    ttl: Optional[float] = None,
    limit: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    symbol = _clean_symbol(symbol)
    tier = str(tier or "MID").upper()
    ttl = _env_float("SPREAD_CACHE_TTL", 5.0) if ttl is None else float(ttl)
    limit = _env_int("SPREAD_ORDER_BOOK_LIMIT", 5) if limit is None else int(limit)
    threshold_info = get_threshold_for_symbol(symbol, tier)

    now = time.time()
    cached = _SPREAD_CACHE.get(symbol)
    if not force and cached and (now - float(cached.get("ts", 0))) <= ttl:
        row = dict(cached)
        row["cache"] = "hit"
        row["age"] = round(now - float(row.get("ts", now)), 3)
        return row

    if client is None:
        row = {
            "symbol": symbol,
            "tier": tier,
            "ok": False,
            "reason": "client_not_ready",
            "threshold_pct": threshold_info.get("threshold"),
            "warn_pct": threshold_info.get("warn_at"),
            "cache": "miss",
            "ts": now,
        }
        _SPREAD_CACHE[symbol] = row
        return row

    try:
        orderbook = client.futures_order_book(symbol=symbol, limit=limit)
        best_bid, best_ask = _extract_orderbook(orderbook)
        mid = (best_bid + best_ask) / 2.0
        spread_abs = best_ask - best_bid
        spread_pct = spread_abs / max(mid, 1e-12)
        threshold = threshold_info.get("threshold")
        warn_at = threshold_info.get("warn_at")

        if threshold is None:
            ok = False
            reason = "UNSUPPORTED_TIER"
        elif spread_pct > threshold:
            ok = False
            reason = "SPREAD_TOO_WIDE"
        elif warn_at is not None and spread_pct >= warn_at:
            ok = True
            reason = "SPREAD_WARN"
        else:
            ok = True
            reason = "OK"

        row = {
            "symbol": symbol,
            "tier": tier,
            "ok": ok,
            "reason": reason,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_abs": spread_abs,
            "spread_pct": spread_pct,
            "threshold_pct": threshold,
            "warn_pct": warn_at,
            "threshold_source": threshold_info.get("source"),
            "cache": "miss",
            "limit": limit,
            "ts": now,
        }
    except Exception as exc:
        row = {
            "symbol": symbol,
            "tier": tier,
            "ok": False,
            "reason": "ORDERBOOK_ERROR",
            "error": str(exc),
            "threshold_pct": threshold_info.get("threshold"),
            "warn_pct": threshold_info.get("warn_at"),
            "cache": "miss",
            "ts": now,
        }

    _SPREAD_CACHE[symbol] = row
    return row


def check_spread_gate(client: Any, symbol: str, tier: str, force: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    row = get_live_spread(client, symbol, tier, force=force)
    ok = bool(row.get("ok"))
    reason = str(row.get("reason") or "UNKNOWN")
    if ok and reason == "SPREAD_WARN":
        return True, "SPREAD_WARN", row
    if ok:
        return True, "OK", row
    return False, reason, row


def get_spread_cache_snapshot() -> Dict[str, Dict[str, Any]]:
    now = time.time()
    out: Dict[str, Dict[str, Any]] = {}
    for symbol, row in _SPREAD_CACHE.items():
        item = dict(row)
        item["age"] = round(now - float(item.get("ts", now)), 3)
        out[symbol] = item
    return out
