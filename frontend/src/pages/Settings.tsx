import { useEffect, useState } from "react";
import {
  Building2,
  Mail,
  Monitor,
  Moon,
  Shield,
  Sun,
  User as UserIcon,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import ApiKeysSection from "../components/ApiKeysSection";
import PrimaryButton from "../components/PrimaryButton";
import { useToast } from "../components/Toast";
import { getCurrentEmail, logout } from "../api/auth";
import { useFadeIn } from "../hooks/animation";
import { useTheme, type Theme } from "../hooks/theme";

const COMPACT_KEY = "aigov_compact";

export default function Settings() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const email = getCurrentEmail();

  const { theme, effective, setTheme } = useTheme();
  const [compact, setCompact] = useState<boolean>(
    localStorage.getItem(COMPACT_KEY) === "1"
  );

  useEffect(() => {
    localStorage.setItem(COMPACT_KEY, compact ? "1" : "0");
  }, [compact]);

  function initials(): string {
    if (!email) return "?";
    const local = email.split("@")[0];
    const parts = local.split(/[._-]/).filter(Boolean);
    return (parts.length >= 2
      ? parts[0][0] + parts[1][0]
      : local.slice(0, 2)
    ).toUpperCase();
  }

  function organisationGuess(): string {
    if (!email) return "—";
    const domain = email.split("@")[1] ?? "";
    return domain.split(".")[0] || "—";
  }

  function onSignOut() {
    logout();
    showToast("Signed out", "info");
    navigate("/login");
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6 md:p-8">
      <header className="mb-6" style={useFadeIn(0)}>
        <h1 className="text-2xl font-bold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500">
          Account, security, and preferences
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Profile card */}
        <section
          className="vigil-card vigil-card-interactive bg-white p-5 lg:col-span-1"
          style={useFadeIn(80)}
        >
          <div className="flex items-center gap-4">
            <div
              className="flex h-16 w-16 items-center justify-center rounded-full text-xl font-semibold text-white shadow-md"
              style={{
                background:
                  "linear-gradient(135deg, var(--vigil-green) 0%, var(--vigil-green-dark) 100%)",
              }}
            >
              {initials()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-base font-semibold text-slate-900" title={email ?? ""}>
                {email ?? "Signed in"}
              </div>
              <div className="text-xs text-slate-500">Viewer · Free plan</div>
            </div>
          </div>

          <dl className="mt-5 space-y-3 text-sm">
            <Row icon={Mail} label="Email" value={email ?? "—"} />
            <Row icon={Building2} label="Organisation" value={organisationGuess()} />
            <Row icon={Shield} label="Role" value="Viewer" />
          </dl>

          <p className="mt-5 text-xs text-slate-400">
            Profile editing isn't wired to an endpoint yet. Need to update
            something? Talk to your admin.
          </p>
        </section>

        {/* Preferences */}
        <section
          className="vigil-card vigil-card-interactive bg-white p-5 lg:col-span-2"
          style={useFadeIn(160)}
        >
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <UserIcon className="h-4 w-4 text-slate-500" />
            Preferences
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Saved locally on this device only.
          </p>

          <div className="mt-5 space-y-4">
            <Toggle
              label="Compact tables"
              hint="Reduces row padding across log and registry tables."
              checked={compact}
              onChange={setCompact}
            />

            <div>
              <div className="text-sm font-medium text-slate-700">Theme</div>
              <div className="mt-2 inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
                {(
                  [
                    ["light", "Light", Sun],
                    ["dark", "Dark", Moon],
                    ["system", "System", Monitor],
                  ] as [Theme, string, typeof Sun][]
                ).map(([t, label, Icon]) => {
                  const active = theme === t;
                  return (
                    <button
                      key={t}
                      onClick={() => setTheme(t)}
                      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-sm font-medium transition ${
                        active
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-500 hover:text-slate-700"
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-xs text-slate-400">
                Currently displaying:{" "}
                <span className="font-medium text-slate-600">{effective}</span>
              </p>
            </div>
          </div>
        </section>

        {/* API keys (full width) */}
        <div className="lg:col-span-3" style={useFadeIn(240)}>
          <ApiKeysSection />
        </div>

        {/* Danger zone */}
        <section
          className="vigil-card bg-white p-5 lg:col-span-3"
          style={{
            ...useFadeIn(320),
            border: "1px solid #fee2e2",
            background: "linear-gradient(180deg, #fef2f2 0%, #ffffff 60%)",
          }}
        >
          <h2 className="text-sm font-semibold text-red-700">Account</h2>
          <p className="mt-1 text-xs text-red-600/80">
            Sign out clears your token from this device. Refresh tokens
            issued elsewhere remain valid until they expire.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <PrimaryButton
              onClick={onSignOut}
              style={{ background: "#dc2626" }}
            >
              Sign out of this device
            </PrimaryButton>
          </div>
        </section>
      </div>
    </div>
  );
}

function Row({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Mail;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <Icon className="h-4 w-4 shrink-0 text-slate-400" />
      <dt className="w-28 shrink-0 text-xs uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="truncate text-slate-800" title={value}>
        {value}
      </dd>
    </div>
  );
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start justify-between gap-4">
      <div>
        <div className="text-sm font-medium text-slate-700">{label}</div>
        {hint && <div className="text-xs text-slate-500">{hint}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${
          checked ? "" : "bg-slate-300"
        }`}
        style={{ background: checked ? "var(--vigil-green)" : undefined }}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}
