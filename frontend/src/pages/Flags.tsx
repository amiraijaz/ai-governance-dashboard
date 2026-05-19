import { useEffect, useMemo, useState } from "react";
import { Loader2, Shield, X } from "lucide-react";

import { useToast } from "../components/Toast";
import {
  FlagReviewRequest,
  FlagSeverity,
  FlagStats,
  ReviewStatus,
  SafetyFlagItem,
  getFlagStats,
  getFlags,
  reviewFlag,
} from "../api/flags";

type SeverityFilter = "all" | FlagSeverity;
type ReviewedFilter = "all" | "unreviewed" | "reviewed";

const SEVERITY_PILL: Record<FlagSeverity, string> = {
  RED: "bg-red-100 text-red-700 ring-red-200",
  YELLOW: "bg-amber-100 text-amber-800 ring-amber-200",
  GREEN: "bg-green-100 text-green-700 ring-green-200",
};

const CONFIDENCE_BAR: Record<FlagSeverity, string> = {
  RED: "bg-red-500",
  YELLOW: "bg-amber-500",
  GREEN: "bg-green-500",
};

function relTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

export default function Flags() {
  const [stats, setStats] = useState<FlagStats | null>(null);
  const [items, setItems] = useState<SafetyFlagItem[] | null>(null);
  const [severity, setSeverity] = useState<SeverityFilter>("all");
  const [reviewedFilter, setReviewedFilter] = useState<ReviewedFilter>("unreviewed");
  const [active, setActive] = useState<SafetyFlagItem | null>(null);
  const { showToast } = useToast();

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    (async () => {
      try {
        const reviewed =
          reviewedFilter === "all" ? undefined : reviewedFilter === "reviewed";
        const [s, list] = await Promise.all([
          getFlagStats(),
          getFlags({
            severity: severity === "all" ? undefined : severity,
            reviewed,
            limit: 100,
          }),
        ]);
        if (cancelled) return;
        setStats(s);
        setItems(list.items);
      } catch (err) {
        if (!cancelled)
          showToast(err instanceof Error ? err.message : "Failed to load", "error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [severity, reviewedFilter, showToast]);

  async function onReview(id: string, payload: FlagReviewRequest) {
    await reviewFlag(id, payload);
    setItems((prev) => (prev ? prev.filter((f) => f.id !== id) : prev));
    setActive(null);
    showToast("Flag reviewed", "success");
    // re-pull stats; don't block UI on it
    getFlagStats().then(setStats).catch(() => {});
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Review Queue</h1>
        <p className="text-sm text-slate-500">Human review of safety flags</p>
      </header>

      <section className="mb-4 flex flex-wrap items-center gap-2">
        <StatPill label="Total" value={stats?.total} tone="slate" />
        <StatPill label="Open" value={stats?.open} tone="slate" />
        <StatPill label="Yellow" value={stats?.yellow} tone="yellow" />
        <StatPill label="Red" value={stats?.red} tone="red" />
      </section>

      <section className="mb-5 flex flex-wrap items-center gap-3">
        <Select<SeverityFilter>
          label="Severity"
          value={severity}
          onChange={setSeverity}
          options={[
            ["all", "All"],
            ["GREEN", "Green"],
            ["YELLOW", "Yellow"],
            ["RED", "Red"],
          ]}
        />
        <Select<ReviewedFilter>
          label="Status"
          value={reviewedFilter}
          onChange={setReviewedFilter}
          options={[
            ["all", "All"],
            ["unreviewed", "Unreviewed"],
            ["reviewed", "Reviewed"],
          ]}
        />
      </section>

      {items === null ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-44 animate-pulse rounded-lg bg-white shadow-sm" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((flag) => (
            <FlagCard key={flag.id} flag={flag} onReview={() => setActive(flag)} />
          ))}
        </div>
      )}

      {active && (
        <ReviewModal
          flag={active}
          onClose={() => setActive(null)}
          onSubmit={(p) => onReview(active.id, p)}
        />
      )}

    </div>
  );
}

