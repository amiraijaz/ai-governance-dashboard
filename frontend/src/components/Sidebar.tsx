import {
  BarChart3,
  Database,
  FileText,
  FlaskConical,
  Home,
  List,
  LogOut,
  LucideIcon,
  Moon,
  Settings,
  Shield,
  Sun,
} from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";

import { logout } from "../api/auth";
import { useTheme } from "../hooks/theme";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: Home },
  { to: "/models", label: "Model Registry", icon: Database },
  { to: "/logs", label: "Audit Logs", icon: List },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/flags", label: "Review Queue", icon: Shield },
  { to: "/evaluations", label: "Evaluations", icon: FlaskConical },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/settings", label: "Settings", icon: Settings },
];

function initialsOf(email: string | null | undefined): string {
  if (!email) return "?";
  const local = email.split("@")[0];
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

export default function Sidebar({ email }: { email?: string | null }) {
  const navigate = useNavigate();
  const { effective, setTheme } = useTheme();

  function onLogout() {
    logout();
    navigate("/login");
  }

  function toggleTheme() {
    setTheme(effective === "dark" ? "light" : "dark");
  }

  return (
    <aside
      className="fixed inset-y-0 left-0 flex w-60 flex-col bg-white"
      style={{ borderRight: "1px solid rgba(0,0,0,0.06)" }}
    >
      <div className="flex items-center gap-2 px-5 py-5">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-full"
          style={{ background: "var(--vigil-green)" }}
          aria-hidden
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2 4 5v6c0 5 3.5 9 8 11 4.5-2 8-6 8-11V5l-8-3Z" />
            <circle cx="12" cy="11" r="2.2" />
          </svg>
        </span>
        <div>
          <div className="text-base font-semibold leading-tight text-slate-900">Vigil</div>
          <div className="text-[11px] uppercase tracking-wide text-slate-400">AI Governance</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `vigil-nav ${isActive ? "active" : ""}`}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-slate-100 px-3 py-3">
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
            style={{ background: "var(--vigil-green-dark)" }}
          >
            {initialsOf(email)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs text-slate-600" title={email ?? ""}>
              {email ?? "Signed in"}
            </div>
          </div>
          <button
            onClick={toggleTheme}
            title={effective === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            {effective === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </button>
          <button
            onClick={onLogout}
            title="Log out"
            className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
