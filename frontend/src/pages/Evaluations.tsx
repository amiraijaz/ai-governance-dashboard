import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Loader2,
  Plus,
  RefreshCw,
  X,
  XCircle,
} from "lucide-react";

import {
  createSuite,
  deleteSuite,
  getRun,
  getRunResults,
  getSuites,
  runSuite,
} from "../api/evals";
import { getModels } from "../api/models";
import { useToast } from "../components/Toast";
import type {
  EvalResult,
  EvalRun,
  EvalSuite,
  EvalSuiteCreate,
  EvalType,
  Model,
  RunStatus,
} from "../types";

// ---------------------------------------------------------------------------
// Constants + helpers
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 60_000;

const TYPE_LABEL: Record<EvalType, string> = {
  rag: "RAG",
  llm_judge: "LLM Judge",
  drift: "Drift",
};

const TYPE_PILL: Record<EvalType, { bg: string; fg: string }> = {
  rag:       { bg: "var(--accent-blue-tint)",   fg: "var(--accent-blue)" },
  llm_judge: { bg: "var(--accent-purple-tint)", fg: "var(--accent-purple)" },
  drift:     { bg: "var(--accent-amber-tint)",  fg: "var(--accent-amber)" },
};

const STATUS_STYLE: Record<RunStatus, { fg: string; bg: string; label: string }> = {
  pending:  { fg: "var(--color-text-muted)",   bg: "var(--color-pill-bg)",      label: "Pending" },
  running:  { fg: "var(--accent-blue)",        bg: "var(--accent-blue-tint)",   label: "Running" },
  complete: { fg: "var(--accent-green)",       bg: "var(--accent-green-tint)",  label: "Complete" },
  failed:   { fg: "var(--accent-red)",         bg: "var(--accent-red-tint)",    label: "Failed" },
};

