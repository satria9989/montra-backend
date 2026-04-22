import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { createChart, IChartApi, ISeriesApi, LineStyle, UTCTimestamp } from "lightweight-charts";

type Signal = {
  symbol: string;
  type: "BUY" | "SELL";
  entry: number;
  sl: number;
  tp: number;
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

const API_URL = (process.env.REACT_APP_API_URL || "http://localhost:8000").replace(/\/+$/, "");

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

function getRange(values: number[]) {
  if (!values.length) return { min: 0, max: 0 };
  return {
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

export default function Chart({ symbol, selected, apiUrl }: Props) {
  const backendUrl = useMemo(() => (apiUrl || API_URL).replace(/\/+$/, ""), [apiUrl]);
  const [mode, setMode] = useState<ViewMode>("SCAN");
  const [candles15m, setCandles15m] = useState<Candle[]>([]);
  const [candles1h, setCandles1h] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
      try {
        setLoading(true);
        const [res15m, res1h] = await Promise.all([
          axios.get(`${backendUrl}/ohlcv/${symbol}?timeframe=15m&limit=160`),
          axios.get(`${backendUrl}/ohlcv/${symbol}?timeframe=1h&limit=120`),
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
    const id = window.setInterval(fetchData, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [backendUrl, symbol]);

  useEffect(() => {
    if (!containerRef.current || candles15m.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 560,
      layout: {
        background: { color: "#07101d" },
        textColor: "#b8c7e6",
      },
      grid: {
        vertLines: { color: "rgba(123, 146, 184, 0.08)" },
        horzLines: { color: "rgba(123, 146, 184, 0.08)" },
      },
      rightPriceScale: {
        borderColor: "rgba(123,146,184,0.15)",
      },
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

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#00d9a6",
      downColor: "#ff6b6b",
      wickUpColor: "#00d9a6",
      wickDownColor: "#ff6b6b",
      borderVisible: false,
      priceLineVisible: true,
      lastValueVisible: true,
    });

    candleSeries.setData(candles15m);
    chart.timeScale().fitContent();

    const lineSeries: ISeriesApi<"Line">[] = [];

    const addLevel = (value: number, color: string, title: string) => {
      const line = chart.addLineSeries({
        color,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: true,
        title,
      });
      const first = candles15m[0]?.time;
      const last = candles15m[candles15m.length - 1]?.time;
      if (first && last) {
        line.setData([
          { time: first, value },
          { time: last, value },
        ]);
      }
      lineSeries.push(line);
    };

    if ((mode === "ANALYSIS" || mode === "DEBUG") && selected) {
      addLevel(Number(selected.entry), "#4fc3ff", "ENTRY");
      addLevel(Number(selected.sl), "#ff7272", "SL");
      addLevel(Number(selected.tp), "#00ffaa", "TP");

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

    if (mode === "DEBUG" && candles1h.length > 0) {
      const recentHighs = candles1h.slice(-24).map((c) => c.high);
      const recentLows = candles1h.slice(-24).map((c) => c.low);
      const { min } = getRange(recentLows);
      const { max } = getRange(recentHighs);
      addLevel(max, "rgba(255,176,0,0.9)", "H1 HIGH");
      addLevel(min, "rgba(255,176,0,0.9)", "H1 LOW");
    }

    const handleResize = () => {
      if (!containerRef.current) return;
      chart.applyOptions({ width: containerRef.current.clientWidth });
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      lineSeries.forEach((series) => chart.removeSeries(series));
      chart.remove();
    };
  }, [candles15m, candles1h, mode, selected]);

  const lastCandle = candles15m[candles15m.length - 1];
  const h1Trend = useMemo(() => {
    if (candles1h.length < 50) return "RANGE";
    const closes = candles1h.map((c) => c.close);
    const ma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
    const ma50 = closes.slice(-50).reduce((a, b) => a + b, 0) / 50;
    const last = closes[closes.length - 1];
    if (last > ma20 && ma20 > ma50) return "BULL";
    if (last < ma20 && ma20 < ma50) return "BEAR";
    return "RANGE";
  }, [candles1h]);

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
        <span>{mode === "SCAN" ? "Raw backend candles only" : mode === "ANALYSIS" ? "Backend signal overlay active" : "Backend signal + simple context bands"}</span>
      </div>

      {selected ? (
        <div style={{
          marginBottom: 10,
          padding: 10,
          borderRadius: 10,
          border: "1px solid #1a2a46",
          background: "#091322",
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
          fontSize: 12,
        }}>
          <span><strong>{selected.symbol}</strong> {selected.type}</span>
          <span>Entry {Number(selected.entry).toFixed(4)}</span>
          <span style={{ color: "#ff7272" }}>SL {Number(selected.sl).toFixed(4)}</span>
          <span style={{ color: "#00ffaa" }}>TP {Number(selected.tp).toFixed(4)}</span>
          <span>Score {selected.score ?? "-"}</span>
          <span>Tier {selected.pair_tier || "-"}</span>
          <span>Regime {selected.pair_regime || "-"}</span>
          {selected.reason ? <span style={{ color: "#ffb000" }}>Reason {selected.reason}</span> : null}
        </div>
      ) : null}

      {error ? (
        <div style={{ color: "#ff9b9b", fontSize: 12, marginBottom: 10 }}>{error}</div>
      ) : null}

      {loading && candles15m.length === 0 ? (
        <div style={{ color: "#8ea4c9", fontSize: 12, padding: "14px 0" }}>Loading chart from backend...</div>
      ) : null}

      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: 560,
          border: "1px solid #182741",
          borderRadius: 12,
          overflow: "hidden",
          background: "#07101d",
        }}
      />

      <div style={{ marginTop: 10, fontSize: 11, color: "#6f819f" }}>
        Chart ini tidak lagi membuat signal sendiri. SCAN = candle backend, ANALYSIS = candle + signal backend terpilih, DEBUG = ANALYSIS + band konteks sederhana.
      </div>
    </div>
  );
}
