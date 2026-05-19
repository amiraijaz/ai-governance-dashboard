interface TooltipEntry {
  name?: string;
  value?: number | string;
  color?: string;
}

interface Props {
  active?: boolean;
  label?: string | number;
  payload?: TooltipEntry[];
}

export default function ChartTooltip({ active, payload, label }: Props) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="vigil-tooltip">
      {label !== undefined && <div className="vigil-tooltip-label">{label}</div>}
      {payload.map((p, i) => (
        <div key={i} style={{ display: "flex", gap: 8 }}>
          <span style={{ color: p.color ?? "#64748b" }}>●</span>
          <span style={{ color: "#475569" }}>{p.name}</span>
          <span style={{ marginLeft: "auto", fontWeight: 600 }}>{p.value}</span>
        </div>
      ))}
    </div>
  );
}
