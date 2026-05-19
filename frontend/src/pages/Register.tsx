import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";

import { login, register } from "../api/auth";
import PrimaryButton from "../components/PrimaryButton";
import AuthSplit from "../components/AuthSplit";
import { AuthField, AuthPasswordField } from "./Login";

export default function Register() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await register(email, password, organisation || undefined);
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setError("That email is already registered");
      } else if (axios.isAxiosError(err) && err.response?.status === 422) {
        setError("Password must be at least 8 characters");
      } else if (axios.isAxiosError(err) && err.response?.status === 429) {
        setError("Too many attempts. Try again in a minute.");
      } else {
        setError("Registration failed. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthSplit>
      <h1
        className="auth-fade text-[22px] font-medium text-slate-900"
        style={{ animationDelay: "0ms" }}
      >
        Create your account
      </h1>
      <p
        className="auth-fade mt-1.5 text-sm text-slate-500"
        style={{ animationDelay: "0ms" }}
      >
        Start governing your LLM deployments in minutes
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
          <AuthField
            label="Organisation (optional)"
            type="text"
            value={organisation}
            onChange={setOrganisation}
            autoComplete="organization"
          />
        </div>
        <div className="auth-fade" style={{ animationDelay: "100ms" }}>
          <AuthPasswordField
            label="Password"
            value={password}
            onChange={setPassword}
            show={showPassword}
            onToggleShow={() => setShowPassword((v) => !v)}
            autoComplete="new-password"
          />
        </div>

        <div className="auth-fade pt-2" style={{ animationDelay: "200ms" }}>
          <PrimaryButton type="submit" disabled={busy} className="w-full">
            {busy ? "Creating..." : "Create account"}
          </PrimaryButton>

          {error && (
            <p className="mt-3 text-sm text-red-600" role="alert">
              {error}
            </p>
          )}

          <p className="mt-5 text-sm text-slate-500">
            Already have an account?{" "}
            <Link to="/login" className="font-medium text-slate-900 hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </form>
    </AuthSplit>
  );
}