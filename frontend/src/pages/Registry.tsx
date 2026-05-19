import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Archive,
  Loader2,
  Pencil,
  Plus,
  Search,
  X,
} from "lucide-react";

import {
  ModelCreate,
  ModelUpdate,
  archiveModel,
  createModel,
  getModels,
  updateModel,
} from "../api/models";
import { useToast } from "../components/Toast";
import type { Model, ModelStatus, RiskLevel } from "../types";

const PROVIDERS = ["OpenAI", "Anthropic", "Google", "HuggingFace", "Custom"];
const RISK_LEVELS: RiskLevel[] = ["Low", "Medium", "High", "Critical"];
const STATUSES: ModelStatus[] = ["Active", "Paused", "Archived"];

const RISK_BADGE: Record<RiskLevel, string> = {
  Low: "bg-green-100 text-green-700 ring-green-200",
  Medium: "bg-amber-100 text-amber-800 ring-amber-200",
  High: "bg-orange-100 text-orange-800 ring-orange-200",
  Critical: "bg-red-100 text-red-700 ring-red-200",
};

const STATUS_BADGE: Record<ModelStatus, string> = {
  Active: "bg-green-100 text-green-700 ring-green-200",
  Paused: "bg-amber-100 text-amber-800 ring-amber-200",
  Archived: "bg-slate-200 text-slate-600 ring-slate-300",
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function Registry() {
  const [models, setModels] = useState<Model[] | null>(null);
  const { showToast } = useToast();

  const [provider, setProvider] = useState("all");
  const [risk, setRisk] = useState<RiskLevel | "all">("all");
  const [status, setStatus] = useState<ModelStatus | "all">("all");
  const [search, setSearch] = useState("");

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Model | null>(null);
  const [confirmArchive, setConfirmArchive] = useState<Model | null>(null);

  async function refresh() {
    try {
      const data = await getModels();
      setModels(data);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to load", "error");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const filtered = useMemo(() => {
    if (!models) return [];
    const needle = search.trim().toLowerCase();
    return models.filter((m) => {
      if (provider !== "all" && m.provider !== provider) return false;
      if (risk !== "all" && m.risk_level !== risk) return false;
      if (status !== "all" && m.status !== status) return false;
      if (needle && !m.name.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [models, provider, risk, status, search]);

  function openCreate() {
    setEditing(null);
    setDrawerOpen(true);
  }

  function openEdit(m: Model) {
    setEditing(m);
    setDrawerOpen(true);
  }

  async function doArchive() {
    if (!confirmArchive) return;
    try {
      const name = confirmArchive.name;
      await archiveModel(confirmArchive.id);
      setConfirmArchive(null);
      await refresh();
      showToast(`Archived "${name}"`, "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Archive failed", "error");
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Model Registry</h1>
          <p className="text-sm text-slate-500">All LLM deployments in your organisation</p>
        </div>
        <button
          onClick={openCreate}
          className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          <Plus className="h-4 w-4" />
          Register Model
        </button>
      </header>

      <section className="mb-4 flex flex-wrap items-center gap-3">
        <Select
          label="Provider"
          value={provider}
          onChange={setProvider}
          options={[["all", "All"], ...PROVIDERS.map((p) => [p, p] as [string, string])]}
        />
        <Select
          label="Risk"
          value={risk}
          onChange={(v) => setRisk(v as RiskLevel | "all")}
          options={[["all", "All"], ...RISK_LEVELS.map((r) => [r, r] as [string, string])]}
        />
        <Select
          label="Status"
          value={status}
          onChange={(v) => setStatus(v as ModelStatus | "all")}
          options={[["all", "All"], ...STATUSES.map((s) => [s, s] as [string, string])]}
        />
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name"
            className="rounded-md border border-slate-300 bg-white py-1.5 pl-8 pr-3 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
          />
        </div>
      </section>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Provider</th>
              <th className="px-4 py-2 font-medium">Version</th>
              <th className="px-4 py-2 font-medium">Risk</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Owner Team</th>
              <th className="px-4 py-2 font-medium">Deployed</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {models === null ? (
              Array.from({ length: 4 }).map((_, i) => (
                <tr key={i}>
                  <td colSpan={8} className="px-4 py-3">
                    <div className="h-5 w-full animate-pulse rounded bg-slate-100" />
                  </td>
                </tr>
              ))
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-sm text-slate-400">
                  {models.length === 0
                    ? "No models registered yet"
                    : "No models match these filters"}
                </td>
              </tr>
            ) : (
              filtered.map((m) => (
                <tr key={m.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-900">{m.name}</td>
                  <td className="px-4 py-2 text-slate-700">{m.provider}</td>
                  <td className="px-4 py-2 text-slate-700">{m.model_version}</td>
                  <td className="px-4 py-2">
                    <Badge cls={RISK_BADGE[m.risk_level] ?? RISK_BADGE.Low}>
                      {m.risk_level}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    <Badge cls={STATUS_BADGE[m.status] ?? STATUS_BADGE.Active}>
                      {m.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-slate-700">{m.owner_team ?? "—"}</td>
                  <td className="px-4 py-2 text-slate-700">{fmtDate(m.deployment_date)}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center justify-end gap-1">
                      <IconButton title="Edit" onClick={() => openEdit(m)}>
                        <Pencil className="h-4 w-4" />
                      </IconButton>
                      <IconButton
                        title="Archive"
                        onClick={() => setConfirmArchive(m)}
                        disabled={m.status === "Archived"}
                      >
                        <Archive className="h-4 w-4" />
                      </IconButton>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {drawerOpen && (
        <Drawer
          model={editing}
          onClose={() => setDrawerOpen(false)}
          onSaved={async (name, wasEdit) => {
            setDrawerOpen(false);
            await refresh();
            showToast(
              wasEdit ? `Updated "${name}"` : `Registered "${name}"`,
              "success"
            );
          }}
        />
      )}

      {confirmArchive && (
        <ConfirmDialog
          title="Archive model?"
          message={`This will set "${confirmArchive.name}" to Archived. Logs are kept.`}
          confirmLabel="Archive"
          onCancel={() => setConfirmArchive(null)}
          onConfirm={doArchive}
        />
      )}
    </div>
  );
}

function Drawer({
  model,
  onClose,
  onSaved,
}: {
  model: Model | null;
  onClose: () => void;
  onSaved: (name: string, wasEdit: boolean) => Promise<void>;
}) {
  const isEdit = model !== null;
  const [name, setName] = useState(model?.name ?? "");
  const [provider, setProvider] = useState(model?.provider ?? "OpenAI");
  const [version, setVersion] = useState(model?.model_version ?? "");
  const [useCase, setUseCase] = useState(model?.use_case ?? "");
  const [ownerTeam, setOwnerTeam] = useState(model?.owner_team ?? "");
  const [ownerEmail, setOwnerEmail] = useState(model?.owner_email ?? "");
  const [deploymentDate, setDeploymentDate] = useState(model?.deployment_date ?? "");
  const [risk, setRisk] = useState<RiskLevel>(model?.risk_level ?? "Low");
  const [status, setStatus] = useState<ModelStatus>(model?.status ?? "Active");
  const [description, setDescription] = useState(model?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const payload: ModelCreate = {
        name: name.trim(),
        provider,
        model_version: version.trim(),
        use_case: useCase.trim() || undefined,
        owner_team: ownerTeam.trim() || undefined,
        owner_email: ownerEmail.trim() || undefined,
        deployment_date: deploymentDate || undefined,
        risk_level: risk,
        status,
        description: description.trim() || undefined,
      };
      if (isEdit && model) {
        await updateModel(model.id, payload as ModelUpdate);
      } else {
        await createModel(payload);
      }
      await onSaved(payload.name, isEdit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div
        className="vigil-modal-backdrop absolute inset-0"
        onClick={busy ? undefined : onClose}
      />
      <div
        className="vigil-modal-pop relative flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        style={{ borderRadius: "var(--radius-card)" }}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {isEdit ? "Edit model" : "Register model"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={onSubmit} className="flex flex-1 flex-col overflow-y-auto">
          <div className="flex-1 space-y-3 px-5 py-4">
            <Field label="Name *" value={name} onChange={setName} required />
            <SelectField
              label="Provider *"
              value={provider}
              onChange={setProvider}
              options={PROVIDERS}
              required
            />
            <Field label="Model Version" value={version} onChange={setVersion} />
            <Field label="Use Case" value={useCase} onChange={setUseCase} />
            <Field label="Owner Team" value={ownerTeam} onChange={setOwnerTeam} />
            <Field
              label="Owner Email"
              type="email"
              value={ownerEmail}
              onChange={setOwnerEmail}
            />
            <Field
              label="Deployment Date"
              type="date"
              value={deploymentDate}
              onChange={setDeploymentDate}
            />
            <SelectField
              label="Risk Level *"
              value={risk}
              onChange={(v) => setRisk(v as RiskLevel)}
              options={RISK_LEVELS}
              required
            />
            <SelectField
              label="Status"
              value={status}
              onChange={(v) => setStatus(v as ModelStatus)}
              options={STATUSES}
            />
            <label className="block">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Description
              </span>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
              />
            </label>

            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || !name || !provider || !risk}
              className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {isEdit ? "Save changes" : "Register"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <p className="mt-2 text-sm text-slate-600">{message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            onClick={go}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  type = "text",
  value,
  onChange,
  required,
}: {
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
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
        required={required}
        className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function Select({
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
    <label className="inline-flex items-center gap-2 text-sm text-slate-600">
      <span className="font-medium text-slate-500">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
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

function Badge({ cls, children }: { cls: string; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}
    >
      {children}
    </span>
  );
}

function IconButton({
  children,
  title,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  title: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}
