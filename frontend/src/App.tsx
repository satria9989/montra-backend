import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import axios from "axios";
import Chart from "./Chart";

type TrendState = "BULL" | "BEAR" | "RANGE" | string;

type BackendSignal = {
  symbol: string;
  type: "BUY" | "SELL";
  entry: number;
  sl: number | null;
  tp: number | null;
  score?: number;
  rr?: number | string;
  regime?: string;
  pair_regime?: string;
  pair_tier?: string;
  vol?: number;
  explain?: string;
  reason?: string;
  ai?: string;
  setupTag?: string;
  [key: string]: any;
};

type AccountRow = {
  name: string;
  balance?: number;
  equity?: number;
  unrealized?: number;
  positions?: number;
  error?: string;
};

type PositionRow = {
  symbol: string;
  type: "BUY" | "SELL";
  entry?: number;
  mark?: number;
  sl?: number | null;
  tp?: number | null;
  rr?: number | null;
  size?: number;
  position_amt?: number;
  unrealized?: number;
  leverage?: number;
  locked?: boolean;
  has_snapshot?: boolean;
  protective_resolved?: boolean;
  sl_resolved?: boolean;
  tp_resolved?: boolean;
  account?: string;
};

type SkipSummaryRow = {
  reason: string;
  count: number;
};

type ExecutionDecisionRow = {
  time: string;
  stage: string;
  symbol: string;
  status: string;
  detail?: Record<string, any>;
};

type ExecutionSummary = {
  status: string;
  reason?: string;
  symbol?: string | null;
  side?: "BUY" | "SELL" | string | null;
  source?: string;
  candidate?: boolean;
  live_position?: boolean;
  protection?: string;
  last_stage?: string | null;
  last_status?: string | null;
  last_detail?: Record<string, any>;
  recent_decisions?: ExecutionDecisionRow[];
  since?: string | null;
  age_seconds?: number | null;
  last_scan_age_seconds?: number | null;
  updated_at?: string;
};

type DecisionBoard = {
  mode: string;
  validation_mode: boolean;
  kill_switch: boolean;
  auto_mode: boolean;
  auto_trading: boolean;
  ws: {
    running: boolean;
    thread_alive: boolean;
    app_alive?: boolean;
    restart_count: number;
    last_error: string | null;
    message_count?: number;
    last_message_age?: number;
    last_stream?: string | null;
    last_event?: string | null;
    subscribed_count?: number;
    sample_age: Record<string, number>;
    healthy?: boolean;
    degraded?: boolean;
    block?: boolean;
    reason?: string;
    stale?: string[];
    since_good?: number;
  };
  risk: {
    start_equity: number | null;
    daily_start_equity: number | null;
    daily_loss: number;
    current_risk: number;
    max_open_trades: number;
  };
  locks: {
    symbol_lock_count: number;
    execution_in_progress_count: number;
    locked_symbols: string[];
    executing_symbols: string[];
  };
  portfolio: {
    rows: { symbol: string; weight: number }[];
  };
  candidates: {
    count: number;
    rows: BackendSignal[];
  };
  selected: {
    count: number;
    rows: BackendSignal[];
  };
  live_positions?: {
    count: number;
    rows: PositionRow[];
  };
  skip_reasons: {
    count: number;
    summary: SkipSummaryRow[];
    rows: { time: string; symbol: string; reason: string; [key: string]: any }[];
  };
  execution_decisions: {
    count: number;
    rows: ExecutionDecisionRow[];
  };
  final_execution?: ExecutionSummary;
  circuit_breaker?: { active: boolean; remaining: number; consecutive_errors: number; threshold: number; pause: number };
  spread?: { threshold_top: number; threshold_mid: number; cache_ttl: number };
  telegram_alerts?: {
    enabled: boolean;
    available: boolean;
    cooldown_seconds: number;
    blocked_alert_minutes: number;
    scan_stale_alert_seconds: number;
    ws_block_alert_seconds: number;
    unprotected_alert_seconds: number;
    last_sent_ago_by_key?: Record<string, number>;
    last_alerts?: { key: string; time: string; sent: boolean; message: string }[];
  };
  sweep_memory?: { lookback: number; window: number; require_reclaim: boolean };
  analytics: {
    total_trades: number;
    open_snapshots: number;
    replay_log_size: number;
  };
};

type HealthReady = {
  status: string;
  mode: string;
  binance: boolean;
  openai: boolean;
  accounts: number;
};

type HealthLive = {
  status: string;
  mode: string;
};