function FlagCard({
  flag,
  onReview,
}: {
  flag: SafetyFlagItem;
  onReview: () => void;
}) {
  const conf = Math.max(0, Math.min(100, Math.round(flag.confidence * 100)));
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${SEVERITY_PILL[flag.severity]}`}
          >
            {flag.severity === "RED" && <span className="vigil-pulse-red" />}
            {flag.severity}
          </span>
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
            {flag.flag_type}
          </span>
        </div>
        <span className="text-xs text-slate-500">{relTime(flag.timestamp)}</span>
      </div>

      <div>
        <div className="text-sm font-medium text-slate-900">
          {flag.model_name ?? "Unknown model"}
        </div>
        <div className="mt-2">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Confidence</span>
            <span>{conf}%</span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full ${CONFIDENCE_BAR[flag.severity]}`}
              style={{ width: `${conf}%` }}
            />
          </div>
        </div>
      </div>

      <div className="mt-auto pt-2">
        <button
          onClick={onReview}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          Review
        </button>
      </div>
    </div>
  );
}

function ReviewModal({
  flag,
  onClose,
  onSubmit,
}: {
  flag: SafetyFlagItem;
  onClose: () => void;
  onSubmit: (payload: FlagReviewRequest) => Promise<void>;
}) {
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<ReviewStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const detailsJson = useMemo(
    () => (flag.details ? JSON.stringify(flag.details, null, 2) : null),
    [flag.details]
  );

  async function submit(status: ReviewStatus) {
    setBusy(status);
    setError(null);
    try {
      await onSubmit({ review_status: status, review_notes: notes || undefined });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Review flag</h2>
            <p className="text-xs text-slate-500">{flag.model_name ?? "Unknown model"}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="grid grid-cols-3 gap-3 text-sm">
            <Stat label="Type" value={flag.flag_type} />
            <Stat label="Severity">
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${SEVERITY_PILL[flag.severity]}`}
              >
                {flag.severity}
              </span>
            </Stat>
            <Stat label="Confidence" value={`${Math.round(flag.confidence * 100)}%`} />
          </div>

          {detailsJson && (
            <div>
              <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                Details
              </div>
              <pre className="max-h-48 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                {detailsJson}
              </pre>
            </div>
          )}

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Notes (optional)
            </span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Why is this flag safe / an issue / escalated?"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
            />
          </label>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">
          <ActionButton
            label="Mark Safe"
            tone="green"
            loading={busy === "safe"}
            disabled={busy !== null}
            onClick={() => submit("safe")}
          />
          <ActionButton
            label="Issue Found"
            tone="orange"
            loading={busy === "issue_found"}
            disabled={busy !== null}
            onClick={() => submit("issue_found")}
          />
          <ActionButton
            label="Escalate"
            tone="red"
            loading={busy === "escalated"}
            disabled={busy !== null}
            onClick={() => submit("escalated")}
          />
        </div>
      </div>
    </div>
  );
}

const TONE: Record<string, string> = {
  green: "bg-green-600 hover:bg-green-700 text-white",
  orange: "bg-amber-600 hover:bg-amber-700 text-white",
  red: "bg-red-600 hover:bg-red-700 text-white",
};

function ActionButton({
  label,
  tone,
  loading,
  disabled,
  onClick,
}: {
  label: string;
  tone: keyof typeof TONE;
  loading: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60 ${TONE[tone]}`}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {label}
    </button>
  );
}

function Stat({
  label,
  value,
  children,
}: {
  label: string;
  value?: string;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-0.5 text-sm text-slate-900">{children ?? value}</div>
    </div>
  );
}

const PILL_TONE: Record<string, string> = {
  slate: "bg-white text-slate-700 ring-slate-200",
  yellow: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
};

function StatPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | undefined;
  tone: keyof typeof PILL_TONE;
}) {
  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ring-1 shadow-sm ${PILL_TONE[tone]}`}
    >
      <span className="text-slate-500">{label}</span>
      <span className="font-semibold">{value ?? "—"}</span>
    </div>
  );
}

function Select<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T;
  onChange: (v: T) => void;
  options: [T, string][];
}) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-slate-600">
      <span className="font-medium text-slate-500">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
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

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white py-16 text-center">
      <Shield className="h-12 w-12 text-slate-300" />
      <p className="mt-4 text-sm font-medium text-slate-700">
        No flags to review
      </p>
      <p className="text-xs text-slate-500">Your models are clean.</p>
    </div>
  );
}
