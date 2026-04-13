import { useEffect, useRef } from "react";
import axios from "axios";
import { createChart } from "lightweight-charts";

// 🔔 SOUND ALERT
const alertSound = new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg");

// 🚫 anti spam
let lastAlert = "";

type Props = {
  symbol: string;
};

type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

type Zone = {
  type: "bullish" | "bearish";
  level: number;
  strength: number;
  time: number;
  label: string;
};

type AlertMode = "LONG" | "SHORT" | "WAIT" | "NO TRADE";

function detectHTFTrend(data: Candle[]) {
  if (data.length < 50) return "RANGE";

  const closes = data.map((c) => c.close);
  const ma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const ma50 = closes.slice(-50).reduce((a, b) => a + b, 0) / 50;
  const last = closes[closes.length - 1];

  if (last > ma20 && ma20 > ma50) return "BULL";
  if (last < ma20 && ma20 < ma50) return "BEAR";
  return "RANGE";
}

function detectAutoBias(trend: string, zones: Zone[]): AlertMode {
  if (trend === "RANGE") return "NO TRADE";

  const top = zones[0];
  if (!top) return "NO TRADE";

  if (trend === "BULL" && top.type === "bullish") return "LONG";
  if (trend === "BEAR" && top.type === "bearish") return "SHORT";

  return "WAIT";
}

function cinematicLabel(bias: AlertMode) {
  if (bias === "LONG") return "SAFE LONG";
  if (bias === "SHORT") return "SAFE SHORT";
  if (bias === "WAIT") return "WATCH MODE";
  return "NO TRADE";
}

function filterTopZones(zones: Zone[]) {
  return zones.sort((a, b) => b.strength - a.strength).slice(0, 10);
}

function detectStructure(data: Candle[]) {
  const result: any[] = [];

  for (let i = 1; i < data.length - 1; i++) {
    const prev = data[i - 1];
    const curr = data[i];
    const next = data[i + 1];

    if (curr.high > prev.high && curr.high > next.high) {
      result.push({ type: "HH", time: curr.time, price: curr.high });
    }

    if (curr.low < prev.low && curr.low < next.low) {
      result.push({ type: "HL", time: curr.time, price: curr.low });
    }
  }

  return result;
}

function detectFVG(data: Candle[]) {
  const fvgZones: any[] = [];

  for (let i = 2; i < data.length; i++) {
    const c1 = data[i - 2];
    const c3 = data[i];

    if (c1.high < c3.low) {
      fvgZones.push({
        type: "bullish",
        startTime: c1.time,
        endTime: c3.time,
        top: c3.low,
        bottom: c1.high,
      });
    }

    if (c1.low > c3.high) {
      fvgZones.push({
        type: "bearish",
        startTime: c1.time,
        endTime: c3.time,
        top: c1.low,
        bottom: c3.high,
      });
    }
  }

  return fvgZones;
}

function detectOrderBlock(data: Candle[]) {
  const zones: any[] = [];
  const seen = new Set<string>();
  const lookback = 5;

  for (let i = lookback; i < data.length - 2; i++) {
    const recentWindow = data.slice(i - lookback, i);
    const current = data[i + 1];

    const recentHigh = Math.max(...recentWindow.map((c) => c.high));
    const recentLow = Math.min(...recentWindow.map((c) => c.low));

    const bullishBOS =
      current.close > recentHigh && current.close > current.open;
    const bearishBOS =
      current.close < recentLow && current.close < current.open;

    if (bullishBOS) {
      let obIndex: number | undefined;

      for (let j = i - 1; j >= i - lookback; j--) {
        if (data[j].close < data[j].open) {
          obIndex = j;
          break;
        }
      }

      if (obIndex !== undefined) {
        const ob = data[obIndex];
        const key = `bull_${ob.time}_${current.time}`;

        if (!seen.has(key)) {
          seen.add(key);
          zones.push({
            type: "bullish",
            startTime: ob.time,
            endTime: current.time,
            top: ob.open,
            bottom: ob.low,
          });
        }
      }
    }

    if (bearishBOS) {
      let obIndex: number | undefined;

      for (let j = i - 1; j >= i - lookback; j--) {
        if (data[j].close > data[j].open) {
          obIndex = j;
          break;
        }
      }

      if (obIndex !== undefined) {
        const ob = data[obIndex];
        const key = `bear_${ob.time}_${current.time}`;

        if (!seen.has(key)) {
          seen.add(key);
          zones.push({
            type: "bearish",
            startTime: ob.time,
            endTime: current.time,
            top: ob.high,
            bottom: ob.open,
          });
        }
      }
    }
  }

  return zones;
}

