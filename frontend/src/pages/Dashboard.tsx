import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Calendar,
  ChevronRight,
  Database,
  DollarSign,
  LucideIcon,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getDashboardSummary, getModelAnalytics, getRequestAnalytics } from "../api/analytics";
import { getLogs } from "../api/logs";
import { getModels } from "../api/models";
import ApiKeysSection from "../components/ApiKeysSection";
import ChartTooltip from "../components/ChartTooltip";
import { useToast } from "../components/Toast";
import { useCountUp, useFadeIn } from "../hooks/animation";
import { useTheme } from "../hooks/theme";
import type {
  AnalyticsModel,
  AnalyticsRequests,
  AuditLog,
  CostDriver,
  DashboardSummary,
  FlagSeverity,
  MetricDelta,
  Model,
  RiskBreakdown,
  SeverityBreakdown,
} from "../types";

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function fmtUsd(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(6)}`;
  return `$${n.toFixed(2)}`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtRange(start: Date, end: Date): string {
  const sameYear = start.getFullYear() === end.getFullYear();
  const sFmt: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const eFmt: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric" };
  if (!sameYear) sFmt.year = "numeric";
  return `${start.toLocaleDateString(undefined, sFmt)} – ${end.toLocaleDateString(undefined, eFmt)}`;
}

// ---------------------------------------------------------------------------
// Card palette — each metric card has its own accent for icon + tint.
// Per-visual colors (risk levels, severity, cost shades) are local to the
// card that uses them so the palette stays self-documenting.
// ---------------------------------------------------------------------------

type Accent = "blue" | "purple" | "green" | "red";

const ACCENT: Record<Accent, { tint: string; iconBg: string; iconColor: string }> = {
  blue:   { tint: "var(--accent-blue-tint)",   iconBg: "var(--accent-blue-tint)",   iconColor: "var(--accent-blue)" },
  purple: { tint: "var(--accent-purple-tint)", iconBg: "var(--accent-purple-tint)", iconColor: "var(--accent-purple)" },
  green:  { tint: "var(--accent-green-tint)",  iconBg: "var(--accent-green-tint)",  iconColor: "var(--accent-green)" },
  red:    { tint: "var(--accent-red-tint)",    iconBg: "var(--accent-red-tint)",    iconColor: "var(--accent-red)" },
};

const BAR_COLORS = [
  "var(--accent-blue)",
  "var(--accent-green)",
  "var(--accent-purple)",
  "var(--accent-amber)",
  "var(--accent-red)",
];

// Spec colors — kept literal (not via vars) because they're brand-specific
// per the design system and must read the same in light + dark.
const RISK = {
  Low:      "#97C459",
  Medium:   "#EF9F27",
  High:     "#D85A30",
  Critical: "#E24B4A",
} as const;

const SEVERITY = {
  RED:    "#E24B4A",
  YELLOW: "#EF9F27",
  GREEN:  "#97C459",
} as const;

const COST_SHADES = ["#1D9E75", "#5DCAA5", "#9FE1CB"] as const;

const CALLS_PURPLE = "#7F77DD";
const CALLS_PURPLE_LIGHT = "#CECBF6";

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [requestSeries, setRequestSeries] = useState<AnalyticsRequests[]>([]);
  const [modelAnalytics, setModelAnalytics] = useState<AnalyticsModel[]>([]);
  const [recentLogs, setRecentLogs] = useState<AuditLog[]>([]);
  const [recentFlagged, setRecentFlagged] = useState<AuditLog[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const { showToast } = useToast();
  const { effective } = useTheme();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [s, ra, ma, rl, rf, ms] = await Promise.all([
          getDashboardSummary(),
          getRequestAnalytics("30d"),
          getModelAnalytics(),
          getLogs({ limit: 5 }),
          getLogs({ flagged: true, limit: 5 }),
          getModels(),
        ]);
        if (cancelled) return;
        setSummary(s);
        setRequestSeries(ra);
        setModelAnalytics(ma);
        setRecentLogs(rl.items);
        setRecentFlagged(rf.items);
        setModels(ms);
      } catch (err) {
        if (!cancelled)
          showToast(err instanceof Error ? err.message : "Failed to load", "error");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [showToast, refreshKey]);

  const modelById = useMemo(() => {
    const map = new Map<string, Model>();
    for (const m of models) map.set(m.id, m);
    return map;
  }, [models]);

  const topModels = useMemo(
    () => [...modelAnalytics].sort((a, b) => b.total_calls - a.total_calls).slice(0, 5),
    [modelAnalytics]
  );

  // Page header date range — last 30 days.
  const now = useMemo(() => new Date(), [refreshKey]);
  const rangeStart = new Date(now);
  rangeStart.setDate(rangeStart.getDate() - 29);
  const pageRange = fmtRange(rangeStart, now);

  // Theme-aware chart colors.
  const gridColor = effective === "dark" ? "#1f2937" : "#e5e7eb";
  const axisColor = effective === "dark" ? "#6b7280" : "#94a3b8";

  return (
    <div className="min-h-screen p-6 md:p-8" style={{ background: "var(--color-page-bg)" }}>
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--color-text-primary)" }}>
            Dashboard
          </h1>
          <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
            AI governance overview
          </p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangePill label={pageRange} />
          <button
            onClick={() => setRefreshKey((k) => k + 1)}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition hover:translate-y-[-1px]"
            style={{
              background: "var(--color-card-bg)",
              borderColor: "var(--color-card-border)",
              color: "var(--color-text-primary)",
            }}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ModelsCard delay={0} loading={loading} breakdown={summary?.models_by_risk} />
        <CallsCard
          delay={100}
          loading={loading}
          count={summary?.calls_this_month ?? 0}
          delta={summary?.calls_delta}
          requestSeries={requestSeries}
        />
        <CostCard
          delay={200}
          loading={loading}
          cost={summary?.cost_this_month ?? 0}
          delta={summary?.cost_delta}
          drivers={summary?.top_cost_models ?? []}
        />
        <OpenFlagsCard
          delay={300}
          loading={loading}
          openCount={summary?.open_flags ?? 0}
          delta={summary?.flags_delta}
          breakdown={summary?.open_flags_by_severity}
        />
      </section>

      <section className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2" style={useFadeIn(400)}>
        <Card title="Daily Cost (last 30 days)" rightSlot={<MiniSelect label="Daily" />}>
          {loading ? (
            <ChartSkeleton />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart
                data={(summary?.cost_last_30_days ?? []).map((p) => ({
                  date: fmtDate(p.date),
                  cost: p.cost,
                }))}
                margin={{ top: 10, right: 16, bottom: 0, left: 0 }}
              >
                <defs>
                  <linearGradient id="dashCostFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%"   stopColor="var(--accent-green)" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="var(--accent-green)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="4 4" stroke={gridColor} vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke={axisColor} tickLine={false} axisLine={false} />
                <YAxis
                  tick={{ fontSize: 11 }}
                  stroke={axisColor}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
                />
                <Tooltip
                  content={<ChartTooltip />}
                  formatter={(v) => [fmtUsd(Number(v)), "Cost"]}
                  cursor={{ stroke: gridColor, strokeWidth: 1 }}
                />
                <Area
                  type="monotone"
                  dataKey="cost"
                  stroke="var(--accent-green)"
                  strokeWidth={2.25}
                  fill="url(#dashCostFill)"
                  dot={{
                    r: 3.5,
                    fill: effective === "dark" ? "#11161f" : "#ffffff",
                    stroke: "var(--accent-green)",
                    strokeWidth: 2,
                  }}
                  activeDot={{ r: 5, stroke: "var(--accent-green)", strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Requests by Model (top 5)" rightSlot={<MiniSelect label="This Month" />}>
          {loading ? (
            <ChartSkeleton />
          ) : topModels.length === 0 ? (
            <EmptyState text="No model usage yet" />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart
                layout="vertical"
                data={topModels}
                margin={{ top: 10, right: 56, bottom: 0, left: 8 }}
              >
                <CartesianGrid strokeDasharray="4 4" stroke={gridColor} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} stroke={axisColor} tickLine={false} axisLine={false} />
                <YAxis
                  type="category"
                  dataKey="model_name"
                  tick={{ fontSize: 12 }}
                  stroke={axisColor}
                  tickLine={false}
                  axisLine={false}
                  width={140}
                />
                <Tooltip
                  content={<ChartTooltip />}
                  formatter={(v) => [Number(v).toLocaleString(), "Requests"]}
                  cursor={{ fill: "transparent" }}
                />
                <Bar dataKey="total_calls" radius={[0, 6, 6, 0]} barSize={18}>
                  {topModels.map((m, i) => (
                    <Cell key={m.model_name} fill={BAR_COLORS[i % BAR_COLORS.length]} />
                  ))}
                  <LabelList
                    dataKey="total_calls"
                    position="right"
                    offset={8}
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      fill: "var(--color-text-primary)",
                    }}
                    formatter={(v) => Number(v ?? 0).toLocaleString()}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </section>

      <section className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2" style={useFadeIn(500)}>
        <Card
          title="Recent Flags"
          rightSlot={
            <a href="/flags" className="text-xs font-medium" style={{ color: "var(--vigil-green)" }}>
              View all →
            </a>
          }
        >
          {loading ? (
            <TableSkeleton rows={5} />
          ) : recentFlagged.length === 0 ? (
            <EmptyState text="No flagged calls" />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider" style={{ color: "var(--color-text-muted)" }}>
                  <th className="pb-2 pr-3 font-medium">Severity</th>
                  <th className="pb-2 pr-3 font-medium">Model</th>
                  <th className="pb-2 pr-3 font-medium">When</th>
                  <th className="pb-2 w-6" aria-hidden />
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: "var(--color-divider)" }}>
                {recentFlagged.map((log) => (
                  <tr key={log.id} className="vigil-row">
                    <td className="py-2.5 pr-3">
                      <SeverityPill severity={log.flag_severity} />
                    </td>
                    <td className="py-2.5 pr-3" style={{ color: "var(--color-text-primary)" }}>
                      {modelById.get(log.model_id)?.name ?? "—"}
                    </td>
                    <td className="py-2.5 pr-3" style={{ color: "var(--color-text-secondary)" }}>
                      {fmtTime(log.timestamp)}
                    </td>
                    <td className="py-2.5 text-right">
                      <ChevronRight className="inline h-4 w-4" style={{ color: "var(--color-text-muted)" }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card
          title="Recent Logs"
          rightSlot={
            <a href="/logs" className="text-xs font-medium" style={{ color: "var(--vigil-green)" }}>
              View all →
            </a>
          }
        >
          {loading ? (
            <TableSkeleton rows={5} />
          ) : recentLogs.length === 0 ? (
            <EmptyState text="No audit logs yet" />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider" style={{ color: "var(--color-text-muted)" }}>
                  <th className="pb-2 pr-3 font-medium">Time</th>
                  <th className="pb-2 pr-3 font-medium">Model</th>
                  <th className="pb-2 pr-3 font-medium">Cost</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: "var(--color-divider)" }}>
                {recentLogs.map((log) => (
                  <tr key={log.id} className="vigil-row">
                    <td className="py-2.5 pr-3" style={{ color: "var(--color-text-secondary)" }}>
                      {fmtTime(log.timestamp)}
                    </td>
                    <td className="py-2.5 pr-3" style={{ color: "var(--color-text-primary)" }}>
                      {modelById.get(log.model_id)?.name ?? "—"}
                    </td>
                    <td className="py-2.5 pr-3" style={{ color: "var(--color-text-primary)" }}>
                      {fmtUsd(log.total_cost_usd)}
                    </td>
                    <td className="py-2.5">
                      <StatusPill status={log.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </section>

      <section className="mt-6">
        <ApiKeysSection />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DateRangePill({ label }: { label: string }) {
  return (
    <span
      className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium"
      style={{
        background: "var(--color-card-bg)",
        borderColor: "var(--color-card-border)",
        color: "var(--color-text-primary)",
      }}
    >
      <Calendar className="h-4 w-4" style={{ color: "var(--color-text-secondary)" }} />
      {label}
    </span>
  );
}

function MiniSelect({ label }: { label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium"
      style={{
        background: "var(--color-card-bg)",
        borderColor: "var(--color-card-border)",
        color: "var(--color-text-secondary)",
      }}
    >
      {label}
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden>
        <path d="M2.5 4 5 6.5 7.5 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Shared card shell — header (icon + label), big number, slot for visual,
// slot for footer. The four specialized cards below compose into it.
// ---------------------------------------------------------------------------

function CardShell({
  icon: Icon,
  label,
  numericValue,
  accent,
  loading,
  delay,
  formatter,
  visual,
  footer,
}: {
  icon: LucideIcon;
  label: string;
  numericValue: number;
  accent: Accent;
  loading: boolean;
  delay: number;
  formatter?: (n: number) => string;
  visual: React.ReactNode;
  footer: React.ReactNode;
}) {
  const a = ACCENT[accent];
  const animated = useCountUp(loading ? 0 : numericValue, 800);
  const fadeStyle = useFadeIn(delay);
  const display = formatter ? formatter(animated) : Math.round(animated).toLocaleString();
  return (
    <div
      className="vigil-card vigil-card-interactive flex flex-col p-4"
      style={{
        ...fadeStyle,
        background: `linear-gradient(180deg, ${a.tint} 0%, var(--color-card-bg) 70%)`,
        border: "1px solid var(--color-card-border)",
      }}
    >
      <div className="flex items-center gap-2.5">
        <span
          className="flex h-9 w-9 items-center justify-center rounded-full"
          style={{ background: a.iconBg }}
        >
          <Icon className="h-4 w-4" style={{ color: a.iconColor }} />
        </span>
        <span
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--color-text-secondary)" }}
        >
          {label}
        </span>
      </div>

      <div className="mt-3">
        {loading ? (
          <div className="vigil-shimmer h-8 w-20 rounded" />
        ) : (
          <div className="text-3xl font-semibold" style={{ color: "var(--color-text-primary)" }}>
            {display}
          </div>
        )}
      </div>

      <div className="mt-3 flex-1">{loading ? <div className="vigil-shimmer h-6 w-full rounded" /> : visual}</div>

      <div className="mt-3 text-xs" style={{ color: "var(--color-text-muted)" }}>
        {loading ? <div className="vigil-shimmer h-4 w-32 rounded" /> : footer}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card 1 — Models Registered: stacked bar by risk + legend
// ---------------------------------------------------------------------------

function ModelsCard({
  delay,
  loading,
  breakdown,
}: {
  delay: number;
  loading: boolean;
  breakdown?: RiskBreakdown;
}) {
  const b = breakdown ?? { low: 0, medium: 0, high: 0, critical: 0, added_this_month: 0 };
  const total = b.low + b.medium + b.high + b.critical;
  const segments = [
    { count: b.low,      color: RISK.Low,      label: "low" },
    { count: b.medium,   color: RISK.Medium,   label: "med" },
    { count: b.high,     color: RISK.High,     label: "high" },
    { count: b.critical, color: RISK.Critical, label: "critical" },
  ];
  return (
    <CardShell
      icon={Database}
      label="Models Registered"
      numericValue={total}
      accent="blue"
      loading={loading}
      delay={delay}
      visual={
        total === 0 ? (
          <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>No models yet</div>
        ) : (
          <>
            <StackedBar segments={segments} total={total} />
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
              {segments
                .filter((s) => s.count > 0)
                .map((s, i, arr) => (
                  <span key={s.label} className="inline-flex items-center gap-1">
                    <Dot color={s.color} />
                    <span style={{ color: "var(--color-text-primary)" }}>{s.count}</span>
                    <span>{s.label}</span>
                    {i < arr.length - 1 && <span style={{ color: "var(--color-text-muted)" }}>·</span>}
                  </span>
                ))}
            </div>
          </>
        )
      }
      footer={
        b.added_this_month > 0
          ? `${b.added_this_month} added this month`
          : "No new models this month"
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Card 2 — Calls This Month: 14 daily-bucketed bars + signed delta
// ---------------------------------------------------------------------------

const CALLS_BUCKET_COUNT = 14;

function bucketCounts(series: number[], buckets: number): number[] {
  if (series.length === 0) return Array(buckets).fill(0);
  const out: number[] = [];
  for (let i = 0; i < buckets; i++) {
    const start = Math.floor((i * series.length) / buckets);
    const end = Math.floor(((i + 1) * series.length) / buckets);
    let sum = 0;
    for (let j = start; j < end; j++) sum += series[j] ?? 0;
    out.push(sum);
  }
  return out;
}

function CallsCard({
  delay,
  loading,
  count,
  delta,
  requestSeries,
}: {
  delay: number;
  loading: boolean;
  count: number;
  delta?: MetricDelta;
  requestSeries: AnalyticsRequests[];
}) {
  const buckets = bucketCounts(requestSeries.map((p) => p.count), CALLS_BUCKET_COUNT);
  const peak = Math.max(1, ...buckets);
  const peakIndex = buckets.indexOf(Math.max(...buckets));
  return (
    <CardShell
      icon={Activity}
      label="Calls This Month"
      numericValue={count}
      accent="purple"
      loading={loading}
      delay={delay}
      visual={
        <div className="flex h-10 items-end gap-1">
          {buckets.map((v, i) => (
            <div
              key={i}
              className="flex-1 rounded-sm"
              style={{
                height: `${Math.max(4, (v / peak) * 100)}%`,
                background: i === peakIndex ? CALLS_PURPLE : CALLS_PURPLE_LIGHT,
                transition: "height 0.4s ease",
              }}
            />
          ))}
        </div>
      }
      footer={
        <DeltaText
          delta={delta}
          invert={false}
          formatFallback={(n) => `${Math.round(n).toLocaleString()} calls this period`}
        />
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Card 3 — Cost This Month: top driver name + 3-segment cost-share bar
// ---------------------------------------------------------------------------

function CostCard({
  delay,
  loading,
  cost,
  delta,
  drivers,
}: {
  delay: number;
  loading: boolean;
  cost: number;
  delta?: MetricDelta;
  drivers: CostDriver[];
}) {
  const top3 = drivers.slice(0, 3);
  const total = top3.reduce((s, d) => s + d.cost, 0);
  const segments = top3.map((d, i) => ({
    count: d.cost,
    color: COST_SHADES[i] ?? COST_SHADES[COST_SHADES.length - 1],
    label: d.name,
  }));
  return (
    <CardShell
      icon={DollarSign}
      label="Cost This Month"
      numericValue={cost}
      formatter={fmtUsd}
      accent="green"
      loading={loading}
      delay={delay}
      visual={
        top3.length === 0 ? (
          <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>No spend yet</div>
        ) : (
          <>
            <div className="flex items-center justify-between text-xs">
              <span
                className="truncate pr-2"
                style={{ color: "var(--color-text-primary)" }}
                title={top3[0].name}
              >
                {top3[0].name}
              </span>
              <span className="font-semibold" style={{ color: COST_SHADES[0] }}>
                {Math.round(top3[0].share_pct)}%
              </span>
            </div>
            <div className="mt-2">
              <StackedBar segments={segments} total={total || 1} />
            </div>
          </>
        )
      }
      footer={
        <DeltaText
          delta={delta}
          invert={false}
          formatFallback={(n) => `${fmtUsd(n)} this period`}
        />
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Card 4 — Open Flags: stacked bar by severity + legend
// ---------------------------------------------------------------------------

function OpenFlagsCard({
  delay,
  loading,
  openCount,
  delta,
  breakdown,
}: {
  delay: number;
  loading: boolean;
  openCount: number;
  delta?: MetricDelta;
  breakdown?: SeverityBreakdown;
}) {
  const b = breakdown ?? { red: 0, yellow: 0, green: 0 };
  const total = b.red + b.yellow + b.green;
  const segments = [
    { count: b.red,    color: SEVERITY.RED,    label: "red" },
    { count: b.yellow, color: SEVERITY.YELLOW, label: "yellow" },
    { count: b.green,  color: SEVERITY.GREEN,  label: "green" },
  ];
  return (
    <CardShell
      icon={AlertTriangle}
      label="Open Flags"
      numericValue={openCount}
      accent="red"
      loading={loading}
      delay={delay}
      visual={
        total === 0 ? (
          <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>No open flags</div>
        ) : (
          <>
            <StackedBar segments={segments} total={total} />
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
              {segments
                .filter((s) => s.count > 0)
                .map((s, i, arr) => (
                  <span key={s.label} className="inline-flex items-center gap-1">
                    <Dot color={s.color} />
                    <span style={{ color: "var(--color-text-primary)" }}>{s.count}</span>
                    <span>{s.label}</span>
                    {i < arr.length - 1 && <span style={{ color: "var(--color-text-muted)" }}>·</span>}
                  </span>
                ))}
            </div>
          </>
        )
      }
      footer={
        delta && delta.pct_change !== null ? (
          <DeltaText delta={delta} invert formatFallback={() => ""} />
        ) : (
          // No prior-period comparison → describe the current state directly.
          // delta.current would be "flags raised last 30d", not what the user
          // sees as the headline number; use openCount instead.
          <span>
            {openCount.toLocaleString()} open flag{openCount === 1 ? "" : "s"}
          </span>
        )
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Small shared primitives for the cards
// ---------------------------------------------------------------------------

function StackedBar({
  segments,
  total,
}: {
  segments: { count: number; color: string }[];
  total: number;
}) {
  return (
    <div
      className="flex h-2 w-full overflow-hidden rounded-full"
      style={{ background: "var(--color-pill-bg)" }}
    >
      {segments.map((s, i) =>
        s.count > 0 ? (
          <div
            key={i}
            style={{
              width: `${(s.count / total) * 100}%`,
              background: s.color,
              transition: "width 0.4s ease",
            }}
          />
        ) : null
      )}
    </div>
  );
}

function Dot({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 rounded-full"
      style={{ background: color }}
      aria-hidden
    />
  );
}

function DeltaText({
  delta,
  invert,
  formatFallback,
}: {
  delta?: MetricDelta;
  invert: boolean;
  formatFallback: (current: number) => string;
}) {
  if (!delta || delta.pct_change === null) {
    if (delta && delta.current > 0) {
      return <span>{formatFallback(delta.current)}</span>;
    }
    return <span>vs prev. 30 days</span>;
  }
  const pct = delta.pct_change;
  const up = pct >= 0;
  // "up is good" by default; flip for metrics where up = bad (open flags).
  const positive = invert ? !up : up;
  const color = positive ? "var(--accent-green)" : "var(--accent-red)";
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon className="h-3.5 w-3.5" style={{ color }} />
      <span className="font-semibold" style={{ color }}>
        {up ? "↑" : "↓"} {Math.abs(pct).toFixed(0)}%
      </span>
      <span style={{ color: "var(--color-text-muted)" }}>vs prev. 30 days</span>
    </span>
  );
}

function Card({
  title,
  children,
  rightSlot,
}: {
  title: string;
  children: React.ReactNode;
  rightSlot?: React.ReactNode;
}) {
  return (
    <div
      className="rounded-xl p-5 shadow-sm"
      style={{
        background: "var(--color-card-bg)",
        border: "1px solid var(--color-card-border)",
      }}
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold" style={{ color: "var(--color-text-primary)" }}>
          {title}
        </h2>
        {rightSlot}
      </div>
      {children}
    </div>
  );
}

function ChartSkeleton() {
  return <div className="vigil-shimmer h-[260px] w-full rounded" />;
}

function TableSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="vigil-shimmer h-8 w-full rounded" />
      ))}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div
      className="flex h-[200px] items-center justify-center text-sm"
      style={{ color: "var(--color-text-muted)" }}
    >
      {text}
    </div>
  );
}

function SeverityPill({ severity }: { severity: FlagSeverity | null }) {
  const styles: Record<FlagSeverity, { bg: string; color: string }> = {
    RED:    { bg: "var(--accent-red-tint)",    color: "var(--accent-red)" },
    YELLOW: { bg: "var(--accent-amber-tint)",  color: "var(--accent-amber)" },
    GREEN:  { bg: "var(--accent-green-tint)",  color: "var(--accent-green)" },
  };
  const s = severity ? styles[severity] : { bg: "var(--color-pill-bg)", color: "var(--color-text-muted)" };
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide"
      style={{ background: s.bg, color: s.color }}
    >
      {severity ?? "—"}
    </span>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    success: { bg: "var(--accent-green-tint)", color: "var(--accent-green)", label: "Success" },
    error:   { bg: "var(--accent-red-tint)",   color: "var(--accent-red)",   label: "Error" },
    timeout: { bg: "var(--accent-amber-tint)", color: "var(--accent-amber)", label: "Timeout" },
  };
  const s = map[status] ?? { bg: "var(--color-pill-bg)", color: "var(--color-text-secondary)", label: status };
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={{ background: s.bg, color: s.color }}
    >
      {s.label}
    </span>
  );
}

