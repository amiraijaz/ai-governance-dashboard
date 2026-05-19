import { ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  loading?: boolean;
}

export default function AuthSubmit({
  loading,
  children,
  disabled,
  className = "",
  ...rest
}: Props) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={`group flex w-full items-center justify-center gap-2 rounded-md px-3 py-2.5 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      style={{ background: "#1D9E75" }}
      onMouseOver={(e) => {
        if (!disabled && !loading) e.currentTarget.style.background = "#0F6E56";
      }}
      onMouseOut={(e) => {
        e.currentTarget.style.background = "#1D9E75";
      }}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}
