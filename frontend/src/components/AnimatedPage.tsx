import { ReactNode, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

/** Fades the routed content in on every route change. */
export default function AnimatedPage({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [show, setShow] = useState(false);

  useEffect(() => {
    setShow(false);
    const id = requestAnimationFrame(() => setShow(true));
    return () => cancelAnimationFrame(id);
  }, [location.pathname]);

  return (
    <div
      style={{
        opacity: show ? 1 : 0,
        transition: "opacity 0.15s ease",
      }}
    >
      {children}
    </div>
  );
}