type PairHealth = {
  scan_pairs: string[];
  top_pairs: string[];
  mid_pairs: string[];
  low_pairs: string[];
  validation_only: string[];
  remove_from_core: string[];
  limits: Record<string, number>;
};

type ApiError = {
  message: string;
};

type AccountsResponse = {
  accounts: AccountRow[];
  cached?: boolean;
  warning?: string;
};

const API_URL = (process.env.REACT_APP_API_URL || "http://localhost:8000").replace(/\/+$/, "");
const POLL_MS = 30_000;
const ACCOUNTS_POLL_MS = 45_000;

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  background: "#050b14",
  color: "#e8f1ff",
  fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif",
};

const cardStyle: CSSProperties = {
  background: "#0b1526",
  border: "1px solid #182741",
  borderRadius: 12,
  padding: 14,
  boxShadow: "0 10px 30px rgba(0,0,0,0.18)",
};

function formatNum(value: unknown, digits = 2) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : "-";
}

function positionToSignal(position: PositionRow | null): BackendSignal | null {
  if (!position) return null;
  const sl = position.sl == null ? null : Number(position.sl);
  const tp = position.tp == null ? null : Number(position.tp);
  return {
    symbol: position.symbol,
    type: position.type,
    entry: Number(position.entry ?? 0),
    sl: Number.isFinite(Number(sl)) ? sl : null,
    tp: Number.isFinite(Number(tp)) ? tp : null,
    rr: position.rr ?? undefined,
    score: undefined,
    regime: undefined,
    pair_regime: undefined,
    pair_tier: undefined,
    size: position.size,
    unrealized: position.unrealized,
    leverage: position.leverage,
    mark: position.mark,
    protective_resolved: position.protective_resolved,
    sl_resolved: position.sl_resolved,
    tp_resolved: position.tp_resolved,
    account: position.account,
  };
}

function StatusPill({ label, ok, warn }: { label: string; ok?: boolean; warn?: boolean }) {
  const bg = ok ? "rgba(0,255,170,0.18)" : warn ? "rgba(255,176,0,0.18)" : "rgba(255,68,68,0.18)";
  const color = ok ? "#00ffaa" : warn ? "#ffb000" : "#ff7272";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 10px",
        borderRadius: 999,
        border: `1px solid ${color}`,
        background: bg,
        color,
        fontSize: 12,
        fontWeight: 700,
      }}
    >
      {label}
    </span>
  );
}

function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section style={cardStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, letterSpacing: 0.2 }}>{title}</h3>
        {right}
      </div>
      {children}
    </section>
  );
}

function KeyValue({ label, value, accent }: { label: string; value: React.ReactNode; accent?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12, padding: "6px 0", borderBottom: "1px solid #132037" }}>
      <span style={{ color: "#8ea4c9" }}>{label}</span>
      <span style={{ color: accent || "#eef5ff", fontWeight: 700, textAlign: "right" }}>{value}</span>
    </div>
  );
}

function SignalCard({
  title,
  signal,
  onInspect,
  active,
}: {
  title: string;
  signal: BackendSignal | null;
  onInspect?: (signal: BackendSignal) => void;
  active?: boolean;
}) {
  if (!signal) {
    return (
      <Section title={title}>
        <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada data.</div>
      </Section>
    );
  }

  const rr = signal.rr ?? (Math.abs(Number(signal.tp) - Number(signal.entry)) / Math.max(Math.abs(Number(signal.entry) - Number(signal.sl)), 1e-9));

  return (
    <Section
      title={title}
      right={
        onInspect ? (
          <button
            onClick={() => onInspect(signal)}
            style={{
              border: "1px solid #1f6feb",
              background: active ? "#1f6feb" : "transparent",
              color: "#fff",
              borderRadius: 8,
              padding: "6px 10px",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {active ? "Sedang dilihat" : "Inspect"}
          </button>
        ) : null
      }
    >
      <div style={{ display: "grid", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800 }}>{signal.symbol}</div>
            <div style={{ fontSize: 12, color: signal.type === "BUY" ? "#00ffaa" : "#ff7272", fontWeight: 700 }}>{signal.type}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 12, color: "#8ea4c9" }}>Score</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: Number(signal.score) >= 70 ? "#00ffaa" : "#ffb000" }}>{formatNum(signal.score, 0)}</div>
          </div>
        </div>
        <KeyValue label="Entry" value={formatNum(signal.entry, 4)} accent="#8fd3ff" />
        <KeyValue label="SL" value={formatNum(signal.sl, 4)} accent="#ff7272" />
        <KeyValue label="TP" value={formatNum(signal.tp, 4)} accent="#00ffaa" />
        <KeyValue label="RR" value={typeof rr === "string" ? rr : formatNum(rr, 2)} />
        <KeyValue label="Tier" value={signal.pair_tier || "-"} />
        <KeyValue label="Regime" value={signal.pair_regime || signal.regime || "-"} />
        {signal.reason ? <KeyValue label="Reason" value={String(signal.reason)} accent="#ffb000" /> : null}
      </div>
    </Section>
  );
}

