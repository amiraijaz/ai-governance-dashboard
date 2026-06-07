import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import ProtectedLayout from "./components/ProtectedLayout";
import { ToastProvider } from "./components/Toast";
import Analytics from "./pages/Analytics";
import Dashboard from "./pages/Dashboard";
import Evaluations from "./pages/Evaluations";
import Flags from "./pages/Flags";
import Login from "./pages/Login";
import Logs from "./pages/Logs";
import Register from "./pages/Register";
import Registry from "./pages/Registry";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/models" element={<Registry />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/flags" element={<Flags />} />
            <Route path="/evaluations" element={<Evaluations />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<Settings />} />
          </Route>

          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  );
}
