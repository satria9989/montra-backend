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

// ─── SESSION HELPERS ───────────────────────────────────────────────────────────

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

// ─── ANALYSIS HELPERS ──────────────────────────────────────────────────────────

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
      sweepLow
        ? Number(c.close) < Number(c.open)
        : Number(c.close) > Number(c.open)
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

// ─── STATS HELPERS ─────────────────────────────────────────────────────────────

function getStreak(journal: JournalItem[]) {
  let win = 0;
  let lose = 0;
  for (let i = 0; i < journal.length; i++) {
    if (journal[i].result === "TP") { win++; lose = 0; }
    else if (journal[i].result === "SL") { lose++; win = 0; }
  }
  return { win, lose };
}

function getPairStats(journal: JournalItem[]) {
  const map: any = {};
  journal.forEach((j) => {
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

// ─── [7] TRADE DECISION ENGINE ─────────────────────────────────────────────────
// Menentukan aksi berdasarkan score confluence:
//   ≥80 → langsung execute | ≥60 → tunggu konfirmasi tambahan | <60 → skip
function getDecision(score: number) {
  if (score >= 75) return "EXECUTE";
  if (score >= 55) return "WAIT";
  return "SKIP";
}

// ─── [2] BIAS CARD ─────────────────────────────────────────────────────────────
function BiasCard({
  trend,
  h4Trend,
  session,
  kill,
}: {
  trend: TrendState;
  h4Trend: TrendState;
  session: string;
  kill: boolean;
}) {
  return (
    <div className="card">
      <h3>🧭 BIAS</h3>
      <p>
        H1: <strong style={{ color: trend === "BULL" ? "#00FFAA" : trend === "BEAR" ? "#FF4444" : "#FFB000" }}>{trend}</strong>
        {" | "}
        H4: <strong style={{ color: h4Trend === "BULL" ? "#00FFAA" : h4Trend === "BEAR" ? "#FF4444" : "#FFB000" }}>{h4Trend}</strong>
      </p>
      <p>
        {session}{" "}
        {kill ? <span style={{ color: "#00FFAA" }}>🔥 KILLZONE</span> : <span style={{ color: "#555" }}>• No Kill</span>}
      </p>
    </div>
  );
}

// ─── [3] CONFLUENCE CARD (DNA) ─────────────────────────────────────────────────
// Null-safe: tidak render jika belum ada signal selected
function ConfluenceCard({ selected }: { selected: Signal | null }) {
  if (!selected) return (
    <div className="card" style={{ opacity: 0.4 }}>
      <h3>🧬 DNA</h3>
      <p style={{ color: "#555" }}>— Pilih signal —</p>
    </div>
  );
  return (
    <div className="card">
      <h3>🧬 DNA</h3>
      <p>SCORE: <strong style={{ color: selected.score >= 80 ? "#00FFAA" : selected.score >= 60 ? "#00E5FF" : "#ffaa00" }}>{selected.score}</strong></p>
      <p>SETUP: {selected.setupTag || "—"}</p>
      <p style={{ fontSize: "11px", color: "#aaa" }}>AI: {selected.ai}</p>
    </div>
  );
}

// ─── [4] AI MEMORY CARD ────────────────────────────────────────────────────────
// Menampilkan memory score per pair dari backend /ai-memory
function AIMemoryCard({ aiMemory }: { aiMemory: Record<string, any> }) {
  const entries = Object.entries(aiMemory);
  return (
    <div className="card">
      <h3>🤖 AI MEMORY</h3>
      {entries.length === 0 ? (
        <p style={{ color: "#555", fontSize: "11px" }}>— No data —</p>
      ) : (
        entries.map(([sym, v]: any) => (
          <div key={sym} style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "3px" }}>
            <span>{sym}</span>
            <span style={{ color: v.score >= 80 ? "#00FFAA" : v.score >= 60 ? "#00E5FF" : "#ffaa00" }}>
              {v.score}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

// ─── [5] EXECUTION CARD ────────────────────────────────────────────────────────
// Ringkasan eksekusi signal terpilih; trigger setPendingTrade untuk semi-auto flow
function ExecutionCard({
  selected,
  setPendingTrade,
  lot,
  riskPercent,
  balance,
}: {
  selected: Signal | null;
  setPendingTrade: (s: Signal) => void;
  lot: number;
  riskPercent: number;
  balance: number;
}) {
  if (!selected) return (
    <div className="card" style={{ opacity: 0.4 }}>
      <h3>🎯 EXECUTION</h3>
      <p style={{ color: "#555" }}>— Pilih signal —</p>
    </div>
  );
  const decision = getDecision(selected.score);
  const decisionColor = decision === "EXECUTE" ? "#00FFAA" : decision === "WAIT" ? "#FFB000" : "#FF4444";
  const riskAmount = (balance * riskPercent) / 100;
  const stopDistance = Math.abs(selected.entry - selected.sl);
  const calculatedLot = riskAmount / stopDistance; // fallback jika prop lot tidak terdefinisi
  const displayLot = lot > 0 ? lot : calculatedLot;

  return (
    <div className="card">
      <h3>🎯 EXECUTION</h3>
      <p>
        <strong>{selected.symbol}</strong>{" "}
        <span style={{ color: selected.type === "BUY" ? "#00FFAA" : "#FF4444" }}>{selected.type}</span>
      </p>
      <p>ENTRY: {selected.entry}</p>
      <p>SL: <span style={{ color: "#FF4444" }}>{selected.sl}</span></p>
      <p>TP: <span style={{ color: "#00FFAA" }}>{selected.tp}</span></p>
      <p>RR: {selected.rr}</p>
      <p>CONF: {selected.score}%</p>
      {/* [1] AUTO POSITION SIZING */}
      <p>LOT SIZE: {displayLot.toFixed(4)}</p>
      {/* [2] SMART ENTRY FILTER (COUNTER TREND) */}
      {selected.explain.includes("Melawan trend") && (
        <p style={{ color: "#FF4444" }}>⚠ COUNTER TREND</p>
      )}
      {/* Decision engine label */}
      <p style={{ fontWeight: "bold", color: decisionColor, marginTop: "6px" }}>
        DECISION: {decision}
      </p>
      <button
        onClick={() => setPendingTrade(selected)}
        style={{
          marginTop: "10px",
          background: decision === "EXECUTE" ? "#00FFAA" : "#333",
          color: decision === "EXECUTE" ? "#000" : "#fff",
          fontWeight: "bold",
          border: "none",
          borderRadius: "4px",
        }}
      >
        🚀 EXECUTE
      </button>
    </div>
  );
}

// ─── [6] JOURNAL CARD ──────────────────────────────────────────────────────────
// Menampilkan 5 trade terakhir (dibalik agar terbaru di atas)
function JournalCard({ journal }: { journal: JournalItem[] }) {
  const recent = [...journal].reverse().slice(0, 5);
  return (
    <div className="card">
      <h3>📜 JOURNAL</h3>
      {recent.length === 0 ? (
        <p style={{ color: "#555", fontSize: "11px" }}>— Belum ada trade —</p>
      ) : (
        recent.map((j, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: "12px",
              padding: "4px 0",
              borderBottom: "1px solid #222",
            }}
          >
            <span>{j.symbol} <span style={{ color: j.type === "BUY" ? "#00FFAA" : "#FF4444" }}>{j.type}</span></span>
            <span style={{ color: j.result === "TP" ? "#00FFAA" : j.result === "SL" ? "#FF4444" : "#00E5FF" }}>
              {j.result}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

// ─── MAIN APP ──────────────────────────────────────────────────────────────────

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

  // ─── [4] AI MEMORY STATE ─────────────────────────────────────────────────────
  const [aiMemory, setAiMemory] = useState<Record<string, any>>({});

  // ─── AUTO MODE TOGGLE (UI Control) ──────────────────────────────────────────
  const [autoMode, setAutoMode] = useState(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastSignalsRef = useRef<Signal[]>([]);
  const sentPreRef = useRef<{ [key: string]: boolean }>({});

  const session = getSessionUTC();
  const kill = isKillzone();

  // ─── AUTH ─────────────────────────────────────────────────────────────────────

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, (u) => setUser(u));
    return () => unsub();
  }, []);

  // ─── ACCOUNTS ─────────────────────────────────────────────────────────────────

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

  // ─── [4] FETCH AI MEMORY ─────────────────────────────────────────────────────
  // Endpoint relatif /ai-memory; diambil sekali saat mount
  useEffect(() => {
    axios
      .get("https://montra-backend-9wku.onrender.com/ai-memory")
      .then((res) => setAiMemory(res.data || {}))
      .catch(() => {}); // silent fail jika endpoint belum tersedia
  }, []);

  const loginGoogle = async () => {
    try {
      const provider = new GoogleAuthProvider();
      const res = await signInWithPopup(auth, provider);
      console.log(res.user);
    } catch (e) {
      console.error("LOGIN ERROR:", e);
      alert("Login gagal, cek console");
    }
  };

  const name = user?.displayName || user?.email;
  const photo = user?.photoURL;

  // ─── AUDIO ────────────────────────────────────────────────────────────────────

  useEffect(() => {
    audioRef.current = new Audio(
      "https://actions.google.com/sounds/v1/alarms/beep_short.ogg"
    );
  }, []);

  // ─── PERSIST JOURNAL ──────────────────────────────────────────────────────────

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
      setJournal(snap.docs.map((d) => d.data()) as JournalItem[]);
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
              { ...j, uid: user.uid }
            );
            changed = true;
            return { ...j, saved: true };
          } catch {
            return j;
          }
        })
      );
      if (changed) setJournal(updated);
    };
    saveClosedTrades();
  }, [journal, user]);

  // ─── CHART CAPTURE ────────────────────────────────────────────────────────────

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

  // ─── AI FILTER ────────────────────────────────────────────────────────────────

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

  // ─── TOAST ────────────────────────────────────────────────────────────────────

  const pushToast = (text: string) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, text }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  };

  // ─── EXECUTE TRADE ────────────────────────────────────────────────────────────

  const executeTrade = async () => {
    if (!pendingTrade) return;
    if (riskBlocked) {
      alert("🚫 RISK LIMIT HIT!\nTrading diblokir hari ini.");
      return;
    }
    const cooldown = 60 * 5;
    if (Date.now() - lastTradeTime < cooldown * 1000) {
      const remaining = Math.ceil(
        (cooldown * 1000 - (Date.now() - lastTradeTime)) / 1000
      );
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
        risk: riskPercent,
      });
      pushToast(`🚀 TRADE SENT: ${pendingTrade.symbol}`);
      setPendingTrade(null);
      setLastTradeTime(Date.now());
    } catch (err) {
      console.error(err);
      pushToast("❌ TRADE FAILED");
    }
  };

  // ─── SCAN ENGINE ──────────────────────────────────────────────────────────────

  useEffect(() => {
    // if (!user) return;

    const scan = async () => {
      const results: Signal[] = [];
      try {
        const [h1Res, h4Res] = await Promise.all([
          axios.get(
            "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=100"
          ),
          axios.get(
            "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=100"
          ),
        ]);

        const mapCandle = (c: any[]) => ({
          time: Math.floor(c[0] / 1000),
          open: Number(c[1]),
          high: Number(c[2]),
          low: Number(c[3]),
          close: Number(c[4]),
        });

        const h1Data = (h1Res.data ?? []).map(mapCandle);
        const h4Data = (h4Res.data ?? []).map(mapCandle);

        const h1Trend = detectHTFTrend(h1Data);
        const h4TrendLocal = detectHTFTrend(h4Data);

        setTrend(h1Trend);
        setH4Trend(h4TrendLocal);

        for (const p of PAIRS) {
          try {
            const res = await axios.get(
              `https://api.binance.com/api/v3/klines?symbol=${p}&interval=1h&limit=100`
            );
            const data = (res.data ?? []).map(mapCandle);
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

            const body = Math.abs(Number(lastCandle.close) - Number(lastCandle.open));
            const range = Math.max(Number(lastCandle.high) - Number(lastCandle.low), 1e-9);
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
              inOBZone =
                Number(lastCandle.close) <= Number(ob.high) &&
                Number(lastCandle.close) >= Number(ob.low);
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
              (signal.type === "BUY" && h1Trend === "BULL" && h4TrendLocal === "BULL") ||
              (signal.type === "SELL" && h1Trend === "BEAR" && h4TrendLocal === "BEAR");

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

            const explain = generateExplain({ ...signal, score }, h1Trend, kill);
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

            if (fakeBreakout && newSignal.score >= 50 && !sentPreRef.current[preKey + "_fake"]) {
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
              // PAIR FILTER
              const pairStats = getPairStats(journal);
              const pair = pairStats[p] || { win: 0, loss: 0 };
              if (pair.loss >= 3 && pair.win === 0) continue;

              // ADAPTIVE SCORE BOOST
              const setupStats = getSetupStats(journal);
              const stat = setupStats[newSignal.setupTag || "UNKNOWN"];
              if (stat) {
                const setupTotal = stat.win + stat.loss;
                const setupWinrate = setupTotal > 0 ? stat.win / setupTotal : 0;
                if (setupWinrate >= 0.7 && setupTotal >= 5) score += 10;
                if (setupWinrate <= 0.3 && setupTotal >= 5) score -= 15;
              }

              // PAIR RANKING BOOST
              const pairTotal = pair.win + pair.loss;
              const pairWinrate = pairTotal > 0 ? pair.win / pairTotal : 0;
              if (pairWinrate >= 0.65 && pairTotal >= 5) score += 5;
              if (pairWinrate <= 0.35 && pairTotal >= 5) score -= 10;

              score = Math.max(0, Math.min(100, score));
              newSignal.score = score;

              results.push(newSignal);

              // ─── HUBUNGKAN DENGAN SIGNAL (kirim ke backend) ───────────────────
              // Mengirim sinyal valid ke endpoint /signal
              try {
                await axios.post("https://montra-backend-9wku.onrender.com/signal", newSignal);
              } catch (err) {
                console.error("Gagal mengirim signal ke backend:", err);
              }

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

  // ─── SUGGESTION SYNC ─────────────────────────────────────────────────────────

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

  // ─── PRICE WEBSOCKET ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (!user) return;
    const ws = new WebSocket(
      `wss://stream.binance.com:9443/stream?streams=${PAIRS.map(
        (p) => `${p.toLowerCase()}@trade`
      ).join("/")}`
    );
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      const sym = msg?.data?.s;
      const price = Number(msg?.data?.p);
      if (!sym || !Number.isFinite(price)) return;
      setPrices((prev) => {
        if (prev[sym] === price) return prev;
        return { ...prev, [sym]: price };
      });
    };
    return () => ws.close();
  }, [user]);

  // ─── TRAILING / TP HIT CHECK ─────────────────────────────────────────────────

  useEffect(() => {
    setJournal((prev) =>
      prev.map((j) => {
        const price = prices[j.symbol];
        if (!price || j.result !== "OPEN") return j;

        let newTrailing = j.trailing ?? j.sl;
        const move = Math.abs(j.tp - j.entry) * 0.3;

        if (j.type === "BUY") {
          if (price > j.entry + move)
            newTrailing = Math.max(newTrailing, price - move);
          if (!j.hitTP1 && price >= j.tp1!) { j.hitTP1 = true; newTrailing = j.entry; }
          if (!j.hitTP2 && price >= j.tp2!) { j.hitTP2 = true; newTrailing = j.tp1!; }
          if (price >= j.tp3!) return { ...j, result: "TP", hitTP3: true };
          if (price <= newTrailing) return { ...j, result: "SL" };
          return { ...j, trailing: newTrailing };
        }

        if (j.type === "SELL") {
          if (price < j.entry - move)
            newTrailing = Math.min(newTrailing, price + move);
          if (!j.hitTP1 && price <= j.tp1!) { j.hitTP1 = true; newTrailing = j.entry; }
          if (!j.hitTP2 && price <= j.tp2!) { j.hitTP2 = true; newTrailing = j.tp1!; }
          if (price <= j.tp3!) return { ...j, result: "TP", hitTP3: true };
          if (price >= newTrailing) return { ...j, result: "SL" };
          return { ...j, trailing: newTrailing };
        }

        return j;
      })
    );
  }, [prices]);

  // ─── STATS + RISK MANAGER ────────────────────────────────────────────────────

  useEffect(() => {
    let total = 0, win = 0, loss = 0, pnl = 0;
    const today = new Date().toDateString();
    let dayLoss = 0;
    let tradesToday = 0;

    journal.forEach((j) => {
      const tradeDate = new Date(j.time).toDateString();
      if (j.result === "TP") {
        total++; win++;
        pnl += Math.abs(j.tp - j.entry) * (j.lot || 1);
        if (tradeDate === today) tradesToday++;
      }
      if (j.result === "SL") {
        total++; loss++;
        const lossAmount = Math.abs(j.entry - j.sl) * (j.lot || 1);
        pnl -= lossAmount;
        if (tradeDate === today) { tradesToday++; dayLoss += lossAmount; }
      }
      if (j.unrealized && j.result === "OPEN") pnl += j.unrealized;
    });

    const winrate = total ? (win / total) * 100 : 0;
    setStats({ total, win, loss, pnl: Number(pnl.toFixed(2)), winrate: Number(winrate.toFixed(1)) });
    setDailyLoss(dayLoss);
    setTodayTrades(tradesToday);

    const lossPercent = balance > 0 ? (dayLoss / balance) * 100 : 0;
    const equityDrop = startBalance > 0 ? ((startBalance - balance) / startBalance) * 100 : 0;
    setRiskBlocked(lossPercent >= maxDailyLoss || tradesToday >= maxTrades || equityDrop >= 10);
  }, [journal, balance, maxDailyLoss, maxTrades, startBalance]);

  // ─── FETCH REAL POSITIONS ────────────────────────────────────────────────────

  useEffect(() => {
    const fetchPositions = async () => {
      try {
        // const res = await axios.get("https://montra-backend-9wku.onrender.com/positions");
        const positions: any[] = [];
        setJournal((prev) => {
          const updated = [...prev];
          positions.forEach((p: any) => {
            const exist = updated.find(
              (j) => j.symbol === p.symbol && j.result === "OPEN"
            );
            if (!exist) {
              updated.unshift({
                symbol: p.symbol, type: p.side, entry: p.entry,
                sl: 0, tp: 0, time: new Date().toISOString(), result: "OPEN",
                lot: p.size, exchangeId: p.symbol, unrealized: p.unrealized,
                rr: "", ai: "", score: 0, explain: "",
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

  // ─── DETECT CLOSED POSITIONS ─────────────────────────────────────────────────

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
              const relatedTrades = trades.filter(
                (t: any) => Math.abs(parseFloat(t.realizedPnl)) > 0
              );
              if (!relatedTrades.length) return j;
              const totalPnl = relatedTrades.reduce(
                (acc: number, t: any) => acc + parseFloat(t.realizedPnl),
                0
              );
              const hitTP1 = totalPnl > 0;
              const hitTP2 = totalPnl > Math.abs(j.entry - j.sl) * 0.5;
              const hitTP3 = totalPnl > Math.abs(j.entry - j.sl);
              if (hitTP3) return { ...j, result: "TP", hitTP3: true };
              if (totalPnl < 0) return { ...j, result: "SL" };
              return { ...j, hitTP1, hitTP2, unrealized: totalPnl };
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

  // ─── DYNAMIC RISK ────────────────────────────────────────────────────────────

  const { win: streakWin, lose: streakLose } = getStreak(journal);
  let dynamicRisk = riskPercent;
  if (streakWin >= 3) dynamicRisk = riskPercent * 1.5;
  if (streakLose >= 2) dynamicRisk = riskPercent * 0.5;
  dynamicRisk = Math.max(0.5, Math.min(dynamicRisk, 3));
  const effectiveRisk = riskBlocked ? 0 : dynamicRisk;
  const lot = selected
    ? ((balance * effectiveRisk) / 100) / Math.abs(selected.entry - selected.sl)
    : 0;

  // ─── [3] AUTO EXECUTION ──────────────────────────────────────────────────────
  // Ketika autoMode aktif dan pendingTrade memiliki skor ≥ 85, langsung eksekusi.
  useEffect(() => {
    if (!autoMode || !pendingTrade) return;
    if (pendingTrade.score >= 85) {
      executeTrade();
    }
  }, [pendingTrade, autoMode]);

  // ─── EXPORT CSV ──────────────────────────────────────────────────────────────

  function exportCSV() {
    if (!journal.length) return;
    const headers = ["Time", "Symbol", "Type", "Entry", "SL", "TP", "TP1", "TP2", "Result", "PnL"];
    const rows = journal.map((j) => {
      const pnl =
        j.result === "TP"
          ? (Math.abs(j.tp - j.entry) * (j.lot || 1)).toFixed(2)
          : j.result === "SL"
          ? (-Math.abs(j.entry - j.sl) * (j.lot || 1)).toFixed(2)
          : "0";
      return [j.time, j.symbol, j.type, j.entry, j.sl, j.tp, j.tp1 ?? "", j.tp2 ?? "", j.result, pnl].join(",");
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

  // ─── LOADING / LOGIN GATES ────────────────────────────────────────────────────

  if (user === undefined) {
    return (
      <div style={{ display: "flex", height: "100vh", background: "#0b0f14", color: "#fff", justifyContent: "center", alignItems: "center" }}>
        Loading...
      </div>
    );
  }

  if (!user) {
    return (
      <div style={{ display: "flex", height: "100vh", background: "#0b0f14", color: "#fff", justifyContent: "center", alignItems: "center", flexDirection: "column" }}>
        <h2>MONTRA ⚡</h2>
        <p style={{ color: "#aaa" }}>AI Crypto Trading Terminal</p>
        <button
          onClick={loginGoogle}
          style={{ marginTop: "20px", padding: "10px 20px", background: "#fff", color: "#000", border: "none", borderRadius: "5px", cursor: "pointer", fontWeight: "bold", fontSize: "16px" }}
        >
          🔐 Login with Google
        </button>
      </div>
    );
  }

  const grouped = groupBySymbol(journal);

  // ─── [1] RENDER — 4-PANEL LAYOUT ─────────────────────────────────────────────

  return (
    <div style={{ background: "#0b0f14", color: "#fff", minHeight: "100vh", fontSize: "14px", padding: "10px", boxSizing: "border-box" }}>

      {/* ── GLOBAL STYLES ── */}
      <style>{`
        * { box-sizing: border-box; }
        button {
          width: 100%;
          padding: 10px 12px;
          font-size: 13px;
          cursor: pointer;
        }
        input {
          width: 100%;
          padding: 8px 10px;
          margin-bottom: 5px;
          background: #222;
          color: #fff;
          border: 1px solid #444;
          border-radius: 4px;
        }
        input[type="checkbox"] {
          width: auto;
          margin-right: 8px;
        }

        /* ── CARD COMPONENT ── */
        .card {
          background: #0f172a;
          border: 1px solid #1e293b;
          border-radius: 8px;
          padding: 10px 12px;
          margin-bottom: 10px;
          font-size: 13px;
        }
        .card h3 {
          margin: 0 0 8px 0;
          font-size: 12px;
          color: #00E5FF;
          letter-spacing: 1px;
          text-transform: uppercase;
        }
        .card p {
          margin: 4px 0;
          color: #ccc;
        }

        /* ── [1] 4-PANEL GRID LAYOUT ── */
        .layout {
          display: grid;
          grid-template-columns: 260px 1fr 260px;
          grid-template-rows: 1fr auto;
          grid-template-areas:
            "left   center right"
            "btm    center right";
          gap: 10px;
          height: calc(100vh - 20px);
        }
        .panel-left    { grid-area: left;   overflow-y: auto; }
        .panel-center  { grid-area: center; overflow: hidden; border-radius: 8px; }
        .panel-btm     { grid-area: btm;    overflow-y: auto; }
        .panel-right   { grid-area: right;  overflow-y: auto; }

        /* ── MOBILE: stack vertically ── */
        @media (max-width: 900px) {
          .layout {
            grid-template-columns: 1fr;
            grid-template-rows: auto;
            grid-template-areas:
              "left"
              "center"
              "btm"
              "right";
            height: auto;
          }
          .panel-center { min-height: 350px; }
        }
      `}</style>

      {/* ── HEADER ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
        <h3 style={{ margin: 0 }}>MONTRA ⚡</h3>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {/* UI Control: Auto Mode Toggle */}
          <button
            onClick={() => setAutoMode(!autoMode)}
            style={{
              background: autoMode ? "#FF4444" : "#00E5FF",
              color: "#000",
              fontWeight: "bold",
              border: "none",
              borderRadius: "4px",
              padding: "4px 10px",
              fontSize: "12px",
              width: "auto",
              cursor: "pointer",
            }}
          >
            {autoMode ? "🛑 AUTO OFF" : "🤖 AUTO ON"}
          </button>
          {photo && <img src={photo} style={{ width: "28px", borderRadius: "50%" }} alt="User" />}
          <span style={{ color: "#00E5FF", fontWeight: "bold", fontSize: "12px" }}>{name}</span>
        </div>
      </div>

      {/* ── [1] 4-PANEL LAYOUT ── */}
      <div className="layout">

        {/* ── LEFT PANEL: Bias + DNA + AI Memory + Signal List ── */}
        <div className="panel-left">

          {/* [2] BIAS CARD */}
          <BiasCard trend={trend} h4Trend={h4Trend} session={session} kill={kill} />

          {/* [3] CONFLUENCE / DNA CARD */}
          <ConfluenceCard selected={selected} />

          {/* [4] AI MEMORY CARD */}
          <AIMemoryCard aiMemory={aiMemory} />

          <hr style={{ borderColor: "#1e293b", margin: "10px 0" }} />

          {/* STRICT MODE TOGGLE */}
          <label style={{ display: "flex", alignItems: "center", marginBottom: "10px", cursor: "pointer", fontSize: "12px", color: "#aaa" }}>
            <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
            STRICT MODE
          </label>

          {/* ACCOUNTS */}
          <div className="card">
            <h3>🏦 Accounts</h3>
            {accounts.map((a, i) => (
              <div key={i} style={{ marginBottom: "8px", fontSize: "11px" }}>
                <div style={{ fontWeight: "bold", color: "#fff" }}>{a.name}</div>
                {a.error ? (
                  <div style={{ color: "#FF4444" }}>ERROR</div>
                ) : (
                  <>
                    <div>Balance: {a.balance.toFixed(2)}</div>
                    <div style={{ color: a.unrealized >= 0 ? "#00FFAA" : "#FF4444" }}>
                      PnL: {a.unrealized.toFixed(2)}
                    </div>
                    <div>Equity: {a.equity.toFixed(2)} | Pos: {a.positions}</div>
                  </>
                )}
              </div>
            ))}
          </div>

          {/* PERFORMANCE */}
          <div className="card">
            <h3>📊 Performance</h3>
            <div>Total: {stats.total} | W: {stats.win} | L: {stats.loss}</div>
            <div>Winrate: {stats.winrate}%</div>
            <div style={{ color: stats.pnl >= 0 ? "#00FFAA" : "#FF4444", fontWeight: "bold", marginTop: "4px" }}>
              PnL: {stats.pnl}
            </div>
            <button onClick={exportCSV} style={{ marginTop: "8px", background: "#00E5FF", color: "#000", border: "none", borderRadius: "4px", fontWeight: "bold" }}>
              📁 Export CSV
            </button>
            {/* PnL history strip */}
            <div style={{ height: "40px", marginTop: "8px", background: "#111", borderRadius: "4px", padding: "4px", fontSize: "10px", overflowX: "auto", whiteSpace: "nowrap" }}>
              {journal.map((j, i) => (
                <span key={i} style={{ color: j.result === "TP" ? "#00FFAA" : j.result === "SL" ? "#FF4444" : "#555", marginRight: "4px" }}>
                  {j.result}
                </span>
              ))}
            </div>
          </div>

          {/* RISK MANAGER */}
          <div className="card" style={{ borderColor: riskBlocked ? "#FF4444" : "#1e293b" }}>
            <h3>🧠 Risk Manager</h3>
            <div>Daily Loss: {dailyLoss.toFixed(2)}</div>
            <div>Trades: {todayTrades}/{maxTrades}</div>
            <div style={{ color: riskBlocked ? "#FF4444" : "#00FFAA", fontWeight: "bold", marginTop: "4px" }}>
              {riskBlocked ? "🚫 BLOCKED" : "✅ SAFE"}
            </div>
          </div>

          {/* SIGNAL LIST */}
          {signals.length === 0 ? (
            <div style={{ color: "#555", textAlign: "center", padding: "15px 0", fontSize: "12px" }}>
              NO VALID SIGNAL ⚠️
            </div>
          ) : (
            signals.map((s, i) => (
              <div
                key={i}
                onClick={() => { setSelected(s); setSymbol(s.symbol); }}
                style={{
                  marginBottom: "8px",
                  cursor: "pointer",
                  padding: "8px",
                  border: selected?.symbol === s.symbol ? "1px solid #00E5FF" : "1px solid #222",
                  borderRadius: "6px",
                  background: "#111",
                }}
              >
                <div style={{ color: s.score >= 80 ? "#00FFAA" : s.score >= 60 ? "#00E5FF" : "#ffaa00", fontWeight: "bold" }}>
                  {s.symbol} {s.type} ({s.rr}) 🔥{s.score}
                </div>
                <div style={{ fontSize: "10px", opacity: 0.6, marginTop: "3px" }}>{s.explain}</div>
                <div style={{ fontSize: "10px", color: "#aaa", marginTop: "2px" }}>MARK: {s.setupTag || "—"}</div>
              </div>
            ))
          )}
        </div>

        {/* ── CENTER PANEL: Chart ── */}
        <div className="panel-center" id="chart-area">
          {/* selected prop added per spec; Chart dapat menggunakannya untuk overlay level */}
          <Chart symbol={symbol} selected={selected} />
        </div>

        {/* ── RIGHT PANEL: Journal ── */}
        <div className="panel-right">

          {/* [6] JOURNAL CARD — 5 trade terakhir */}
          <JournalCard journal={journal} />

          {/* AUTO SETUP READY */}
          {suggestion && (
            <div className="card" style={{ borderColor: "#00E5FF" }}>
              <h3 style={{ color: "#00E5FF" }}>⚡ Auto Setup Ready</h3>
              <div style={{ fontWeight: "bold" }}>{suggestion.symbol} {suggestion.type}</div>
              <div>RR: {suggestion.rr} | SCORE: 🔥{suggestion.score}</div>
              <div style={{ fontSize: "11px", color: "#aaa" }}>SETUP: {suggestion.setupTag}</div>
              <div style={{ fontSize: "10px", marginTop: "6px", opacity: 0.7, background: "rgba(0,0,0,0.3)", padding: "5px", borderRadius: "4px" }}>
                {suggestion.explain}
              </div>
              <button
                onClick={async () => {
                  if (riskBlocked) { alert("🚫 RISK LIMIT HIT!\nTrading diblokir hari ini."); return; }
                  const confirmTrade = window.confirm(`CONFIRM TRADE 🚨\n\n${suggestion.symbol} ${suggestion.type}\n\nRR: ${suggestion.rr}\nSCORE: ${suggestion.score}\nTREND: ${trend}\n\nGas entry?`);
                  if (!confirmTrade) return;
                  const riskSugg = Math.abs(suggestion.entry - suggestion.sl);
                  setJournal((prev) => [{
                    ...suggestion,
                    lot,
                    time: new Date().toLocaleString(),
                    result: "OPEN",
                    trailing: suggestion.sl,
                    tp1: suggestion.type === "BUY" ? suggestion.entry + riskSugg * 1.5 : suggestion.entry - riskSugg * 1.5,
                    tp2: suggestion.type === "BUY" ? suggestion.entry + riskSugg * 2.5 : suggestion.entry - riskSugg * 2.5,
                    tp3: suggestion.tp,
                    hitTP1: false, hitTP2: false, hitTP3: false,
                  }, ...prev]);
                  pushToast(`📝 Auto suggestion logged: ${suggestion.symbol}`);
                  setLastTradeTime(Date.now());
                }}
                style={{ marginTop: "10px", background: "#00E5FF", color: "#000", fontWeight: "bold", border: "none", borderRadius: "4px" }}
              >
                🚀 CONFIRM TRADE
              </button>
            </div>
          )}

          {/* SEMI AUTO READY */}
          {pendingTrade && (
            <div className="card" style={{ borderColor: "#FFB000" }}>
              <h3 style={{ color: "#FFB000" }}>⚡ Semi Auto Ready</h3>
              <div style={{ fontWeight: "bold" }}>{pendingTrade.symbol} {pendingTrade.type}</div>
              <div>RR: {pendingTrade.rr} | SCORE: {pendingTrade.score}</div>
              <div style={{ fontSize: "11px", color: "#aaa" }}>SETUP: {pendingTrade.setupTag || "-"}</div>
              <button
                onClick={executeTrade}
                style={{ marginTop: "10px", background: "#FFB000", color: "#000", fontWeight: "bold", border: "none", borderRadius: "4px" }}
              >
                🚀 EXECUTE
              </button>
            </div>
          )}

          {/* FULL GROUPED JOURNAL */}
          <div className="card">
            <h3>📓 Full Journal</h3>
            {Object.entries(grouped).map(([sym, trades]) => (
              <div key={sym} style={{ marginBottom: "12px" }}>
                <div style={{ fontWeight: "bold", color: "#00E5FF", fontSize: "12px" }}>
                  {sym} ({trades.length})
                </div>
                {trades.map((j, i) => (
                  <div key={i} style={{
                    background: "#1a1e24",
                    padding: "8px",
                    marginTop: "4px",
                    borderLeft: j.result === "TP" ? "3px solid #00ff88" : j.result === "SL" ? "3px solid #ff4444" : "3px solid #00E5FF",
                    borderRadius: "0 4px 4px 0",
                  }}>
                    <div style={{ fontWeight: "bold", fontSize: "12px" }}>{j.type} → {j.result}</div>
                    <div style={{ fontSize: "10px", color: "#aaa", marginTop: "3px" }}>
                      TP1: {j.hitTP1 ? "✔" : "-"} | TP2: {j.hitTP2 ? "✔" : "-"} | TP3: {j.hitTP3 ? "✔" : "-"}
                    </div>
                    {j.unrealized !== undefined && (
                      <div style={{ color: j.unrealized >= 0 ? "#00FFAA" : "#FF4444", fontSize: "10px" }}>
                        PnL: {j.unrealized.toFixed(2)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* ── BOTTOM-LEFT PANEL: Execution ── */}
        <div className="panel-btm">

          {/* [5] EXECUTION CARD dengan props tambahan */}
          <ExecutionCard
            selected={selected}
            setPendingTrade={setPendingTrade}
            lot={lot}
            riskPercent={riskPercent}
            balance={balance}
          />

          {/* BALANCE + RISK INPUTS */}
          {selected && (
            <div className="card">
              <h3>⚙️ Position Sizing</h3>
              <label style={{ color: "#ccc", fontSize: "12px" }}>Balance</label>
              <input
                type="number"
                value={balance}
                onChange={(e) => setBalance(Number(e.target.value))}
              />
              <label style={{ color: "#ccc", fontSize: "12px" }}>Risk %</label>
              <input
                type="number"
                value={riskPercent}
                onChange={(e) => setRiskPercent(Number(e.target.value))}
              />
              <div style={{ marginTop: "6px", fontWeight: "bold", fontSize: "12px" }}>
                Lot: {lot.toFixed(4)}
              </div>
              <button
                style={{ marginTop: "10px", background: "#222", color: "#fff", border: "1px solid #444", borderRadius: "5px", fontWeight: "bold" }}
                onClick={async () => {
                  if (riskBlocked) { alert("🚫 RISK LIMIT HIT!\nTrading diblokir hari ini."); return; }
                  const confirmTrade = window.confirm(
                    `CONFIRM TRADE 🚨\n\n${selected.symbol} ${selected.type}\n\nRR: ${selected.rr}\nSCORE: ${selected.score}\nTREND: ${trend}\n\nGas entry?`
                  );
                  if (!confirmTrade) return;
                  const risk = Math.abs(selected.entry - selected.sl);
                  setJournal((prev) => [{
                    ...selected, lot,
                    time: new Date().toLocaleString(),
                    result: "OPEN",
                    trailing: selected.sl,
                    tp1: selected.type === "BUY" ? selected.entry + risk * 1.5 : selected.entry - risk * 1.5,
                    tp2: selected.type === "BUY" ? selected.entry + risk * 2.5 : selected.entry - risk * 2.5,
                    tp3: selected.tp,
                    hitTP1: false, hitTP2: false, hitTP3: false,
                  }, ...prev]);
                  pushToast(`📝 Manual trade logged: ${selected.symbol}`);
                  setLastTradeTime(Date.now());
                }}
              >
                EXECUTE MANUAL
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── TOAST NOTIFICATIONS ── */}
      <div style={{ position: "fixed", bottom: 20, right: 20, zIndex: 999 }}>
        {toasts.map((t) => (
          <div key={t.id} style={{
            background: "#111",
            padding: "10px 14px",
            marginBottom: "5px",
            borderLeft: "4px solid #00E5FF",
            boxShadow: "0 4px 6px rgba(0,0,0,0.5)",
            borderRadius: "4px",
            fontWeight: "bold",
            fontSize: "13px",
          }}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}