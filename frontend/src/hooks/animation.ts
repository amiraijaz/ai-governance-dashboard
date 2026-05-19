import { useEffect, useState, type CSSProperties } from "react";

/** Smoothly animate a number from 0 to `target` over `duration` ms. */
export function useCountUp(target: number, duration = 800): number {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (Number.isNaN(target)) return;
    if (target === 0) {
      setValue(0);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const ease = (t: number) => 1 - Math.pow(1 - t, 3); // easeOutCubic

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const current = target * ease(t);
      setValue(current);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);

  return value;
}

/** Returns inline style for a staggered fade-up animation that runs on mount. */
export function useFadeIn(delayMs = 0): CSSProperties {
  return {
    opacity: 0,
    transform: "translateY(12px)",
    animation: `vigilFadeUp 0.45s cubic-bezier(0.16, 1, 0.3, 1) ${delayMs}ms forwards`,
  };
}