function detectLiquidityPools(data: Candle[]) {
  const pools: any[] = [];
  const seen = new Set<string>();
  const tolerancePct = 0.0015;

  for (let i = 2; i < data.length - 2; i++) {
    const left = data[i - 1];
    const mid = data[i];
    const right = data[i + 1];

    const highMax = Math.max(left.high, mid.high, right.high);
    const highMin = Math.min(left.high, mid.high, right.high);
    const lowMax = Math.max(left.low, mid.low, right.low);
    const lowMin = Math.min(left.low, mid.low, right.low);

    const equalHigh =
      (highMax - highMin) / highMax <= tolerancePct &&
      highMax > data[i - 2].high &&
      highMax > data[i + 2].high;

    if (equalHigh) {
      const level = (left.high + mid.high + right.high) / 3;
      const key = `eqh_${Math.round(level * 100)}_${left.time}_${right.time}`;

      if (!seen.has(key)) {
        seen.add(key);
        pools.push({
          type: "equal_high",
          startTime: left.time,
          endTime: right.time,
          level,
        });
      }
    }

    const equalLow =
      (lowMax - lowMin) / lowMax <= tolerancePct &&
      lowMin < data[i - 2].low &&
      lowMin < data[i + 2].low;

    if (equalLow) {
      const level = (left.low + mid.low + right.low) / 3;
      const key = `eql_${Math.round(level * 100)}_${left.time}_${right.time}`;

      if (!seen.has(key)) {
        seen.add(key);
        pools.push({
          type: "equal_low",
          startTime: left.time,
          endTime: right.time,
          level,
        });
      }
    }
  }

  return pools;
}

function detectSweeps(data: Candle[], pools: any[]) {
  const sweeps: any[] = [];

  pools.forEach((p) => {
    for (let i = 0; i < data.length; i++) {
      const c = data[i];

      if (p.type === "equal_high" && c.high > p.level && c.close < p.level) {
        sweeps.push({ type: "sweep_high", time: c.time, price: c.high });
      }

      if (p.type === "equal_low" && c.low < p.level && c.close > p.level) {
        sweeps.push({ type: "sweep_low", time: c.time, price: c.low });
      }
    }
  });

  return sweeps;
}

function detectSniperEntry(sweeps: any[], ob: any[], fvg: any[]) {
  const entries: any[] = [];

  sweeps.forEach((s) => {
    ob.forEach((o) => {
      fvg.forEach((f) => {
        const isTrendValid =
          (s.type === "sweep_low" && o.type === "bullish") ||
          (s.type === "sweep_high" && o.type === "bearish");

        const entry = s.price;
        const sl = o.type === "bullish" ? o.bottom : o.top;
        const tp = f.type === "bullish" ? f.top : f.bottom;

        const risk = Math.abs(entry - sl);
        const reward = Math.abs(tp - entry);
        const isRRValid = reward / risk >= 3;

        if (!isTrendValid || !isRRValid) return;

        if (
          s.type === "sweep_low" &&
          o.type === "bullish" &&
          f.type === "bullish" &&
          s.price >= o.bottom &&
          s.price <= o.top
        ) {
          entries.push({
            type: "BUY",
            time: s.time,
            price: s.price,
            sl: o.bottom,
            tp: f.top,
          });
        }

        if (
          s.type === "sweep_high" &&
          o.type === "bearish" &&
          f.type === "bearish" &&
          s.price <= o.top &&
          s.price >= o.bottom
        ) {
          entries.push({
            type: "SELL",
            time: s.time,
            price: s.price,
            sl: o.bottom,
            tp: f.top,
          });
        }
      });
    });
  });

  return entries;
}

