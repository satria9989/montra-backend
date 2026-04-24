import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import {
  createChart,
  IChartApi,
  ISeriesApi,
  LineStyle,
  UTCTimestamp,
} from "lightweight-charts";

type Signal = {
  symbol: string;
  type: "BUY" | "SELL";
  entry: number;
  sl: number | null;
  tp: number | null;
  score?: number;
  rr?: number | string;
  reason?: string;
  pair_tier?: string;
  pair_regime?: string;
};

type Props = {
  symbol: string;
  selected?: Signal | null;
  apiUrl?: string;
};

type ViewMode = "SCAN" | "ANALYSIS" | "DEBUG";

type Candle = {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

type Zone = {
  type: "bullish" | "bearish";
  top: number;
  bottom: number;
  label: string;
  strength: number;
  sourceTime: UTCTimestamp;
};

type LiquidityBand = {
  top: number;
  bottom: number;
  strength: number;
  label: string;
};

type SweepMarker = {
  time: UTCTimestamp;
  price: number;
  type: "sweep_high" | "sweep_low";
};

const API_URL = (process.env.REACT_APP_API_URL || "http://localhost:8000").replace(/\/+$/, "");
const CHART_POLL_MS = 60_000;

function hasValidPrice(value: unknown) {
  const num = Number(value);
  return Number.isFinite(num) && num > 0;
}

function formatPrice(value: unknown, digits = 4) {
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? num.toFixed(digits) : "-";
}

function normalizeCandle(row: any): Candle | null {
  if (Array.isArray(row)) {
    const ts = Number(row[0]);
    const time = Math.floor((ts > 1e12 ? ts : ts * 1000) / 1000) as UTCTimestamp;
    return {
      time,
      open: Number(row[1]),
      high: Number(row[2]),
      low: Number(row[3]),
      close: Number(row[4]),
      volume: Number(row[5] ?? 0),
    };
  }

  const rawTime = Number(row?.time ?? row?.timestamp ?? row?.open_time ?? 0);
  if (!Number.isFinite(rawTime)) return null;
  const time = Math.floor((rawTime > 1e12 ? rawTime : rawTime * 1000) / 1000) as UTCTimestamp;

  return {
    time,
    open: Number(row?.open),
    high: Number(row?.high),
    low: Number(row?.low),
    close: Number(row?.close),
    volume: Number(row?.volume ?? 0),
  };
}

function sma(values: number[], period: number) {
  const out: number[] = [];
  for (let i = 0; i < values.length; i++) {
    const start = Math.max(0, i - period + 1);
    const window = values.slice(start, i + 1);
    out.push(window.reduce((a, b) => a + b, 0) / Math.max(window.length, 1));
  }
  return out;
}

function getH1Trend(candles: Candle[]) {
  if (candles.length < 50) return "RANGE";
  const closes = candles.map((c) => c.close);
  const ma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const ma50 = closes.slice(-50).reduce((a, b) => a + b, 0) / 50;
  const last = closes[closes.length - 1];
  if (last > ma20 && ma20 > ma50) return "BULL";
  if (last < ma20 && ma20 < ma50) return "BEAR";
  return "RANGE";
}

function detectFvgZones(candles: Candle[]): Zone[] {
  const zones: Zone[] = [];
  for (let i = 2; i < candles.length; i++) {
    const c1 = candles[i - 2];
    const c3 = candles[i];
    if (c1.high < c3.low) {
      zones.push({
        type: "bullish",
        top: c3.low,
        bottom: c1.high,
        label: "H1 FVG",
        strength: Math.abs(c3.low - c1.high),
        sourceTime: c3.time,
      });
    }
    if (c1.low > c3.high) {
      zones.push({
        type: "bearish",
        top: c1.low,
        bottom: c3.high,
        label: "H1 FVG",
        strength: Math.abs(c1.low - c3.high),
        sourceTime: c3.time,
      });
    }
  }
  return zones.slice(-8);
}

function detectOrderBlockZones(candles: Candle[]): Zone[] {
  const zones: Zone[] = [];
  const lookback = 5;
  for (let i = lookback; i < candles.length - 1; i++) {
    const current = candles[i + 1];
    const recent = candles.slice(i - lookback, i);
    const recentHigh = Math.max(...recent.map((c) => c.high));
    const recentLow = Math.min(...recent.map((c) => c.low));

    const bullishBos = current.close > recentHigh && current.close > current.open;
    const bearishBos = current.close < recentLow && current.close < current.open;

    if (bullishBos) {
      for (let j = i; j >= i - lookback; j--) {
        if (candles[j].close < candles[j].open) {
          zones.push({
            type: "bullish",
            top: candles[j].open,
            bottom: candles[j].low,
            label: "H1 OB",
            strength: Math.abs(candles[j].open - candles[j].low),
            sourceTime: candles[j].time,
          });
          break;
        }
      }
    }

    if (bearishBos) {
      for (let j = i; j >= i - lookback; j--) {
        if (candles[j].close > candles[j].open) {
          zones.push({
            type: "bearish",
            top: candles[j].high,
            bottom: candles[j].open,
            label: "H1 OB",
            strength: Math.abs(candles[j].high - candles[j].open),
            sourceTime: candles[j].time,
          });
          break;
        }
      }
    }
  }
  return zones.slice(-8);
}

function buildLiquidityBands(candles: Candle[]): LiquidityBand[] {
  if (candles.length === 0) return [];
  const recent = candles.slice(-120);
  const lows = recent.map((c) => c.low);
  const highs = recent.map((c) => c.high);
  const low = Math.min(...lows);
  const high = Math.max(...highs);
  const bins = 24;
  const step = Math.max((high - low) / bins, 1e-9);
  const profile = Array.from({ length: bins }, (_, idx) => ({ idx, volume: 0 }));

  recent.forEach((c) => {
    const typical = (c.high + c.low + c.close) / 3;
    const bin = Math.max(0, Math.min(bins - 1, Math.floor((typical - low) / step)));
    profile[bin].volume += Number(c.volume ?? 0);
  });

  const maxVol = Math.max(...profile.map((b) => b.volume), 1);
  return profile
    .map((b) => ({
      top: low + (b.idx + 1) * step,
      bottom: low + b.idx * step,
      strength: b.volume / maxVol,
      label: b.volume / maxVol >= 0.78 ? "MAGNET" : b.volume / maxVol >= 0.55 ? "LIQ" : "SHELF",
    }))
    .filter((b) => b.strength >= 0.42)
    .sort((a, b) => b.strength - a.strength)
    .slice(0, 6)
    .sort((a, b) => a.bottom - b.bottom);
}

function detectSweeps(candles: Candle[]): SweepMarker[] {
  const markers: SweepMarker[] = [];
  const lookback = 6;
  for (let i = lookback; i < candles.length; i++) {
    const c = candles[i];
    const prev = candles.slice(i - lookback, i);
    const prevHigh = Math.max(...prev.map((x) => x.high));
    const prevLow = Math.min(...prev.map((x) => x.low));

    if (c.high > prevHigh && c.close < prevHigh) {
      markers.push({ time: c.time, price: c.high, type: "sweep_high" });
    }
    if (c.low < prevLow && c.close > prevLow) {
      markers.push({ time: c.time, price: c.low, type: "sweep_low" });
    }
  }
  return markers.slice(-8);
}

function formatNum(value: number | undefined, digits = 2) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "-";
}