const EXAMPLE_RUBRIC =
  `name: "Support quality"\n` +
  `criteria:\n` +
  `  - name: tone\n` +
  `    description: "Polite and professional throughout"\n` +
  `    scale: 5\n` +
  `  - name: factual_accuracy\n` +
  `    description: "All claims are accurate and not fabricated"\n` +
  `    scale: 5\n` +
  `  - name: helpfulness\n` +
  `    description: "Response addresses the user's need"\n` +
  `    scale: 5\n` +
  `pass_threshold: 3.5\n`;

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// Suite-card headline metric — type-aware. Returns null when there's no run yet.
function headline(suite: EvalSuite, run?: EvalRun | null): { text: string; tone?: "good" | "warn" | "bad" } | null {
  if (!run || run.status !== "complete" || !run.summary) return null;
  const s = run.summary;

  if (suite.eval_type === "rag") {
    const m = s.metrics ?? {};
    const f = typeof m.faithfulness === "number" ? m.faithfulness : null;
    const r = typeof m.answer_relevancy === "number" ? m.answer_relevancy : null;
    const parts: string[] = [];
    if (f !== null) parts.push(`faithfulness ${f.toFixed(2)}`);
    if (r !== null) parts.push(`relevancy ${r.toFixed(2)}`);
    if (!parts.length && typeof s.note === "string") return { text: s.note, tone: "warn" };
    return parts.length ? { text: parts.join(" · ") } : null;
  }

  if (suite.eval_type === "llm_judge") {
    if (typeof s.note === "string" && !s.criteria_means) {
      return { text: s.note, tone: "warn" };
    }
    const means: number[] = Object.values(s.criteria_means ?? {}).filter(
      (v) => typeof v === "number",
    ) as number[];
    const mean = means.length ? means.reduce((a, b) => a + b, 0) / means.length : null;
    const passed = s.passed ?? 0;
    const total = s.total_cases ?? 0;
    if (mean === null && !total) return null;
    const meanStr = mean !== null ? `mean ${mean.toFixed(1)}` : null;
    const ratio = total ? `${passed}/${total} passed` : null;
    return { text: [meanStr, ratio].filter(Boolean).join(" · ") };
  }

  if (suite.eval_type === "drift") {
    if (s.insufficient_data) return { text: "insufficient data", tone: "warn" };
    const sig = s.signals ?? {};
    const drifted: string[] = [];
    if (sig.latency?.drifted) drifted.push("latency");
    if (sig.response_length?.drifted) drifted.push("response length");
    if (sig.error_rate?.drifted) drifted.push("error rate");
    if (drifted.length === 0) return { text: "no drift", tone: "good" };
    return { text: `${drifted.join(" + ")} drift detected`, tone: "bad" };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Evaluations() {
  const [suites, setSuites] = useState<EvalSuite[] | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  // Latest run per suite — populated after the first load and after triggers.
  const [latestRunBySuite, setLatestRunBySuite] = useState<Record<string, EvalRun | null>>({});
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { showToast } = useToast();

  const modelById = useMemo(() => {
    const m = new Map<string, Model>();
    for (const x of models) m.set(x.id, x);
    return m;
  }, [models]);

  const load = useCallback(async () => {
    try {
      const [list, modelList] = await Promise.all([getSuites(), getModels()]);
      setSuites(list);
      setModels(modelList);
      // Pull each suite's most recent run for the headline metric.
      const runs = await Promise.all(
        list.map(async (s) => {
          try {
            const detail = await import("../api/evals").then((m) => m.getSuite(s.id));
            return [s.id, detail.recent_runs[0] ?? null] as const;
          } catch {
            return [s.id, null] as const;
          }
        }),
      );
      setLatestRunBySuite(Object.fromEntries(runs));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to load", "error");
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  async function onRun(suite: EvalSuite) {
    try {
      const { run_id } = await runSuite(suite.id);
      showToast(`${TYPE_LABEL[suite.eval_type]} run queued`, "info");
      // Optimistically flip the card to running.
      setLatestRunBySuite((prev) => ({
        ...prev,
        [suite.id]: {
          id: run_id,
          suite_id: suite.id,
          status: "running",
          started_at: null,
          completed_at: null,
          summary: null,
          error_message: null,
          triggered_by: null,
          created_at: new Date().toISOString(),
        },
      }));
      // Poll until terminal.
      const final = await pollRun(run_id);
      setLatestRunBySuite((prev) => ({ ...prev, [suite.id]: final }));
      showToast(
        final.status === "complete"
          ? "Run complete"
          : `Run ${final.status}${final.error_message ? `: ${final.error_message}` : ""}`,
        final.status === "complete" ? "success" : "error",
      );
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Run failed", "error");
    }
  }

  async function onDelete(suite: EvalSuite) {
    if (!confirm(`Delete suite "${suite.name}"? Its runs and results will also be deleted.`)) return;
    try {
      await deleteSuite(suite.id);
      setSuites((prev) => prev?.filter((s) => s.id !== suite.id) ?? null);
      showToast("Suite deleted", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Delete failed", "error");
    }
  }

  async function onCreated(_created: EvalSuite) {
    setDrawerOpen(false);
    await load();
    showToast("Suite created", "success");
  }

  return (
    <div className="min-h-screen p-6 md:p-8" style={{ background: "var(--color-page-bg)" }}>
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--color-text-primary)" }}>
            Evaluations
          </h1>
          <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
            Continuous governance evals for your models
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium"
            style={{
              background: "var(--color-card-bg)",
              borderColor: "var(--color-card-border)",
              color: "var(--color-text-primary)",
            }}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            onClick={() => setDrawerOpen(true)}
            className="btn-primary"
          >
            <Plus className="h-4 w-4" />
            New Eval Suite
          </button>
        </div>
      </header>

      {suites === null ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => <div key={i} className="vigil-shimmer h-48 rounded-xl" />)}
        </div>
      ) : suites.length === 0 ? (
        <EmptyState onCreate={() => setDrawerOpen(true)} />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {suites.map((s) => (
            <SuiteCard
              key={s.id}
              suite={s}
              latestRun={latestRunBySuite[s.id] ?? null}
              modelName={s.model_id ? modelById.get(s.model_id)?.name ?? "—" : "ad-hoc"}
              onRun={() => onRun(s)}
              onOpen={() => {
                const run = latestRunBySuite[s.id];
                if (run) setActiveRunId(run.id);
              }}
              onDelete={() => onDelete(s)}
            />
          ))}
        </div>
      )}

      {drawerOpen && (
        <NewSuiteDrawer
          models={models}
          onClose={() => setDrawerOpen(false)}
          onCreated={onCreated}
        />
      )}

      {activeRunId && (
        <RunDetailModal
          runId={activeRunId}
          suites={suites ?? []}
          onClose={() => setActiveRunId(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suite card
// ---------------------------------------------------------------------------

function SuiteCard({
  suite,
  latestRun,
  modelName,
  onRun,
  onOpen,
  onDelete,
}: {
  suite: EvalSuite;
  latestRun: EvalRun | null;
  modelName: string;
  onRun: () => void;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const pill = TYPE_PILL[suite.eval_type];
  const status = latestRun?.status;
  const headlineInfo = headline(suite, latestRun);
  const headlineColor =
    headlineInfo?.tone === "good" ? "var(--accent-green)" :
    headlineInfo?.tone === "warn" ? "var(--accent-amber)" :
    headlineInfo?.tone === "bad"  ? "var(--accent-red)"   :
    "var(--color-text-primary)";

  return (
    <div
      className="vigil-card vigil-card-interactive flex flex-col p-4"
      style={{
        background: "var(--color-card-bg)",
        border: "1px solid var(--color-card-border)",
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <button
            onClick={onOpen}
            disabled={!latestRun}
            className="text-left text-base font-semibold leading-tight hover:underline disabled:cursor-default disabled:no-underline"
            style={{ color: "var(--color-text-primary)" }}
          >
            {suite.name}
          </button>
          <div className="mt-1 text-xs" style={{ color: "var(--color-text-secondary)" }}>
            {modelName}
          </div>
        </div>
        <span
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide"
          style={{ background: pill.bg, color: pill.fg }}
        >
          {TYPE_LABEL[suite.eval_type]}
        </span>
      </div>

      <div className="mt-4 min-h-[3rem]">
        {status ? (
          <div className="flex items-center gap-2 text-xs">
            <StatusBadge status={status} />
            <span style={{ color: "var(--color-text-muted)" }}>
              {relTime(latestRun?.completed_at ?? latestRun?.started_at ?? latestRun?.created_at ?? null)}
            </span>
          </div>
        ) : (
          <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            No runs yet
          </div>
        )}
        {headlineInfo && (
          <div
            className="mt-2 text-sm font-medium leading-tight"
            style={{ color: headlineColor }}
          >
            {headlineInfo.text}
          </div>
        )}
        {status === "failed" && latestRun?.error_message && (
          <div
            className="mt-2 truncate text-xs"
            style={{ color: "var(--accent-red)" }}
            title={latestRun.error_message}
          >
            {latestRun.error_message}
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between">
        <button
          onClick={onRun}
          disabled={status === "running" || status === "pending"}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            background: "var(--color-card-bg)",
            borderColor: "var(--color-card-border)",
            color: "var(--color-text-primary)",
          }}
        >
          {status === "running" || status === "pending" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <ArrowRight className="h-3.5 w-3.5" />
          )}
          Run
        </button>
        <button
          onClick={onDelete}
          className="text-xs"
          style={{ color: "var(--color-text-muted)" }}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: RunStatus }) {
  const s = STATUS_STYLE[status];
  const Icon =
    status === "complete" ? CheckCircle2 :
    status === "failed"   ? XCircle      :
    status === "running"  ? Loader2      :
    AlertCircle;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: s.bg, color: s.fg }}
    >
      <Icon className={`h-3 w-3 ${status === "running" ? "animate-spin" : ""}`} />
      {s.label}
    </span>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div
      className="rounded-xl p-10 text-center"
      style={{
        background: "var(--color-card-bg)",
        border: "1px dashed var(--color-card-border)",
      }}
    >
      <FlaskConical
        className="mx-auto h-10 w-10"
        style={{ color: "var(--color-text-muted)" }}
      />
      <h3 className="mt-3 text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
        No eval suites yet
      </h3>
      <p className="mx-auto mt-1 max-w-md text-sm" style={{ color: "var(--color-text-secondary)" }}>
        Define a rubric for an LLM-as-judge, a faithfulness check for RAG, or
        drift detection on a model's traffic patterns. Suites are reusable —
        run them on a schedule or before a release.
      </p>
      <button onClick={onCreate} className="btn-primary mx-auto mt-5">
        <Plus className="h-4 w-4" />
        New Eval Suite
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Polling helper
// ---------------------------------------------------------------------------

async function pollRun(runId: string): Promise<EvalRun> {
  const started = Date.now();
  let run = await getRun(runId);
  while (
    (run.status === "pending" || run.status === "running") &&
    Date.now() - started < POLL_TIMEOUT_MS
  ) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    run = await getRun(runId);
  }
  return run;
}

// ---------------------------------------------------------------------------
// Run detail modal
// ---------------------------------------------------------------------------

function RunDetailModal({
  runId, suites, onClose,
}: {
  runId: string;
  suites: EvalSuite[];
  onClose: () => void;
}) {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [results, setResults] = useState<EvalResult[] | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const limit = 25;
  const { showToast } = useToast();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await getRun(runId);
        if (cancelled) return;
        setRun(r);
        if (r.status === "complete" || r.status === "failed") {
          const res = await getRunResults(runId, page, limit);
          if (cancelled) return;
          setResults(res.items);
          setTotal(res.total);
        } else {
          setResults([]);
          setTotal(0);
        }
      } catch (err) {
        if (!cancelled)
          showToast(err instanceof Error ? err.message : "Failed to load run", "error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, page, showToast]);

  const suite = useMemo(
    () => suites.find((s) => s.id === run?.suite_id),
    [suites, run],
  );

  return (
    <div
      className="vigil-modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="vigil-modal-pop w-full max-w-3xl overflow-hidden rounded-xl shadow-xl"
        style={{
          background: "var(--color-card-bg)",
          border: "1px solid var(--color-card-border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-start justify-between px-5 py-4"
          style={{ borderBottom: "1px solid var(--color-divider)" }}
        >
          <div>
            <h2 className="text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
              {suite?.name ?? "Run detail"}
            </h2>
            <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
              {suite ? TYPE_LABEL[suite.eval_type] : "—"} · triggered by{" "}
              {run?.triggered_by ?? "—"} · {fmtTime(run?.started_at ?? null)}
              {run?.completed_at && ` → ${fmtTime(run.completed_at)}`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1"
            style={{ color: "var(--color-text-muted)" }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          {!run ? (
            <div className="vigil-shimmer h-32 w-full rounded" />
          ) : run.status === "failed" ? (
            <div
              className="rounded-md p-4 text-sm"
              style={{
                background: "var(--accent-red-tint)",
                color: "var(--accent-red)",
              }}
            >
              <div className="font-semibold">Run failed</div>
              <div className="mt-1 whitespace-pre-wrap break-words">
                {run.error_message ?? "no error message provided"}
              </div>
            </div>
          ) : run.status !== "complete" ? (
            <div className="flex items-center gap-2 text-sm" style={{ color: "var(--color-text-secondary)" }}>
              <Loader2 className="h-4 w-4 animate-spin" />
              Run is {run.status} — refresh to update
            </div>
          ) : suite?.eval_type === "drift" ? (
            <DriftSummary summary={run.summary} />
          ) : (
            <CaseResultsTable
              results={results}
              total={total}
              page={page}
              limit={limit}
              onPage={setPage}
              evalType={suite?.eval_type}
              summary={run.summary}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drift signals panel
// ---------------------------------------------------------------------------

function DriftSummary({ summary }: { summary: Record<string, any> | null }) {
  if (!summary) return null;
  if (summary.insufficient_data) {
    return (
      <div className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
        Not enough samples in one of the windows to compare (need {" "}
        {summary.min_samples_per_window} per window).
      </div>
    );
  }
  const sig = summary.signals ?? {};
  const rows = [
    { key: "latency", label: "Latency p95", info: sig.latency },
    { key: "response_length", label: "Response length (tokens)", info: sig.response_length },
    { key: "error_rate", label: "Error rate", info: sig.error_rate },
  ];

  const formatRow = (key: string, info: any) => {
    if (!info) return null;
    if (key === "error_rate") {
      return {
        baseline: `${(info.baseline_rate * 100).toFixed(1)}%`,
        current: `${(info.current_rate * 100).toFixed(1)}%`,
        change: `${(info.delta * 100).toFixed(1)} pp`,
        pValue: "—",
      };
    }
    const base = key === "latency" ? info.baseline_p95 : info.baseline_mean;
    const curr = key === "latency" ? info.current_p95 : info.current_mean;
    return {
      baseline: typeof base === "number" ? base.toFixed(0) : "—",
      current: typeof curr === "number" ? curr.toFixed(0) : "—",
      change: typeof info.pct_change === "number" ? `${info.pct_change.toFixed(1)}%` : "—",
      pValue: typeof info.p_value === "number" ? info.p_value.toFixed(3) : "—",
    };
  };

  return (
    <div>
      <div className="mb-4 flex items-center gap-3 text-sm">
        <span style={{ color: "var(--color-text-secondary)" }}>
          {summary.baseline_window?.n ?? 0} baseline / {summary.current_window?.n ?? 0} current samples
        </span>
        {summary.overall_drift ? (
          <span
            className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
            style={{ background: "var(--accent-amber-tint)", color: "var(--accent-amber)" }}
          >
            Drift detected
          </span>
        ) : (
          <span
            className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
            style={{ background: "var(--accent-green-tint)", color: "var(--accent-green)" }}
          >
            Stable
          </span>
        )}
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider" style={{ color: "var(--color-text-muted)" }}>
            <th className="pb-2 pr-3 font-medium">Signal</th>
            <th className="pb-2 pr-3 font-medium">Baseline</th>
            <th className="pb-2 pr-3 font-medium">Current</th>
            <th className="pb-2 pr-3 font-medium">Change</th>
            <th className="pb-2 pr-3 font-medium">p-value</th>
            <th className="pb-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y" style={{ borderColor: "var(--color-divider)" }}>
          {rows.map(({ key, label, info }) => {
            const fmt = formatRow(key, info);
            const drifted = info?.drifted;
            return (
              <tr
                key={key}
                style={drifted ? { background: "var(--accent-amber-tint)" } : undefined}
              >
                <td className="py-2.5 pr-3" style={{ color: "var(--color-text-primary)" }}>
                  {label}
                </td>
                <td className="py-2.5 pr-3" style={{ color: "var(--color-text-secondary)" }}>
                  {fmt?.baseline ?? "—"}
                </td>
                <td className="py-2.5 pr-3" style={{ color: "var(--color-text-primary)" }}>
                  {fmt?.current ?? "—"}
                </td>
                <td className="py-2.5 pr-3" style={{ color: "var(--color-text-secondary)" }}>
                  {fmt?.change ?? "—"}
                </td>
                <td className="py-2.5 pr-3" style={{ color: "var(--color-text-secondary)" }}>
                  {fmt?.pValue ?? "—"}
                </td>
                <td className="py-2.5">
                  <span
                    className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    style={
                      drifted
                        ? { background: "var(--accent-amber-tint)", color: "var(--accent-amber)" }
                        : { background: "var(--accent-green-tint)", color: "var(--accent-green)" }
                    }
                  >
                    {drifted ? "Drifted" : "Stable"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-case results table (RAG + LLM Judge)
// ---------------------------------------------------------------------------

function CaseResultsTable({
  results, total, page, limit, onPage, evalType, summary,
}: {
  results: EvalResult[] | null;
  total: number;
  page: number;
  limit: number;
  onPage: (p: number) => void;
  evalType?: EvalType;
  summary: Record<string, any> | null;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (results === null) return <div className="vigil-shimmer h-32 w-full rounded" />;
  if (results.length === 0) {
    return (
      <div className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
        {summary?.note ?? "No per-case results."}
      </div>
    );
  }

  const pages = Math.max(1, Math.ceil(total / limit));

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  return (
    <div>
      {summary && (
        <div
          className="mb-4 rounded-md px-3 py-2 text-xs"
          style={{ background: "var(--color-pill-bg)", color: "var(--color-text-secondary)" }}
        >
          {summary.total_cases ?? results.length} cases ·{" "}
          {summary.passed ?? 0} passed ·{" "}
          {summary.failed ?? 0} failed
          {summary.errored ? ` · ${summary.errored} errored` : ""}
        </div>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider" style={{ color: "var(--color-text-muted)" }}>
            <th className="w-6 pb-2" />
            <th className="pb-2 pr-3 font-medium">Input</th>
            <th className="pb-2 pr-3 font-medium">Scores</th>
            <th className="pb-2 font-medium">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y" style={{ borderColor: "var(--color-divider)" }}>
          {results.map((r) => {
            const isOpen = expanded.has(r.id);
            const scoreEntries = Object.entries(r.scores ?? {});
            return (
              <>
                <tr key={r.id} className="cursor-pointer" onClick={() => toggle(r.id)}>
                  <td className="py-2.5">
                    {isOpen
                      ? <ChevronDown className="h-4 w-4" style={{ color: "var(--color-text-muted)" }} />
                      : <ChevronRight className="h-4 w-4" style={{ color: "var(--color-text-muted)" }} />}
                  </td>
                  <td className="max-w-xs truncate py-2.5 pr-3" style={{ color: "var(--color-text-primary)" }}>
                    {r.case_input ?? "—"}
                  </td>
                  <td className="py-2.5 pr-3" style={{ color: "var(--color-text-secondary)" }}>
                    {scoreEntries.length
                      ? scoreEntries
                          .slice(0, 3)
                          .map(([k, v]) => `${k}=${formatScore(v)}`)
                          .join(", ")
                      : "—"}
                  </td>
                  <td className="py-2.5">
                    <span
                      className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                      style={
                        r.passed
                          ? { background: "var(--accent-green-tint)", color: "var(--accent-green)" }
                          : { background: "var(--accent-red-tint)", color: "var(--accent-red)" }
                      }
                    >
                      {r.passed ? "Passed" : (r.details?.error ? "Errored" : "Failed")}
                    </span>
                  </td>
                </tr>
                {isOpen && (
                  <tr key={`${r.id}-detail`}>
                    <td />
                    <td colSpan={3} className="py-3 pr-3">
                      <CaseDetail result={r} evalType={evalType} />
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>

      {pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-xs" style={{ color: "var(--color-text-muted)" }}>
          <span>Page {page} of {pages}</span>
          <div className="flex gap-1">
            <button
              onClick={() => onPage(Math.max(1, page - 1))}
              disabled={page === 1}
              className="rounded border px-2 py-1 disabled:opacity-40"
              style={{ borderColor: "var(--color-card-border)" }}
            >
              Prev
            </button>
            <button
              onClick={() => onPage(Math.min(pages, page + 1))}
              disabled={page === pages}
              className="rounded border px-2 py-1 disabled:opacity-40"
              style={{ borderColor: "var(--color-card-border)" }}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function formatScore(v: any): string {
  if (typeof v === "number") return v.toFixed(2);
  if (v && typeof v === "object" && typeof v.score === "number") return v.score.toFixed(1);
  return String(v);
}

function CaseDetail({ result, evalType }: { result: EvalResult; evalType?: EvalType }) {
  return (
    <div
      className="rounded-md p-3 text-xs"
      style={{ background: "var(--color-pill-bg)", color: "var(--color-text-secondary)" }}
    >
      {result.case_output && (
        <div className="mb-2">
          <div className="font-semibold" style={{ color: "var(--color-text-primary)" }}>
            Output
          </div>
          <div className="mt-1 whitespace-pre-wrap">{result.case_output}</div>
        </div>
      )}
      {evalType === "llm_judge" && result.scores && (
        <div className="mb-2">
          <div className="font-semibold" style={{ color: "var(--color-text-primary)" }}>
            Per-criterion rationale
          </div>
          <ul className="mt-1 space-y-1">
            {Object.entries(result.scores).map(([k, v]: [string, any]) => (
              <li key={k}>
                <span style={{ color: "var(--color-text-primary)" }}>{k}</span> ·{" "}
                {typeof v?.score === "number" ? v.score.toFixed(1) : String(v?.score ?? v)} —{" "}
                {v?.rationale ?? "no rationale"}
              </li>
            ))}
          </ul>
        </div>
      )}
      {evalType === "rag" && Array.isArray(result.details?.contexts) && result.details?.contexts.length > 0 && (
        <div className="mb-2">
          <div className="font-semibold" style={{ color: "var(--color-text-primary)" }}>
            Retrieved contexts
          </div>
          <ol className="mt-1 list-decimal space-y-1 pl-5">
            {(result.details.contexts as string[]).map((c, i) => (
              <li key={i} className="break-words">{c}</li>
            ))}
          </ol>
        </div>
      )}
      {result.details?.error && (
        <div style={{ color: "var(--accent-red)" }}>
          {String(result.details.error)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// New suite drawer
// ---------------------------------------------------------------------------

function NewSuiteDrawer({
  models, onClose, onCreated,
}: {
  models: Model[];
  onClose: () => void;
  onCreated: (s: EvalSuite) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [evalType, setEvalType] = useState<EvalType>("drift");
  const [modelId, setModelId] = useState<string>("");
  const [ragThreshold, setRagThreshold] = useState(0.7);
  const [rubric, setRubric] = useState(EXAMPLE_RUBRIC);
  const [currentDays, setCurrentDays] = useState(7);
  const [baselineDays, setBaselineDays] = useState(7);
  const [latencyPct, setLatencyPct] = useState(25);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    if (evalType === "drift" && !modelId) {
      setError("Drift suites need a target model.");
      return;
    }

    const payload: EvalSuiteCreate = {
      name: name.trim(),
      description: description.trim() || null,
      eval_type: evalType,
      model_id: modelId || null,
      config: buildConfig(evalType, {
        ragThreshold, rubric, currentDays, baselineDays, latencyPct,
      }),
    };

    setSubmitting(true);
    try {
      const created = await createSuite(payload);
      onCreated(created);
    } catch (err: any) {
      // Backend returns the 422 detail string — surface it inline.
      const msg =
        err?.response?.data?.detail ??
        (err instanceof Error ? err.message : "Failed to create");
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div
        className="vigil-backdrop fixed inset-0 z-40 bg-slate-900/40"
        onClick={onClose}
      />
      <aside
        className="vigil-drawer fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col shadow-xl"
        style={{
          background: "var(--color-card-bg)",
          borderLeft: "1px solid var(--color-card-border)",
        }}
      >
        <div
          className="flex items-start justify-between px-5 py-4"
          style={{ borderBottom: "1px solid var(--color-divider)" }}
        >
          <div>
            <h2 className="text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
              New eval suite
            </h2>
            <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
              Define a reusable evaluation you can run on demand or on a schedule.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1"
            style={{ color: "var(--color-text-muted)" }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={onSubmit} className="flex flex-1 flex-col overflow-y-auto">
          <div className="space-y-4 px-5 py-4">
            <Field label="Name" required>
              <input
                ref={nameRef}
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-md border px-3 py-1.5 text-sm"
                style={{
                  background: "var(--color-card-bg)",
                  borderColor: "var(--color-card-border)",
                  color: "var(--color-text-primary)",
                }}
                placeholder="e.g. Support quality (weekly)"
              />
            </Field>

            <Field label="Description (optional)">
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="w-full rounded-md border px-3 py-1.5 text-sm"
                style={{
                  background: "var(--color-card-bg)",
                  borderColor: "var(--color-card-border)",
                  color: "var(--color-text-primary)",
                }}
              />
            </Field>

            <Field label="Type" required>
              <div className="grid grid-cols-3 gap-2">
                {(["drift", "rag", "llm_judge"] as EvalType[]).map((t) => {
                  const pill = TYPE_PILL[t];
                  const active = evalType === t;
                  return (
                    <button
                      type="button"
                      key={t}
                      onClick={() => setEvalType(t)}
                      className="rounded-md border px-2 py-1.5 text-xs font-semibold"
                      style={{
                        background: active ? pill.bg : "transparent",
                        color: active ? pill.fg : "var(--color-text-secondary)",
                        borderColor: active ? pill.fg : "var(--color-card-border)",
                      }}
                    >
                      {TYPE_LABEL[t]}
                    </button>
                  );
                })}
              </div>
            </Field>

            <Field
              label="Target model"
              required={evalType === "drift"}
              hint={evalType !== "drift" ? "Leave blank for an ad-hoc suite." : undefined}
            >
              <select
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                className="w-full rounded-md border px-3 py-1.5 text-sm"
                style={{
                  background: "var(--color-card-bg)",
                  borderColor: "var(--color-card-border)",
                  color: "var(--color-text-primary)",
                }}
              >
                <option value="">— select a model —</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </Field>

            {evalType === "rag" && (
              <Field label={`Pass threshold (${ragThreshold.toFixed(2)})`}>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={ragThreshold}
                  onChange={(e) => setRagThreshold(parseFloat(e.target.value))}
                  className="w-full"
                />
                <div className="mt-1 text-xs" style={{ color: "var(--color-text-muted)" }}>
                  A case passes when every metric is at or above this score.
                </div>
              </Field>
            )}

            {evalType === "llm_judge" && (
              <Field
                label="Rubric (YAML)"
                hint="The judge LLM scores each criterion 1..scale. Mean across criteria is compared to pass_threshold."
              >
                <textarea
                  value={rubric}
                  onChange={(e) => setRubric(e.target.value)}
                  rows={14}
                  className="w-full rounded-md border px-3 py-2 font-mono text-xs"
                  style={{
                    background: "var(--color-card-bg)",
                    borderColor: "var(--color-card-border)",
                    color: "var(--color-text-primary)",
                  }}
                />
              </Field>
            )}

            {evalType === "drift" && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Current window (days)">
                  <input
                    type="number"
                    min={1}
                    value={currentDays}
                    onChange={(e) => setCurrentDays(parseInt(e.target.value || "1", 10))}
                    className="w-full rounded-md border px-3 py-1.5 text-sm"
                    style={{
                      background: "var(--color-card-bg)",
                      borderColor: "var(--color-card-border)",
                      color: "var(--color-text-primary)",
                    }}
                  />
                </Field>
                <Field label="Baseline window (days)">
                  <input
                    type="number"
                    min={1}
                    value={baselineDays}
                    onChange={(e) => setBaselineDays(parseInt(e.target.value || "1", 10))}
                    className="w-full rounded-md border px-3 py-1.5 text-sm"
                    style={{
                      background: "var(--color-card-bg)",
                      borderColor: "var(--color-card-border)",
                      color: "var(--color-text-primary)",
                    }}
                  />
                </Field>
                <Field label="Latency p95 % threshold">
                  <input
                    type="number"
                    min={0}
                    value={latencyPct}
                    onChange={(e) => setLatencyPct(parseFloat(e.target.value || "0"))}
                    className="w-full rounded-md border px-3 py-1.5 text-sm"
                    style={{
                      background: "var(--color-card-bg)",
                      borderColor: "var(--color-card-border)",
                      color: "var(--color-text-primary)",
                    }}
                  />
                </Field>
              </div>
            )}

            {error && (
              <div
                className="rounded-md p-3 text-xs"
                style={{
                  background: "var(--accent-red-tint)",
                  color: "var(--accent-red)",
                }}
              >
                {error}
              </div>
            )}
          </div>

          <div
            className="mt-auto flex items-center justify-end gap-2 px-5 py-3"
            style={{ borderTop: "1px solid var(--color-divider)" }}
          >
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border px-3 py-1.5 text-sm"
              style={{
                background: "var(--color-card-bg)",
                borderColor: "var(--color-card-border)",
                color: "var(--color-text-primary)",
              }}
            >
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create suite
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}

function buildConfig(
  type: EvalType,
  v: { ragThreshold: number; rubric: string; currentDays: number; baselineDays: number; latencyPct: number },
): Record<string, any> {
  switch (type) {
    case "rag":
      return { threshold: v.ragThreshold };
    case "llm_judge":
      return { rubric: v.rubric };
    case "drift":
      return {
        current_days: v.currentDays,
        baseline_days: v.baselineDays,
        latency_pct_threshold: v.latencyPct,
      };
  }
}

function Field({
  label, required, hint, children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--color-text-secondary)" }}>
          {label}{required && <span style={{ color: "var(--accent-red)" }}> *</span>}
        </span>
      </div>
      {children}
      {hint && <div className="mt-1 text-xs" style={{ color: "var(--color-text-muted)" }}>{hint}</div>}
    </label>
  );
}
