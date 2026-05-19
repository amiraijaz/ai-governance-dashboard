import { Navigate, Outlet } from "react-router-dom";

import Sidebar from "./Sidebar";
import AnimatedPage from "./AnimatedPage";
import { TOKEN_KEY } from "../api/client";
import { AuthProvider, useAuth } from "../context/AuthContext";

function Shell() {
  const { user, loading } = useAuth();

  // While we resolve /auth/me on first load, show a tiny placeholder so the
  // sidebar doesn't briefly render "Signed in" before populating.
  if (loading && !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-400">
        Loading…
      </div>
    );
  }

  // /auth/me returned an error and the token was already cleared by the
  // 401 interceptor; redirect to login.
  if (!loading && !user) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Sidebar email={user?.email ?? null} />
      <main className="ml-60">
        <AnimatedPage>
          <Outlet />
        </AnimatedPage>
      </main>
    </div>
  );
}

export default function ProtectedLayout() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return <Navigate to="/login" replace />;

  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