function detectPseudoLiquidationZones(data: Candle[], pools: any[]): Zone[] {
  const zones: Zone[] = [];
  const seen = new Set<string>();

  const avgRange =
    data.reduce((acc, c) => acc + Math.max(c.high - c.low, 1), 0) /
    Math.max(data.length, 1);

  const avgVol =
    data.reduce((acc, c) => acc + (c.volume ?? 0), 0) /
    Math.max(data.length, 1);

  const pushZone = (
    level: number,
    side: "bullish" | "bearish",
    strength: number,
    time: number,
    label: string
  ) => {
    const key = `${side}_${Math.round(level * 10)}`;
    if (seen.has(key)) return;
    seen.add(key);
    zones.push({ level, type: side, strength, time, label });
  };

  for (let i = 2; i < data.length - 2; i++) {
    const prev = data[i - 1];
    const curr = data[i];
    const next = data[i + 1];

    const vol = curr.volume ?? 0;
    const volBoost = avgVol > 0 ? Math.min(2.5, vol / avgVol) : 1;

    const swingHigh = curr.high > prev.high && curr.high > next.high;
    const swingLow = curr.low < prev.low && curr.low < next.low;

    if (swingHigh) {
      const wick = Math.max(curr.high - Math.max(curr.open, curr.close), 0);
      const strength = 1 + wick / avgRange + volBoost * 0.6;
      pushZone(curr.high, "bearish", strength, curr.time, "SHORT LIQ");
    }

    if (swingLow) {
      const wick = Math.max(Math.min(curr.open, curr.close) - curr.low, 0);
      const strength = 1 + wick / avgRange + volBoost * 0.6;
      pushZone(curr.low, "bullish", strength, curr.time, "LONG LIQ");
    }

    const body = Math.abs(curr.close - curr.open);
    const spike = avgVol > 0 && vol > avgVol * 1.8;

    if (spike && body > avgRange * 0.2) {
      const level = curr.close;
      const side = curr.close >= curr.open ? "bearish" : "bullish";
      const strength = 1.2 + volBoost;
      pushZone(
        level,
        side,
        strength,
        curr.time,
        side === "bearish" ? "PUSH UP" : "PUSH DOWN"
      );
    }
  }

  pools.forEach((p) => {
    if (p.type === "equal_high") {
      pushZone(p.level, "bearish", 1.8, p.startTime, "EQH LIQ");
    }
    if (p.type === "equal_low") {
      pushZone(p.level, "bullish", 1.8, p.startTime, "EQL LIQ");
    }
  });

  return zones.sort((a, b) => b.strength - a.strength).slice(0, 24);
}

function createOverlayCanvas(container: HTMLDivElement) {
  const canvas = document.createElement("canvas");
  canvas.style.position = "absolute";
  canvas.style.top = "0";
  canvas.style.left = "0";
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.pointerEvents = "none";
  canvas.style.zIndex = "5";

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(container.clientWidth * dpr);
  canvas.height = Math.floor(500 * dpr);

  const ctx = canvas.getContext("2d");
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  container.appendChild(canvas);

  return {
    canvas,
    ctx,
    resize: () => {
      const ndpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(container.clientWidth * ndpr);
      canvas.height = Math.floor(500 * ndpr);
      const nctx = canvas.getContext("2d");
      if (nctx) nctx.setTransform(ndpr, 0, 0, ndpr, 0, 0);
    },
    clear: () => {
      const c = canvas.getContext("2d");
      if (!c) return;
      c.clearRect(0, 0, container.clientWidth || 1000, 500);
    },
    destroy: () => canvas.remove(),
  };
}

