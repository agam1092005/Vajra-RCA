"use client";
import { Check, Loader2 } from "lucide-react";

// The real LangGraph pipeline order (backend/app/agents/graph.py).
// Labels are judge-facing: what each agent is actually doing.
export const AGENT_STAGES: { key: string; label: string }[] = [
  { key: "coordinator", label: "Correlating signals" },
  { key: "metric", label: "Analyzing metrics" },
  { key: "log", label: "Scanning logs" },
  { key: "trace", label: "Following traces" },
  { key: "graph", label: "Traversing topology" },
  { key: "rag", label: "Querying runbooks" },
  { key: "root_cause", label: "Causal inference" },
  { key: "report", label: "Synthesizing report" },
];

/**
 * Live multi-agent progress stepper. Driven by the `agent_step` websocket stream:
 * the pipeline is strictly linear, so the current node implies every prior node is
 * done and every later node is pending. `done` renders the whole chain complete.
 */
export function AgentPipeline({
  currentNode,
  focalNode,
  done = false,
}: {
  currentNode: string | null;
  focalNode?: string | null;
  done?: boolean;
}) {
  const isIdle = !currentNode && !done;
  const currentIndex = done
    ? AGENT_STAGES.length
    : AGENT_STAGES.findIndex((s) => s.key === currentNode);

  return (
    <div className="border-b border-[var(--border)] bg-[#0f0f11] px-5 py-2.5">
      <div className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
        <span className="flex items-center gap-1.5 text-[var(--accent)]">
          {isIdle ? (
            <span className="h-2 w-2 rounded-full bg-[var(--muted)] animate-pulse" />
          ) : done ? (
            <Check size={13} />
          ) : (
            <Loader2 size={13} className="animate-spin" />
          )}
          {isIdle
            ? "Diagnostic Pipeline: Standby"
            : done
            ? "Analysis complete"
            : "Multi-agent analysis running"}
        </span>
        {focalNode && <span className="mono normal-case text-[var(--text)]">· {focalNode}</span>}
      </div>
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {AGENT_STAGES.map((stage, i) => {
          const isDone = i < currentIndex;
          const isActive = i === currentIndex && !done;
          return (
            <div key={stage.key} className="flex shrink-0 items-center">
              <div
                className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                  isActive
                    ? "border-[var(--accent)] bg-[var(--panel-2)] text-[var(--text)]"
                    : isDone
                    ? "border-[#14532d] bg-[#0d2418] text-[#4ade80]"
                    : "border-[var(--border)] bg-[var(--panel)] text-[var(--muted)]"
                }`}
              >
                <span className="flex h-4 w-4 items-center justify-center">
                  {isDone ? (
                    <Check size={12} />
                  ) : isActive ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <span className="h-1.5 w-1.5 rounded-full bg-current opacity-50" />
                  )}
                </span>
                <span className={`mono whitespace-nowrap ${isActive ? "font-semibold" : ""}`}>
                  {stage.label}
                </span>
              </div>
              {i < AGENT_STAGES.length - 1 && (
                <span
                  className={`mx-0.5 h-px w-4 shrink-0 ${
                    i < currentIndex ? "bg-[#14532d]" : "bg-[var(--border)]"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
