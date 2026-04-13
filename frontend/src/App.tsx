import { useEffect, useRef, useState } from "react";
import Chart from "./Chart";
import axios from "axios";
import { db, auth } from "./firebase";
import { collection, getDocs, query, where } from "firebase/firestore";
import { doc, setDoc } from "firebase/firestore";
import {
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
} from "firebase/auth";
import html2canvas from "html2canvas";

type TrendState = "BULL" | "BEAR" | "RANGE";

type Signal = {
  symbol: string;
  type: "BUY" | "SELL";
  rr: string;
  ai: string;
  score: number;
  explain: string;
  entry: number;
  sl: number;
  tp: number;
  setupTag?: string;
};

type JournalItem = Signal & {
  time: string;
  result: "OPEN" | "TP" | "SL";
  lot?: number;
  trailing?: number;
  tp1?: number;
  tp2?: number;
  tp3?: number;
  hitTP1?: boolean;
  hitTP2?: boolean;
  hitTP3?: boolean;
  exchangeId?: string;
  unrealized?: number;
  saved?: boolean;
};

type Toast = {
  id: number;
  text: string;
};

const PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"];

function getSessionUTC() {
  const h = new Date().getUTCHours();
  if (h < 7) return "ASIA";
  if (h < 13) return "LONDON";
  if (h < 22) return "NEWYORK";
  return "OFF";
}

function isKillzone() {
  const h = new Date().getUTCHours();
  return (h >= 7 && h <= 10) || (h >= 13 && h <= 16);
}

function detectHTFTrend(data: any[]): TrendState {
  if (data.length < 50) return "RANGE";

  const closes = data.map((c) => Number(c.close)).filter(Number.isFinite);
  if (closes.length < 50) return "RANGE";

  const ma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const ma50 = closes.slice(-50).reduce((a, b) => a + b, 0) / 50;
  const last = closes[closes.length - 1];

  if (last > ma20 && ma20 > ma50) return "BULL";
  if (last < ma20 && ma20 < ma50) return "BEAR";
  return "RANGE";
}

function calcConfluenceScore(s: any, trend: TrendState, kill: boolean) {
  let score = 0;

  const rr = parseFloat(s.rr || "0");
  score += Math.min(30, rr * 10);

  if (s.ai?.includes("STRONG")) score += 25;
  else if (s.ai?.includes("VALID")) score += 18;

  if (
    (trend === "BULL" && s.type === "BUY") ||
    (trend === "BEAR" && s.type === "SELL")
  ) {
    score += 20;
  }

  if (kill) score += 15;

  score += 5;

  return Math.min(100, Math.floor(score));
}

function generateExplain(s: any, trend: TrendState, kill: boolean) {
  const reasons: string[] = [];
  const rr = parseFloat(s.rr || "0");

  if (rr >= 3) reasons.push("RR bagus (≥3)");
  else reasons.push("RR lemah");

  if (s.ai?.includes("STRONG")) reasons.push("AI strong confluence");
  else if (s.ai?.includes("VALID")) reasons.push("AI valid setup");

  if (
    (trend === "BULL" && s.type === "BUY") ||
    (trend === "BEAR" && s.type === "SELL")
  ) {
    reasons.push("Sejalan trend HTF");
  } else {
    reasons.push("Melawan trend HTF");
  }

  if (kill) reasons.push("Dalam killzone");
  else reasons.push("Di luar killzone");

  if (s.score >= 80) reasons.push("High probability setup");
  else if (s.score >= 60) reasons.push("Mid probability");
  else reasons.push("Low quality");

  return reasons.join(" | ");
}

function calcDynamicTPSL(
  data: any[],
  side: "BUY" | "SELL",
  entry: number,
  score: number
) {
  const recent = data.slice(-14);

  const avgRange =
    recent.reduce(
      (acc, c) => acc + Math.max(Number(c.high) - Number(c.low), 1),
      0
    ) / Math.max(recent.length, 1);

  const rrTarget =
    score >= 85 ? 5 : score >= 75 ? 4 : score >= 60 ? 3.2 : 2.5;

  const buffer = avgRange * (score >= 80 ? 0.6 : 0.9);

  let sl = 0;
  let tp = 0;

  if (side === "BUY") {
    const swingLow = Math.min(...recent.map((c) => Number(c.low)));
    sl = swingLow - buffer;
    tp = entry + Math.abs(entry - sl) * rrTarget;
  } else {
    const swingHigh = Math.max(...recent.map((c) => Number(c.high)));
    sl = swingHigh + buffer;
    tp = entry - Math.abs(entry - sl) * rrTarget;
  }

  return {
    sl: Number(sl.toFixed(2)),
    tp: Number(tp.toFixed(2)),
    rrTarget: Number(rrTarget.toFixed(2)),
  };
}

function runSniperEngine(data: any[]) {
  if (data.length < 20) return null;

  const last = data[data.length - 1];
  const prev = data[data.length - 2];

  const sweepLow =
    Number(last.low) < Number(prev.low) &&
    Number(last.close) > Number(prev.low);
  const sweepHigh =
    Number(last.high) > Number(prev.high) &&
    Number(last.close) < Number(prev.high);

  const ob = data
    .slice(-10)
    .reverse()
    .find((c: any) =>
      sweepLow ? Number(c.close) < Number(c.open) : Number(c.close) > Number(c.open)
    );

  if (!ob) return null;

  const c1 = data[data.length - 3];
  const c3 = data[data.length - 1];

  const fvgBull = Number(c1.high) < Number(c3.low);
  const fvgBear = Number(c1.low) > Number(c3.high);

  const entry = Number(last.close);
  const sl = sweepLow ? Number(ob.low) : Number(ob.high);
  const tp = sweepLow ? Number(c3.low) : Number(c3.high);

  const rr = Math.abs(tp - entry) / Math.abs(entry - sl);

  if (sweepLow && fvgBull && rr >= 3)
    return { type: "BUY" as const, rr: rr.toFixed(2) };
  if (sweepHigh && fvgBear && rr >= 3)
    return { type: "SELL" as const, rr: rr.toFixed(2) };

  return null;
}

function getStreak(journal: JournalItem[]) {
  let win = 0;
  let lose = 0;
  for (let i = 0; i < journal.length; i++) {
    if (journal[i].result === "TP") {
      win++;
      lose = 0;
    } else if (journal[i].result === "SL") {
      lose++;
      win = 0;
    }
  }
  return { win, lose };
}

