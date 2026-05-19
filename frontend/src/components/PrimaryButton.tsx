import { ButtonHTMLAttributes, MouseEvent, useState } from "react";

interface Ripple {
  id: number;
  x: number;
  y: number;
  size: number;
}

export default function PrimaryButton({
  children,
  onClick,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  const [ripples, setRipples] = useState<Ripple[]>([]);

  function handleClick(e: MouseEvent<HTMLButtonElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const r: Ripple = {
      id: Date.now() + Math.random(),
      x: e.clientX - rect.left - size / 2,
      y: e.clientY - rect.top - size / 2,
      size,
    };
    setRipples((prev) => [...prev, r]);
    setTimeout(() => {
      setRipples((prev) => prev.filter((p) => p.id !== r.id));
    }, 600);
    onClick?.(e);
  }

  return (
    <button {...rest} onClick={handleClick} className={`btn-primary ${className}`}>
      {children}
      {ripples.map((r) => (
        <span
          key={r.id}
          className="ripple"
          style={{
            left: r.x,
            top: r.y,
            width: r.size,
            height: r.size,
          }}
        />
      ))}
    </button>
  );
}
