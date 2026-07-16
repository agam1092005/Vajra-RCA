"use client";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  GitCommitHorizontal,
  Network,
  Send,
  Sparkles,
  Radius,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Attribution, Explanation, Hypothesis, Incident } from "@/lib/types";
import { ConfidenceBar, ExpandButton, SeverityBadge, TierBadge } from "./ui";

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
          <li key={i} className="rounded-md bg-[var(--panel)] p-2 text-xs leading-snug text-[var(--text)]">
            {e.text}
            {e.source && <span className="mono ml-1 text-[10px] text-[var(--muted)]">· {e.source}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function HypothesisCard({
  h,
  incidentId,
  savedVote,
}: {
  h: Hypothesis;
  incidentId: string;
  savedVote: boolean | null;
}) {
  const top = h.rank === 1;
  const [vote, setVote] = useState<boolean | null>(savedVote);
  const [saving, setSaving] = useState(false);

  // Saved votes load asynchronously (after this card may have mounted) — adopt
  // the persisted vote once it arrives.
  useEffect(() => {
    setVote(savedVote);
  }, [savedVote]);

  const sendVote = async (isCorrect: boolean) => {
    const next = vote === isCorrect ? null : isCorrect; // toggle off if re-clicked
    if (next === null) return; // keep it simple: a vote can be flipped, not cleared
    setSaving(true);
    setVote(isCorrect); // optimistic
    try {
      await api.submitFeedback(incidentId, {
        hypothesis_rank: h.rank,
        hypothesis_kind: h.kind,
        root_cause: h.root_cause,
        is_correct: isCorrect,
      });
    } catch (err) {
      console.error("Feedback submit failed", err);
      setVote(savedVote); // revert on failure
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className={`rounded-xl border p-4 ${top ? "border-[var(--accent-2)] bg-[var(--panel-2)]" : "border-[var(--border)] bg-[var(--panel)]"}`}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="mono rounded-md bg-[var(--bg)] px-1.5 py-0.5 text-xs font-bold text-[var(--accent)]">
            #{h.rank}
          </span>
          <span className="font-semibold text-[var(--text)]">{h.root_cause}</span>
        </div>
        <span className="mono rounded bg-[var(--bg)] px-1.5 py-0.5 text-[10px] uppercase text-[var(--muted)]">
          {h.kind.replace(/_/g, " ")}
        </span>
      </div>
      <div className="mb-3">
        <ConfidenceBar value={h.confidence} />
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {Object.entries(h.score_breakdown).map(([k, v]) => (
          <span key={k} className="mono rounded bg-[var(--bg)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
            {k.replace(/_/g, " ")}{" "}
            <span className={v >= 0 ? "text-[var(--accent)]" : "text-red-400"}>
              {v >= 0 ? "+" : ""}{v}
            </span>
          </span>
        ))}
      </div>
      {h.signature?.mitre_id && (
        <div className="mb-3 flex items-center gap-2">
          <span className="mono rounded bg-[var(--bg)] px-1.5 py-0.5 text-[10px] font-bold text-red-400">
            MITRE {h.signature.mitre_id}
          </span>
          <span className="text-[11px] text-[var(--muted)]">{h.signature.mitre_name}</span>
        </div>
      )}
      {h.attribution && h.attribution.length > 0 && (
        <div className="mb-3">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Why this flow is anomalous — feature attribution
          </div>
          <div className="space-y-1">
            {h.attribution.map((a) => {
              const mag = Math.min(100, Math.abs(a.z) * 20);
              const up = a.z >= 0;
              return (
                <div key={a.feature} className="flex items-center gap-2 text-[11px]">
                  <span className="mono w-28 shrink-0 text-[var(--muted)]">{a.feature}</span>
                  <div className="relative h-2 flex-1 rounded bg-[var(--bg)]">
                    <div
                      className="absolute top-0 h-2 rounded"
                      style={{ width: `${mag}%`, background: up ? "var(--accent)" : "var(--muted)" }}
                    />
                  </div>
                  <span className="mono w-32 shrink-0 text-right text-[var(--text)]">
                    {a.z >= 0 ? "+" : ""}{a.z}σ · obs {a.value}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="mb-3 flex flex-col gap-3 sm:flex-row">
        <EvidenceColumn
          title="Confirmed"
          color="var(--accent)"
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
          color="var(--muted)"
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
              <li key={i} className="flex items-start gap-2 text-xs text-[var(--text)]">
                <TierBadge tier={r.tier} />
                <span>
                  {r.action}
                  {r.requires_human_approval && (
                    <span className="ml-1 text-[10px] font-semibold text-[var(--accent)]">· needs approval</span>
                  )}
                  <span className="block text-[11px] text-[var(--muted)]">{r.reason}</span>
                  {r.warning && (
                    <span className="block text-[10px] font-semibold text-red-400 mt-0.5 animate-pulse">
                      ⚠️ {r.warning}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-3 flex items-center gap-2 border-t border-[var(--border)] pt-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          Was this RCA correct?
        </span>
        <button
          type="button"
          disabled={saving}
          onClick={() => sendVote(true)}
          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition disabled:opacity-50 ${
            vote === true
              ? "border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--accent)]"
              : "border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
          }`}
        >
          <ThumbsUp size={13} /> Correct RCA
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => sendVote(false)}
          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition disabled:opacity-50 ${
            vote === false
              ? "border-red-400 bg-red-400/15 text-red-400"
              : "border-[var(--border)] text-[var(--muted)] hover:border-red-400 hover:text-red-400"
          }`}
        >
          <ThumbsDown size={13} /> Wrong RCA
        </button>
        {vote !== null && (
          <span className="text-[10px] text-[var(--muted)]">
            Recorded — will tune future ranking on this node.
          </span>
        )}
      </div>
    </div>
  );
}

export function IncidentDetail({
  id,
  liveBusinessImpact,
  wide = false,
  expanded = false,
  onToggleExpand,
}: {
  id: string;
  liveBusinessImpact?: any;
  wide?: boolean;
  expanded?: boolean;
  onToggleExpand?: () => void;
}) {
  const [inc, setInc] = useState<Incident | null>(null);
  const [expl, setExpl] = useState<Explanation | null>(null);
  const [loadingExpl, setLoadingExpl] = useState(false);
  const [chat, setChat] = useState<{ q: string; a: string }[]>([]);
  const [question, setQuestion] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [similar, setSimilar] = useState<{ title: string; text: string; source: string; related_nodes: string[]; upstream: string[]; blast_radius: number }[] | null>(null);
  const [loadingSimilar, setLoadingSimilar] = useState(false);
  const [attr, setAttr] = useState<Attribution | null>(null);
  const [loadingAttr, setLoadingAttr] = useState(false);
  const [feedbackByRank, setFeedbackByRank] = useState<Record<number, boolean>>({});

  useEffect(() => {
    setInc(null);
    setExpl(null);
    setChat([]);
    setSimilar(null);
    setAttr(null);
    setFeedbackByRank({});
    api.getFeedback(id)
      .then((rows) =>
        setFeedbackByRank(
          Object.fromEntries(rows.map((f) => [f.hypothesis_rank, f.is_correct]))
        )
      )
      .catch(console.error);
    api.incident(id).then((d) => {
      setInc(d);
      setExpl(d.explanation ?? null);
      
      setLoadingAttr(true);
      api.attribution(id)
        .then(setAttr)
        .catch(console.error)
        .finally(() => setLoadingAttr(false));
    });
  }, [id]);

  const fetchAttr = async () => {
    setLoadingAttr(true);
    try {
      setAttr(await api.attribution(id));
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingAttr(false);
    }
  };

  const fetchSimilar = async () => {
    setLoadingSimilar(true);
    try {
      setSimilar(await api.similar(id));
    } catch (e) {
      console.error(e);
      setSimilar([]);
    } finally {
      setLoadingSimilar(false);
    }
  };

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
    <div className={`flex flex-col ${wide ? "" : "h-full"}`}>
      <div
        className={`border-b border-[var(--border)] p-4 ${
          wide ? "sticky top-0 z-10 rounded-t-xl bg-[var(--panel)]/95 backdrop-blur-md" : ""
        }`}
      >
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <SeverityBadge severity={inc.severity} />
          <span className="mono text-[11px] text-[var(--muted)]">#{inc.incident_id}</span>
          <span className="rounded bg-[var(--panel-2)] px-1.5 py-0.5 text-[10px] uppercase text-[var(--muted)] border border-[var(--border)]">
            {inc.status}
          </span>
          {inc.report_url ? (
            <a
              href={inc.report_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mono rounded bg-[var(--panel-2)] hover:bg-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--text)] flex items-center gap-1 transition border border-[var(--border)]"
            >
              Download PDF Report
            </a>
          ) : (
            <button
              onClick={generateReport}
              disabled={generatingReport}
              className="mono rounded border border-[var(--border)] bg-[var(--panel-2)] hover:bg-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--text)] disabled:opacity-50 transition"
            >
              {generatingReport ? "Generating PDF..." : "Generate PDF Report"}
            </button>
          )}
          {onToggleExpand && (
            <div className="ml-auto">
              <ExpandButton
                expanded={expanded}
                onClick={onToggleExpand}
                title={expanded ? "Exit focus view (Esc)" : "Expand analysis"}
              />
            </div>
          )}
        </div>
        <h2 className={`font-semibold text-[var(--text)] ${wide ? "text-2xl" : "text-lg"}`}>{inc.title}</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">{inc.summary}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          <span className="mono rounded bg-[var(--panel-2)] border border-[var(--border)] px-2 py-1 text-[var(--muted)]">
            focal <span className="text-[var(--text)]">{inc.focal_node}</span>
          </span>
          <span className="mono flex items-center gap-1 rounded bg-[var(--panel-2)] border border-[var(--border)] px-2 py-1 text-[var(--muted)]">
            <Radius size={12} /> blast {inc.blast_radius?.count ?? 0}
          </span>
          {Object.entries(inc.signal_counts).map(([k, v]) => (
            <span key={k} className="mono rounded bg-[var(--panel-2)] border border-[var(--border)] px-2 py-1 text-[var(--muted)]">
              {k.replace(/_/g, " ")} <span className="text-[var(--text)]">{v}</span>
            </span>
          ))}
        </div>
      </div>

      <div
        className={
          wide
            ? "p-6 lg:[column-count:2] lg:[column-gap:1.5rem] [&>*]:mb-6 [&>*]:break-inside-avoid"
            : "min-h-0 flex-1 space-y-4 overflow-auto p-4"
        }
      >
        {(() => {
          const businessImpact = (inc?.business_impact?.status === "degraded" && liveBusinessImpact?.status === "degraded")
            ? { ...inc.business_impact, ...liveBusinessImpact }
            : inc?.business_impact;

          if (!businessImpact || businessImpact.status !== "degraded") return null;

          const protocolImpact = businessImpact.protocol_impact || (() => {
            const successRate = businessImpact.upi_success_rate ?? 99.4;
            const latency = businessImpact.api_latency_ms ?? 85.0;
            const severityFactor = Math.min(1.0, Math.max(0.05, (99.4 - successRate) / 50.0));
            return {
              tcp_loss_pct: Math.round((severityFactor * 2.5) * 100) / 100 || 0.05,
              udp_loss_pct: Math.round((severityFactor * 4.8) * 100) / 100 || 0.12,
              tcp_buffer_delay_ms: Math.round((85.0 + severityFactor * 220.0) * 10) / 10 || 15.2,
              udp_jitter_ms: Math.round((2.1 + severityFactor * 8.5) * 10) / 10 || 2.1,
              avg_tcp_window_size: Math.round(65535 * (1.0 - severityFactor * 0.25)),
              buffer_overflow_risk: (85.0 + severityFactor * 220.0) > 200 ? "critical" : (85.0 + severityFactor * 220.0) > 100 ? "degraded" : "nominal"
            };
          })();

          return (
            <div className="rounded-xl border border-red-500/20 bg-red-950/10 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-red-400">
                  <AlertTriangle size={13} className="text-red-400 animate-pulse" /> Business Impact Analysis
                </span>
                <span className="mono rounded bg-red-900/30 px-2 py-0.5 text-[10px] uppercase font-bold text-red-300">
                  {businessImpact.status}
                </span>
              </div>
              <p className="text-sm leading-relaxed text-red-200">{businessImpact.description}</p>
              
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                  <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">UPI Success Rate</div>
                  <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">{businessImpact.upi_success_rate}%</div>
                </div>
                <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                  <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">Card Auth Rate</div>
                  <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">{businessImpact.card_success_rate}%</div>
                </div>
                <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                  <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">Checkout Latency</div>
                  <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">{businessImpact.api_latency_ms}ms</div>
                </div>
                <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                  <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">Est. Revenue Loss</div>
                  <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">${businessImpact.revenue_loss_per_min}/min</div>
                </div>
              </div>

              {/* Protocol Impact Analysis Section */}
              {protocolImpact && (
                <div className="mt-4 border-t border-red-900/30 pt-3">
                  <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-red-400">
                    <span>Protocol Performance & Buffer Impact</span>
                    <span className={`mono rounded px-1.5 py-0.5 text-[9px] uppercase font-bold ${
                      protocolImpact.buffer_overflow_risk === "critical"
                        ? "bg-red-500/20 text-red-300 border border-red-500/30 animate-pulse"
                        : protocolImpact.buffer_overflow_risk === "degraded"
                        ? "bg-yellow-500/20 text-yellow-300 border border-yellow-500/30"
                        : "bg-green-500/20 text-green-300 border border-green-500/30"
                    }`}>
                      buffer risk: {protocolImpact.buffer_overflow_risk}
                    </span>
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {/* TCP Metrics Column */}
                    <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                      <div className="text-[10px] font-bold text-red-400 uppercase tracking-wide mb-1.5 border-b border-red-900/10 pb-1">TCP Protocol</div>
                      <div className="space-y-1.5 text-xs">
                        <div className="flex justify-between">
                          <span className="text-[var(--muted)]">Packet Drop Rate:</span>
                          <span className="mono text-[var(--text)] font-semibold">{protocolImpact.tcp_loss_pct}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[var(--muted)]">Buffer Delay (RTT):</span>
                          <span className="mono text-[var(--text)] font-semibold">{protocolImpact.tcp_buffer_delay_ms}ms</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[var(--muted)]">Avg Win Size:</span>
                          <span className="mono text-[var(--text)] font-semibold">{(protocolImpact.avg_tcp_window_size / 1024).toFixed(1)} KB</span>
                        </div>
                      </div>
                    </div>

                    {/* UDP Metrics Column */}
                    <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                      <div className="text-[10px] font-bold text-red-400 uppercase tracking-wide mb-1.5 border-b border-red-900/10 pb-1">UDP Protocol</div>
                      <div className="space-y-1.5 text-xs">
                        <div className="flex justify-between">
                          <span className="text-[var(--muted)]">Packet Drop Rate:</span>
                          <span className="mono text-[var(--text)] font-semibold">{protocolImpact.udp_loss_pct}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[var(--muted)]">Jitter:</span>
                          <span className="mono text-[var(--text)] font-semibold">{protocolImpact.udp_jitter_ms}ms</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[var(--muted)]">Stream Status:</span>
                          <span className={`mono font-bold ${protocolImpact.udp_loss_pct > 2.0 ? "text-red-400 animate-pulse" : "text-green-400"}`}>
                            {protocolImpact.udp_loss_pct > 2.0 ? "Unreliable" : "Healthy"}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })()}

        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--accent)]">
              <Sparkles size={13} /> AI explanation
            </span>
            <button
              onClick={explain}
              disabled={loadingExpl}
              className="rounded-md bg-[var(--panel-2)] border border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--text)] hover:bg-[var(--border)] disabled:opacity-50"
            >
              {loadingExpl ? "Generating…" : expl ? "Regenerate" : "Explain"}
            </button>
          </div>
          {expl ? (
            <div>
              <p className="text-sm leading-relaxed text-[var(--text)]">{expl.narrative}</p>
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

        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--text)]">
              <Sparkles size={13} className="text-[var(--accent)]" /> Model Explainability
              {attr && (
                <span
                  className={`ml-1 mono rounded px-1.5 py-0.5 text-[10px] font-bold ${
                    attr.method === "shap"
                      ? "bg-[var(--panel-2)] text-[var(--accent)]"
                      : "bg-[var(--panel-2)] text-[var(--muted)]"
                  }`}
                >
                  {attr.method === "shap" ? "SHAP (model-faithful)" : "baseline-deviation"}
                </span>
              )}
            </div>
            {attr && (
              <button
                onClick={fetchAttr}
                disabled={loadingAttr}
                className="rounded-md bg-[var(--panel-2)] border border-[var(--border)] px-2 py-0.5 text-[10px] font-medium text-[var(--text)] hover:bg-[var(--border)] disabled:opacity-50"
              >
                {loadingAttr ? "Recalculating…" : "Recalculate"}
              </button>
            )}
          </div>

          {loadingAttr && attr === null && (
            <div className="flex items-center gap-2 p-2 text-xs text-[var(--muted)]">
              <div className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
              Computing SHAP feature attribution...
            </div>
          )}

          {attr === null && !loadingAttr && (
            <div className="flex items-center justify-between">
              <p className="text-xs text-[var(--muted)]">
                Compute per-feature attribution for the detector on this node’s anomalous flows.
              </p>
              <button
                onClick={fetchAttr}
                disabled={loadingAttr}
                className="rounded-md bg-[var(--panel-2)] border border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--text)] hover:bg-[var(--border)] disabled:opacity-50"
              >
                Explain detector
              </button>
            </div>
          )}

          {attr && (
            <div className="space-y-3">
              {attr.signature?.mitre_id && (
                <div className="flex items-center gap-2">
                  <span className="mono rounded bg-[var(--bg)] px-1.5 py-0.5 text-[10px] font-bold text-red-400">
                    MITRE {attr.signature.mitre_id}
                  </span>
                  <span className="text-[11px] text-[var(--text)]">{attr.signature.label} — {attr.signature.mitre_name}</span>
                </div>
              )}

              <p className="text-xs text-[var(--muted)] leading-relaxed">
                Feature attribution breakdown shows which network parameters deviated most from the model's normal baseline to trigger the anomaly:
              </p>

              <div className="space-y-2">
                {(() => {
                  const total = attr.features.reduce((sum, f) => sum + Math.abs(f.contribution), 0) || 1;
                  return attr.features.map((f) => {
                    const pct = Math.round((Math.abs(f.contribution) / total) * 100);
                    const isPositive = f.contribution >= 0;
                    return (
                      <div key={f.feature} className="flex flex-col gap-1 rounded-lg bg-[var(--bg)] p-2 border border-[var(--border)]">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="mono font-semibold text-[var(--text)]">{f.feature}</span>
                          <span className="mono text-[var(--muted)] text-[10px]">
                            value: <strong className="text-[var(--text)]">{f.value}</strong> (vs baseline {f.baseline})
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="relative h-2 flex-1 rounded bg-[var(--panel-2)]">
                            <div
                              className="absolute top-0 h-2 rounded"
                              style={{
                                width: `${pct}%`,
                                background: isPositive ? "var(--accent)" : "var(--muted)"
                              }}
                            />
                          </div>
                          <span className="mono w-16 text-right text-xs font-bold text-[var(--text)]">
                            {isPositive ? "+" : ""}{pct}%
                          </span>
                        </div>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>
          )}
        </div>

        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Ranked root-cause hypotheses
          </div>
          <div className="space-y-3">
            {inc.hypotheses.map((h) => (
              <HypothesisCard
                key={h.rank}
                h={h}
                incidentId={id}
                savedVote={h.rank in feedbackByRank ? feedbackByRank[h.rank] : null}
              />
            ))}
          </div>
        </div>

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
                        ? "var(--muted)"
                        : t.type === "security_alert"
                        ? "#ef4444"
                        : t.type === "anomaly"
                        ? "var(--accent)"
                        : "var(--border)",
                  }}
                />
                <div className="flex items-baseline gap-2">
                  <span className="mono text-[11px] text-[var(--muted)]">{t.time}</span>
                  {t.type === "config_change" && <GitCommitHorizontal size={12} className="text-[var(--accent)]" />}
                  <span className="text-xs text-[var(--text)]">{t.text}</span>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
              <BookOpen size={13} /> Similar Runbooks
              <span className="ml-1 text-[10px] text-[var(--muted)]">(GraphRAG: Qdrant + Neo4j)</span>
            </div>
            {similar === null && (
              <button
                onClick={fetchSimilar}
                disabled={loadingSimilar}
                className="flex items-center gap-1 rounded-md bg-[var(--panel-2)] border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--text)] hover:bg-[var(--border)] disabled:opacity-50"
              >
                {loadingSimilar ? "Loading…" : "Search"}
              </button>
            )}
          </div>
          {similar === null && !loadingSimilar && (
            <p className="text-xs text-[var(--muted)]">Click Search to find topology-aware runbooks for this incident.</p>
          )}
          {similar !== null && similar.length === 0 && (
            <p className="text-xs text-[var(--muted)]">No matching runbooks found.</p>
          )}
          {similar !== null && similar.length > 0 && (
            <div className="space-y-2">
              {similar.map((doc, i) => (
                <div key={i} className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-2.5">
                  <div className="mb-1 flex items-start justify-between gap-2">
                    <span className="text-xs font-semibold text-[var(--accent)]">{doc.title}</span>
                    {doc.source && (
                      <span className="mono rounded bg-[var(--bg)] px-1 py-0.5 text-[10px] text-[var(--muted)]">{doc.source}</span>
                    )}
                  </div>
                  <p className="mb-1.5 text-[11px] leading-snug text-[var(--muted)]">{doc.text?.slice(0, 200)}{doc.text?.length > 200 ? "…" : ""}</p>
                  {doc.related_nodes?.length > 0 && (
                    <div className="flex items-center gap-1 flex-wrap">
                      <Network size={11} className="text-[var(--muted)]" />
                      {doc.related_nodes.slice(0, 5).map((n, j) => (
                        <span key={j} className="mono rounded bg-[var(--bg)] px-1 py-0.5 text-[10px] text-[var(--text)]">{n}</span>
                      ))}
                      {doc.blast_radius > 0 && (
                        <span className="mono text-[10px] text-[var(--accent)]">blast={doc.blast_radius}</span>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* chat */}
        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Ask the assistant
          </div>
          <div className="mb-2 space-y-2">
            {chat.map((m, i) => (
              <div key={i} className="text-xs">
                <div className="text-[var(--accent)]">▸ {m.q}</div>
                <div className="whitespace-pre-wrap text-[var(--text)]">{m.a}</div>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask()}
              placeholder="Why is this the most likely cause?"
              className="mono flex-1 rounded-md border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
            />
            <button
              onClick={ask}
              disabled={chatBusy}
              className="flex items-center gap-1 rounded-md bg-[var(--panel-2)] border border-[var(--border)] px-2.5 py-1.5 text-xs text-[var(--text)] hover:bg-[#3f3f46] disabled:opacity-50"
            >
              <Send size={13} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