async function drawLiquidationHeatmapAndFootprint(
  chart: any,
  symbol: string,
  overlay: {
    clear: () => void;
    canvas: HTMLCanvasElement;
    ctx: CanvasRenderingContext2D | null;
    resize: () => void;
  },
  candles: Candle[],
  liqZones: Zone[],
  trend: string,
  bias: AlertMode
) {
  if (!overlay.ctx) return;

  try {
    const res = await axios.get(
      `https://api.binance.com/api/v3/depth?symbol=${symbol}&limit=100`
    );

    const bids = res.data?.bids ?? [];
    const asks = res.data?.asks ?? [];

    const levels = [
      ...bids.map((b: any) => ({
        side: "bid",
        price: Number(b[0]),
        size: Number(b[1]),
      })),
      ...asks.map((a: any) => ({
        side: "ask",
        price: Number(a[0]),
        size: Number(a[1]),
      })),
    ].filter((x: any) => Number.isFinite(x.price) && Number.isFinite(x.size));

    overlay.clear();

    const ctx = overlay.ctx;
    const width = overlay.canvas.clientWidth || 1000;
    const height = overlay.canvas.clientHeight || 500;
    const panelH = 94;
    const priceAreaH = height - panelH;
    const maxSize = Math.max(...levels.map((x: any) => x.size), 1);

    if (trend === "RANGE") {
      ctx.save();
      ctx.fillStyle = "rgba(255,255,0,0.05)";
      ctx.fillRect(0, 0, width, height);
      ctx.restore();
    }

    liqZones.forEach((z) => {
      const y = chart.priceScale("right").priceToCoordinate(z.level);
      if (y === null || y === undefined || !Number.isFinite(y)) return;

      const intensity = Math.max(0.12, Math.min(0.7, z.strength / 4));
      const bandH = 10 + z.strength * 12;
      const top = y - bandH / 2;

      ctx.save();

      ctx.fillStyle =
        z.type === "bullish"
          ? `rgba(0,255,150,${intensity})`
          : `rgba(255,80,80,${intensity})`;

      ctx.shadowBlur = 18 + z.strength * 12;
      ctx.shadowColor =
        z.type === "bullish"
          ? `rgba(0,255,150,${intensity})`
          : `rgba(255,80,80,${intensity})`;

      ctx.fillRect(0, top, width, bandH);

      ctx.shadowBlur = 0;
      ctx.strokeStyle =
        z.type === "bullish" ? "rgba(0,255,150,0.95)" : "rgba(255,80,80,0.95)";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(0, top, width, bandH);
      ctx.setLineDash([]);

      ctx.strokeStyle =
        z.type === "bullish" ? "rgba(0,255,150,0.95)" : "rgba(255,80,80,0.95)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, top);
      ctx.lineTo(width, top);
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(0, top + bandH);
      ctx.lineTo(width, top + bandH);
      ctx.stroke();

      ctx.fillStyle =
        z.type === "bullish" ? "rgba(0,255,150,1)" : "rgba(255,80,80,1)";
      ctx.font = "bold 11px monospace";
      ctx.fillText(`${z.label} ${z.level.toFixed(2)}`, 10, Math.max(12, top - 3));

      ctx.save();
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      const boxW = 128;
      const boxH = 16;
      const boxX = width - boxW - 8;
      const boxY = Math.max(2, y - boxH / 2);
      ctx.fillRect(boxX, boxY, boxW, boxH);

      ctx.fillStyle = "#fff";
      ctx.font = "10px monospace";
      ctx.fillText(`${z.label} (${z.strength.toFixed(1)})`, boxX + 6, boxY + 11);
      ctx.restore();

      ctx.fillStyle = z.type === "bullish" ? "#00FFAA" : "#FF4444";
      ctx.font = "bold 12px monospace";
      ctx.fillText(z.type === "bullish" ? "▲" : "▼", width / 2, Math.max(12, y + 4));

      ctx.restore();
    });

    if (liqZones.length > 0 && bias !== "NO TRADE" && bias !== "WAIT") {
      const z = liqZones[0];
      const y = chart.priceScale("right").priceToCoordinate(z.level);
      if (y !== null && y !== undefined && Number.isFinite(y)) {
        ctx.save();

        ctx.strokeStyle = bias === "LONG" ? "#00FFAA" : "#FF4444";
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);

        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();

        ctx.setLineDash([]);
        ctx.fillStyle = bias === "LONG" ? "#00FFAA" : "#FF4444";
        ctx.font = "bold 12px monospace";
        ctx.fillText(`🎯 ${bias} ZONE`, width / 2 - 40, y - 6);

        ctx.restore();
      }
    }

    levels.forEach((x: any) => {
      if (x.size < 5) return;

      const y = chart.priceScale("right").priceToCoordinate(x.price);
      if (y === null || y === undefined || !Number.isFinite(y)) return;
      if (y > priceAreaH + 12) return;

      const intensity = x.size / maxSize;
      const alpha = Math.max(0.03, Math.min(0.8, intensity));
      const bandHeight = 2 + intensity * 16;
      const top = y - bandHeight / 2;
      const isBid = x.side === "bid";

      ctx.save();
      ctx.fillStyle = isBid
        ? `rgba(0,229,255,${alpha})`
        : `rgba(255,80,80,${alpha})`;
      ctx.shadowBlur = 14 + intensity * 18;
      ctx.shadowColor = isBid
        ? `rgba(0,229,255,${alpha})`
        : `rgba(255,80,80,${alpha})`;

      ctx.fillRect(0, top, width, bandHeight);
      ctx.restore();
    });

    if (candles.length > 0) {
      const last = candles[candles.length - 1];
      const y = chart.priceScale("right").priceToCoordinate(last.close);
      if (y !== null && y !== undefined && Number.isFinite(y) && y < priceAreaH) {
        ctx.save();
        ctx.strokeStyle = "rgba(255,255,255,0.65)";
        ctx.setLineDash([6, 6]);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(255,255,255,0.8)";
        ctx.font = "12px sans-serif";
        ctx.fillText(`LIVE ${last.close.toFixed(2)}`, width - 110, Math.max(12, y - 6));
        ctx.restore();
      }
    }

    const deltas = candles.map((c) => {
      const vol = c.volume && Number.isFinite(c.volume) ? c.volume : 1;
      const direction = c.close >= c.open ? 1 : -1;
      return (c.close - c.open) * vol * direction;
    });

    const maxAbs = Math.max(...deltas.map((d) => Math.abs(d)), 1);
    const barWidth = Math.max(2, width / Math.max(candles.length, 1));
    const panelTop = priceAreaH;
    const baseY = panelTop + panelH * 0.62;
    const panelMaxHeight = panelH * 0.45;

    ctx.save();
    ctx.fillStyle = "rgba(255,255,255,0.12)";
    ctx.fillRect(0, panelTop, width, 1);

    ctx.fillStyle = "rgba(255,255,255,0.55)";
    ctx.font = "11px sans-serif";
    ctx.fillText("FOOTPRINT DELTA", 10, panelTop + 14);

    deltas.forEach((delta, idx) => {
      const norm = delta / maxAbs;
      const barH = Math.max(2, Math.abs(norm) * panelMaxHeight);
      const x = idx * barWidth;
      const y = norm >= 0 ? baseY - barH : baseY;

      ctx.fillStyle =
        norm >= 0 ? "rgba(0,229,255,0.75)" : "rgba(255,80,80,0.75)";

      ctx.fillRect(x, y, Math.max(1, barWidth * 0.78), barH);
    });

    ctx.fillStyle = "rgba(255,255,255,0.28)";
    ctx.fillRect(0, baseY, width, 1);
    ctx.restore();

    ctx.save();

    let color = "#aaa";
    if (trend === "BULL") color = "#00FFAA";
    if (trend === "BEAR") color = "#FF5555";

    ctx.fillStyle = color;
    ctx.font = "12px monospace";
    ctx.fillText(`TREND: ${trend}`, 10, 20);

    if (trend === "RANGE") {
      ctx.fillStyle = "rgba(255,200,0,0.9)";
      ctx.fillText("⚠ RANGE MARKET", 10, 36);
    }

    ctx.restore();

    ctx.save();

    let biasColor = "#aaa";
    if (bias === "LONG") biasColor = "#00FFAA";
    if (bias === "SHORT") biasColor = "#FF4444";
    if (bias === "WAIT") biasColor = "#FFB000";

    ctx.fillStyle = biasColor;
    ctx.font = "bold 12px monospace";
    ctx.fillText(`BIAS: ${bias}`, 10, 52);

    ctx.fillStyle =
      bias === "LONG" ? "#00FFAA" : bias === "SHORT" ? "#FF4444" : "#FFB000";
    ctx.font = "bold 14px monospace";
    ctx.fillText(cinematicLabel(bias), 10, 70);

    ctx.restore();

    // ===== BADGE ALERT KANAN ATAS =====
    ctx.save();

    const badgeText =
      bias === "LONG"
        ? "SAFE LONG"
        : bias === "SHORT"
        ? "SAFE SHORT"
        : bias === "WAIT"
        ? "WATCH MODE"
        : "NO TRADE";

    let bgColor = "rgba(120,120,120,0.25)";
    let glow = "rgba(255,255,255,0.2)";

    if (bias === "LONG") {
      bgColor = "rgba(0,255,150,0.18)";
      glow = "rgba(0,255,150,0.6)";
    }
    if (bias === "SHORT") {
      bgColor = "rgba(255,80,80,0.18)";
      glow = "rgba(255,80,80,0.6)";
    }
    if (bias === "WAIT") {
      bgColor = "rgba(255,180,0,0.18)";
      glow = "rgba(255,180,0,0.6)";
    }

    const boxW = 140;
    const boxH = 34;
    const x = width - boxW - 12;
    const y = 12;

    // background
    ctx.fillStyle = bgColor;
    ctx.shadowBlur = 20;
    ctx.shadowColor = glow;
    ctx.fillRect(x, y, boxW, boxH);

    // border
    ctx.shadowBlur = 0;
    ctx.strokeStyle = glow;
    ctx.lineWidth = 1.2;
    ctx.strokeRect(x, y, boxW, boxH);

    // text
    ctx.fillStyle = "#fff";
    ctx.font = "bold 13px monospace";
    ctx.fillText(badgeText, x + 14, y + 21);

    // mini dot indicator
    ctx.beginPath();
    ctx.arc(x + 8, y + 17, 4, 0, Math.PI * 2);
    ctx.fillStyle =
      bias === "LONG"
        ? "#00FFAA"
        : bias === "SHORT"
        ? "#FF4444"
        : bias === "WAIT"
        ? "#FFB000"
        : "#999";
    ctx.fill();

    ctx.restore();

    // ===== REAL ALERT TRIGGER =====
    const signal = bias === "LONG" ? "SAFE LONG" :
                   bias === "SHORT" ? "SAFE SHORT" : "";

    if (signal && signal !== lastAlert) {
      lastAlert = signal;

      // 🔔 sound
      alertSound.play().catch(() => {});

      // 📢 browser notification
      if (Notification.permission === "granted") {
        new Notification("MONTRA SIGNAL 🚀", {
          body: `${symbol} → ${signal}`,
        });
      }
    }

  } catch {
    // ignore orderbook errors
  }
}

