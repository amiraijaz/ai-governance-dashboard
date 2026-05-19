import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
} from "lucide-react";

import {
  ReportSummary,
  downloadReport,
  generateReport,
  getReport,
  getReports,
} from "../api/reports";
import { getModels } from "../api/models";
import { useToast } from "../components/Toast";
import type { Model } from "../types";

const POLL_INTERVAL_MS = 2000;

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function fmtBytes(n: number | null): string {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fmtRange(from: string, to: string): string {
  const fmt = (s: string) =>
    new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${fmt(from)} – ${fmt(to)}`;
}

function fmtGenerated(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Reports() {
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [allModelsSelected, setAllModelsSelected] = useState(true);

  const [dateFrom, setDateFrom] = useState(isoDaysAgo(30));
  const [dateTo, setDateTo] = useState(todayIso());

  const [generating, setGenerating] = useState(false);
  const { showToast } = useToast();

  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const pollersRef = useRef<Map<string, ReturnType<typeof setInterval>>>(
    new Map()
  );

  useEffect(() => {
    getModels()
      .then((ms) => {
        setModels(ms);
        setSelectedModels(new Set(ms.map((m) => m.id)));
      })
      .catch(() => {});
    refresh();

    const pollers = pollersRef.current;
    return () => {
      for (const id of pollers.values()) clearInterval(id);
      pollers.clear();
    };
  }, []);

  // Whenever the list changes, ensure every pending report has a poller.
  useEffect(() => {
    if (!reports) return;
    const pollers = pollersRef.current;

    for (const r of reports) {
      if (r.status === "pending" && !pollers.has(r.id)) {
        const handle = setInterval(() => pollOnce(r.id), POLL_INTERVAL_MS);
        pollers.set(r.id, handle);
      }
    }
    // Drop pollers for reports that are no longer pending or no longer present.
    const presentPending = new Set(
      reports.filter((r) => r.status === "pending").map((r) => r.id)
    );
    for (const [id, handle] of pollers.entries()) {
      if (!presentPending.has(id)) {
        clearInterval(handle);
        pollers.delete(id);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reports]);

  async function pollOnce(id: string) {
    try {
      const updated = await getReport(id);
      setReports((prev) =>
        prev ? prev.map((r) => (r.id === id ? updated : r)) : prev
      );
      if (updated.status === "complete") {
        showToast("Report ready", "success");
      } else if (updated.status === "failed") {
        showToast(
          updated.error_message ?? "Report generation failed",
          "error"
        );
      }
    } catch {
      // Transient errors are fine — keep polling.
    }
  }

  async function refresh() {
    try {
      const data = await getReports();
      setReports(data);
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to load reports",
        "error"
      );
    }
  }

  function toggleModel(id: string) {
    setAllModelsSelected(false);
    setSelectedModels((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (allModelsSelected) {
      setAllModelsSelected(false);
      setSelectedModels(new Set());
    } else {
      setAllModelsSelected(true);
      setSelectedModels(new Set(models.map((m) => m.id)));
    }
  }

  const noneSelected = !allModelsSelected && selectedModels.size === 0;
  const invalidDates = dateFrom && dateTo && dateTo < dateFrom;

  const formError = useMemo(() => {
    if (invalidDates) return "To date must be on or after From date.";
    if (noneSelected) return "Select at least one model (or use 'All models').";
    return null;
  }, [invalidDates, noneSelected]);

  async function onGenerate(e: FormEvent) {
    e.preventDefault();
    if (formError) return;
    setGenerating(true);
    try {
      const created = await generateReport({
        date_from: dateFrom,
        date_to: dateTo,
        model_ids: allModelsSelected ? null : Array.from(selectedModels),
        format: "pdf",
      });
      showToast("Report queued — generating in background", "info");
      // Optimistically add a pending row; the polling effect picks it up.
      const optimistic: ReportSummary = {
        id: created.id,
        generated_at: new Date().toISOString(),
        date_from: dateFrom,
        date_to: dateTo,
        file_size_bytes: null,
        status: "pending",
        error_message: null,
      };
      setReports((prev) => [optimistic, ...(prev ?? [])]);
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Generation failed",
        "error"
      );
    } finally {
      setGenerating(false);
    }
  }

  async function onDownload(id: string) {
    setDownloadingId(id);
    try {
      await downloadReport(id);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Download failed", "error");
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Reports</h1>
        <p className="text-sm text-slate-500">
          Generate compliance reports mapped to NIST AI RMF
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: Generate form */}
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">Generate Report</h2>
          <form onSubmit={onGenerate} className="mt-4 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="From"
                type="date"
                value={dateFrom}
                onChange={setDateFrom}
              />
              <Field
                label="To"
                type="date"
                value={dateTo}
                onChange={setDateTo}
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Models
                </span>
                <button
                  type="button"
                  onClick={toggleAll}
                  className="text-xs font-medium text-slate-600 hover:text-slate-900"
                >
                  {allModelsSelected ? "Clear all" : "Select all"}
                </button>
              </div>
              <div className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded-md border border-slate-200 p-2">
                {models.length === 0 ? (
                  <p className="px-2 py-1 text-xs text-slate-500">
                    No models registered yet
                  </p>
                ) : (
                  models.map((m) => {
                    const checked =
                      allModelsSelected || selectedModels.has(m.id);
                    return (
                      <label
                        key={m.id}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm text-slate-700 hover:bg-slate-50"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleModel(m.id)}
                          className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900"
                        />
                        <span className="font-medium">{m.name}</span>
                        <span className="text-xs text-slate-400">
                          {m.provider}
                        </span>
                      </label>
                    );
                  })
                )}
              </div>
            </div>

            <div>
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Framework
              </span>
              <div className="mt-2">
                <span className="inline-flex cursor-default items-center gap-1.5 rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold text-white">
                  <CheckCircle2 className="h-3 w-3" />
                  NIST AI RMF
                </span>
              </div>
            </div>

            {formError && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {formError}
              </div>
            )}

            <button
              type="submit"
              disabled={generating || !!formError}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {generating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <FileText className="h-4 w-4" />
                  Generate PDF Report
                </>
              )}
            </button>
          </form>
        </section>

        {/* Right: Past reports */}
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">Past Reports</h2>

          {reports === null ? (
            <div className="mt-4 space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-16 w-full animate-pulse rounded-md bg-slate-100"
                />
              ))}
            </div>
          ) : reports.length === 0 ? (
            <div className="mt-6 flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 py-10 text-center">
              <FileText className="h-10 w-10 text-slate-300" />
              <p className="mt-3 text-sm text-slate-500">
                No reports generated yet.
              </p>
            </div>
          ) : (
            <ul className="mt-4 space-y-2">
              {reports.map((r) => (
                <li
                  key={r.id}
                  className="flex items-center justify-between gap-3 rounded-md border border-slate-200 p-3 hover:bg-slate-50"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="text-sm font-medium text-slate-900">
                        {fmtRange(r.date_from, r.date_to)}
                      </div>
                      {r.status === "pending" && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          Generating…
                        </span>
                      )}
                      {r.status === "failed" && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-medium text-red-700">
                          <AlertTriangle className="h-3 w-3" />
                          Failed
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      {fmtGenerated(r.generated_at)}
                      {r.status === "complete" && (
                        <> · {fmtBytes(r.file_size_bytes)}</>
                      )}
                    </div>
                    {r.status === "failed" && r.error_message && (
                      <div className="mt-1 text-xs text-red-600">
                        {r.error_message}
                      </div>
                    )}
                  </div>
                  {r.status === "complete" ? (
                    <button
                      onClick={() => onDownload(r.id)}
                      disabled={downloadingId === r.id}
                      className="inline-flex shrink-0 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {downloadingId === r.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Download className="h-4 w-4" />
                      )}
                      Download PDF
                    </button>
                  ) : r.status === "pending" ? (
                    <span className="inline-flex shrink-0 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm font-medium text-slate-400">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Pending
                    </span>
                  ) : (
                    <span className="inline-flex shrink-0 items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-sm font-medium text-red-600">
                      Unavailable
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function Field({
  label,
  type,
  value,
  onChange,
}: {
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
      />
    </label>
  );
}
