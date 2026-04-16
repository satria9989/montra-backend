import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { createChart, UTCTimestamp } from "lightweight-charts";

// 🔔 SOUND ALERT
const alertSound = new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg");

// 🚫 anti spam
let lastAlert = "";

type Signal = {
  symbol: string;
  type: "BUY" | "SELL";
  entry: number;
  sl: number;
  tp: number;
};

type Props = {
  symbol: string;
  selected?: Signal | null;
};

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
  level: number;
  strength: number;
  time: UTCTimestamp;
  label: string;
};

type AlertMode = "LONG" | "SHORT" | "WAIT" | "NO TRADE";

type ViewMode = "SCAN" | "ANALYSIS" | "DEBUG";

// ========== MARKET STATE ENGINE ==========
function detectMarketState(trend: string, liqZones: Zone[]) {
  if (trend === "RANGE") return "ACCUMULATION";
  if (liqZones.length > 10) return "MANIPULATION";
  return "EXPANSION";
}

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
    time: UTCTimestamp,
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
  candleSeries: any,
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
  bias: AlertMode,
  mode: ViewMode,
  selectedSignal?: Signal | null,
  lastPrice?: number,
  htfZones?: any[] // tambahan HTF zones (OB + FVG dari 1h)
) {
  if (!overlay.ctx) return;
  overlay.clear();
  const ctx = overlay.ctx;
  const width = overlay.canvas.clientWidth || 1000;
  const height = overlay.canvas.clientHeight || 500;
  const panelH = 94;
  const priceAreaH = height - panelH;

  // ===== MARKET STATE ENGINE =====
  const marketState = detectMarketState(trend, liqZones);
  ctx.save();
  let stateColor = "#FFB000";
  if (marketState === "EXPANSION") stateColor = "#00FFAA";
  if (marketState === "MANIPULATION") stateColor = "#FF4444";
  ctx.fillStyle = stateColor;
  ctx.font = "bold 11px monospace";
  ctx.fillText(`STATE: ${marketState}`, width - 150, 80);
  ctx.restore();

  // ===== BASE INFO (selalu ditampilkan) =====
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
  ctx.fillStyle = bias === "LONG" ? "#00FFAA" : bias === "SHORT" ? "#FF4444" : "#FFB000";
  ctx.font = "bold 14px monospace";
  ctx.fillText(cinematicLabel(bias), 10, 70);
  ctx.restore();

  // Badge kanan atas
  ctx.save();
  const badgeText = bias === "LONG" ? "SAFE LONG" : bias === "SHORT" ? "SAFE SHORT" : bias === "WAIT" ? "WATCH MODE" : "NO TRADE";
  let bgColor = "rgba(120,120,120,0.25)";
  let glow = "rgba(255,255,255,0.2)";
  if (bias === "LONG") { bgColor = "rgba(0,255,150,0.18)"; glow = "rgba(0,255,150,0.6)"; }
  if (bias === "SHORT") { bgColor = "rgba(255,80,80,0.18)"; glow = "rgba(255,80,80,0.6)"; }
  if (bias === "WAIT") { bgColor = "rgba(255,180,0,0.18)"; glow = "rgba(255,180,0,0.6)"; }
  const boxW = 140, boxH = 34, x = width - boxW - 12, y = 12;
  ctx.fillStyle = bgColor;
  ctx.shadowBlur = 20;
  ctx.shadowColor = glow;
  ctx.fillRect(x, y, boxW, boxH);
  ctx.shadowBlur = 0;
  ctx.strokeStyle = glow;
  ctx.lineWidth = 1.2;
  ctx.strokeRect(x, y, boxW, boxH);
  ctx.fillStyle = "#fff";
  ctx.font = "bold 13px monospace";
  ctx.fillText(badgeText, x + 14, y + 21);
  ctx.beginPath();
  ctx.arc(x + 8, y + 17, 4, 0, Math.PI * 2);
  ctx.fillStyle = bias === "LONG" ? "#00FFAA" : bias === "SHORT" ? "#FF4444" : bias === "WAIT" ? "#FFB000" : "#999";
  ctx.fill();
  ctx.restore();

  // LIVE PRICE DISTANCE dari selected signal (jika ada dan mode bukan SCAN)
  if (selectedSignal && mode !== "SCAN" && lastPrice !== undefined) {
    const distance = ((lastPrice - selectedSignal.entry) / selectedSignal.entry) * 100;
    const sign = distance >= 0 ? "+" : "";
    const distanceText = `${sign}${distance.toFixed(2)}% dari entry`;
    ctx.save();
    ctx.fillStyle = "#FFD966";
    ctx.font = "bold 11px monospace";
    ctx.fillText(distanceText, width - 160, height - 12);
    ctx.restore();
  }

  // LIVE TRADE STATUS (PnL)
  if (selectedSignal && mode !== "SCAN" && lastPrice !== undefined) {
    const pnl = ((lastPrice - selectedSignal.entry) / selectedSignal.entry) * 100;
    ctx.save();
    ctx.fillStyle = pnl > 0 ? "#00FFAA" : "#FF4444";
    ctx.font = "bold 12px monospace";
    ctx.fillText(`PnL: ${pnl.toFixed(2)}%`, width - 120, height - 28);
    ctx.restore();
  }

  // Garis harga terakhir
  if (candles.length > 0) {
    const last = candles[candles.length - 1];
    const yPrice = candleSeries.priceToCoordinate(last.close);
    if (yPrice !== null && yPrice !== undefined && Number.isFinite(yPrice) && yPrice < priceAreaH) {
      ctx.save();
      ctx.strokeStyle = "rgba(255,255,255,0.65)";
      ctx.setLineDash([6, 6]);
      ctx.beginPath();
      ctx.moveTo(0, yPrice);
      ctx.lineTo(width, yPrice);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(255,255,255,0.8)";
      ctx.font = "12px sans-serif";
      ctx.fillText(`LIVE ${last.close.toFixed(2)}`, width - 110, Math.max(12, yPrice - 6));
      ctx.restore();
    }
  }

  // ===== HTF ZONES (OB + FVG dari 1h) transparan, hanya untuk ANALYSIS/DEBUG =====
  if ((mode === "ANALYSIS" || mode === "DEBUG") && htfZones && htfZones.length > 0) {
    htfZones.forEach((z: any) => {
      const yTop = candleSeries.priceToCoordinate(z.top);
      const yBottom = candleSeries.priceToCoordinate(z.bottom);
      if (yTop === null || yBottom === null || yTop === undefined || yBottom === undefined) return;
      const topY = Math.min(yTop, yBottom);
      const bottomY = Math.max(yTop, yBottom);
      ctx.save();
      ctx.fillStyle = z.type === "bullish"
        ? "rgba(0,255,150,0.08)"
        : "rgba(255,80,80,0.08)";
      ctx.fillRect(0, topY, width, bottomY - topY);
      ctx.restore();
    });
  }

  // ===== TOP LIQUIDITY ZONES (TARGET MARKET MAKER) =====
  if ((mode === "ANALYSIS" || mode === "DEBUG") && liqZones.length > 0) {
    const topLiquidity = liqZones.slice(0, 3);
    topLiquidity.forEach((z) => {
      const y = candleSeries.priceToCoordinate(z.level);
      if (y === null || y === undefined || !Number.isFinite(y)) return;
      ctx.save();
      ctx.strokeStyle = "#FFD700";
      ctx.lineWidth = 2;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
      ctx.fillStyle = "#FFD700";
      ctx.font = "bold 10px monospace";
      ctx.fillText("TARGET", width - 80, y - 4);
      ctx.restore();
    });
  }

  // Jika bukan mode DEBUG, hanya info dasar + HTF zones + top liquidity (sudah ditampilkan)
  if (mode !== "DEBUG") {
    return;
  }

  // ===== DEBUG: FULL HEATMAP, LIQUIDATION ZONES, FOOTPRINT =====
  try {
    // 🔥 DIRECT BINANCE (ANTI BACKEND MATI)
    const res = await axios.get(
      `https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=15m&limit=100`
    );
    
    const raw = res.data.map((c: any[]) => ({
      time: c[0],
      open: c[1],
      high: c[2],
      low: c[3],
      close: c[4],
      volume: c[5],
    }));
    const bids = res.data?.bids ?? [];
    const asks = res.data?.asks ?? [];
    const levels = [
      ...bids.map((b: any) => ({ side: "bid", price: Number(b[0]), size: Number(b[1]) })),
      ...asks.map((a: any) => ({ side: "ask", price: Number(a[0]), size: Number(a[1]) })),
    ].filter((x: any) => Number.isFinite(x.price) && Number.isFinite(x.size));

    const maxSize = Math.max(...levels.map((x: any) => x.size), 1);

    // RANGE background
    if (trend === "RANGE") {
      ctx.save();
      ctx.fillStyle = "rgba(255,255,0,0.05)";
      ctx.fillRect(0, 0, width, height);
      ctx.restore();
    }

    // Liquidation zones (semua)
    liqZones.forEach((z) => {
      const y = candleSeries.priceToCoordinate(z.level);
      if (y === null || y === undefined || !Number.isFinite(y)) return;
      const intensity = Math.max(0.12, Math.min(0.7, z.strength / 4));
      const bandH = 10 + z.strength * 12;
      const top = y - bandH / 2;
      ctx.save();
      ctx.fillStyle = z.type === "bullish" ? `rgba(0,255,150,${intensity})` : `rgba(255,80,80,${intensity})`;
      ctx.shadowBlur = 18 + z.strength * 12;
      ctx.shadowColor = z.type === "bullish" ? `rgba(0,255,150,${intensity})` : `rgba(255,80,80,${intensity})`;
      ctx.fillRect(0, top, width, bandH);
      ctx.shadowBlur = 0;
      ctx.strokeStyle = z.type === "bullish" ? "rgba(0,255,150,0.95)" : "rgba(255,80,80,0.95)";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(0, top, width, bandH);
      ctx.setLineDash([]);
      ctx.strokeStyle = z.type === "bullish" ? "rgba(0,255,150,0.95)" : "rgba(255,80,80,0.95)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, top);
      ctx.lineTo(width, top);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, top + bandH);
      ctx.lineTo(width, top + bandH);
      ctx.stroke();
      ctx.fillStyle = z.type === "bullish" ? "rgba(0,255,150,1)" : "rgba(255,80,80,1)";
      ctx.font = "bold 11px monospace";
      ctx.fillText(`${z.label} ${z.level.toFixed(2)}`, 10, Math.max(12, top - 3));
      ctx.save();
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      const boxW = 128, boxH = 16, boxX = width - boxW - 8, boxY = Math.max(2, y - boxH / 2);
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
      const y = candleSeries.priceToCoordinate(z.level);
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

    // Orderbook heatmap
    levels.forEach((x: any) => {
      if (x.size < 5) return;
      const y = candleSeries.priceToCoordinate(x.price);
      if (y === null || y === undefined || !Number.isFinite(y)) return;
      if (y > priceAreaH + 12) return;
      const intensity = x.size / maxSize;
      const alpha = Math.max(0.03, Math.min(0.8, intensity));
      const bandHeight = 2 + intensity * 16;
      const top = y - bandHeight / 2;
      const isBid = x.side === "bid";
      ctx.save();
      ctx.fillStyle = isBid ? `rgba(0,229,255,${alpha})` : `rgba(255,80,80,${alpha})`;
      ctx.shadowBlur = 14 + intensity * 18;
      ctx.shadowColor = isBid ? `rgba(0,229,255,${alpha})` : `rgba(255,80,80,${alpha})`;
      ctx.fillRect(0, top, width, bandHeight);
      ctx.restore();
    });

    // Footprint delta
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
      ctx.fillStyle = norm >= 0 ? "rgba(0,229,255,0.75)" : "rgba(255,80,80,0.75)";
      ctx.fillRect(x, y, Math.max(1, barWidth * 0.78), barH);
    });
    ctx.fillStyle = "rgba(255,255,255,0.28)";
    ctx.fillRect(0, baseY, width, 1);
    ctx.restore();
  } catch {
    // ignore orderbook errors
  }

  // Alert suara & notifikasi
  const signal = bias === "LONG" ? "SAFE LONG" : bias === "SHORT" ? "SAFE SHORT" : "";
  if (signal && signal !== lastAlert) {
    lastAlert = signal;
    alertSound.play().catch(() => {});
    if (Notification.permission === "granted") {
      new Notification("MONTRA SIGNAL 🚀", { body: `${symbol} → ${signal}` });
    }
  }
}