export default function Chart({ symbol }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    Notification.requestPermission();
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML = "";
    container.style.position = "relative";

    const overlay = createOverlayCanvas(container);

    const chart = createChart(container, {
      width: container.clientWidth || 1000,
      height: 500,
      layout: {
        background: { color: "#111111" },
        textColor: "#E5E7EB",
      },
      grid: {
        vertLines: { color: "#222222" },
        horzLines: { color: "#222222" },
      },
      rightPriceScale: {
        borderColor: "#2A2A2A",
      },
      timeScale: {
        borderColor: "#2A2A2A",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addCandlestickSeries();
    let alive = true;
    let latestCandles: Candle[] = [];
    let latestZones: Zone[] = [];
    let latestTrend: string = "RANGE";
    let latestBias: AlertMode = "NO TRADE";

    const loadData = async () => {
      try {
        const res = await axios.get(
          `https://montra-backend-9wku.onrender.com/ohlcv/${symbol}?timeframe=15m&limit=100`
        );

        const raw = res.data?.data ?? [];
        const data: Candle[] = raw
          .map((c: any) => ({
            time: Math.floor(Number(c.time) / 1000),
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
            volume: Number(c.volume ?? 0),
          }))
          .filter(
            (c: Candle) =>
              Number.isFinite(c.time) &&
              Number.isFinite(c.open) &&
              Number.isFinite(c.high) &&
              Number.isFinite(c.low) &&
              Number.isFinite(c.close)
          );

        if (!alive) return;

        latestCandles = data;

        const htfRes = await axios.get(
          `https://montra-backend-9wku.onrender.com/ohlcv/${symbol}?timeframe=1h&limit=100`
        );

        const htfData: Candle[] = (htfRes.data?.data ?? []).map((c: any) => ({
          time: Math.floor(Number(c.time) / 1000),
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
        }));

        latestTrend = detectHTFTrend(htfData);

        const structure = detectStructure(data);
        const fvg = detectFVG(data);
        const ob = detectOrderBlock(data);
        const pools = detectLiquidityPools(data);
        const sweeps = detectSweeps(data, pools);
        const entries = detectSniperEntry(sweeps, ob, fvg);

        const rawZones = detectPseudoLiquidationZones(data, pools);
        latestZones = filterTopZones(rawZones);
        latestBias = detectAutoBias(latestTrend, latestZones);

        candleSeries.setData(data as any);

        const markers: any[] = [
          ...structure.map((s: any) => ({
            time: s.time,
            position: s.type === "HH" ? "aboveBar" : "belowBar",
            color: s.type === "HH" ? "green" : "red",
            shape: s.type === "HH" ? "arrowDown" : "arrowUp",
            text: s.type,
          })),
          ...ob.map((z: any) => ({
            time: z.startTime,
            position: z.type === "bullish" ? "belowBar" : "aboveBar",
            color: z.type === "bullish" ? "#00E5FF" : "#FFB000",
            shape: "circle",
            text: z.type === "bullish" ? "OB+" : "OB-",
          })),
          ...pools.map((p: any) => ({
            time: p.startTime,
            position: p.type === "equal_high" ? "aboveBar" : "belowBar",
            color: p.type === "equal_high" ? "#B388FF" : "#FF6D00",
            shape: "diamond",
            text: p.type === "equal_high" ? "EQH" : "EQL",
          })),
          ...sweeps.map((s: any) => ({
            time: s.time,
            position: s.type === "sweep_high" ? "aboveBar" : "belowBar",
            color: "#FF1744",
            shape: "arrowDown",
            text: s.type === "sweep_high" ? "SWEEP↑" : "SWEEP↓",
          })),
          ...entries.map((e: any) => ({
            time: e.time,
            position: e.type === "BUY" ? "belowBar" : "aboveBar",
            color: e.type === "BUY" ? "#00FF00" : "#FF0000",
            shape: "arrowUp",
            text: `${e.type}\nSL:${e.sl.toFixed(0)}\nTP:${e.tp.toFixed(0)}`,
          })),
        ].sort((a, b) => a.time - b.time);

        candleSeries.setMarkers(markers as any);

        fvg.forEach((zone: any) => {
          const upper = chart.addLineSeries({
            color:
              zone.type === "bullish"
                ? "rgba(0,255,0,0.35)"
                : "rgba(255,0,0,0.35)",
            lineWidth: 2,
          });

          upper.setData([
            { time: zone.startTime, value: zone.top },
            { time: zone.endTime, value: zone.top },
          ]);

          const lower = chart.addLineSeries({
            color:
              zone.type === "bullish"
                ? "rgba(0,255,0,0.35)"
                : "rgba(255,0,0,0.35)",
            lineWidth: 2,
          });

          lower.setData([
            { time: zone.startTime, value: zone.bottom },
            { time: zone.endTime, value: zone.bottom },
          ]);
        });

        ob.forEach((zone: any) => {
          const upper = chart.addLineSeries({
            color:
              zone.type === "bullish"
                ? "rgba(0,229,255,0.45)"
                : "rgba(255,176,0,0.45)",
            lineWidth: 2,
          });

          upper.setData([
            { time: zone.startTime, value: zone.top },
            { time: zone.endTime, value: zone.top },
          ]);

          const lower = chart.addLineSeries({
            color:
              zone.type === "bullish"
                ? "rgba(0,229,255,0.45)"
                : "rgba(255,176,0,0.45)",
            lineWidth: 2,
          });

          lower.setData([
            { time: zone.startTime, value: zone.bottom },
            { time: zone.endTime, value: zone.bottom },
          ]);
        });

        pools.forEach((pool: any) => {
          const line = chart.addLineSeries({
            color:
              pool.type === "equal_high"
                ? "rgba(179,136,255,0.55)"
                : "rgba(255,109,0,0.55)",
            lineWidth: 2,
          });

          line.setData([
            { time: pool.startTime, value: pool.level },
            { time: pool.endTime, value: pool.level },
          ]);
        });

        chart.timeScale().fitContent();

        await drawLiquidationHeatmapAndFootprint(
          chart,
          symbol,
          overlay,
          latestCandles,
          latestZones,
          latestTrend,
          latestBias
        );
      } catch (err) {
        console.error("Gagal load chart:", err);
      }
    };

    loadData();

    const redrawOverlay = async () => {
      if (!alive) return;
      await drawLiquidationHeatmapAndFootprint(
        chart,
        symbol,
        overlay,
        latestCandles,
        latestZones,
        latestTrend,
        latestBias
      );
    };

    const interval = setInterval(redrawOverlay, 3000);

    const handleResize = () => {
      if (!containerRef.current) return;

      chart.applyOptions({
        width: containerRef.current.clientWidth || 1000,
      });

      overlay.resize();
      redrawOverlay();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      alive = false;
      clearInterval(interval);
      window.removeEventListener("resize", handleResize);
      overlay.destroy();
      chart.remove();
    };
  }, [symbol]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "500px",
        minHeight: "500px",
        background: "#111111",
        border: "1px solid #222",
        borderRadius: "12px",
        overflow: "hidden",
        position: "relative",
      }}
    />
  );
}