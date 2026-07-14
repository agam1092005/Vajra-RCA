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
} from "lucide-react";
import { api } from "@/lib/api";
import type { Attribution, Explanation, Hypothesis, Incident } from "@/lib/types";
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
          <li key={i} className="rounded-md bg-[var(--panel)] p-2 text-xs leading-snug text-[var(--text)]">
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
            {k.replace(/_/g, " ")} <span className="text-[var(--accent)]">+{v}</span>
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
  const [similar, setSimilar] = useState<{ title: string; text: string; source: string; related_nodes: string[]; upstream: string[]; blast_radius: number }[] | null>(null);
  const [loadingSimilar, setLoadingSimilar] = useState(false);
  const [attr, setAttr] = useState<Attribution | null>(null);
  const [loadingAttr, setLoadingAttr] = useState(false);

  useEffect(() => {
    setInc(null);
    setExpl(null);
    setChat([]);
    setSimilar(null);
    setAttr(null);
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
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--border)] p-4">
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
        </div>
        <h2 className="text-lg font-semibold text-[var(--text)]">{inc.title}</h2>
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

      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {inc.business_impact && inc.business_impact.status === "degraded" && (
          <div className="rounded-xl border border-red-500/20 bg-red-950/10 p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-red-400">
                <AlertTriangle size={13} className="text-red-400 animate-pulse" /> Business Impact Analysis
              </span>
              <span className="mono rounded bg-red-900/30 px-2 py-0.5 text-[10px] uppercase font-bold text-red-300">
                {inc.business_impact.status}
              </span>
            </div>
            <p className="text-sm leading-relaxed text-red-200">{inc.business_impact.description}</p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">UPI Success Rate</div>
                <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">{inc.business_impact.upi_success_rate}%</div>
              </div>
              <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">Card Auth Rate</div>
                <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">{inc.business_impact.card_success_rate}%</div>
              </div>
              <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">Checkout Latency</div>
                <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">{inc.business_impact.api_latency_ms}ms</div>
              </div>
              <div className="rounded-lg bg-[var(--panel-2)] p-2.5 border border-red-900/20">
                <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-semibold">Est. Revenue Loss</div>
                <div className="mono text-lg font-bold text-[var(--text)] mt-0.5">${inc.business_impact.revenue_loss_per_min}/min</div>
              </div>
            </div>
          </div>
        )}

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
              <HypothesisCard key={h.rank} h={h} />
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
