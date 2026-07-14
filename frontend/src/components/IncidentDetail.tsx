"use client";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  GitCommitHorizontal,
  Send,
  Sparkles,
  Radius,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Explanation, Hypothesis, Incident } from "@/lib/types";
import { ConfidenceBar, SeverityBadge, TierBadge } from "./ui";

function EvidenceColumn({
  title,
  icon,
  color,
  items,
}: {
  title: string;
  icon: React.ReactNode;
  color: string;
  items: { text: string; source: string }[];
}) {
  return (
    <div className="flex-1">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color }}>
        {icon} {title} <span className="text-[var(--muted)]">({items.length})</span>
      </div>
      <ul className="space-y-1.5">
        {items.length === 0 && <li className="text-xs text-[var(--muted)]">—</li>}
        {items.map((e, i) => (
          <li key={i} className="rounded-md bg-[#0b111b] p-2 text-xs leading-snug text-[#c6d4e6]">
            {e.text}
            {e.source && <span className="mono ml-1 text-[10px] text-[var(--muted)]">· {e.source}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function HypothesisCard({ h }: { h: Hypothesis }) {
  const top = h.rank === 1;
  return (
    <div
      className={`rounded-xl border p-4 ${top ? "border-[#33507a] bg-[#0f1826]" : "border-[var(--border)] bg-[#0b111b]"}`}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="mono rounded-md bg-[#1b2536] px-1.5 py-0.5 text-xs font-bold text-[var(--accent)]">
            #{h.rank}
          </span>
          <span className="font-semibold text-[#e9f1fb]">{h.root_cause}</span>
        </div>
        <span className="mono rounded bg-[#131b28] px-1.5 py-0.5 text-[10px] uppercase text-[var(--muted)]">
          {h.kind.replace(/_/g, " ")}
        </span>
      </div>
      <div className="mb-3">
        <ConfidenceBar value={h.confidence} />
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {Object.entries(h.score_breakdown).map(([k, v]) => (
          <span key={k} className="mono rounded bg-[#131b28] px-1.5 py-0.5 text-[10px] text-[#9fb4cc]">
            {k.replace(/_/g, " ")} <span className="text-[var(--accent)]">+{v}</span>
          </span>
        ))}
      </div>
      <div className="mb-3 flex flex-col gap-3 sm:flex-row">
        <EvidenceColumn
          title="Confirmed"
          color="#34d399"
          icon={<CheckCircle2 size={13} />}
          items={h.confirmed_evidence}
        />
        <EvidenceColumn
          title="Correlated"
          color="#eab308"
          icon={<AlertTriangle size={13} />}
          items={h.correlated_signals}
        />
        <EvidenceColumn
          title="Missing"
          color="#8397ad"
          icon={<CircleHelp size={13} />}
          items={h.missing_evidence}
        />
      </div>
      {h.recommendations.length > 0 && (
        <div className="border-t border-[var(--border)] pt-2">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Recommended next steps
          </div>
          <ul className="space-y-1.5">
            {h.recommendations.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-[#cfdcec]">
                <TierBadge tier={r.tier} />
                <span>
                  {r.action}
                  {r.requires_human_approval && (
                    <span className="ml-1 text-[10px] font-semibold text-[#f97316]">· needs approval</span>
                  )}
                  <span className="block text-[11px] text-[var(--muted)]">{r.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function IncidentDetail({ id }: { id: string }) {
  const [inc, setInc] = useState<Incident | null>(null);
  const [expl, setExpl] = useState<Explanation | null>(null);
  const [loadingExpl, setLoadingExpl] = useState(false);
  const [chat, setChat] = useState<{ q: string; a: string }[]>([]);
  const [question, setQuestion] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [generatingReport, setGeneratingReport] = useState(false);

  useEffect(() => {
    setInc(null);
    setExpl(null);
    setChat([]);
    api.incident(id).then((d) => {
      setInc(d);
      setExpl(d.explanation ?? null);
    });
  }, [id]);

  const generateReport = async () => {
    setGeneratingReport(true);
    try {
      const res = await api.report(id);
      if (res.report_url) {
        setInc(prev => prev ? { ...prev, report_url: res.report_url } : null);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setGeneratingReport(false);
    }
  };

  if (!inc) return <div className="p-6 text-sm text-[var(--muted)]">Loading incident…</div>;

  const explain = async () => {
    setLoadingExpl(true);
    try {
      setExpl(await api.explain(id));
    } finally {
      setLoadingExpl(false);
    }
  };

  const ask = async () => {
    if (!question.trim()) return;
    const q = question.trim();
    setQuestion("");
    setChatBusy(true);
    setChat((c) => [...c, { q, a: "…" }]);
    try {
      const res = await api.chat(id, q);
      setChat((c) => c.map((m, i) => (i === c.length - 1 ? { q, a: res.answer } : m)));
    } finally {
      setChatBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <div className="border-b border-[var(--border)] p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <SeverityBadge severity={inc.severity} />
          <span className="mono text-[11px] text-[var(--muted)]">#{inc.incident_id}</span>
          <span className="rounded bg-[#131b28] px-1.5 py-0.5 text-[10px] uppercase text-[var(--muted)]">
            {inc.status}
          </span>
          {inc.report_url ? (
            <a
              href={inc.report_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mono rounded bg-[#1e293b] hover:bg-[#334155] px-2 py-0.5 text-[10px] text-[#38bdf8] flex items-center gap-1 transition"
            >
              Download PDF Report
            </a>
          ) : (
            <button
              onClick={generateReport}
              disabled={generatingReport}
              className="mono rounded bg-[#1e293b] hover:bg-[#334155] px-2 py-0.5 text-[10px] text-[var(--muted)] disabled:opacity-50 transition"
            >
              {generatingReport ? "Generating PDF..." : "Generate PDF Report"}
            </button>
          )}
        </div>
        <h2 className="text-lg font-semibold text-[#eef4fb]">{inc.title}</h2>
        <p className="mt-1 text-sm text-[#a9bbd0]">{inc.summary}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          <span className="mono rounded bg-[#0b111b] px-2 py-1 text-[#9fb4cc]">
            focal <span className="text-[#e6edf6]">{inc.focal_node}</span>
          </span>
          <span className="mono flex items-center gap-1 rounded bg-[#0b111b] px-2 py-1 text-[#9fb4cc]">
            <Radius size={12} /> blast {inc.blast_radius?.count ?? 0}
          </span>
          {Object.entries(inc.signal_counts).map(([k, v]) => (
            <span key={k} className="mono rounded bg-[#0b111b] px-2 py-1 text-[#9fb4cc]">
              {k.replace(/_/g, " ")} <span className="text-[#e6edf6]">{v}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {/* AI explanation */}
        <div className="rounded-xl border border-[#2a3b58] bg-gradient-to-b from-[#101a2b] to-[#0c1420] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--accent)]">
              <Sparkles size={13} /> AI explanation
            </span>
            <button
              onClick={explain}
              disabled={loadingExpl}
              className="rounded-md bg-[#1c2b44] px-2.5 py-1 text-xs font-medium text-[#cfe0f2] hover:bg-[#233650] disabled:opacity-50"
            >
              {loadingExpl ? "Generating…" : expl ? "Regenerate" : "Explain"}
            </button>
          </div>
          {expl ? (
            <div>
              <p className="text-sm leading-relaxed text-[#dbe7f4]">{expl.narrative}</p>
              <span className="mono mt-2 block text-[10px] text-[var(--muted)]">
                generated by {expl.generated_by}
              </span>
            </div>
          ) : (
            <p className="text-sm text-[var(--muted)]">
              Generate a natural-language operator summary (what / where / when / why / evidence).
            </p>
          )}
        </div>

        {/* hypotheses */}
        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Ranked root-cause hypotheses
          </div>
          <div className="space-y-3">
            {inc.hypotheses.map((h) => (
              <HypothesisCard key={h.rank} h={h} />
            ))}
          </div>
        </div>

        {/* timeline */}
        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Incident timeline
          </div>
          <ol className="relative ml-2 border-l border-[var(--border)]">
            {inc.timeline.map((t, i) => (
              <li key={i} className="mb-2.5 ml-4">
                <span
                  className="absolute -left-[5px] mt-1 h-2 w-2 rounded-full"
                  style={{
                    background:
                      t.type === "config_change"
                        ? "#38bdf8"
                        : t.type === "security_alert"
                        ? "#ef4444"
                        : t.type === "anomaly"
                        ? "#f97316"
                        : "#3a4a63",
                  }}
                />
                <div className="flex items-baseline gap-2">
                  <span className="mono text-[11px] text-[var(--muted)]">{t.time}</span>
                  {t.type === "config_change" && <GitCommitHorizontal size={12} className="text-[var(--accent)]" />}
                  <span className="text-xs text-[#cfdcec]">{t.text}</span>
                </div>
              </li>
            ))}
          </ol>
        </div>

        {/* chat */}
        <div className="rounded-xl border border-[var(--border)] bg-[#0b111b] p-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Ask the assistant
          </div>
          <div className="mb-2 space-y-2">
            {chat.map((m, i) => (
              <div key={i} className="text-xs">
                <div className="text-[var(--accent)]">▸ {m.q}</div>
                <div className="whitespace-pre-wrap text-[#cfdcec]">{m.a}</div>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask()}
              placeholder="Why is this the most likely cause?"
              className="mono flex-1 rounded-md border border-[var(--border)] bg-[#070b12] px-2.5 py-1.5 text-xs text-[#e6edf6] outline-none focus:border-[var(--accent)]"
            />
            <button
              onClick={ask}
              disabled={chatBusy}
              className="flex items-center gap-1 rounded-md bg-[#1c2b44] px-2.5 py-1.5 text-xs text-[#cfe0f2] hover:bg-[#233650] disabled:opacity-50"
            >
              <Send size={13} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
