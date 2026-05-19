import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getCostAnalytics,
  getLatencyAnalytics,
  getModelAnalytics,
  getRequestAnalytics,
} from "../api/analytics";
import { useToast } from "../components/Toast";
import type {
  AnalyticsCost,
  AnalyticsLatency,
  AnalyticsModel,
  AnalyticsRequests,
  Period,
} from "../types";

const PERIODS: Period[] = ["7d", "30d", "90d"];
const PERIOD_LABEL: Record<Period, string> = {
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
};

const BAR_PALETTE = [
  "#6366f1",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#0ea5e9",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
];

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

type SortKey =
  | "model_name"
  | "provider"
  | "total_calls"
  | "total_cost_usd"
  | "avg_latency_ms"
  | "total_tokens";
type SortDir = "asc" | "desc";

export default function Analytics() {
  const [period, setPeriod] = useState<Period>("30d");
  const [cost, setCost] = useState<AnalyticsCost[] | null>(null);
  const [requests, setRequests] = useState<AnalyticsRequests[] | null>(null);
  const [latency, setLatency] = useState<AnalyticsLatency[] | null>(null);
  const [modelStats, setModelStats] = useState<AnalyticsModel[] | null>(null);
  const { showToast } = useToast();

  const [sortKey, setSortKey] = useState<SortKey>("total_cost_usd");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    let cancelled = false;
    setCost(null);
    setRequests(null);
    setLatency(null);
    setModelStats(null);

    Promise.all([
      getCostAnalytics(period, "day"),
      getRequestAnalytics(period),
      getLatencyAnalytics(period),
      getModelAnalytics(),
    ])
      .then(([c, r, l, m]) => {
        if (cancelled) return;
        setCost(c);
        setRequests(r);
        setLatency(l);
        setModelStats(m);
      })
      .catch((err) => {
        if (!cancelled)
          showToast(err instanceof Error ? err.message : "Failed to load", "error");
      });

    return () => {
      cancelled = true;
    };
  }, [period, showToast]);

  const costByModel = useMemo(() => {
    if (!modelStats) return [];
    return [...modelStats]
      .sort((a, b) => b.total_cost_usd - a.total_cost_usd)
      .slice(0, 10);
  }, [modelStats]);

  const sortedModels = useMemo(() => {
    if (!modelStats) return [];
    const copy = [...modelStats];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return copy;
  }, [modelStats, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "model_name" || key === "provider" ? "asc" : "desc");
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Analytics</h1>
          <p className="text-sm text-slate-500">Cost, requests, and latency</p>
        </div>
        <PeriodTabs value={period} onChange={setPeriod} />
      </header>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Cost Over Time">
          <ChartSlot loading={cost === null} empty={cost?.length === 0}>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart
                data={(cost ?? []).map((p) => ({
                  date: fmtDate(p.label),
                  cost: p.total_cost_usd,
                }))}
                margin={{ top: 10, right: 16, bottom: 0, left: 0 }}
              >
                <defs>
                  <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <YAxis
                  tick={{ fontSize: 12 }}
                  stroke="#94a3b8"
                  tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
                />
                <Tooltip
                  formatter={(v) => [fmtUsd(Number(v)), "Cost"]}
                  contentStyle={{ borderRadius: 6, fontSize: 12 }}
                />
                <Area
                  type="monotone"
                  dataKey="cost"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="url(#costFill)"
                  activeDot={{ r: 5 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </ChartSlot>
        </Card>

        <Card title="Requests Per Day">
          <ChartSlot loading={requests === null} empty={requests?.length === 0}>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={(requests ?? []).map((r) => ({
                  date: fmtDate(r.date),
                  success: r.success_count,
                  error: r.error_count,
                  flagged: r.flagged_count,
                }))}
                margin={{ top: 10, right: 16, bottom: 0, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <YAxis tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <Tooltip contentStyle={{ borderRadius: 6, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="success" stackId="r" fill="#10b981" />
                <Bar dataKey="error" stackId="r" fill="#ef4444" />
                <Bar dataKey="flagged" stackId="r" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>
          </ChartSlot>
        </Card>

        <Card title="Latency Trends (ms)">
          <ChartSlot loading={latency === null} empty={latency?.length === 0}>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart
                data={(latency ?? []).map((p) => ({
                  date: fmtDate(p.date),
                  avg: Math.round(p.avg_latency_ms),
                  p95: Math.round(p.p95_latency_ms),
                  p99: Math.round(p.p99_latency_ms),
                }))}
                margin={{ top: 10, right: 16, bottom: 0, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <YAxis tick={{ fontSize: 12 }} stroke="#94a3b8" />
                <Tooltip
                  formatter={(v, name) => [`${Number(v).toLocaleString()} ms`, name]}
                  contentStyle={{ borderRadius: 6, fontSize: 12 }}
                />
                <Legend
                  verticalAlign="bottom"
                  height={28}
                  wrapperStyle={{ fontSize: 12 }}
                />
                <Line type="monotone" dataKey="avg" stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="p95" stroke="#f59e0b" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="p99" stroke="#ef4444" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartSlot>
        </Card>

        <Card title="Cost by Model">
          <ChartSlot loading={modelStats === null} empty={costByModel.length === 0}>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                layout="vertical"
                data={costByModel}
                margin={{ top: 10, right: 16, bottom: 0, left: 16 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  type="number"
                  tick={{ fontSize: 12 }}
                  stroke="#94a3b8"
                  tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
                />
                <YAxis
                  type="category"
                  dataKey="model_name"
                  tick={{ fontSize: 12 }}
                  stroke="#94a3b8"
                  width={140}
                />
                <Tooltip
                  formatter={(v) => [fmtUsd(Number(v)), "Cost"]}
                  contentStyle={{ borderRadius: 6, fontSize: 12 }}
                />
                <Bar dataKey="total_cost_usd" radius={[0, 4, 4, 0]}>
                  {costByModel.map((m, i) => (
                    <Cell key={m.model_name + i} fill={BAR_PALETTE[i % BAR_PALETTE.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartSlot>
        </Card>
      </section>

      <section className="mt-6">
        <Card title="Model Breakdown">
          {modelStats === null ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-8 w-full animate-pulse rounded bg-slate-100" />
              ))}
            </div>
          ) : sortedModels.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-400">No model usage yet</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr className="border-b border-slate-200">
                    <Th label="Model" k="model_name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    <Th label="Provider" k="provider" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    <Th label="Total Calls" k="total_calls" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} numeric />
                    <Th label="Total Cost" k="total_cost_usd" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} numeric />
                    <Th label="Avg Latency" k="avg_latency_ms" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} numeric />
                    <Th label="Total Tokens" k="total_tokens" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} numeric />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sortedModels.map((m, i) => (
                    <tr key={m.model_name + m.provider + i}>
                      <td className="py-2 text-slate-800">{m.model_name}</td>
                      <td className="py-2 text-slate-600">{m.provider}</td>
                      <td className="py-2 text-right text-slate-700">{m.total_calls.toLocaleString()}</td>
                      <td className="py-2 text-right text-slate-700">{fmtUsd(m.total_cost_usd)}</td>
                      <td className="py-2 text-right text-slate-700">{Math.round(m.avg_latency_ms).toLocaleString()} ms</td>
                      <td className="py-2 text-right text-slate-700">{m.total_tokens.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}

function PeriodTabs({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1 shadow-sm">
      {PERIODS.map((p) => {
        const active = p === value;
        return (
          <button
            key={p}
            onClick={() => onChange(p)}
            className={`rounded-md px-3 py-1 text-sm font-medium transition ${
              active
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {PERIOD_LABEL[p]}
          </button>
        );
      })}
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

function ChartSlot({
  loading,
  empty,
  children,
}: {
  loading: boolean;
  empty?: boolean;
  children: React.ReactNode;
}) {
  if (loading) {
    return (
      <div className="flex h-[280px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }
  if (empty) {
    return (
      <div className="flex h-[280px] items-center justify-center text-sm text-slate-400">
        No data for this period
      </div>
    );
  }
  return <>{children}</>;
}

function Th({
  label,
  k,
  sortKey,
  sortDir,
  onClick,
  numeric,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (k: SortKey) => void;
  numeric?: boolean;
}) {
  const active = k === sortKey;
  return (
    <th
      className={`cursor-pointer select-none pb-2 font-medium ${
        numeric ? "text-right" : "text-left"
      }`}
      onClick={() => onClick(k)}
    >
      <span
        className={`inline-flex items-center gap-1 ${
          active ? "text-slate-900" : "text-slate-500 hover:text-slate-700"
        }`}
      >
        {label}
        {active &&
          (sortDir === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          ))}
      </span>
    </th>
  );
}
