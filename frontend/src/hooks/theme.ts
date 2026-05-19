import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "aigov_theme";

function readStored(): Theme {
  const v = localStorage.getItem(STORAGE_KEY);
  return v === "light" || v === "dark" || v === "system" ? v : "system";
}

function resolveEffective(theme: Theme): "light" | "dark" {
  if (theme !== "system") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function apply(effective: "light" | "dark") {
  const root = document.documentElement;
  if (effective === "dark") root.setAttribute("data-theme", "dark");
  else root.removeAttribute("data-theme");
}

/** Apply the persisted theme as early as possible, before React mounts. */
export function bootstrapTheme(): void {
  apply(resolveEffective(readStored()));
}

/** Hook for reading and updating the theme preference. */
export function useTheme(): {
  theme: Theme;
  effective: "light" | "dark";
  setTheme: (t: Theme) => void;
} {
  const [theme, setThemeState] = useState<Theme>(readStored);
  const [effective, setEffective] = useState<"light" | "dark">(() =>
    resolveEffective(readStored())
  );

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, theme);
    const eff = resolveEffective(theme);
    setEffective(eff);
    apply(eff);
  }, [theme]);

  // Re-resolve when the OS preference flips and the user is on "system".
  useEffect(() => {
    if (theme !== "system") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const eff = resolveEffective("system");
      setEffective(eff);
      apply(eff);
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [theme]);

  return { theme, effective, setTheme: setThemeState };
}