export default function Chart({ symbol, selected, apiUrl }: Props) {
  const backendUrl = useMemo(() => (apiUrl || API_URL).replace(/\/+$/, ""), [apiUrl]);
  const [mode, setMode] = useState<ViewMode>("ANALYSIS");
  const [candles15m, setCandles15m] = useState<Candle[]>([]);
  const [candles1h, setCandles1h] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const mainContainerRef = useRef<HTMLDivElement | null>(null);
  const mainChartHostRef = useRef<HTMLDivElement | null>(null);
  const deltaChartHostRef = useRef<HTMLDivElement | null>(null);
  const regimeChartHostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
      try {
        setLoading(true);
        const [res15m, res1h] = await Promise.all([
          axios.get(`${backendUrl}/ohlcv/${symbol}?timeframe=15m&limit=220`),
          axios.get(`${backendUrl}/ohlcv/${symbol}?timeframe=1h&limit=180`),
        ]);

        if (cancelled) return;

        const next15m = (res15m.data?.data || []).map(normalizeCandle).filter(Boolean) as Candle[];
        const next1h = (res1h.data?.data || []).map(normalizeCandle).filter(Boolean) as Candle[];

        setCandles15m(next15m);
        setCandles1h(next1h);
        setError("");
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || "Gagal memuat chart backend.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchData();
    const id = window.setInterval(fetchData, CHART_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [backendUrl, symbol]);

  const h1Trend = useMemo(() => getH1Trend(candles1h), [candles1h]);
  const htfZones = useMemo(() => {
    const zones = [...detectOrderBlockZones(candles1h), ...detectFvgZones(candles1h)];
    return zones.slice(-10);
  }, [candles1h]);
  const liquidityBands = useMemo(() => buildLiquidityBands(candles15m), [candles15m]);
  const sweeps = useMemo(() => detectSweeps(candles15m), [candles15m]);

  const metricData = useMemo(() => {
    const delta: { time: UTCTimestamp; value: number }[] = [];
    const participation: { time: UTCTimestamp; value: number; color: string }[] = [];
    const expansion: { time: UTCTimestamp; value: number }[] = [];

    if (!candles15m.length) return { delta, participation, expansion };

    const vols = candles15m.map((c) => Number(c.volume ?? 0));
    const volSma = sma(vols, 20);
    const ranges = candles15m.map((c) => c.high - c.low);
    const rangeSma = sma(ranges, 20);
    let cumulative = 0;

    candles15m.forEach((c, idx) => {
      const body = c.close - c.open;
      const range = Math.max(c.high - c.low, 1e-9);
      const vol = Number(c.volume ?? 0);
      const signedVol = (body / range) * vol;
      cumulative += signedVol;
      delta.push({ time: c.time, value: cumulative });

      const participationValue = vol / Math.max(volSma[idx] || 1, 1e-9);
      participation.push({
        time: c.time,
        value: participationValue,
        color: body >= 0 ? "rgba(0,255,170,0.65)" : "rgba(255,114,114,0.65)",
      });

      const expansionValue = range / Math.max(rangeSma[idx] || 1, 1e-9);
      expansion.push({ time: c.time, value: expansionValue });
    });

    return { delta, participation, expansion };
  }, [candles15m]);

  useEffect(() => {
    if (!mainChartHostRef.current || !deltaChartHostRef.current || !regimeChartHostRef.current || candles15m.length === 0) return;

    const host = mainChartHostRef.current;
    const overlay = document.createElement("canvas");
    overlay.style.position = "absolute";
    overlay.style.inset = "0";
    overlay.style.pointerEvents = "none";
    overlay.style.zIndex = "4";
    host.appendChild(overlay);

    const applyCanvasSize = () => {
      const dpr = window.devicePixelRatio || 1;
      overlay.width = Math.floor(host.clientWidth * dpr);
      overlay.height = Math.floor(host.clientHeight * dpr);
      overlay.style.width = `${host.clientWidth}px`;
      overlay.style.height = `${host.clientHeight}px`;
      const ctx = overlay.getContext("2d");
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const mainChart = createChart(host, {
      width: host.clientWidth,
      height: 560,
      layout: { background: { color: "#07101d" }, textColor: "#b8c7e6" },
      grid: {
        vertLines: { color: "rgba(123, 146, 184, 0.08)" },
        horzLines: { color: "rgba(123, 146, 184, 0.08)" },
      },
      rightPriceScale: { borderColor: "rgba(123,146,184,0.15)" },
      timeScale: {
        borderColor: "rgba(123,146,184,0.15)",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: "rgba(143, 211, 255, 0.35)", labelBackgroundColor: "#0f1b2d" },
        horzLine: { color: "rgba(143, 211, 255, 0.35)", labelBackgroundColor: "#0f1b2d" },
      },
    });

    const candleSeries = mainChart.addCandlestickSeries({
      upColor: "#00d9a6",
      downColor: "#ff6b6b",
      wickUpColor: "#00d9a6",
      wickDownColor: "#ff6b6b",
      borderVisible: false,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    candleSeries.setData(candles15m);

    const levelSeries: ISeriesApi<any>[] = [];
    const addLevel = (value: number, color: string, title: string, lineStyle = LineStyle.Dashed) => {
      const line = mainChart.addLineSeries({
        color,
        lineWidth: 2,
        lineStyle,
        priceLineVisible: false,
        lastValueVisible: true,
        title,
      });
      line.setData([
        { time: candles15m[0].time, value },
        { time: candles15m[candles15m.length - 1].time, value },
      ]);
      levelSeries.push(line);
    };

    if ((mode === "ANALYSIS" || mode === "DEBUG") && selected) {
      if (hasValidPrice(selected.entry)) addLevel(Number(selected.entry), "#4fc3ff", "ENTRY");
      if (hasValidPrice(selected.sl)) addLevel(Number(selected.sl), "#ff7272", "SL");
      if (hasValidPrice(selected.tp)) addLevel(Number(selected.tp), "#00ffaa", "TP");
      const lastTime = candles15m[candles15m.length - 1]?.time;
      if (lastTime) {
        candleSeries.setMarkers([
          {
            time: lastTime,
            position: selected.type === "BUY" ? "belowBar" : "aboveBar",
            color: selected.type === "BUY" ? "#00ffaa" : "#ff7272",
            shape: selected.type === "BUY" ? "arrowUp" : "arrowDown",
            text: `${selected.symbol} ${selected.type}`,
          },
        ]);
      }
    } else {
      candleSeries.setMarkers([]);
    }

    const deltaChart = createChart(deltaChartHostRef.current, {
      width: deltaChartHostRef.current.clientWidth,
      height: 120,
      layout: { background: { color: "#07101d" }, textColor: "#8ea4c9" },
      grid: {
        vertLines: { color: "rgba(123, 146, 184, 0.06)" },
        horzLines: { color: "rgba(123, 146, 184, 0.06)" },
      },
      rightPriceScale: { borderColor: "rgba(123,146,184,0.12)" },
      timeScale: { borderColor: "rgba(123,146,184,0.12)", timeVisible: true },
    });
    const deltaSeries = deltaChart.addLineSeries({ color: "#00ffaa", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "Delta proxy" });
    deltaSeries.setData(metricData.delta);

    const regimeChart = createChart(regimeChartHostRef.current, {
      width: regimeChartHostRef.current.clientWidth,
      height: 140,
      layout: { background: { color: "#07101d" }, textColor: "#8ea4c9" },
      grid: {
        vertLines: { color: "rgba(123, 146, 184, 0.06)" },
        horzLines: { color: "rgba(123, 146, 184, 0.06)" },
      },
      rightPriceScale: { borderColor: "rgba(123,146,184,0.12)" },
      timeScale: { borderColor: "rgba(123,146,184,0.12)", timeVisible: true },
    });
    const participationSeries = regimeChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: true, title: "Participation proxy" });
    participationSeries.setData(metricData.participation as any);
    const expansionSeries = regimeChart.addLineSeries({ color: "#ffb000", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "Expansion" });
    expansionSeries.setData(metricData.expansion);

    mainChart.timeScale().fitContent();
    deltaChart.timeScale().fitContent();
    regimeChart.timeScale().fitContent();

    const syncRange = () => {
      const visible = mainChart.timeScale().getVisibleLogicalRange();
      if (visible) {
        deltaChart.timeScale().setVisibleLogicalRange(visible);
        regimeChart.timeScale().setVisibleLogicalRange(visible);
      }
    };
    mainChart.timeScale().subscribeVisibleLogicalRangeChange(syncRange);

    const drawOverlay = () => {
      applyCanvasSize();
      const ctx = overlay.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, host.clientWidth, host.clientHeight);

      const priceToY = (price: number) => candleSeries.priceToCoordinate(price);
      const timeToX = (time: UTCTimestamp) => mainChart.timeScale().timeToCoordinate(time);
      const width = host.clientWidth;
      const height = host.clientHeight;

      if (mode === "ANALYSIS" || mode === "DEBUG") {
        htfZones.forEach((zone, idx) => {
          const yTop = priceToY(zone.top);
          const yBottom = priceToY(zone.bottom);
          if (yTop == null || yBottom == null) return;
          const top = Math.min(yTop, yBottom);
          const bottom = Math.max(yTop, yBottom);
          ctx.save();
          ctx.fillStyle = zone.type === "bullish" ? "rgba(0,255,170,0.08)" : "rgba(255,114,114,0.08)";
          ctx.strokeStyle = zone.type === "bullish" ? "rgba(0,255,170,0.35)" : "rgba(255,114,114,0.35)";
          ctx.lineWidth = 1;
          ctx.fillRect(0, top, width, bottom - top);
          ctx.strokeRect(0, top, width, bottom - top);
          ctx.fillStyle = zone.type === "bullish" ? "#00ffaa" : "#ff7272";
          ctx.font = "11px Inter, sans-serif";
          ctx.fillText(`${zone.label}`, 10, Math.max(12, top - 4 + (idx % 2) * 12));
          ctx.restore();
        });

        liquidityBands.forEach((band) => {
          const yTop = priceToY(band.top);
          const yBottom = priceToY(band.bottom);
          if (yTop == null || yBottom == null) return;
          const top = Math.min(yTop, yBottom);
          const bottom = Math.max(yTop, yBottom);
          const alpha = 0.05 + band.strength * 0.16;
          ctx.save();
          ctx.fillStyle = `rgba(255,176,0,${alpha})`;
          ctx.fillRect(0, top, width, bottom - top);
          ctx.strokeStyle = `rgba(255,176,0,${Math.min(0.65, alpha + 0.15)})`;
          ctx.setLineDash([4, 4]);
          ctx.strokeRect(0, top, width, bottom - top);
          ctx.setLineDash([]);
          ctx.fillStyle = "rgba(255,230,160,0.95)";
          ctx.font = "10px Inter, sans-serif";
          ctx.fillText(band.label, width - 62, Math.max(12, top + 11));
          ctx.restore();
        });
      }

      if (mode === "DEBUG") {
        const recent = candles15m.slice(-96);
        if (recent.length > 0) {
          const swingHigh = Math.max(...recent.map((c) => c.high));
          const swingLow = Math.min(...recent.map((c) => c.low));
          const mid = (swingHigh + swingLow) / 2;
          const yHigh = priceToY(swingHigh);
          const yLow = priceToY(swingLow);
          const yMid = priceToY(mid);
          if (yHigh != null && yLow != null && yMid != null) {
            ctx.save();
            ctx.fillStyle = "rgba(255,114,114,0.05)";
            ctx.fillRect(0, yHigh, width, yMid - yHigh);
            ctx.fillStyle = "rgba(0,255,170,0.05)";
            ctx.fillRect(0, yMid, width, yLow - yMid);
            ctx.strokeStyle = "rgba(143,211,255,0.35)";
            ctx.setLineDash([6, 6]);
            ctx.beginPath();
            ctx.moveTo(0, yMid);
            ctx.lineTo(width, yMid);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = "#8fd3ff";
            ctx.font = "11px Inter, sans-serif";
            ctx.fillText("EQ / Premium-Discount midpoint", 10, Math.max(12, yMid - 6));
            ctx.restore();
          }
        }

        sweeps.forEach((sweep) => {
          const x = timeToX(sweep.time);
          const y = priceToY(sweep.price);
          if (x == null || y == null) return;
          ctx.save();
          ctx.fillStyle = sweep.type === "sweep_low" ? "#00ffaa" : "#ff7272";
          ctx.font = "bold 13px Inter, sans-serif";
          ctx.fillText(sweep.type === "sweep_low" ? "▲" : "▼", x - 4, sweep.type === "sweep_low" ? y + 16 : y - 6);
          ctx.font = "10px Inter, sans-serif";
          ctx.fillText(sweep.type === "sweep_low" ? "SWEEP LOW" : "SWEEP HIGH", x + 6, sweep.type === "sweep_low" ? y + 14 : y - 8);
          ctx.restore();
        });
      }

      if (selected && (mode === "ANALYSIS" || mode === "DEBUG") && hasValidPrice(selected.entry)) {
        const entryY = priceToY(Number(selected.entry));
        if (entryY != null) {
          const rrLabel = hasValidPrice(selected.sl) && hasValidPrice(selected.tp)
            ? (typeof selected.rr === "string" ? selected.rr : formatNum(Number(selected.rr), 2))
            : "pending";
          ctx.save();
          ctx.fillStyle = "rgba(79,195,255,0.95)";
          ctx.font = "bold 11px Inter, sans-serif";
          ctx.fillText(`Selected ${selected.type} · score ${formatNum(Number(selected.score), 0)} · RR ${rrLabel}`,
            10,
            Math.max(16, entryY - 10)
          );
          ctx.restore();
        }
      }
    };

    drawOverlay();
    syncRange();

    const handleResize = () => {
      if (!mainChartHostRef.current || !deltaChartHostRef.current || !regimeChartHostRef.current) return;
      mainChart.applyOptions({ width: mainChartHostRef.current.clientWidth });
      deltaChart.applyOptions({ width: deltaChartHostRef.current.clientWidth });
      regimeChart.applyOptions({ width: regimeChartHostRef.current.clientWidth });
      drawOverlay();
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncRange);
      levelSeries.forEach((s) => mainChart.removeSeries(s));
      mainChart.remove();
      deltaChart.remove();
      regimeChart.remove();
      overlay.remove();
    };
  }, [candles15m, candles1h, htfZones, liquidityBands, sweeps, metricData, mode, selected]);

  const lastCandle = candles15m[candles15m.length - 1];
  const lastDelta = metricData.delta[metricData.delta.length - 1]?.value;
  const lastParticipation = metricData.participation[metricData.participation.length - 1]?.value;
  const lastExpansion = metricData.expansion[metricData.expansion.length - 1]?.value;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        {(["SCAN", "ANALYSIS", "DEBUG"] as ViewMode[]).map((item) => (
          <button
            key={item}
            onClick={() => setMode(item)}
            style={{
              border: `1px solid ${mode === item ? (item === "SCAN" ? "#00ffaa" : item === "ANALYSIS" ? "#ffb000" : "#ff7272") : "#1a2a46"}`,
              background: mode === item ? (item === "SCAN" ? "rgba(0,255,170,0.16)" : item === "ANALYSIS" ? "rgba(255,176,0,0.16)" : "rgba(255,114,114,0.16)") : "#0a1220",
              color: "#eef5ff",
              borderRadius: 8,
              padding: "8px 12px",
              fontWeight: 700,
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            {item}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 10, fontSize: 12, color: "#8ea4c9" }}>
        <span>Symbol: <strong style={{ color: "#eef5ff" }}>{symbol}</strong></span>
        <span>Last: <strong style={{ color: "#8fd3ff" }}>{lastCandle ? lastCandle.close.toFixed(2) : "-"}</strong></span>
        <span>H1 trend: <strong style={{ color: h1Trend === "BULL" ? "#00ffaa" : h1Trend === "BEAR" ? "#ff7272" : "#ffb000" }}>{h1Trend}</strong></span>
        <span>{mode === "SCAN" ? "Backend candles only" : mode === "ANALYSIS" ? "Structure + liquidity context" : "Analysis + sweep + premium/discount + proxies"}</span>
      </div>

      {selected ? (
        <div
          style={{
            marginBottom: 10,
            padding: 10,
            borderRadius: 10,
            border: "1px solid #1a2a46",
            background: "#091322",
            display: "flex",
            gap: 16,
            flexWrap: "wrap",
            fontSize: 12,
          }}
        >
          <span><strong>{selected.symbol}</strong> {selected.type}</span>
          <span>Entry {formatPrice(selected.entry)}</span>
          <span style={{ color: hasValidPrice(selected.sl) ? "#ff7272" : "#ffb000" }}>SL {formatPrice(selected.sl)}</span>
          <span style={{ color: hasValidPrice(selected.tp) ? "#00ffaa" : "#ffb000" }}>TP {formatPrice(selected.tp)}</span>
          <span>Score {selected.score ?? "-"}</span>
          <span>Tier {selected.pair_tier || "-"}</span>
          <span>Regime {selected.pair_regime || selected.reason || "-"}</span>
          {!hasValidPrice(selected.sl) || !hasValidPrice(selected.tp) ? <span style={{ color: "#ffb000" }}>Protective orders resolving</span> : null}
          {selected.reason ? <span style={{ color: "#ffb000" }}>Reason {selected.reason}</span> : null}
        </div>
      ) : null}

      {error ? <div style={{ color: "#ff9b9b", fontSize: 12, marginBottom: 10 }}>{error}</div> : null}

      {loading && candles15m.length === 0 ? (
        <div style={{ color: "#8ea4c9", fontSize: 12, padding: "14px 0" }}>Loading chart from backend...</div>
      ) : null}

      <div
        ref={mainContainerRef}
        style={{
          width: "100%",
          border: "1px solid #182741",
          borderRadius: 12,
          overflow: "hidden",
          background: "#07101d",
          marginBottom: 12,
        }}
      >
        <div
          ref={mainChartHostRef}
          style={{
            position: "relative",
            width: "100%",
            height: 560,
            background: "#07101d",
          }}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginBottom: 12, fontSize: 12 }}>
        <div style={{ padding: 10, borderRadius: 10, border: "1px solid #182741", background: "#091322" }}>
          <div style={{ color: "#8ea4c9", marginBottom: 6 }}>HTF zones</div>
          <div style={{ color: "#eef5ff", fontWeight: 800 }}>{htfZones.length}</div>
          <div style={{ color: "#6f819f", marginTop: 4 }}>OB/FVG dari candle backend 1H</div>
        </div>
        <div style={{ padding: 10, borderRadius: 10, border: "1px solid #182741", background: "#091322" }}>
          <div style={{ color: "#8ea4c9", marginBottom: 6 }}>Liquidity bands</div>
          <div style={{ color: "#eef5ff", fontWeight: 800 }}>{liquidityBands.length}</div>
          <div style={{ color: "#6f819f", marginTop: 4 }}>Volume-profile bands dari 15m backend</div>
        </div>
        <div style={{ padding: 10, borderRadius: 10, border: "1px solid #182741", background: "#091322" }}>
          <div style={{ color: "#8ea4c9", marginBottom: 6 }}>Recent sweeps</div>
          <div style={{ color: "#eef5ff", fontWeight: 800 }}>{sweeps.length}</div>
          <div style={{ color: "#6f819f", marginTop: 4 }}>Sweep markers lokal dari candle backend</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 12 }}>
        <div style={{ border: "1px solid #182741", borderRadius: 12, overflow: "hidden", background: "#07101d" }}>
          <div style={{ padding: "10px 12px", borderBottom: "1px solid #132037", fontSize: 12, color: "#8ea4c9", display: "flex", justifyContent: "space-between" }}>
            <span>Delta proxy</span>
            <strong style={{ color: Number(lastDelta) >= 0 ? "#00ffaa" : "#ff7272" }}>{formatNum(Number(lastDelta), 0)}</strong>
          </div>
          <div ref={deltaChartHostRef} style={{ width: "100%", height: 120, background: "#07101d" }} />
        </div>
        <div style={{ border: "1px solid #182741", borderRadius: 12, overflow: "hidden", background: "#07101d" }}>
          <div style={{ padding: "10px 12px", borderBottom: "1px solid #132037", fontSize: 12, color: "#8ea4c9", display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <span>Participation + expansion proxy</span>
            <span style={{ color: "#eef5ff" }}>Part. <strong>{formatNum(Number(lastParticipation), 2)}x</strong></span>
            <span style={{ color: "#ffb000" }}>Exp. <strong>{formatNum(Number(lastExpansion), 2)}x</strong></span>
          </div>
          <div ref={regimeChartHostRef} style={{ width: "100%", height: 140, background: "#07101d" }} />
        </div>
      </div>

      <div style={{ marginTop: 10, fontSize: 11, color: "#6f819f" }}>
        Chart 2.0 tetap backend-first: frontend tidak membuat signal baru. Overlay struktur dan likuiditas dihitung dari candle backend, sementara panel bawah adalah proxy jujur berbasis harga/volume — bukan feed Coinglass, funding, atau OI real-time.
      </div>
    </div>
  );
}