function shortDetail(detail?: Record<string, any>) {
  if (!detail || Object.keys(detail).length === 0) return "-";
  const text = JSON.stringify(detail);
  return text.length > 140 ? `${text.slice(0, 140)}...` : text;
}

function ExecutionSummarySection({ summary }: { summary?: ExecutionSummary | null }) {
  if (!summary) {
    return (
      <Section title="Execution summary">
        <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada ringkasan eksekusi.</div>
      </Section>
    );
  }

  const isGood = ["LIVE_PROTECTED", "ORDER_OK_PROTECTED"].includes(summary.status);
  const isWarn = ["CANDIDATE_WAITING", "ORDER_SENT_WAITING_POSITION", "CANDIDATE_AUTO_TRADING_OFF", "AUTO_MODE_OFF"].includes(summary.status);
  const accent = isGood ? "#00ffaa" : isWarn ? "#ffb000" : "#ff7272";

  return (
    <Section title="Execution summary">
      <div style={{ display: "grid", gap: 8 }}>
        <KeyValue label="Status" value={summary.status || "-"} accent={accent} />
        <KeyValue label="Age" value={summary.age_seconds == null ? "-" : `${formatNum(summary.age_seconds, 0)}s`} accent={Number(summary.age_seconds || 0) > 300 ? "#ffb000" : undefined} />
        <KeyValue label="Last scan age" value={summary.last_scan_age_seconds == null ? "-" : `${formatNum(summary.last_scan_age_seconds, 0)}s`} />
        <KeyValue label="Symbol" value={summary.symbol || "-"} />
        <KeyValue label="Side" value={summary.side || "-"} accent={summary.side === "BUY" ? "#00ffaa" : summary.side === "SELL" ? "#ff7272" : undefined} />
        <KeyValue label="Reason" value={summary.reason || "-"} accent={accent} />
        <KeyValue label="Protection" value={summary.protection || "-"} accent={summary.protection === "RESOLVED" ? "#00ffaa" : summary.protection === "PENDING" ? "#ffb000" : undefined} />
        <KeyValue label="Last stage" value={summary.last_stage || "-"} />
        <KeyValue label="Last status" value={summary.last_status || "-"} accent={summary.last_status === "PASS" || summary.last_status === "OK" ? "#00ffaa" : summary.last_status === "BLOCK" ? "#ffb000" : undefined} />
        <div style={{ fontSize: 11, color: "#6f819f", lineHeight: 1.45, wordBreak: "break-word" }}>
          Detail: {shortDetail(summary.last_detail)}
        </div>
      </div>
    </Section>
  );
}