function getPairStats(journal: JournalItem[]) {
  const map: any = {};
  journal.forEach(j => {
    if (!map[j.symbol]) map[j.symbol] = { win: 0, loss: 0 };
    if (j.result === "TP") map[j.symbol].win++;
    if (j.result === "SL") map[j.symbol].loss++;
  });
  return map;
}

function getSetupStats(journal: JournalItem[]) {
  const map: Record<string, { win: number; loss: number }> = {};
  journal.forEach((j) => {
    const key = j.setupTag || "UNKNOWN";
    if (!map[key]) map[key] = { win: 0, loss: 0 };
    if (j.result === "TP") map[key].win++;
    if (j.result === "SL") map[key].loss++;
  });
  return map;
}

function groupBySymbol(journal: JournalItem[]) {
  const map: Record<string, JournalItem[]> = {};

  journal.forEach((j) => {
    if (!map[j.symbol]) map[j.symbol] = [];
    map[j.symbol].push(j);
  });

  return map;
}

export default function App() {
  const [user, setUser] = useState<any>(undefined);
  const [trend, setTrend] = useState<TrendState>("RANGE");
  const [h4Trend, setH4Trend] = useState<TrendState>("RANGE");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [signals, setSignals] = useState<Signal[]>([]);
  const [selected, setSelected] = useState<Signal | null>(null);
  const [suggestion, setSuggestion] = useState<any>(null);
  const [journal, setJournal] = useState<JournalItem[]>([]);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [strict, setStrict] = useState(false);

  const [balance, setBalance] = useState(1000);
  const [riskPercent, setRiskPercent] = useState(1);

  // --- RISK MANAGER STATE ---
  const [dailyLoss, setDailyLoss] = useState(0);
  const [maxDailyLoss] = useState(5); // %
  const [maxTrades] = useState(5);
  const [todayTrades, setTodayTrades] = useState(0);
  const [riskBlocked, setRiskBlocked] = useState(false);
  const [startBalance] = useState(1000);
  const [lastTradeTime, setLastTradeTime] = useState(0);

  const [toasts, setToasts] = useState<Toast[]>([]);
  const [stats, setStats] = useState({
    total: 0,
    win: 0,
    loss: 0,
    pnl: 0,
    winrate: 0,
  });

  const [pendingTrade, setPendingTrade] = useState<Signal | null>(null);
  const [accounts, setAccounts] = useState<any[]>([]);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastSignalsRef = useRef<Signal[]>([]);
  const sentPreRef = useRef<{ [key: string]: boolean }>({});

  const session = getSessionUTC();
  const kill = isKillzone();

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(u);
    });
    return () => unsub();
  }, []);

  useEffect(() => {
    const fetchAccounts = async () => {
      try {
        const res = await axios.get("https://montra-backend-9wku.onrender.com/accounts");
        setAccounts(res.data.accounts || []);
      } catch {}
    };
    fetchAccounts();
    const i = setInterval(fetchAccounts, 5000);
    return () => clearInterval(i);
  }, []);

  const loginGoogle = async () => {
    try {
      const provider = new GoogleAuthProvider(); // ✅ WAJIB ADA
      const res = await signInWithPopup(auth, provider);
      console.log(res.user);
    } catch (e) {
      console.error("LOGIN ERROR:", e);
      alert("Login gagal, cek console");
    }
  };
  
  const name = user?.displayName || user?.email;
  const photo = user?.photoURL;

  useEffect(() => {
    audioRef.current = new Audio(
      "https://actions.google.com/sounds/v1/alarms/beep_short.ogg"
    );
  }, []);

  useEffect(() => {
    const j = localStorage.getItem("montra_journal");
    if (j) setJournal(JSON.parse(j));

    const s = localStorage.getItem("montra_last_signals");
    if (s) setSignals(JSON.parse(s));
  }, []);

  useEffect(() => {
    if (!user) return;

    const load = async () => {
      const q = query(collection(db, "trades"), where("uid", "==", user.uid));
      const snap = await getDocs(q);
      const data = snap.docs.map((d) => d.data());
      setJournal(data as JournalItem[]);
    };

    load();
  }, [user]);

  useEffect(() => {
    localStorage.setItem("montra_journal", JSON.stringify(journal));
  }, [journal]);

  useEffect(() => {
    if (!user) return;
  
    const saveClosedTrades = async () => {
      let changed = false;
  
      const updated = await Promise.all(
        journal.map(async (j) => {
          if (j.result === "OPEN" || j.saved) return j;
  
          try {
            await setDoc(
              doc(db, "trades", `${j.symbol}-${j.time}-${j.entry}`),
              {
                ...j,
                uid: user.uid,
              }
            );
  
            changed = true;
            return { ...j, saved: true };
          } catch {
            return j;
          }
        })
      );
  
      if (changed) setJournal(updated); // ✅ hanya kalau berubah
    };
  
    saveClosedTrades();
  }, [journal, user]);

  const captureChart = async (signal: any) => {
    const el = document.getElementById("chart-area");
    if (!el) return null;

    const canvas = await html2canvas(el);
    const ctx = canvas.getContext("2d");
    if (!ctx) return canvas.toDataURL("image/png");

    const h = canvas.height;
    const w = canvas.width;

    const max = Number(signal.tp);
    const min = Number(signal.sl);
    const denom = Math.max(max - min, 1e-9);

    const toY = (price: number) => h - ((price - min) / denom) * h;

    const drawLine = (price: number, color: string, label: string) => {
      const y = toY(price);

      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);

      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();

      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "bold 14px monospace";
      ctx.fillText(label, 10, y - 5);
    };

    const isBuy = signal.type === "BUY";
    drawLine(signal.entry, "#00E5FF", isBuy ? "BUY ENTRY" : "SELL ENTRY");
    drawLine(signal.sl, "#FF4444", "SL");
    drawLine(signal.tp, "#00FFAA", "TP");

    return canvas.toDataURL("image/png");
  };

  const aiFilter = async (s: any) => {
    try {
      const res = await axios.post(
        "https://montra-backend-9wku.onrender.com/ai-filter",
        s
      );
      return res.data.result;
    } catch {
      return "NO TRADE";
    }
  };

  const pushToast = (text: string) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, text }]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  };

  const executeTrade = async () => {
    if (!pendingTrade) return;

    // RISK BLOCK CHECK
    if (riskBlocked) {
      alert("🚫 RISK LIMIT HIT!\nTrading diblokir hari ini.");
      return;
    }

    // COOLDOWN CHECK (5 minutes)
    const cooldown = 60 * 5; // 5 menit
    if (Date.now() - lastTradeTime < cooldown * 1000) {
      const remaining = Math.ceil((cooldown * 1000 - (Date.now() - lastTradeTime)) / 1000);
      alert(`⏳ Tunggu cooldown ${remaining} detik lagi`);
      return;
    }

    const ok = window.confirm(
      `EXECUTE TRADE?\n\n${pendingTrade.symbol} ${pendingTrade.type}\nRR: ${pendingTrade.rr}\nSCORE: ${pendingTrade.score}\nSETUP: ${pendingTrade.setupTag || "-"}`
    );

    if (!ok) return;

    try {
      await axios.post("https://montra-backend-9wku.onrender.com/trade", {
        ...pendingTrade,
        risk: riskPercent
      });
      pushToast(`🚀 TRADE SENT: ${pendingTrade.symbol}`);
      setPendingTrade(null);
      setLastTradeTime(Date.now());
    } catch (err) {
      console.error(err);
      pushToast("❌ TRADE FAILED");
    }
  };

  useEffect(() => {
    if (!user) return;

    const scan = async () => {
      const results: Signal[] = [];

      try {
        const [h1Res, h4Res] = await Promise.all([
          axios.get(
            "https://montra-backend-9wku.onrender.com/ohlcv/BTCUSDT?timeframe=1h&limit=100"
          ),
          axios.get(
            "https://montra-backend-9wku.onrender.com/ohlcv/BTCUSDT?timeframe=4h&limit=100"
          ),
        ]);

        const h1Data = (h1Res.data?.data ?? []).map((c: any) => ({
          time: Math.floor(Number(c.time) / 1000),
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
        }));

        const h4Data = (h4Res.data?.data ?? []).map((c: any) => ({
          time: Math.floor(Number(c.time) / 1000),
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
        }));

        const h1Trend = detectHTFTrend(h1Data);
        const h4TrendLocal = detectHTFTrend(h4Data);

        setTrend(h1Trend);
        setH4Trend(h4TrendLocal);

        for (const p of PAIRS) {
          try {
            const res = await axios.get(
              `https://montra-backend-9wku.onrender.com/ohlcv/${p}?timeframe=15m&limit=100`
            );

            const data = res.data?.data ?? [];
            if (data.length < 20) continue;

            const signal = runSniperEngine(data);
            if (!signal) continue;

            const ai = await aiFilter(signal);
            if (!ai.includes("VALID")) continue;

            if (strict && !kill) continue;

            const lastCandle = data[data.length - 1];
            const prevCandle = data[data.length - 2];
            const c1 = data[data.length - 3];
            const c3 = data[data.length - 1];

            const body = Math.abs(
              Number(lastCandle.close) - Number(lastCandle.open)
            );
            const range = Math.max(
              Number(lastCandle.high) - Number(lastCandle.low),
              1e-9
            );

            const strongBreak = body > range * 0.6;
            const isBullBreak = Number(lastCandle.close) > Number(lastCandle.open);
            const isBearBreak = Number(lastCandle.close) < Number(lastCandle.open);

            const fakeBreakout =
              (isBullBreak && Number(lastCandle.close) < Number(prevCandle.high)) ||
              (isBearBreak && Number(lastCandle.close) > Number(prevCandle.low));

            const entryDistance =
              signal.type === "BUY"
                ? Math.abs(Number(lastCandle.close) - Number(lastCandle.low))
                : Math.abs(Number(lastCandle.high) - Number(lastCandle.close));

            const isSniperEntry = entryDistance <= range * 0.3;

            const sweepLow =
              Number(lastCandle.low) < Number(prevCandle.low) &&
              Number(lastCandle.close) > Number(prevCandle.low);
            const sweepHigh =
              Number(lastCandle.high) > Number(prevCandle.high) &&
              Number(lastCandle.close) < Number(prevCandle.high);

            const validSweep =
              (signal.type === "BUY" && sweepLow) ||
              (signal.type === "SELL" && sweepHigh);

            const ob = data.slice(-10).reverse().find((c: any) =>
              signal.type === "BUY"
                ? Number(c.close) < Number(c.open)
                : Number(c.close) > Number(c.open)
            );

            let inOBZone = false;
            if (ob) {
              const obHigh = Number(ob.high);
              const obLow = Number(ob.low);
              inOBZone =
                Number(lastCandle.close) <= obHigh &&
                Number(lastCandle.close) >= obLow;
            }

            let inFVGZone = false;
            const fvgBull = Number(c1.high) < Number(c3.low);
            const fvgBear = Number(c1.low) > Number(c3.high);

            if (signal.type === "BUY" && fvgBull) {
              inFVGZone =
                Number(lastCandle.close) >= Number(c1.high) &&
                Number(lastCandle.close) <= Number(c3.low);
            }

            if (signal.type === "SELL" && fvgBear) {
              inFVGZone =
                Number(lastCandle.close) <= Number(c1.low) &&
                Number(lastCandle.close) >= Number(c3.high);
            }

            const mtfAligned =
              (signal.type === "BUY" &&
                h1Trend === "BULL" &&
                h4TrendLocal === "BULL") ||
              (signal.type === "SELL" &&
                h1Trend === "BEAR" &&
                h4TrendLocal === "BEAR");

            let score = calcConfluenceScore(signal, h1Trend, kill);
            if (isSniperEntry) score += 10;
            if (fakeBreakout) score -= 20;
            if (validSweep) score += 15;
            if (inOBZone) score += 15;
            if (inFVGZone) score += 15;
            if (mtfAligned) score += 15;
            score = Math.max(0, Math.min(100, score));

            const isSniperValid =
              isSniperEntry &&
              parseFloat(signal.rr) >= 3 &&
              h1Trend !== "RANGE" &&
              h4TrendLocal !== "RANGE" &&
              strongBreak &&
              !fakeBreakout &&
              validSweep &&
              inOBZone &&
              inFVGZone &&
              mtfAligned;

            const signalEntry = Number(lastCandle.close);
            const signalSL =
              signal.type === "BUY"
                ? Number(lastCandle.low)
                : Number(lastCandle.high);

            const explain = generateExplain(
              { ...signal, score },
              h1Trend,
              kill
            );

            const dyn = calcDynamicTPSL(data, signal.type, signalEntry, score);

            const setupTag = [
              validSweep ? "SWEEP" : "",
              inOBZone ? "OB" : "",
              inFVGZone ? "FVG" : "",
              mtfAligned ? "MTF" : "",
            ]
              .filter(Boolean)
              .join(" + ");

            const newSignal = {
              symbol: p,
              type: signal.type,
              rr: dyn.rrTarget.toFixed(2),
              ai,
              score,
              explain,
              entry: signalEntry,
              sl: signalSL,
              tp: dyn.tp,
              setupTag: setupTag || "NO STACK",
            };

            const isPreSignal = newSignal.score >= 50 && newSignal.score < 60;
            const preKey = `${newSignal.symbol}-${newSignal.type}`;

            if (isPreSignal && !sentPreRef.current[preKey]) {
              sentPreRef.current[preKey] = true;

              pushToast(`👁️ PRE ${newSignal.symbol} ${newSignal.type}`);

              try {
                await axios.post(
                  "https://montra-backend-9wku.onrender.com/notify",
                  {
                    text: `👁️ PRE-SIGNAL\n\n${newSignal.symbol} ${newSignal.type}\nRR: ${newSignal.rr}\nSCORE: ${newSignal.score}\n\n⚠️ Belum valid, tapi mendekati`,
                  }
                );
              } catch (e) {
                console.error("Pre-signal notify failed", e);
              }
            }

            if (
              fakeBreakout &&
              newSignal.score >= 50 &&
              !sentPreRef.current[preKey + "_fake"]
            ) {
              sentPreRef.current[preKey + "_fake"] = true;
              try {
                await axios.post(
                  "https://montra-backend-9wku.onrender.com/notify",
                  {
                    text: `⚠️ POSSIBLE FAKE BREAKOUT\n\n${newSignal.symbol}\nHati-hati trap market`,
                  }
                );
              } catch (e) {
                console.error("Fake breakout notify failed", e);
              }
            }

            if (score >= 70 && isSniperValid) {
              // PAIR FILTER: skip pair jelek (loss >= 3 dan belum pernah win)
              const pairStats = getPairStats(journal);
              const pair = pairStats[p] || { win: 0, loss: 0 };
              if (pair.loss >= 3 && pair.win === 0) {
                continue;
              }

              // ADAPTIVE SCORE BOOST berdasarkan performa setup
              const setupStats = getSetupStats(journal);
              const stat = setupStats[newSignal.setupTag || "UNKNOWN"];
              if (stat) {
                const setupTotal = stat.win + stat.loss;
                const setupWinrate = setupTotal > 0 ? stat.win / setupTotal : 0;
                if (setupWinrate >= 0.7 && setupTotal >= 5) {
                  score += 10; // boost setup gacor
                }
                if (setupWinrate <= 0.3 && setupTotal >= 5) {
                  score -= 15; // penalti setup jelek
                }
              }

              // PAIR RANKING BOOST berdasarkan winrate pair
              const pairTotal = pair.win + pair.loss;
              const pairWinrate = pairTotal > 0 ? pair.win / pairTotal : 0;
              if (pairWinrate >= 0.65 && pairTotal >= 5) score += 5;
              if (pairWinrate <= 0.35 && pairTotal >= 5) score -= 10;

              // CLAMP FINAL
              score = Math.max(0, Math.min(100, score));
              newSignal.score = score;

              results.push(newSignal);

              const exist = lastSignalsRef.current.find(
                (x) => x.symbol === newSignal.symbol && x.type === newSignal.type
              );

              if (!exist) {
                if (validSweep && newSignal.score >= 80) {
                  try {
                    await axios.post(
                      "https://montra-backend-9wku.onrender.com/notify",
                      {
                        text: `💧 LIQUIDITY SWEEP\n\n${newSignal.symbol} ${newSignal.type}\nRR: ${newSignal.rr}\nSCORE: ${newSignal.score}\n\n🎯 Stop hunt detected`,
                      }
                    );
                  } catch (e) {
                    console.error("Sweep notify failed", e);
                  }
                }

                if (inOBZone && newSignal.score >= 85) {
                  try {
                    await axios.post(
                      "https://montra-backend-9wku.onrender.com/notify",
                      {
                        text: `🧱 ORDERBLOCK CONFIRM\n\n${newSignal.symbol} ${newSignal.type}\nRR: ${newSignal.rr}\nSCORE: ${newSignal.score}\n\n🎯 Smart money zone`,
                      }
                    );
                  } catch (e) {
                    console.error("OB notify failed", e);
                  }
                }

                if (newSignal.score >= 80) {
                  pushToast(
                    `🔥 ${newSignal.symbol} ${newSignal.type} [${newSignal.setupTag}]`
                  );
                  audioRef.current?.play();

                  try {
                    const img = await captureChart(newSignal);

                    if (img) {
                      await axios.post(
                        "https://montra-backend-9wku.onrender.com/notify-image",
                        {
                          text: `🔥 HIGH SCORE\n\n${newSignal.symbol} ${newSignal.type}\nRR: ${newSignal.rr}\nSCORE: ${newSignal.score}\nSETUP: ${newSignal.setupTag}`,
                          image: img,
                        }
                      );
                    } else {
                      await axios.post(
                        "https://montra-backend-9wku.onrender.com/notify",
                        {
                          text: `🔥 HIGH SCORE\n\n${newSignal.symbol} ${newSignal.type}\nRR: ${newSignal.rr}\nSCORE: ${newSignal.score}\nSETUP: ${newSignal.setupTag}`,
                        }
                      );
                    }
                  } catch (e) {
                    console.error("Notify failed", e);
                  }
                }

                if (newSignal.score >= 85 && isSniperEntry) {
                  try {
                    await axios.post(
                      "https://montra-backend-9wku.onrender.com/notify",
                      {
                        text: `🎯 SNIPER ENTRY\n\n${newSignal.symbol} ${newSignal.type}\nRR: ${newSignal.rr}\nSCORE: ${newSignal.score}\nSETUP: ${newSignal.setupTag}\n\n🔥 ZONA PRESISI`,
                      }
                    );
                  } catch (e) {}
                }
              }
            }
          } catch {}
        }
      } catch {}

      lastSignalsRef.current = results;
      const sorted = results.sort((a, b) => b.score - a.score);
      setSignals(sorted.length ? [sorted[0]] : []);
      localStorage.setItem("montra_last_signals", JSON.stringify(results));
    };

    scan();
    const i = setInterval(scan, 10000);
    return () => clearInterval(i);
  }, [strict, kill, user]);

  useEffect(() => {
    if (!signals.length) {
      setSuggestion(null);
      setPendingTrade(null);
      return;
    }

    const top = signals[0];
    if (!top) return;

    const valid = top.ai.includes("VALID") && parseFloat(top.rr) >= 3;

    if (!valid || top.score < 70) {
      setSuggestion(null);
      setPendingTrade(null);
      return;
    }

    setSuggestion({
      symbol: top.symbol,
      type: top.type,
      entry: top.entry,
      sl: top.sl,
      tp: top.tp,
      rr: top.rr,
      score: top.score,
      explain: top.explain,
      setupTag: top.setupTag,
    });

    setPendingTrade(top);
  }, [signals]);

  useEffect(() => {
    if (!user) return;

    const ws = new WebSocket(
      `wss://stream.binance.com:9443/stream?streams=${PAIRS.map(
        (p) => `${p.toLowerCase()}@trade`
      ).join("/")}`
    );

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      const symbol = msg?.data?.s;
      const price = Number(msg?.data?.p);
	  
	  if (!symbol || !Number.isFinite(price)) return;
      
	  setPrices((prev) => {
		if (prev[symbol] === price) return prev;
		return {
          ...prev,
          [symbol]: price,
        };
      });
    };

  return () => ws.close();
}, [user]);

  useEffect(() => {
    setJournal((prev) =>
      prev.map((j) => {
        const price = prices[j.symbol];
        if (!price || j.result !== "OPEN") return j;

        let newTrailing = j.trailing ?? j.sl;
        const move = Math.abs(j.tp - j.entry) * 0.3;

        if (j.type === "BUY") {
          if (price > j.entry + move) {
            newTrailing = Math.max(newTrailing, price - move);
          }

          if (!j.hitTP1 && price >= j.tp1!) {
            j.hitTP1 = true;
            newTrailing = j.entry;
          }

          if (!j.hitTP2 && price >= j.tp2!) {
            j.hitTP2 = true;
            newTrailing = j.tp1!;
          }

          if (price >= j.tp3!) {
            return { ...j, result: "TP", hitTP3: true };
          }

          if (price <= newTrailing) {
            return { ...j, result: "SL" };
          }

          return { ...j, trailing: newTrailing };
        }

        if (j.type === "SELL") {
          if (price < j.entry - move) {
            newTrailing = Math.min(newTrailing, price + move);
          }

          if (!j.hitTP1 && price <= j.tp1!) {
            j.hitTP1 = true;
            newTrailing = j.entry;
          }

          if (!j.hitTP2 && price <= j.tp2!) {
            j.hitTP2 = true;
            newTrailing = j.tp1!;
          }

          if (price <= j.tp3!) {
            return { ...j, result: "TP", hitTP3: true };
          }

          if (price >= newTrailing) {
            return { ...j, result: "SL" };
          }

          return { ...j, trailing: newTrailing };
        }

        return j;
      })
    );
  }, [prices]);

  useEffect(() => {
    let total = 0;
    let win = 0;
    let loss = 0;
    let pnl = 0;

    // RISK MANAGER CALCULATIONS
    const today = new Date().toDateString();
    let dayLoss = 0;
    let tradesToday = 0;

    journal.forEach((j) => {
      const tradeDate = new Date(j.time).toDateString();

      if (j.result === "TP") {
        total++;
        win++;
        const profit = Math.abs(j.tp - j.entry) * (j.lot || 1);
        pnl += profit;

        if (tradeDate === today) {
          tradesToday++;
          // profit doesn't add to daily loss
        }
      }

      if (j.result === "SL") {
        total++;
        loss++;
        const lossAmount = Math.abs(j.entry - j.sl) * (j.lot || 1);
        pnl -= lossAmount;

        if (tradeDate === today) {
          tradesToday++;
          dayLoss += lossAmount;
        }
      }

      // Include unrealized PnL for open positions
      if (j.unrealized && j.result === "OPEN") {
        pnl += j.unrealized;
      }
    });

    const winrate = total ? (win / total) * 100 : 0;

    setStats({
      total,
      win,
      loss,
      pnl: Number(pnl.toFixed(2)),
      winrate: Number(winrate.toFixed(1)),
    });

    // Update daily risk state
    setDailyLoss(dayLoss);
    setTodayTrades(tradesToday);

    // Check if risk limits are hit
    const lossPercent = balance > 0 ? (dayLoss / balance) * 100 : 0;
    const equityDrop = startBalance > 0 ? ((startBalance - balance) / startBalance) * 100 : 0;

    if (lossPercent >= maxDailyLoss || tradesToday >= maxTrades || equityDrop >= 10) {
      setRiskBlocked(true);
    } else {
      setRiskBlocked(false);
    }
  }, [journal, balance, maxDailyLoss, maxTrades, startBalance]);

  // Fetch real positions periodically
  useEffect(() => {
    const fetchPositions = async () => {
      try {
        const res = await axios.get("https://montra-backend-9wku.onrender.com/positions");
        const positions = res.data.positions || [];

        setJournal((prev) => {
          let updated = [...prev];

          positions.forEach((p: any) => {
            const exist = updated.find(j => j.symbol === p.symbol && j.result === "OPEN");

            if (!exist) {
              updated.unshift({
                symbol: p.symbol,
                type: p.side,
                entry: p.entry,
                sl: 0,
                tp: 0,
                time: new Date().toISOString(),
                result: "OPEN",
                lot: p.size,
                exchangeId: p.symbol,
                unrealized: p.unrealized,
                rr: "",
                ai: "",
                score: 0,
                explain: "",
              } as JournalItem);
            } else {
              exist.unrealized = p.unrealized;
            }
          });

          return updated;
        });

      } catch {}
    };

    const i = setInterval(fetchPositions, 5000);
    return () => clearInterval(i);
  }, []);

  // Detect closed positions & partial TP
  useEffect(() => {
    const checkClosed = async () => {
      try {
        const updated: JournalItem[] = await Promise.all(
          journal.map(async (j) => {
            if (j.result !== "OPEN") return j;

            try {
              const res = await axios.get(
                `https://montra-backend-9wku.onrender.com/position-detail/${j.symbol}`
              );

              const trades = res.data.trades || [];

              // ambil semua realized pnl
              const relatedTrades = trades.filter(
                (t: any) => Math.abs(parseFloat(t.realizedPnl)) > 0
              );

              if (!relatedTrades.length) return j;

              const totalPnl = relatedTrades.reduce(
                (acc: number, t: any) => acc + parseFloat(t.realizedPnl),
                0
              );

              // partial TP detection
              const hitTP1 = totalPnl > 0;
              const hitTP2 = totalPnl > Math.abs(j.entry - j.sl) * 0.5;
              const hitTP3 = totalPnl > Math.abs(j.entry - j.sl);

              if (hitTP3) {
                return { ...j, result: "TP", hitTP3: true };
              }

              if (totalPnl < 0) {
                return { ...j, result: "SL" };
              }

              return {
                ...j,
                hitTP1,
                hitTP2,
                unrealized: totalPnl
              };

            } catch {
              return j;
            }
          })
        );

        setJournal(updated);
      } catch {}
    };

    const i = setInterval(checkClosed, 6000);
    return () => clearInterval(i);
  }, []);

  // Dynamic Risk berdasarkan streak
  const { win: streakWin, lose: streakLose } = getStreak(journal);
  let dynamicRisk = riskPercent;
  if (streakWin >= 3) dynamicRisk = riskPercent * 1.5;
  if (streakLose >= 2) dynamicRisk = riskPercent * 0.5;
  // clamp biar gak liar
  dynamicRisk = Math.max(0.5, Math.min(dynamicRisk, 3));

  // Effective risk percent (0 if blocked)
  const effectiveRisk = riskBlocked ? 0 : dynamicRisk;

  const lot = selected
    ? ((balance * effectiveRisk) / 100) / Math.abs(selected.entry - selected.sl)
    : 0;

  function exportCSV() {
    if (!journal.length) return;

    const headers = [
      "Time",
      "Symbol",
      "Type",
      "Entry",
      "SL",
      "TP",
      "TP1",
      "TP2",
      "Result",
      "PnL",
    ];

    const rows = journal.map((j) => {
      const pnl =
        j.result === "TP"
          ? (Math.abs(j.tp - j.entry) * (j.lot || 1)).toFixed(2)
          : j.result === "SL"
          ? (-Math.abs(j.entry - j.sl) * (j.lot || 1)).toFixed(2)
          : "0";

      return [
        j.time,
        j.symbol,
        j.type,
        j.entry,
        j.sl,
        j.tp,
        j.tp1 ?? "",
        j.tp2 ?? "",
        j.result,
        pnl,
      ].join(",");
    });

    const csvContent = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "montra_journal.csv";
    a.click();

    URL.revokeObjectURL(url);
  }

  if (user === undefined) {
    return (
      <div
        style={{
          display: "flex",
          height: "100vh",
          background: "#0b0f14",
          color: "#fff",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        Loading...
      </div>
    );
  }

  if (!user) {
    return (
      <div
        style={{
          display: "flex",
          height: "100vh",
          background: "#0b0f14",
          color: "#fff",
          justifyContent: "center",
          alignItems: "center",
          flexDirection: "column",
        }}
      >
        <h2>MONTRA ⚡</h2>
        <p style={{ color: "#aaa" }}>AI Crypto Trading Terminal</p>
        <button
          onClick={loginGoogle}
          style={{
            marginTop: "20px",
            padding: "10px 20px",
            background: "#fff",
            color: "#000",
            border: "none",
            borderRadius: "5px",
            cursor: "pointer",
            fontWeight: "bold",
            fontSize: "16px",
          }}
        >
          🔐 Login with Google
        </button>
      </div>
    );
  }

  const grouped = groupBySymbol(journal);

  return (
    <div
      style={{
        maxWidth: "100%",
        padding: "10px",
        fontSize: "14px",
        background: "#0b0f14",
        color: "#fff",
        minHeight: "100vh",
      }}
    >
      <style>{`
        button {
          width: 100%;
          padding: 12px;
          font-size: 14px;
          box-sizing: border-box;
          cursor: pointer;
        }
        input {
          width: 100%;
          padding: 10px;
          margin-bottom: 5px;
          box-sizing: border-box;
        }
        input[type="checkbox"] {
          width: auto;
          margin-right: 8px;
        }
        @media (min-width: 768px) {
          .mobile-grid {
            flex-direction: row !important;
            height: calc(100vh - 20px);
          }
          .sidebar-panel {
            width: 300px !important;
            flex-shrink: 0;
          }
        }
      `}</style>

      <div
        className="mobile-grid"
        style={{ display: "flex", flexDirection: "column", gap: "10px" }}
      >
        <div
          className="sidebar-panel"
          style={{ width: "100%", padding: "10px", overflowY: "auto" }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "15px",
            }}
          >
            <h3 style={{ margin: 0 }}>MONTRA ⚡</h3>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              marginBottom: "15px",
            }}
          >
            {photo && (
              <img
                src={photo}
                style={{ width: "30px", borderRadius: "50%" }}
                alt="User"
              />
            )}

            <div style={{ color: "#00E5FF", fontWeight: "bold" }}>{name}</div>
          </div>

          <div>Session: {session}</div>
          <div style={{ color: kill ? "#00ff88" : "#ff4444" }}>
            Killzone: {kill ? "ON" : "OFF"}
          </div>
          <div>H1 Trend: {trend}</div>
          <div>H4 Trend: {h4Trend}</div>

          <label
            style={{
              display: "flex",
              alignItems: "center",
              marginTop: "10px",
              marginBottom: "10px",
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={strict}
              onChange={(e) => setStrict(e.target.checked)}
            />
            STRICT
          </label>

          <hr style={{ borderColor: "#333", margin: "15px 0" }} />

          <div style={{
            marginBottom: "15px",
            padding: "10px",
            border: "1px solid #333",
            borderRadius: "8px",
            background: "#0f172a"
          }}>
            <div style={{ color: "#00E5FF", fontWeight: "bold", marginBottom: "5px" }}>
              🏦 ACCOUNTS
            </div>
            {accounts.map((a, i) => (
              <div key={i} style={{ marginBottom: "6px", fontSize: "12px" }}>
                <div style={{ fontWeight: "bold" }}>{a.name}</div>
                {a.error ? (
                  <div style={{ color: "#FF4444" }}>ERROR</div>
                ) : (
                  <>
                    <div>Balance: {a.balance.toFixed(2)}</div>
                    <div style={{
                      color: a.unrealized >= 0 ? "#00FFAA" : "#FF4444"
                    }}>
                      PnL: {a.unrealized.toFixed(2)}
                    </div>
                    <div>Equity: {a.equity.toFixed(2)}</div>
                    <div>Pos: {a.positions}</div>
                  </>
                )}
              </div>
            ))}
          </div>

          <div
            style={{
              marginBottom: "15px",
              padding: "10px",
              border: "1px solid #333",
              borderRadius: "8px",
              background: "#0f172a",
            }}
          >
            <div
              style={{
                color: "#00E5FF",
                marginBottom: "5px",
                fontWeight: "bold",
              }}
            >
              📊 PERFORMANCE
            </div>

            <div>Total: {stats.total}</div>
            <div>
              Win: {stats.win} | Loss: {stats.loss}
            </div>
            <div>Winrate: {stats.winrate}%</div>

            <div
              style={{
                color: stats.pnl >= 0 ? "#00FFAA" : "#FF4444",
                fontWeight: "bold",
                marginTop: "5px",
              }}
            >
              PnL: {stats.pnl}
            </div>

            <button
              onClick={exportCSV}
              style={{
                marginTop: "10px",
                padding: "8px",
                background: "#00E5FF",
                color: "#000",
                border: "none",
                borderRadius: "6px",
                fontWeight: "bold",
              }}
            >
              📁 Export CSV
            </button>

            <div
              style={{
                height: "60px",
                marginTop: "10px",
                background: "#111",
                borderRadius: "6px",
                padding: "5px",
                fontSize: "10px",
                overflowX: "auto",
                whiteSpace: "nowrap",
              }}
            >
              {journal.map((j, i) => (
                <span
                  key={i}
                  style={{
                    color:
                      j.result === "TP"
                        ? "#00FFAA"
                        : j.result === "SL"
                        ? "#FF4444"
                        : "#555",
                    marginRight: "5px",
                  }}
                >
                  {j.result}
                </span>
              ))}
            </div>
          </div>

          {/* --- RISK MANAGER PANEL --- */}
          <div style={{
            marginTop: "10px",
            padding: "10px",
            border: "1px solid #333",
            borderRadius: "8px",
            background: "#1a1f2e"
          }}>
            <div style={{ color: "#FFB000", fontWeight: "bold" }}>
              🧠 RISK MANAGER
            </div>

            <div>Daily Loss: {dailyLoss.toFixed(2)}</div>
            <div>Trades Today: {todayTrades}/{maxTrades}</div>

            <div style={{
              color: riskBlocked ? "#FF4444" : "#00FFAA",
              fontWeight: "bold",
              marginTop: "5px"
            }}>
              {riskBlocked ? "🚫 BLOCKED" : "✅ SAFE"}
            </div>
          </div>

          {signals.length === 0 && (
            <div style={{ color: "#777", textAlign: "center", padding: "20px 0" }}>
              NO VALID TRADE ⚠️
            </div>
          )}

          {signals.map((s, i) => (
            <div
              key={i}
              onClick={() => {
                setSelected(s);
                setSymbol(s.symbol);
              }}
              style={{
                marginBottom: "15px",
                cursor: "pointer",
                padding: "8px",
                border:
                  selected?.symbol === s.symbol
                    ? "1px solid #00E5FF"
                    : "1px solid #222",
                borderRadius: "5px",
                background: "#111",
              }}
            >
              <div
                style={{
                  color:
                    s.score >= 80
                      ? "#00FFAA"
                      : s.score >= 60
                      ? "#00E5FF"
                      : "#ffaa00",
                  fontWeight: "bold",
                }}
              >
                {s.symbol} {s.type} ({s.rr}) 🔥{s.score}
              </div>
              <div style={{ fontSize: "11px", opacity: 0.7, marginTop: "4px" }}>
                {s.explain}
              </div>
              <div style={{ fontSize: "11px", color: "#aaa", marginTop: "4px" }}>
                MARK: {s.setupTag || "—"}
              </div>
            </div>
          ))}
        </div>

        <div
          id="chart-area"
          style={{
            flex: 1,
            minHeight: "400px",
            borderRadius: "8px",
            overflow: "hidden",
            position: "relative",
          }}
        >
          <Chart symbol={symbol} />
        </div>

        <div
          className="sidebar-panel"
          style={{ width: "100%", padding: "10px", overflowY: "auto" }}
        >
          {selected && (
            <>
              <h3 style={{ borderBottom: "1px solid #333", paddingBottom: "10px" }}>
                {selected.symbol}
              </h3>

              <div style={{ marginTop: "10px" }}>
                <label
                  style={{
                    display: "block",
                    marginBottom: "5px",
                    color: "#ccc",
                  }}
                >
                  Balance
                </label>
                <input
                  type="number"
                  value={balance}
                  onChange={(e) => setBalance(Number(e.target.value))}
                  style={{
                    background: "#222",
                    color: "#fff",
                    border: "1px solid #444",
                  }}
                />
              </div>

              <div style={{ marginTop: "10px" }}>
                <label
                  style={{
                    display: "block",
                    marginBottom: "5px",
                    color: "#ccc",
                  }}
                >
                  Risk %
                </label>
                <input
                  type="number"
                  value={riskPercent}
                  onChange={(e) => setRiskPercent(Number(e.target.value))}
                  style={{
                    background: "#222",
                    color: "#fff",
                    border: "1px solid #444",
                  }}
                />
              </div>

              <div style={{ marginTop: "10px", fontWeight: "bold" }}>
                Lot: {lot.toFixed(4)}
              </div>

              <button
                style={{
                  marginTop: "15px",
                  padding: "12px",
                  background: "#222",
                  color: "#fff",
                  border: "1px solid #444",
                  borderRadius: "5px",
                  fontWeight: "bold",
                }}
                onClick={async () => {
                  // Check risk block before manual trade as well
                  if (riskBlocked) {
                    alert("🚫 RISK LIMIT HIT!\nTrading diblokir hari ini.");
                    return;
                  }

                  const confirmTrade = window.confirm(
                    `CONFIRM TRADE 🚨\n\n${selected.symbol} ${selected.type}\n\nRR: ${selected.rr}\nSCORE: ${selected.score}\nTREND: ${trend}\n\nGas entry?`
                  );

                  if (!confirmTrade) return;

                  const risk = Math.abs(selected.entry - selected.sl);

                  setJournal((prev) => [
                    {
                      ...selected,
                      lot,
                      time: new Date().toLocaleString(),
                      result: "OPEN",
                      trailing: selected.sl,
                      tp1:
                        selected.type === "BUY"
                          ? selected.entry + risk * 1.5
                          : selected.entry - risk * 1.5,
                      tp2:
                        selected.type === "BUY"
                          ? selected.entry + risk * 2.5
                          : selected.entry - risk * 2.5,
                      tp3: selected.tp,
                      hitTP1: false,
                      hitTP2: false,
                      hitTP3: false,
                    },
                    ...prev,
                  ]);

                  pushToast(`📝 Manual trade logged: ${selected.symbol}`);
                  setLastTradeTime(Date.now());
                }}
              >
                EXECUTE MANUAL
              </button>
            </>
          )}

          {suggestion && (
            <div
              style={{
                marginTop: "20px",
                padding: "15px",
                border: "1px solid #00E5FF",
                borderRadius: "8px",
                background: "rgba(0, 229, 255, 0.05)",
              }}
            >
              <div
                style={{
                  color: "#00E5FF",
                  fontWeight: "bold",
                  fontSize: "16px",
                  marginBottom: "10px",
                }}
              >
                ⚡ AUTO SETUP READY
              </div>

              <div style={{ fontWeight: "bold" }}>
                {suggestion.symbol} {suggestion.type}
              </div>
              <div style={{ marginTop: "4px" }}>RR: {suggestion.rr}</div>
              <div style={{ marginTop: "4px" }}>SCORE: 🔥 {suggestion.score}</div>
              <div style={{ marginTop: "4px" }}>SETUP: {suggestion.setupTag}</div>
              <div
                style={{
                  fontSize: "11px",
                  marginTop: "8px",
                  opacity: 0.8,
                  background: "rgba(0,0,0,0.3)",
                  padding: "5px",
                  borderRadius: "4px",
                }}
              >
                {suggestion.explain}
              </div>

              <button
                style={{
                  marginTop: "15px",
                  background: "#00E5FF",
                  color: "#000",
                  fontWeight: "bold",
                  border: "none",
                  borderRadius: "4px",
                }}
                onClick={async () => {
                  if (riskBlocked) {
                    alert("🚫 RISK LIMIT HIT!\nTrading diblokir hari ini.");
                    return;
                  }

                  const confirmTrade = window.confirm(
                    `CONFIRM TRADE 🚨\n\n${suggestion.symbol} ${suggestion.type}\n\nRR: ${suggestion.rr}\nSCORE: ${suggestion.score}\nTREND: ${trend}\n\nGas entry?`
                  );

                  if (!confirmTrade) return;

                  const riskSugg = Math.abs(suggestion.entry - suggestion.sl);

                  setJournal((prev) => [
                    {
                      ...suggestion,
                      lot,
                      time: new Date().toLocaleString(),
                      result: "OPEN",
                      trailing: suggestion.sl,
                      tp1:
                        suggestion.type === "BUY"
                          ? suggestion.entry + riskSugg * 1.5
                          : suggestion.entry - riskSugg * 1.5,
                      tp2:
                        suggestion.type === "BUY"
                          ? suggestion.entry + riskSugg * 2.5
                          : suggestion.entry - riskSugg * 2.5,
                      tp3: suggestion.tp,
                      hitTP1: false,
                      hitTP2: false,
                      hitTP3: false,
                    },
                    ...prev,
                  ]);

                  pushToast(`📝 Auto suggestion logged: ${suggestion.symbol}`);
                  setLastTradeTime(Date.now());
                }}
              >
                🚀 CONFIRM TRADE
              </button>
            </div>
          )}

          {pendingTrade && (
            <div
              style={{
                marginTop: "20px",
                padding: "15px",
                border: "1px solid #FFB000",
                borderRadius: "8px",
                background: "rgba(255, 176, 0, 0.06)",
              }}
            >
              <div style={{ color: "#FFB000", fontWeight: "bold", marginBottom: "8px" }}>
                ⚡ SEMI AUTO READY
              </div>

              <div style={{ fontWeight: "bold" }}>
                {pendingTrade.symbol} {pendingTrade.type}
              </div>
              <div>RR: {pendingTrade.rr}</div>
              <div>SCORE: {pendingTrade.score}</div>
              <div>SETUP: {pendingTrade.setupTag || "-"}</div>

              <button
                onClick={executeTrade}
                style={{
                  marginTop: "12px",
                  background: "#FFB000",
                  color: "#000",
                  fontWeight: "bold",
                  border: "none",
                  borderRadius: "4px",
                }}
              >
                🚀 EXECUTE
              </button>
            </div>
          )}

          <div style={{ marginTop: "30px" }}>
            <h4
              style={{
                color: "#aaa",
                borderBottom: "1px solid #444",
                paddingBottom: "5px",
                marginBottom: "15px",
              }}
            >
              JOURNAL 📓
            </h4>

            {Object.entries(grouped).map(([symbol, trades]) => (
              <div key={symbol} style={{ marginBottom: "15px" }}>
                <div style={{ fontWeight: "bold", color: "#00E5FF" }}>
                  {symbol} ({trades.length})
                </div>

                {trades.map((j, i) => (
                  <div key={i} style={{
                    background: "#1a1e24",
                    padding: "10px",
                    marginTop: "5px",
                    borderLeft:
                      j.result === "TP"
                        ? "3px solid #00ff88"
                        : j.result === "SL"
                        ? "3px solid #ff4444"
                        : "3px solid #00E5FF"
                  }}>
                    <div style={{ fontWeight: "bold", fontSize: "14px" }}>
                      {j.type} → {j.result}
                    </div>

                    <div style={{ fontSize: "11px", color: "#aaa", marginTop: "4px" }}>
                      TP1: {j.hitTP1 ? "✔" : "-"} | 
                      TP2: {j.hitTP2 ? "✔" : "-"} | 
                      TP3: {j.hitTP3 ? "✔" : "-"}
                    </div>

                    {j.unrealized && (
                      <div style={{ color: "#aaa", fontSize: "11px" }}>
                        PnL: {j.unrealized.toFixed(2)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ position: "fixed", bottom: 20, right: 20, zIndex: 999 }}>
        {toasts.map((t) => (
          <div
            key={t.id}
            style={{
              background: "#111",
              padding: "12px 15px",
              marginBottom: "5px",
              borderLeft: "4px solid #00E5FF",
              boxShadow: "0 4px 6px rgba(0,0,0,0.5)",
              borderRadius: "4px",
              fontWeight: "bold",
            }}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}