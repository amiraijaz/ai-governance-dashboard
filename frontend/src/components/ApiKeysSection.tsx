import { useEffect, useState } from "react";
import { Copy, Key, Loader2, Plus, X } from "lucide-react";

import { APIKeyCreated, APIKeyInfo, createKey, listKeys } from "../api/keys";
import { useToast } from "./Toast";

function fmt(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ApiKeysSection() {
  const { showToast } = useToast();
  const [keys, setKeys] = useState<APIKeyInfo[] | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [shown, setShown] = useState<APIKeyCreated | null>(null);

  async function refresh() {
    try {
      setKeys(await listKeys());
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to load keys", "error");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onCreate() {
    setCreating(true);
    try {
      const created = await createKey(name.trim() || undefined);
      setShown(created);
      setName("");
      await refresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not create key", "error");
    } finally {
      setCreating(false);
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Key className="h-4 w-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-900">API Keys</h2>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Key name (optional)"
            className="rounded-md border border-slate-300 px-2 py-1 text-sm focus:border-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-900"
          />
          <button
            onClick={onCreate}
            disabled={creating}
            className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {creating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Create Key
          </button>
        </div>
      </div>

      {keys === null ? (
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="h-10 w-full animate-pulse rounded bg-slate-100" />
          ))}
        </div>
      ) : keys.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-400">
          No API keys yet. Create one to start logging from the SDK.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="pb-2 font-medium">Name</th>
              <th className="pb-2 font-medium">Created</th>
              <th className="pb-2 font-medium">Last used</th>
              <th className="pb-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {keys.map((k) => (
              <tr key={k.id}>
                <td className="py-2 text-slate-900">{k.name ?? "(unnamed)"}</td>
                <td className="py-2 text-slate-700">{fmt(k.created_at)}</td>
                <td className="py-2 text-slate-700">{fmt(k.last_used_at)}</td>
                <td className="py-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      k.is_active
                        ? "bg-green-100 text-green-700"
                        : "bg-slate-200 text-slate-600"
                    }`}
                  >
                    {k.is_active ? "Active" : "Revoked"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {shown && <ShowKeyModal created={shown} onClose={() => setShown(null)} />}
    </section>
  );
}

function ShowKeyModal({
  created,
  onClose,
}: {
  created: APIKeyCreated;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      showToast("API key copied to clipboard", "success");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      showToast("Could not copy — select and copy manually", "error");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-md rounded-lg bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">
              API key created
            </h3>
            <p className="text-xs text-slate-500">
              {created.name ?? "(unnamed)"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
            This key will only be shown once. Copy it now.
          </div>

          <div className="flex items-stretch gap-2">
            <code className="flex-1 break-all rounded-md border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-800">
              {created.key}
            </code>
            <button
              onClick={copy}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 text-sm font-medium text-white hover:bg-slate-800"
            >
              <Copy className="h-3.5 w-3.5" />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
        <div className="flex justify-end border-t border-slate-200 px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          >
            I've copied it
          </button>
        </div>
      </div>
    </div>
  );
}
