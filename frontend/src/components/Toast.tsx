import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

export type ToastType = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TOAST_TTL = 3000;
const MAX_VISIBLE = 3;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: ToastType = "info") => {
      const id = Date.now() + Math.random();
      setToasts((prev) => {
        const next = [...prev, { id, message, type }];
        // Cap visible toasts; drop oldest if over the limit.
        return next.length > MAX_VISIBLE
          ? next.slice(next.length - MAX_VISIBLE)
          : next;
      });
      setTimeout(() => dismiss(id), TOAST_TTL);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="pointer-events-none fixed top-4 right-4 z-50 flex w-80 max-w-full flex-col gap-2">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const TYPE_STYLES: Record<ToastType, { ring: string; icon: ReactNode; bg: string }> = {
  success: {
    ring: "ring-green-200",
    bg: "bg-white",
    icon: <CheckCircle2 className="h-4 w-4 text-green-600" />,
  },
  error: {
    ring: "ring-red-200",
    bg: "bg-white",
    icon: <AlertCircle className="h-4 w-4 text-red-600" />,
  },
  info: {
    ring: "ring-slate-200",
    bg: "bg-white",
    icon: <Info className="h-4 w-4 text-slate-600" />,
  },
};

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: () => void;
}) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setShow(true));
    return () => cancelAnimationFrame(t);
  }, []);
  const s = TYPE_STYLES[toast.type];
  return (
    <div
      className={`pointer-events-auto flex items-start gap-2 rounded-md ${s.bg} px-3 py-2 text-sm shadow-md ring-1 ${s.ring} transition-all duration-200 ${
        show ? "translate-x-0 opacity-100" : "translate-x-2 opacity-0"
      }`}
    >
      <div className="mt-0.5">{s.icon}</div>
      <div className="flex-1 text-slate-800">{toast.message}</div>
      <button
        onClick={onDismiss}
        className="ml-1 rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
