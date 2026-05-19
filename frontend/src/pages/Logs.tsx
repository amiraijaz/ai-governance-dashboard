import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Download,
  Loader2,
} from "lucide-react";

import { exportCsv, getLogs, LogFilters } from "../api/logs";
import { getModels } from "../api/models";
import type { AuditLog, Model } from "../types";

type StatusFilter = "all" | "success" | "error" | "flagged";

interface DraftFilters {
  model_id: string;
  status: StatusFilter;
  flagged_only: boolean;
  date_from: string;
  date_to: string;
}

const EMPTY_DRAFT: DraftFilters = {
  model_id: "all",
  status: "all",
  flagged_only: false,
  date_from: "",
  date_to: "",
};

function draftToFilters(d: DraftFilters, page: number, limit: number): LogFilters {
  const f: LogFilters = { page, limit };
  if (d.model_id !== "all") f.model_id = d.model_id;
  if (d.status === "success" || d.status === "error") f.status = d.status;
  if (d.status === "flagged" || d.flagged_only) f.flagged = true;
  if (d.date_from) f.date_from = `${d.date_from}T00:00:00`;
  if (d.date_to) f.date_to = `${d.date_to}T23:59:59`;
  return f;
}

function fmtTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fmtCost(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(6)}`;
  return `$${n.toFixed(4)}`;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function Logs() {
  const [models, setModels] = useState<Model[]>([]);
  const [logs, setLogs] = useState<AuditLog[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const [draft, setDraft] = useState<DraftFilters>(EMPTY_DRAFT);
  const [applied, setApplied] = useState<DraftFilters>(EMPTY_DRAFT);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(25);

  const [expanded, setExpanded] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    getModels().then(setModels).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLogs(null);
    setError(null);
    getLogs(draftToFilters(applied, page, limit))
      .then((res) => {
        if (cancelled) return;
        setLogs(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [applied, page, limit]);

  const modelById = useMemo(() => {
    const m = new Map<string, Model>();
    for (const x of models) m.set(x.id, x);
    return m;
  }, [models]);

  function onApply() {
    setApplied(draft);
    setPage(1);
    setExpanded(null);
  }

  function onReset() {
    setDraft(EMPTY_DRAFT);
    setApplied(EMPTY_DRAFT);
    setPage(1);
    setExpanded(null);
  }

  async function onExport() {
    setExporting(true);
    try {
      const filters = draftToFilters(applied, 1, 25);
      delete (filters as Partial<LogFilters>).page;
      delete (filters as Partial<LogFilters>).limit;
      const blob = await exportCsv(filters);
      const stamp = new Date().toISOString().slice(0, 10);
      downloadBlob(blob, `aigov-logs-${stamp}.csv`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  const start = total === 0 ? 0 : (page - 1) * limit + 1;
  const end = Math.min(page * limit, total);
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Audit Logs</h1>
          <p className="text-sm text-slate-500">Every LLM call, logged and searchable</p>
        </div>
        <button
          onClick={onExport}
          disabled={exporting}
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {exporting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          Export CSV
        </button>
      </header>

      <section className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <FieldSelect
          label="Model"
          value={draft.model_id}
          onChange={(v) => setDraft({ ...draft, model_id: v })}
          options={[
            ["all", "All models"],
            ...models.map((m) => [m.id, m.name] as [string, string]),
          ]}
        />
        <FieldSelect
          label="Status"
          value={draft.status}
          onChange={(v) => setDraft({ ...draft, status: v as StatusFilter })}
          options={[
            ["all", "All"],
            ["success", "Success"],
            ["error", "Error"],
            ["flagged", "Flagged"],
          ]}
        />
        <FieldDate
          label="From"
          value={draft.date_from}
          onChange={(v) => setDraft({ ...draft, date_from: v })}
        />
        <FieldDate
          label="To"
          value={draft.date_to}
          onChange={(v) => setDraft({ ...draft, date_to: v })}
        />
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={draft.flagged_only}
            onChange={(e) => setDraft({ ...draft, flagged_only: e.target.checked })}
            className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900"
          />
          Flagged only
        </label>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={onReset}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Reset
          </button>
          <button
            onClick={onApply}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          >
            Apply
          </button>
        </div>
      </section>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="w-6 px-2 py-2"></th>
              <th className="px-3 py-2 font-medium">Timestamp</th>
              <th className="px-3 py-2 font-medium">Model</th>
              <th className="px-3 py-2 font-medium">Prompt Hash</th>
              <th className="px-3 py-2 font-medium">Tokens</th>
              <th className="px-3 py-2 font-medium">Cost</th>
              <th className="px-3 py-2 font-medium">Latency</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Flagged</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {logs === null ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  <td colSpan={9} className="px-3 py-3">
                    <div className="h-5 w-full animate-pulse rounded bg-slate-100" />
                  </td>
                </tr>
              ))
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-12">
                  <EmptyState />
                </td>
              </tr>
            ) : (
              logs.map((log) => {
                const isOpen = expanded === log.id;
                const modelName = modelById.get(log.model_id)?.name ?? "—";
                return (
                  <Row
                    key={log.id}
                    log={log}
                    modelName={modelName}
                    isOpen={isOpen}
                    onToggle={() => setExpanded(isOpen ? null : log.id)}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <section className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
        <div>
          {total === 0
            ? "No results"
            : `Showing ${start.toLocaleString()}–${end.toLocaleString()} of ${total.toLocaleString()}`}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2">
            <span>Per page</span>
            <select
              value={limit}
              onChange={(e) => {
                setLimit(Number(e.target.value));
                setPage(1);
              }}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-md border border-slate-300 bg-white px-3 py-1 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Prev
            </button>
            <span className="px-2 text-slate-500">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="rounded-md border border-slate-300 bg-white px-3 py-1 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function Row({
  log,
  modelName,
  isOpen,
  onToggle,
}: {
  log: AuditLog;
  modelName: string;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const tokens = log.prompt_tokens + log.completion_tokens;
  return (
    <>
      <tr
        className="cursor-pointer hover:bg-slate-50"
        onClick={onToggle}
      >
        <td className="px-2 py-2 text-slate-400">
          {isOpen ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-slate-700">
          {fmtTimestamp(log.timestamp)}
        </td>
        <td className="px-3 py-2 text-slate-900">{modelName}</td>
        <td className="px-3 py-2">
          <code className="font-mono text-xs text-slate-600">
            {log.prompt_hash ? log.prompt_hash.slice(0, 16) : "—"}
          </code>
        </td>
        <td className="px-3 py-2 text-slate-700">
          {log.prompt_tokens.toLocaleString()} + {log.completion_tokens.toLocaleString()} ={" "}
          <span className="font-medium">{tokens.toLocaleString()}</span>
        </td>
        <td className="px-3 py-2 text-slate-700">{fmtCost(log.total_cost_usd)}</td>
        <td className="px-3 py-2 text-slate-700">
          {log.latency_ms.toLocaleString()} ms
        </td>
        <td className="px-3 py-2">
          <StatusBadge status={log.status} />
        </td>
        <td className="px-3 py-2">
          {log.flagged ? (
            <AlertTriangle
              className="h-4 w-4 text-red-600"
              aria-label={log.flag_severity ?? "flagged"}
            />
          ) : (
            <span className="text-slate-400">—</span>
          )}
        </td>
      </tr>
      {isOpen && (
        <tr className="bg-slate-50/60">
          <td></td>
          <td colSpan={8} className="px-3 py-3">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Detail label="Full prompt hash">
                <code className="break-all font-mono text-xs text-slate-700">
                  {log.prompt_hash ?? "—"}
                </code>
              </Detail>
              <Detail label="Session ID">
                <code className="font-mono text-xs text-slate-700">
                  {log.session_id ?? "—"}
                </code>
              </Detail>
              <Detail label="User ID">
                <code className="font-mono text-xs text-slate-700">
                  {log.user_id ?? "—"}
                </code>
              </Detail>
              <div className="md:col-span-3">
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Metadata
                </div>
                <pre className="mt-1 max-h-48 overflow-auto rounded-md border border-slate-200 bg-white p-2 text-xs text-slate-700">
                  {log.metadata ? JSON.stringify(log.metadata, null, 2) : "null"}
                </pre>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
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

function Detail({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function FieldSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium uppercase tracking-wide text-slate-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-700 focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
      >
        {options.map(([v, lbl]) => (
          <option key={v} value={v}>
            {lbl}
          </option>
        ))}
      </select>
    </label>
  );
}

function FieldDate({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium uppercase tracking-wide text-slate-500">
      {label}
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-700 focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
      />
    </label>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <Clipboard className="h-12 w-12 text-slate-300" />
      <p className="mt-4 text-sm font-medium text-slate-700">No logs yet</p>
      <p className="text-xs text-slate-500">
        Make your first SDK call to see data here.
      </p>
    </div>
  );
}