export default function Chart({ symbol, selected }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<ViewMode>("SCAN");
  const extraSeriesRef = useRef<any[]>([]);
  const [htfZones, setHtfZones] = useState<any[]>([]); // HTF zones (OB + FVG dari 1h)

  useEffect(() => {
    Notification.requestPermission();
  }, []);

  // Fungsi untuk mengambil HTF data (1h) dan mengekstrak OB & FVG
  const loadHTF = async (symbol: string) => {
    try {
      const res = await axios.get(
        `https://montra-backend-9wku.onrender.com/ohlcv/${symbol}?timeframe=1h&limit=100`
      );
      const raw = res.data?.data ?? [];
      const htfCandles: Candle[] = raw.map((c: any) => ({
        time: Math.floor(Number(c.time) / 1000) as UTCTimestamp,
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
        volume: Number(c.volume ?? 0),
      }));
      const ob = detectOrderBlock(htfCandles);
      const fvg = detectFVG(htfCandles);
      setHtfZones([...ob, ...fvg]);
    } catch (err) {
      console.error("Gagal load HTF:", err);
    }
  };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
	if (container.clientWidth === 0) {
	  console.log("❌ container width 0");
	  return;
	}

    container.innerHTML = "";
    container.style.position = "relative";

    const overlay = createOverlayCanvas(container);

    const chart = createChart(container, {
      width: container.clientWidth || 1000,
      height: 500,
      layout: {
        background: { color: "#0B0F14" },
        textColor: "#AAB4C3",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.03)" },
        horzLines: { color: "rgba(255,255,255,0.03)" },
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
        // Load HTF zones terlebih dahulu (atau paralel)
        loadHTF(symbol); // jangan pakai await

        const res = await axios.get(
          `https://montra-backend-9wku.onrender.com/ohlcv/${symbol}?timeframe=15m&limit=100`
        );
        const raw = res.data?.data ?? [];

        console.log("🔥 RAW DATA:", raw);
        
        if (!Array.isArray(raw) || raw.length === 0) {
          console.log("❌ DATA KOSONG DARI BACKEND");
          return;
        }
        const data: Candle[] = raw
          .map((c: any) => ({
            time: Math.floor(Number(c.time) / 1000) as UTCTimestamp,
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
          time: Math.floor(Number(c.time) / 1000) as UTCTimestamp,
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

        console.log("📊 FINAL DATA:", data);
		candleSeries.setData(data as any);

        // Hapus semua extra series sebelumnya
        extraSeriesRef.current.forEach((s) => chart.removeSeries(s));
        extraSeriesRef.current = [];

        // Mode SCAN: hanya candle + bias (tanpa marker/tambahan)
        if (mode === "SCAN") {
          candleSeries.setMarkers([]);
        }

        // Mode ANALYSIS: hanya menampilkan selected signal jika ada (tanpa debug overlay)
        if (mode === "ANALYSIS") {
          candleSeries.setMarkers([]);
          if (selected) {
            const start = data[0].time;
            const end = data[data.length - 1].time;
            const lastTime = data[data.length - 1].time;
            const isBuy = selected.type === "BUY";

            const entryColor = isBuy ? "#00E5FF" : "#FFB000";
            const tpColor = isBuy ? "#00FFAA" : "#FF4444";
            const slColor = isBuy ? "#FF4444" : "#00FFAA";

            // ENTRY LINE dengan glow
            const entryLine = chart.addLineSeries({
              color: entryColor,
              lineWidth: 2,
              lineStyle: 0,
            });
            entryLine.setData([
              { time: start, value: selected.entry },
              { time: end, value: selected.entry },
            ]);
            extraSeriesRef.current.push(entryLine);

            // SL ZONE (area)
            const slZone = chart.addAreaSeries({
              topColor: "rgba(255,0,0,0.35)",
              bottomColor: "rgba(255,0,0,0.05)",
              lineColor: slColor,
              lineWidth: 1,
            });
            slZone.setData([
              { time: start, value: selected.sl },
              { time: end, value: selected.sl },
            ]);
            extraSeriesRef.current.push(slZone);

            // TP ZONE (area)
            const tpZone = chart.addAreaSeries({
              topColor: "rgba(0,255,150,0.35)",
              bottomColor: "rgba(0,255,150,0.05)",
              lineColor: tpColor,
              lineWidth: 1,
            });
            tpZone.setData([
              { time: start, value: selected.tp },
              { time: end, value: selected.tp },
            ]);
            extraSeriesRef.current.push(tpZone);

            // RR Visual Bar
            const rr = Math.abs(selected.tp - selected.entry) / Math.abs(selected.entry - selected.sl);
            const rrColor = rr >= 3 ? "#00FFAA" : rr >= 2 ? "#FFB000" : "#FF4444";

            entryLine.setMarkers([
              {
                time: lastTime,
                position: "aboveBar",
                color: entryColor,
                shape: "circle",
                text: `ENTRY ${selected.entry} | RR ${rr.toFixed(2)}`,
              },
              {
                time: lastTime,
                position: "aboveBar",
                color: rrColor,
                shape: "arrowUp",
                text: `RR ${rr.toFixed(2)}`,
              },
            ]);

            tpZone.setMarkers([
              {
                time: lastTime,
                position: "aboveBar",
                color: tpColor,
                shape: "arrowUp",
                text: `TP ${selected.tp}`,
              },
            ]);

            slZone.setMarkers([
              {
                time: lastTime,
                position: "belowBar",
                color: slColor,
                shape: "arrowDown",
                text: `SL ${selected.sl}`,
              },
            ]);
          }
        }

        // Mode DEBUG: semua overlay (FVG, OB, pools, markers, dll)
        if (mode === "DEBUG") {
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
              color: zone.type === "bullish" ? "rgba(0,255,0,0.35)" : "rgba(255,0,0,0.35)",
              lineWidth: 2,
            });
            upper.setData([
              { time: zone.startTime, value: zone.top },
              { time: zone.endTime, value: zone.top },
            ]);
            extraSeriesRef.current.push(upper);
            const lower = chart.addLineSeries({
              color: zone.type === "bullish" ? "rgba(0,255,0,0.35)" : "rgba(255,0,0,0.35)",
              lineWidth: 2,
            });
            lower.setData([
              { time: zone.startTime, value: zone.bottom },
              { time: zone.endTime, value: zone.bottom },
            ]);
            extraSeriesRef.current.push(lower);
          });

          ob.forEach((zone: any) => {
            const upper = chart.addLineSeries({
              color: zone.type === "bullish" ? "rgba(0,229,255,0.45)" : "rgba(255,176,0,0.45)",
              lineWidth: 2,
            });
            upper.setData([
              { time: zone.startTime, value: zone.top },
              { time: zone.endTime, value: zone.top },
            ]);
            extraSeriesRef.current.push(upper);
            const lower = chart.addLineSeries({
              color: zone.type === "bullish" ? "rgba(0,229,255,0.45)" : "rgba(255,176,0,0.45)",
              lineWidth: 2,
            });
            lower.setData([
              { time: zone.startTime, value: zone.bottom },
              { time: zone.endTime, value: zone.bottom },
            ]);
            extraSeriesRef.current.push(lower);
          });

          pools.forEach((pool: any) => {
            const line = chart.addLineSeries({
              color: pool.type === "equal_high" ? "rgba(179,136,255,0.55)" : "rgba(255,109,0,0.55)",
              lineWidth: 2,
            });
            line.setData([
              { time: pool.startTime, value: pool.level },
              { time: pool.endTime, value: pool.level },
            ]);
            extraSeriesRef.current.push(line);
          });

          // Jika di DEBUG dan ada selected signal, tampilkan juga zona entry/SL/TP
          if (selected) {
            const start = data[0].time;
            const end = data[data.length - 1].time;
            const lastTime = data[data.length - 1].time;
            const isBuy = selected.type === "BUY";

            const entryColor = isBuy ? "#00E5FF" : "#FFB000";
            const tpColor = isBuy ? "#00FFAA" : "#FF4444";
            const slColor = isBuy ? "#FF4444" : "#00FFAA";

            const entryLine = chart.addLineSeries({
              color: entryColor,
              lineWidth: 2,
              lineStyle: 0,
            });
            entryLine.setData([
              { time: start, value: selected.entry },
              { time: end, value: selected.entry },
            ]);
            extraSeriesRef.current.push(entryLine);

            const slZone = chart.addAreaSeries({
              topColor: "rgba(255,0,0,0.35)",
              bottomColor: "rgba(255,0,0,0.05)",
              lineColor: slColor,
              lineWidth: 1,
            });
            slZone.setData([
              { time: start, value: selected.sl },
              { time: end, value: selected.sl },
            ]);
            extraSeriesRef.current.push(slZone);

            const tpZone = chart.addAreaSeries({
              topColor: "rgba(0,255,150,0.35)",
              bottomColor: "rgba(0,255,150,0.05)",
              lineColor: tpColor,
              lineWidth: 1,
            });
            tpZone.setData([
              { time: start, value: selected.tp },
              { time: end, value: selected.tp },
            ]);
            extraSeriesRef.current.push(tpZone);

            const rr = Math.abs(selected.tp - selected.entry) / Math.abs(selected.entry - selected.sl);
            const rrColor = rr >= 3 ? "#00FFAA" : rr >= 2 ? "#FFB000" : "#FF4444";

            entryLine.setMarkers([
              {
                time: lastTime,
                position: "aboveBar",
                color: entryColor,
                shape: "circle",
                text: `ENTRY ${selected.entry} | RR ${rr.toFixed(2)}`,
              },
              {
                time: lastTime,
                position: "aboveBar",
                color: rrColor,
                shape: "arrowUp",
                text: `RR ${rr.toFixed(2)}`,
              },
            ]);

            tpZone.setMarkers([
              {
                time: lastTime,
                position: "aboveBar",
                color: tpColor,
                shape: "arrowUp",
                text: `TP ${selected.tp}`,
              },
            ]);

            slZone.setMarkers([
              {
                time: lastTime,
                position: "belowBar",
                color: slColor,
                shape: "arrowDown",
                text: `SL ${selected.sl}`,
              },
            ]);
          }
        }

        chart.timeScale().fitContent();

        const lastPrice = data.length > 0 ? data[data.length - 1].close : undefined;

        await drawLiquidationHeatmapAndFootprint(
          chart,
		  candleSeries,
          symbol,
          overlay,
          latestCandles,
          latestZones,
          latestTrend,
          latestBias,
          mode,
          selected,
          lastPrice,
          htfZones // kirim HTF zones
        );
      } catch (err) {
        console.error("Gagal load chart:", err);
      }
    };

    loadData();

    const redrawOverlay = async () => {
      if (!alive) return;
      const lastPrice = latestCandles.length > 0 ? latestCandles[latestCandles.length - 1].close : undefined;
      await drawLiquidationHeatmapAndFootprint(
        chart,
		candleSeries,
        symbol,
        overlay,
        latestCandles,
        latestZones,
        latestTrend,
        latestBias,
        mode,
        selected,
        lastPrice,
        htfZones
      );
    };

    const interval = setInterval(redrawOverlay, 3000);

    const handleResize = () => {
      if (!containerRef.current) return;
      chart.applyOptions({ width: containerRef.current.clientWidth || 1000 });
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
  }, [symbol, mode, selected]);

  return (
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", gap: "8px", marginBottom: "8px", justifyContent: "center" }}>
        <button onClick={() => setMode("SCAN")} style={{ padding: "6px 12px", background: mode === "SCAN" ? "#00FFAA" : "#333", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}>SCAN</button>
        <button onClick={() => setMode("ANALYSIS")} style={{ padding: "6px 12px", background: mode === "ANALYSIS" ? "#FFB000" : "#333", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}>ANALYSIS</button>
        <button onClick={() => setMode("DEBUG")} style={{ padding: "6px 12px", background: mode === "DEBUG" ? "#FF4444" : "#333", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}>DEBUG</button>
      </div>
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
    </div>
  );
}