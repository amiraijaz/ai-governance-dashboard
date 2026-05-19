import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { Eye, EyeOff } from "lucide-react";

import { login } from "../api/auth";
import PrimaryButton from "../components/PrimaryButton";
import AuthSplit from "../components/AuthSplit";

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        setError("Invalid email or password");
      } else if (axios.isAxiosError(err) && err.response?.status === 429) {
        setError("Too many attempts. Try again in a minute.");
      } else {
        setError("Login failed. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthSplit>
      <h1 className="auth-fade text-[22px] font-medium text-slate-900" style={{ animationDelay: "0ms" }}>
        Welcome back
      </h1>
      <p
        className="auth-fade mt-1.5 text-sm text-slate-500"
        style={{ animationDelay: "0ms" }}
      >
        Sign in to your Vigil dashboard
      </p>

      <form onSubmit={onSubmit} className="mt-8 space-y-4">
        <div className="auth-fade" style={{ animationDelay: "100ms" }}>
          <AuthField
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
            required
          />
        </div>
        <div className="auth-fade" style={{ animationDelay: "100ms" }}>
          <AuthPasswordField
            label="Password"
            value={password}
            onChange={setPassword}
            show={showPassword}
            onToggleShow={() => setShowPassword((v) => !v)}
            autoComplete="current-password"
          />
        </div>

        <div className="auth-fade pt-2" style={{ animationDelay: "200ms" }}>
          <PrimaryButton type="submit" disabled={busy} className="w-full">
            {busy ? "Signing in..." : "Sign in"}
          </PrimaryButton>

          {error && (
            <p className="mt-3 text-sm text-red-600" role="alert">
              {error}
            </p>
          )}

          <p className="mt-5 text-sm text-slate-500">
            Don't have an account?{" "}
            <Link to="/register" className="font-medium text-slate-900 hover:underline">
              Get started
            </Link>
          </p>
        </div>
      </form>
    </AuthSplit>
  );
}

function AuthField({
  label,
  type,
  value,
  onChange,
  autoComplete,
  required,
}: {
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
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
        autoComplete={autoComplete}
        required={required}
        className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 transition focus:border-[color:var(--vigil-green)] focus:outline-none focus:ring-2 focus:ring-[color:var(--vigil-green)]/20"
      />
    </label>
  );
}

function AuthPasswordField({
  label,
  value,
  onChange,
  show,
  onToggleShow,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  show: boolean;
  onToggleShow: () => void;
  autoComplete?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <div className="relative mt-1">
        <input
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          required
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 pr-10 text-sm text-slate-900 transition focus:border-[color:var(--vigil-green)] focus:outline-none focus:ring-2 focus:ring-[color:var(--vigil-green)]/20"
        />
        <button
          type="button"
          onClick={onToggleShow}
          tabIndex={-1}
          aria-label={show ? "Hide password" : "Show password"}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-700"
        >
          {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </label>
  );
}

export { AuthField, AuthPasswordField };