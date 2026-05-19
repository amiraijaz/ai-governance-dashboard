import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Database,
  DollarSign,
  LucideIcon,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getDashboardSummary, getModelAnalytics } from "../api/analytics";
import { getLogs } from "../api/logs";
import { getModels } from "../api/models";
import ApiKeysSection from "../components/ApiKeysSection";
import ChartTooltip from "../components/ChartTooltip";
import { useToast } from "../components/Toast";
import { useCountUp, useFadeIn } from "../hooks/animation";
import type {
  AnalyticsModel,
  AuditLog,
  DashboardSummary,
  FlagSeverity,
  Model,
} from "../types";

const PROVIDER_COLORS: Record<string, string> = {
  openai: "#10a37f",
  OpenAI: "#10a37f",
  anthropic: "#d97757",
  Anthropic: "#d97757",
  google: "#4285f4",
  Google: "#4285f4",
};

const FALLBACK_COLOR = "#6366f1";

function providerColor(provider: string): string {
  return PROVIDER_COLORS[provider] ?? FALLBACK_COLOR;
}

function fmtUsd(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(6)}`;
  return `$${n.toFixed(2)}`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [modelAnalytics, setModelAnalytics] = useState<AnalyticsModel[]>([]);
  const [recentLogs, setRecentLogs] = useState<AuditLog[]>([]);
  const [recentFlagged, setRecentFlagged] = useState<AuditLog[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const { showToast } = useToast();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, ma, rl, rf, ms] = await Promise.all([
          getDashboardSummary(),
          getModelAnalytics(),
          getLogs({ limit: 5 }),
          getLogs({ flagged: true, limit: 5 }),
          getModels(),
        ]);
        if (cancelled) return;
        setSummary(s);
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
  }, [showToast]);

  const modelById = useMemo(() => {
    const map = new Map<string, Model>();
    for (const m of models) map.set(m.id, m);
    return map;
  }, [models]);

  const topModels = useMemo(
    () => [...modelAnalytics].sort((a, b) => b.total_calls - a.total_calls).slice(0, 5),
    [modelAnalytics]
  );

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">AI governance overview</p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          delay={0}
          loading={loading}
          icon={Database}
          label="Models Registered"
          numericValue={summary?.models_registered ?? 0}
          accent="blue"
        />
        <MetricCard
          delay={100}
          loading={loading}
          icon={Activity}
          label="Calls This Month"
          numericValue={summary?.calls_this_month ?? 0}
          accent="purple"
        />
        <MetricCard
          delay={200}
          loading={loading}
          icon={DollarSign}
          label="Cost This Month"
          numericValue={summary?.cost_this_month ?? 0}
          formatter={(n) => fmtUsd(n)}
          accent="green"
        />
        <MetricCard
          delay={300}
          loading={loading}
          icon={AlertTriangle}
          label="Open Flags"
          numericValue={summary?.open_flags ?? 0}
          accent={(summary?.open_flags ?? 0) > 0 ? "red" : "gray"}
        />
      </section>

      <section className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2" style={useFadeIn(400)}>
        <Card title="Daily Cost (last 30 days)">
          {loading ? (
            <ChartSkeleton />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart
                data={(summary?.cost_last_30_days ?? []).map((p) => ({
                  date: fmtDate(p.date),
                  cost: p.cost,
                }))}
                margin={{ top: 10, right: 16, bottom: 0, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <YAxis
                  tick={{ fontSize: 12 }}
                  stroke="#94a3b8"
                  tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
                />
                <Tooltip
                  content={<ChartTooltip />}
                  formatter={(v) => [fmtUsd(Number(v)), "Cost"]}
                />
                <Line
                  type="monotone"
                  dataKey="cost"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Requests by Model (top 5)">
          {loading ? (
            <ChartSkeleton />
          ) : topModels.length === 0 ? (
            <EmptyState text="No model usage yet" />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart
                layout="vertical"
                data={topModels}
                margin={{ top: 10, right: 16, bottom: 0, left: 16 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <YAxis
                  type="category"
                  dataKey="model_name"
                  tick={{ fontSize: 12 }}
                  stroke="#94a3b8"
                  width={120}
                />
                <Tooltip
                  content={<ChartTooltip />}
                  formatter={(v) => [Number(v).toLocaleString(), "Requests"]}
                />
                <Bar dataKey="total_calls" radius={[0, 4, 4, 0]}>
                  {topModels.map((m) => (
                    <Cell key={m.model_name} fill={providerColor(m.provider)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </section>

      <section className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2" style={useFadeIn(500)}>
        <Card title="Recent Flags">
          {loading ? (
            <TableSkeleton rows={5} />
          ) : recentFlagged.length === 0 ? (
            <EmptyState text="No flagged calls" />
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="pb-2 font-medium">Severity</th>
                  <th className="pb-2 font-medium">Model</th>
                  <th className="pb-2 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recentFlagged.map((log) => (
                  <tr key={log.id}>
                    <td className="py-2">
                      <SeverityBadge severity={log.flag_severity} />
                    </td>
                    <td className="py-2 text-slate-700">
                      {modelById.get(log.model_id)?.name ?? "—"}
                    </td>
                    <td className="py-2 text-slate-500">{fmtTime(log.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Recent Logs">
          {loading ? (
            <TableSkeleton rows={5} />
          ) : recentLogs.length === 0 ? (
            <EmptyState text="No audit logs yet" />
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="pb-2 font-medium">Time</th>
                  <th className="pb-2 font-medium">Model</th>
                  <th className="pb-2 font-medium">Cost</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recentLogs.map((log) => (
                  <tr key={log.id}>
                    <td className="py-2 text-slate-500">{fmtTime(log.timestamp)}</td>
                    <td className="py-2 text-slate-700">
                      {modelById.get(log.model_id)?.name ?? "—"}
                    </td>
                    <td className="py-2 text-slate-700">{fmtUsd(log.total_cost_usd)}</td>
                    <td className="py-2">
                      <StatusBadge status={log.status} />
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

const ACCENT: Record<
  string,
  { text: string; iconBg: string; border: string; tint: string }
> = {
  blue:   { text: "text-blue-600",   iconBg: "bg-blue-50",   border: "#3b82f6", tint: "rgba(59,130,246,0.04)" },
  purple: { text: "text-purple-600", iconBg: "bg-purple-50", border: "#a855f7", tint: "rgba(168,85,247,0.04)" },
  green:  { text: "text-green-700",  iconBg: "bg-green-50",  border: "var(--vigil-green)", tint: "var(--vigil-green-light)" },
  red:    { text: "text-red-600",    iconBg: "bg-red-50",    border: "#dc2626", tint: "rgba(220,38,38,0.04)" },
  gray:   { text: "text-slate-500",  iconBg: "bg-slate-100", border: "#cbd5e1", tint: "transparent" },
};

function MetricCard({
  icon: Icon,
  label,
  numericValue,
  accent,
  loading,
  delay,
  formatter,
}: {
  icon: LucideIcon;
  label: string;
  numericValue: number;
  accent: keyof typeof ACCENT;
  loading: boolean;
  delay: number;
  formatter?: (n: number) => string;
}) {
  const a = ACCENT[accent];
  const animated = useCountUp(loading ? 0 : numericValue, 800);
  const fadeStyle = useFadeIn(delay);
  const display = formatter
    ? formatter(animated)
    : Math.round(animated).toLocaleString();
  return (
    <div
      className="vigil-card vigil-card-interactive bg-white p-4"
      style={{
        ...fadeStyle,
        borderLeft: `4px solid ${a.border}`,
        background: `linear-gradient(180deg, ${a.tint} 0%, #ffffff 70%)`,
      }}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {label}
        </span>
        <span className={`rounded-md p-2 ${a.iconBg}`}>
          <Icon className={`h-4 w-4 ${a.text}`} />
        </span>
      </div>
      <div className="mt-3">
        {loading ? (
          <div className="vigil-shimmer h-7 w-20 rounded" />
        ) : (
          <div className={`text-2xl font-semibold ${a.text}`}>{display}</div>
        )}
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">{title}</h2>
      {children}
    </div>
  );
}

function ChartSkeleton() {
  return <div className="h-[260px] w-full animate-pulse rounded bg-slate-100" />;
}

function TableSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 w-full animate-pulse rounded bg-slate-100" />
      ))}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-[200px] items-center justify-center text-sm text-slate-400">
      {text}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: FlagSeverity | null }) {
  const map: Record<FlagSeverity, string> = {
    RED: "bg-red-100 text-red-700",
    YELLOW: "bg-yellow-100 text-yellow-800",
    GREEN: "bg-green-100 text-green-700",
  };
  const cls = severity ? map[severity] : "bg-slate-100 text-slate-600";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {severity ?? "—"}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "success"
      ? "bg-green-100 text-green-700"
      : status === "error"
      ? "bg-red-100 text-red-700"
      : "bg-slate-100 text-slate-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}