function LivePositionsSection({
  positions,
  activeSignal,
  onInspect,
}: {
  positions: PositionRow[];
  activeSignal: BackendSignal | null;
  onInspect: (signal: BackendSignal) => void;
}) {
  return (
    <Section title={`Live positions (${positions.length})`}>
      {positions.length === 0 ? (
        <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada posisi live.</div>
      ) : (
        <div style={{ display: "grid", gap: 10, maxHeight: 360, overflow: "auto", paddingRight: 4 }}>
          {positions.map((pos) => {
            const signal = positionToSignal(pos);
            if (!signal) return null;
            const active = Boolean(activeSignal && activeSignal.symbol === signal.symbol && activeSignal.type === signal.type);
            const protectiveResolved = Boolean(pos.protective_resolved);
            return (
              <div key={`${pos.symbol}-${pos.type}`} style={{ border: `1px solid ${active ? "#1f6feb" : "#132037"}`, borderRadius: 10, padding: 10, background: active ? "#0b1730" : "#08111f" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 8 }}>
                  <div>
                    <div style={{ fontWeight: 800 }}>{pos.symbol}</div>
                    <div style={{ fontSize: 12, color: pos.type === "BUY" ? "#00ffaa" : "#ff7272", fontWeight: 700 }}>{pos.type}</div>
                  </div>
                  <button
                    onClick={() => onInspect(signal)}
                    style={{ border: "1px solid #1f6feb", background: active ? "#1f6feb" : "transparent", color: "#fff", borderRadius: 8, padding: "6px 10px", cursor: "pointer", fontSize: 12, fontWeight: 700 }}
                  >
                    {active ? "Sedang dilihat" : "Inspect"}
                  </button>
                </div>
                <KeyValue label="Entry" value={formatNum(pos.entry, 4)} accent="#8fd3ff" />
                <KeyValue label="Mark" value={formatNum(pos.mark, 4)} />
                <KeyValue label="Unrealized" value={`$${formatNum(pos.unrealized, 2)}`} accent={Number(pos.unrealized) >= 0 ? "#00ffaa" : "#ff7272"} />
                <KeyValue label="Size" value={formatNum(pos.size, 4)} />
                <KeyValue label="SL" value={pos.sl_resolved ? formatNum(pos.sl, 4) : "Pending"} accent={pos.sl_resolved ? "#ff7272" : "#ffb000"} />
                <KeyValue label="TP" value={pos.tp_resolved ? formatNum(pos.tp, 4) : "Pending"} accent={pos.tp_resolved ? "#00ffaa" : "#ffb000"} />
                <KeyValue label="Protection" value={protectiveResolved ? "Resolved" : "Resolving"} accent={protectiveResolved ? "#00ffaa" : "#ffb000"} />
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

export default function App() {
  const [healthLive, setHealthLive] = useState<HealthLive | null>(null);
  const [healthReady, setHealthReady] = useState<HealthReady | null>(null);
  const [pairHealth, setPairHealth] = useState<PairHealth | null>(null);
  const [decisionBoard, setDecisionBoard] = useState<DecisionBoard | null>(null);
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [accountsWarning, setAccountsWarning] = useState<string>("");
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [aiMemory, setAiMemory] = useState<Record<string, any>>({});
  const [apiError, setApiError] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [manualSymbol, setManualSymbol] = useState<string>("BTCUSDT");
  const [inspectedSignal, setInspectedSignal] = useState<BackendSignal | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchCore = async () => {
      try {
        const [liveRes, readyRes, pairsRes, boardRes, positionsRes, memoryRes] = await Promise.all([
          axios.get(`${API_URL}/health/live`),
          axios.get(`${API_URL}/health/ready`),
          axios.get(`${API_URL}/health/pairs`),
          axios.get(`${API_URL}/debug/decision-board`),
          axios.get(`${API_URL}/positions`),
          axios.get(`${API_URL}/ai-memory?active_only=true`),
        ]);

        if (cancelled) return;

        const nextBoard = boardRes.data as DecisionBoard;
        const nextPairs = pairsRes.data as PairHealth;
        const nextPositions = (positionsRes.data?.rows || nextBoard.live_positions?.rows || []) as PositionRow[];

        setHealthLive(liveRes.data);
        setHealthReady(readyRes.data);
        setPairHealth(nextPairs);
        setDecisionBoard(nextBoard);
        setPositions(nextPositions);
        const memoryPayload = memoryRes.data?.data || memoryRes.data || {};
        setAiMemory(memoryPayload);
        setApiError("");

        const backendSignal = nextBoard.selected?.rows?.[0] || nextBoard.candidates?.rows?.[0] || null;
        const firstLiveSignal = positionToSignal(nextPositions[0] || null);
        const preferredSignal = backendSignal || firstLiveSignal;

        setInspectedSignal((prev) => {
          if (prev) {
            const matchedCandidate = [nextBoard.selected?.rows?.[0], nextBoard.candidates?.rows?.[0], ...(nextBoard.candidates?.rows || [])].find((row) => row?.symbol === prev.symbol && row?.type === prev.type);
            if (matchedCandidate) return matchedCandidate;
            const matchedPosition = nextPositions.find((row) => row.symbol === prev.symbol && row.type === prev.type);
            if (matchedPosition) return positionToSignal(matchedPosition);
          }
          return preferredSignal || prev || null;
        });

        if (preferredSignal?.symbol) {
          setManualSymbol((prev) => (prev === preferredSignal.symbol ? prev : preferredSignal.symbol));
        } else if (!preferredSignal && nextPairs.scan_pairs?.length) {
          setManualSymbol((prev) => (nextPairs.scan_pairs.includes(prev) ? prev : nextPairs.scan_pairs[0]));
        }
      } catch (error: any) {
        if (cancelled) return;
        const msg = (error as ApiError)?.message || error?.message || "Frontend gagal membaca backend.";
        setApiError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchCore();
    const id = window.setInterval(fetchCore, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const fetchAccounts = async () => {
      try {
        const res = await axios.get(`${API_URL}/accounts`);
        if (cancelled) return;
        const payload = res.data as AccountsResponse;
        setAccounts(payload.accounts || []);
        setAccountsWarning(payload.warning || (payload.cached ? "accounts summary using cached snapshot" : ""));
      } catch (error: any) {
        if (cancelled) return;
        const msg = (error as ApiError)?.message || error?.message || "Gagal membaca accounts.";
        setAccountsWarning(msg);
      }
    };

    fetchAccounts();
    const id = window.setInterval(fetchAccounts, ACCOUNTS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const selectedSignal = decisionBoard?.selected?.rows?.[0] || null;
  const livePosition = positions?.[0] || decisionBoard?.live_positions?.rows?.[0] || null;
  const livePositionSignal = positionToSignal(livePosition);
  const topCandidate = decisionBoard?.candidates?.rows?.[0] || null;
  const activeSignal = inspectedSignal || selectedSignal || livePositionSignal || topCandidate || null;

  const sortedAiMemory = useMemo(() => {
    const activeSymbols = new Set(pairHealth?.scan_pairs || []);
    return Object.entries(aiMemory)
      .filter(([symbol]) => activeSymbols.size === 0 || activeSymbols.has(symbol))
      .map(([symbol, value]: [string, any]) => ({ symbol, score: Number(value?.score ?? value ?? 0) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 10);
  }, [aiMemory, pairHealth]);

  const symbolOptions = useMemo(() => {
    const set = new Set<string>();
    pairHealth?.scan_pairs?.forEach((s) => set.add(s));
    positions.forEach((p) => set.add(p.symbol));
    if (activeSignal?.symbol) set.add(activeSignal.symbol);
    if (manualSymbol) set.add(manualSymbol);
    return Array.from(set);
  }, [pairHealth, positions, activeSignal, manualSymbol]);

  const chartSymbol = activeSignal?.symbol || manualSymbol;
  const wsHealthy = Boolean(
    decisionBoard?.ws?.healthy === true &&
    decisionBoard?.ws?.block === false &&
    decisionBoard?.ws?.reason === "OK"
  );
  const maxSampleAge = Math.max(
    0,
    ...Object.values(decisionBoard?.ws?.sample_age || {}).map((v) => Number(v) || 0)
  );
  const finalExecution = decisionBoard?.final_execution || null;
  const scanUniverse = pairHealth?.scan_pairs?.length || 0;

  return (
    <div style={shellStyle}>
      <div style={{ maxWidth: 1600, margin: "0 auto", padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 24, fontWeight: 900, letterSpacing: 0.3 }}>MONTRA ⚡</div>
            <div style={{ fontSize: 12, color: "#8ea4c9", marginTop: 4 }}>
              Dashboard backend-first. Frontend tidak scan market sendiri; UI hanya membaca state backend.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <StatusPill label={healthLive?.mode || "-"} ok={healthLive?.status === "ok"} />
            <StatusPill label={decisionBoard?.kill_switch ? "KILL SWITCH ON" : "KILL SWITCH OFF"} ok={!decisionBoard?.kill_switch} warn={decisionBoard?.kill_switch} />
            <StatusPill label={decisionBoard?.auto_mode ? "AUTO MODE ON" : "AUTO MODE OFF"} ok={Boolean(decisionBoard?.auto_mode)} warn={!decisionBoard?.auto_mode} />
            <StatusPill label={decisionBoard?.auto_trading ? "AUTO TRADING ON" : "AUTO TRADING OFF"} ok={Boolean(decisionBoard?.auto_trading)} warn={!decisionBoard?.auto_trading} />
            <StatusPill label={wsHealthy ? "WS HEALTHY" : "WS WARNING"} ok={wsHealthy} warn={!wsHealthy} />
          </div>
        </div>

        {apiError ? (
          <div style={{ ...cardStyle, borderColor: "#6a1f1f", background: "#1a0e14", color: "#ff9b9b", marginBottom: 16 }}>
            Backend read error: {apiError}
          </div>
        ) : null}

        <div style={{ display: "grid", gridTemplateColumns: "320px minmax(0, 1fr) 360px", gap: 16, alignItems: "start" }}>
          <div style={{ display: "grid", gap: 16 }}>
            <Section title="Backend status">
              <KeyValue label="Ready" value={healthReady?.status || (loading ? "Loading..." : "-")} accent={healthReady?.status === "ready" ? "#00ffaa" : "#ffb000"} />
              <KeyValue label="Binance client" value={healthReady?.binance ? "ON" : "OFF"} accent={healthReady?.binance ? "#00ffaa" : "#ff7272"} />
              <KeyValue label="OpenAI" value={healthReady?.openai ? "ON" : "OFF"} accent={healthReady?.openai ? "#00ffaa" : "#ff7272"} />
              <KeyValue label="Accounts" value={healthReady?.accounts ?? "-"} />
              <KeyValue label="Universe scan" value={scanUniverse} />
              <KeyValue label="TOP / MID / LOW" value={`${pairHealth?.top_pairs?.length || 0} / ${pairHealth?.mid_pairs?.length || 0} / ${pairHealth?.low_pairs?.length || 0}`} />
              <KeyValue label="WS reason" value={decisionBoard?.ws?.reason || "-"} accent={wsHealthy ? "#00ffaa" : "#ffb000"} />
              <KeyValue label="WS msg age" value={`${formatNum(decisionBoard?.ws?.last_message_age, 2)}s`} accent={wsHealthy ? "#00ffaa" : "#ffb000"} />
              <KeyValue label="WS max age" value={`${formatNum(maxSampleAge, 2)}s`} accent={maxSampleAge < 20 ? "#00ffaa" : "#ffb000"} />
              <KeyValue label="WS messages" value={formatNum(decisionBoard?.ws?.message_count, 0)} />
              <KeyValue label="WS restarts" value={decisionBoard?.ws?.restart_count ?? "-"} />
            </Section>

            <SignalCard
              title="Selected signal (scan)"
              signal={selectedSignal}
              onInspect={setInspectedSignal}
              active={Boolean(activeSignal && selectedSignal && activeSignal.symbol === selectedSignal.symbol && activeSignal.type === selectedSignal.type)}
            />

            <LivePositionsSection
              positions={positions}
              activeSignal={activeSignal}
              onInspect={setInspectedSignal}
            />

            <Section title="Accounts">
              {accountsWarning ? <div style={{ marginBottom: 10, fontSize: 12, color: accountsWarning.includes("cached") ? "#ffb000" : "#ff9b9b" }}>{accountsWarning}</div> : null}
              <div style={{ display: "grid", gap: 10 }}>
                {accounts.length === 0 ? (
                  <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada data akun.</div>
                ) : (
                  accounts.map((acc) => (
                    <div key={acc.name} style={{ border: "1px solid #132037", borderRadius: 10, padding: 10, background: "#08111f" }}>
                      <div style={{ fontWeight: 800, marginBottom: 8 }}>{acc.name}</div>
                      {acc.error ? (
                        <div style={{ fontSize: 12, color: "#ff9b9b" }}>{acc.error}</div>
                      ) : (
                        <>
                          <KeyValue label="Balance" value={`$${formatNum(acc.balance, 2)}`} />
                          <KeyValue label="Equity" value={`$${formatNum(acc.equity, 2)}`} />
                          <KeyValue label="Unrealized" value={`$${formatNum(acc.unrealized, 2)}`} accent={Number(acc.unrealized) >= 0 ? "#00ffaa" : "#ff7272"} />
                          <KeyValue label="Open positions" value={acc.positions ?? 0} />
                        </>
                      )}
                    </div>
                  ))
                )}
              </div>
            </Section>

            <Section title="AI memory active top 10">
              <div style={{ display: "grid", gap: 8 }}>
                {sortedAiMemory.length === 0 ? (
                  <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada data AI memory.</div>
                ) : (
                  sortedAiMemory.map((row) => (
                    <div key={row.symbol} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                      <span>{row.symbol}</span>
                      <span style={{ color: row.score >= 70 ? "#00ffaa" : row.score >= 50 ? "#8fd3ff" : "#ffb000", fontWeight: 700 }}>{formatNum(row.score, 0)}</span>
                    </div>
                  ))
                )}
              </div>
            </Section>
          </div>

          <div style={{ display: "grid", gap: 16 }}>
            <Section
              title="Chart 2.0 / inspected signal"
              right={
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 12, color: "#8ea4c9" }}>Symbol</span>
                  <select
                    value={chartSymbol}
                    onChange={(e) => {
                      setManualSymbol(e.target.value);
                      const found = [selectedSignal, topCandidate, ...(decisionBoard?.candidates?.rows || [])].find((row) => row?.symbol === e.target.value) || null;
                      const liveFound = positions.find((row) => row.symbol === e.target.value) || null;
                      setInspectedSignal(found || positionToSignal(liveFound));
                    }}
                    style={{
                      background: "#08111f",
                      color: "#eef5ff",
                      border: "1px solid #1a2a46",
                      borderRadius: 8,
                      padding: "8px 10px",
                    }}
                  >
                    {symbolOptions.map((item) => (
                      <option key={item} value={item}>{item}</option>
                    ))}
                  </select>
                </div>
              }
            >
              <div style={{ fontSize: 12, color: "#8ea4c9", marginBottom: 12 }}>
                Source of truth untuk signal: backend `/debug/decision-board`. Chart 2.0 hanya membaca candle backend, lalu menambahkan overlay struktur dan likuiditas yang dihitung lokal dari candle backend. Tidak ada signal baru yang dibuat di frontend, dan panel bawah adalah proxy jujur berbasis harga/volume — bukan feed Coinglass/funding/OI real-time.
              </div>
              <Chart symbol={chartSymbol} selected={activeSignal} apiUrl={API_URL} />
              <div style={{ marginTop: 10, fontSize: 11, color: "#6f819f" }}>
                ANALYSIS = HTF OB/FVG + liquidity bands + selected signal backend. DEBUG = ANALYSIS + premium/discount + sweep markers + delta/participation proxies.
              </div>
            </Section>

            <Section title="Portfolio + runtime snapshot">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
                <div>
                  <div style={{ fontSize: 12, color: "#8ea4c9", marginBottom: 8 }}>Portfolio top weights</div>
                  <div style={{ display: "grid", gap: 8 }}>
                    {(decisionBoard?.portfolio?.rows || []).slice(0, 10).map((row) => (
                      <div key={row.symbol} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                        <span>{row.symbol}</span>
                        <span style={{ fontWeight: 700 }}>{formatNum(row.weight, 6)}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 12, color: "#8ea4c9", marginBottom: 8 }}>Runtime</div>
                  <KeyValue label="Current risk" value={formatNum(decisionBoard?.risk?.current_risk, 4)} />
                  <KeyValue label="Max open trades" value={decisionBoard?.risk?.max_open_trades ?? "-"} />
                  <KeyValue label="Daily loss" value={formatNum(decisionBoard?.risk?.daily_loss, 2)} />
                  <KeyValue label="Open snapshots" value={decisionBoard?.analytics?.open_snapshots ?? 0} />
                  <KeyValue label="Locked symbols" value={decisionBoard?.locks?.symbol_lock_count ?? 0} />
                  <KeyValue label="WS restart count" value={decisionBoard?.ws?.restart_count ?? 0} />
                  <KeyValue label="Circuit breaker" value={decisionBoard?.circuit_breaker?.active ? `PAUSE ${formatNum(decisionBoard?.circuit_breaker?.remaining, 0)}s` : "OK"} accent={decisionBoard?.circuit_breaker?.active ? "#ff7272" : "#00ffaa"} />
                  <KeyValue label="Errors" value={`${decisionBoard?.circuit_breaker?.consecutive_errors ?? 0} / ${decisionBoard?.circuit_breaker?.threshold ?? "-"}`} />
                  <KeyValue label="Spread TOP/MID" value={`${formatNum(decisionBoard?.spread?.threshold_top ? Number(decisionBoard.spread.threshold_top) * 100 : undefined, 3)}% / ${formatNum(decisionBoard?.spread?.threshold_mid ? Number(decisionBoard.spread.threshold_mid) * 100 : undefined, 3)}%`} />
                </div>
              </div>
            </Section>
          </div>

          <div style={{ display: "grid", gap: 16 }}>
            <SignalCard
              title="Top candidate"
              signal={topCandidate}
              onInspect={setInspectedSignal}
              active={Boolean(activeSignal && topCandidate && activeSignal.symbol === topCandidate.symbol && activeSignal.type === topCandidate.type)}
            />

            <Section title={`Candidates (${decisionBoard?.candidates?.count || 0})`}>
              <div style={{ display: "grid", gap: 8, maxHeight: 320, overflowY: "auto", paddingRight: 4 }}>
                {(decisionBoard?.candidates?.rows || []).length === 0 ? (
                  <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada candidate dari backend.</div>
                ) : (
                  (decisionBoard?.candidates?.rows || []).slice(0, 10).map((row, idx) => (
                    <button
                      key={`${row.symbol}-${row.type}-${idx}`}
                      onClick={() => setInspectedSignal(row)}
                      style={{
                        textAlign: "left",
                        background: activeSignal?.symbol === row.symbol && activeSignal?.type === row.type ? "#11213c" : "#08111f",
                        border: `1px solid ${activeSignal?.symbol === row.symbol && activeSignal?.type === row.type ? "#1f6feb" : "#132037"}`,
                        borderRadius: 10,
                        padding: 10,
                        color: "#eef5ff",
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <strong>{row.symbol}</strong>
                        <span style={{ color: row.type === "BUY" ? "#00ffaa" : "#ff7272", fontWeight: 700 }}>{row.type}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginTop: 6, fontSize: 12, color: "#8ea4c9" }}>
                        <span>Score {formatNum(row.score, 0)}</span>
                        <span>RR {typeof row.rr === "string" ? row.rr : formatNum(row.rr, 2)}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </Section>

            <Section title="Skip reasons summary">
              <div style={{ display: "grid", gap: 8 }}>
                {(decisionBoard?.skip_reasons?.summary || []).length === 0 ? (
                  <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada skip reason.</div>
                ) : (
                  (decisionBoard?.skip_reasons?.summary || []).slice(0, 10).map((row) => (
                    <div key={row.reason} style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12 }}>
                      <span style={{ color: "#d8e5ff" }}>{row.reason}</span>
                      <span style={{ fontWeight: 700, color: "#ffb000" }}>{row.count}</span>
                    </div>
                  ))
                )}
              </div>
            </Section>

            <ExecutionSummarySection summary={finalExecution} />

            <Section title="Spread gate monitor">
              <div style={{ display: "grid", gap: 8 }}>
                <KeyValue label="TOP threshold" value={`${formatNum(decisionBoard?.spread?.threshold_top ? Number(decisionBoard.spread.threshold_top) * 100 : undefined, 3)}%`} />
                <KeyValue label="MID threshold" value={`${formatNum(decisionBoard?.spread?.threshold_mid ? Number(decisionBoard.spread.threshold_mid) * 100 : undefined, 3)}%`} />
                <KeyValue label="Cache TTL" value={`${formatNum(decisionBoard?.spread?.cache_ttl, 0)}s`} />
                <div style={{ fontSize: 11, color: "#6f819f", lineHeight: 1.45 }}>
                  Live spread detail: <code>/debug/spread/{chartSymbol}</code>. Orderbook spread hanya dipanggil di pre-entry gate atau endpoint debug ini.
                </div>
              </div>
            </Section>

            <Section title="Sweep + Telegram monitor">
              <div style={{ display: "grid", gap: 8 }}>
                <KeyValue label="Sweep memory" value={`${decisionBoard?.sweep_memory?.window ?? "-"} candles / lookback ${decisionBoard?.sweep_memory?.lookback ?? "-"}`} />
                <KeyValue label="Require reclaim" value={decisionBoard?.sweep_memory?.require_reclaim ? "YES" : "NO"} accent={decisionBoard?.sweep_memory?.require_reclaim ? "#00ffaa" : "#ffb000"} />
                <KeyValue label="Telegram alerts" value={decisionBoard?.telegram_alerts?.enabled ? (decisionBoard?.telegram_alerts?.available ? "ON" : "TOKEN MISSING") : "OFF"} accent={decisionBoard?.telegram_alerts?.enabled && decisionBoard?.telegram_alerts?.available ? "#00ffaa" : "#ffb000"} />
                <KeyValue label="Blocked alert" value={`${formatNum(decisionBoard?.telegram_alerts?.blocked_alert_minutes, 0)}m`} />
                <KeyValue label="Scan stale alert" value={`${formatNum(decisionBoard?.telegram_alerts?.scan_stale_alert_seconds, 0)}s`} />
                <KeyValue label="Last alerts" value={decisionBoard?.telegram_alerts?.last_alerts?.length ?? 0} />
                <div style={{ fontSize: 11, color: "#6f819f", lineHeight: 1.45 }}>
                  Debug: <code>/debug/sweep-memory/{chartSymbol}</code> dan <code>/debug/telegram-alerts</code>.
                </div>
              </div>
            </Section>

            <Section title="Execution decisions">
              <div style={{ display: "grid", gap: 8, maxHeight: 240, overflowY: "auto", paddingRight: 4 }}>
                {(decisionBoard?.execution_decisions?.rows || []).length === 0 ? (
                  <div style={{ color: "#6f819f", fontSize: 12 }}>Belum ada execution decision.</div>
                ) : (
                  (decisionBoard?.execution_decisions?.rows || []).slice().reverse().map((row, idx) => (
                    <div key={`${row.time}-${row.symbol}-${idx}`} style={{ border: "1px solid #132037", borderRadius: 10, padding: 10, background: "#08111f" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12, marginBottom: 6 }}>
                        <strong>{row.symbol}</strong>
                        <span style={{ color: row.status === "PASS" || row.status === "OK" ? "#00ffaa" : "#ffb000", fontWeight: 700 }}>{row.status}</span>
                      </div>
                      <div style={{ fontSize: 12, color: "#8ea4c9" }}>{row.stage} • {row.time}</div>
                    </div>
                  ))
                )}
              </div>
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
