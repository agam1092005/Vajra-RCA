import { Maximize2, Minimize2 } from "lucide-react";
import { SEV_COLOR } from "@/lib/api";

export function ExpandButton({
  expanded,
  onClick,
  title,
}: {
  expanded: boolean;
  onClick: () => void;
  title?: string;
}) {
  const label = title ?? (expanded ? "Collapse" : "Expand");
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--panel-2)] text-[var(--muted)] transition hover:border-[var(--accent)] hover:text-[var(--text)] cursor-pointer"
    >
      {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
    </button>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const c = SEV_COLOR[severity] ?? SEV_COLOR.info;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
      style={{ color: c, background: `color-mix(in oklab, ${c} 16%, transparent)` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      {severity}
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "#ef4444" : pct >= 60 ? "#f97316" : pct >= 40 ? "#eab308" : "#22c55e";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#1b2536]">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="mono w-9 text-right text-xs font-semibold" style={{ color }}>
        {pct}%
      </span>
    </div>
  );
}

export function Section({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`panel flex flex-col ${className}`}>
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <span className="panel-head">{title}</span>
        {right}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
    </div>
  );
}

const TIER_LABEL: Record<string, { label: string; color: string }> = {
  diagnostic: { label: "Diagnostic", color: "#a1a1aa" },
  low_risk: { label: "Low-risk", color: "#22c55e" },
  high_impact: { label: "High-impact", color: "#ef4444" },
};

export function TierBadge({ tier }: { tier: string }) {
  const t = TIER_LABEL[tier] ?? TIER_LABEL.diagnostic;
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ color: t.color, background: `color-mix(in oklab, ${t.color} 15%, transparent)` }}
    >
      {t.label}
    </span>
  );
}
