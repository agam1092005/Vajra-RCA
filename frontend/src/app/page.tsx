"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Network, ShieldAlert, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { useSocket } from "@/lib/socket";
import type { AgentStep, Incident, IncidentSummary, Metrics, TopologyData } from "@/lib/types";
import { MetricsChart, type RatePoint } from "@/components/MetricsChart";
import { TopologyGraph } from "@/components/TopologyGraph";
import { IncidentDetail } from "@/components/IncidentDetail";
import { ExpandButton, Section, SeverityBadge } from "@/components/ui";
import { AgentPipeline } from "@/components/AgentPipeline";

function StatTile({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  accent: string;
}) {
  return (
    <div className="panel flex items-center gap-3 px-4 py-3">
      <div
        className="flex h-9 w-9 items-center justify-center rounded-lg"
        style={{ background: `color-mix(in oklab, ${accent} 16%, transparent)`, color: accent }}
      >
        {icon}
      </div>
      <div>
        <div className="mono text-lg font-bold text-[#eef4fb]">{value}</div>
        <div className="text-[11px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [rates, setRates] = useState<RatePoint[]>([]);
  const [topo, setTopo] = useState<TopologyData>({ nodes: [], edges: [] });
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [focalIncident, setFocalIncident] = useState<Incident | null>(null);
  const [injecting, setInjecting] = useState(false);
  const [leftTab, setLeftTab] = useState<"topology" | "grafana">("topology");
  const [detailExpanded, setDetailExpanded] = useState(false);
  const [topoExpanded, setTopoExpanded] = useState(false);
  const rateRef = useRef<RatePoint[]>([]);
  const [agentStep, setAgentStep] = useState<AgentStep | null>(null);
  const agentStepTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [runComplete, setRunComplete] = useState<{ focal: string } | null>(null);
  const runCompleteTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");

  // Simulated Telemetry Source State
  const [replayActive, setReplayActive] = useState(false);

  const handleToggleReplay = async () => {
    const res = await api.toggleReplay(!replayActive);
    setReplayActive(res.active);
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsAuthenticated(localStorage.getItem("authenticated") === "true");
    }
  }, []);

  // Esc collapses any expanded focus view.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDetailExpanded(false);
        setTopoExpanded(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (username === "admin" && password === "admin") {
      localStorage.setItem("authenticated", "true");
      setIsAuthenticated(true);
      setAuthError("");
    } else {
      setAuthError("Invalid operator credentials");
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("authenticated");
    setIsAuthenticated(false);
    setUsername("");
    setPassword("");
  };

  const refreshIncidents = useCallback(async () => {
    const list = await api.incidents();
    setIncidents(list);
    setSelected((s) => s ?? list[0]?.incident_id ?? null);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    api.topology(60).then(setTopo);
    api.metrics().then(setMetrics);
    api.getReplayStatus().then((d) => setReplayActive(d.active));
    refreshIncidents();
  }, [refreshIncidents, isAuthenticated]);

  // keep focal incident (for topology highlight) in sync with selection
  useEffect(() => {
    if (selected) api.incident(selected).then(setFocalIncident);
  }, [selected]);

  const { connected } = useSocket({
    onMetrics: (m) => {
      const mm = m as Metrics;
      setMetrics(mm);
      const pt: RatePoint = {
        t: mm.ts,
        flows: mm.rate_per_s.network_flow ?? 0,
        anomalies: mm.rate_per_s.anomaly ?? 0,
        alerts: mm.rate_per_s.security_alert ?? 0,
      };
      rateRef.current = [...rateRef.current, pt].slice(-40);
      setRates(rateRef.current);
    },
    onIncident: (d) => {
      // run finished: flash the completed pipeline briefly, then hide.
      const focal = (d as Incident)?.focal_node ?? agentStep?.focal_node ?? "";
      setAgentStep(null);
      if (agentStepTimeout.current) clearTimeout(agentStepTimeout.current);
      setRunComplete({ focal });
      if (runCompleteTimeout.current) clearTimeout(runCompleteTimeout.current);
      runCompleteTimeout.current = setTimeout(() => setRunComplete(null), 2500);
      refreshIncidents();
    },
    onAgentStep: (s) => {
      const step = s as AgentStep;
      setRunComplete(null);
      setAgentStep(step);
      if (agentStepTimeout.current) clearTimeout(agentStepTimeout.current);
      // clear if no further step/incident event arrives (e.g. the run errored out)
      agentStepTimeout.current = setTimeout(() => setAgentStep(null), 6000);
    },
  });

  const inject = async () => {
    setInjecting(true);
    try {
      const inc = await api.injectConfigChange();
      await refreshIncidents();
      if (inc?.incident_id) setSelected(inc.incident_id);
    } finally {
      setInjecting(false);
    }
  };

  const c = metrics?.counters ?? {};

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--bg)] text-[var(--text)]">
        <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-8 shadow-2xl backdrop-blur-md">
          <div className="mb-6 text-center">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--panel-2)] text-[var(--accent)] mb-3">
              <Network size={28} />
            </div>
            <h2 className="text-xl font-bold tracking-tight text-[var(--text)]">Vajra RCA Operations</h2>
            <p className="text-xs text-[var(--muted)] mt-1">Sign in with Operator credentials</p>
          </div>
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--muted)] mb-1">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--muted)] mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
                required
              />
            </div>
            {authError && <div className="text-xs font-medium text-red-500">{authError}</div>}
            <button
              type="submit"
              className="w-full rounded-lg bg-[var(--text)] hover:bg-[#e4e4e7] py-2.5 text-sm font-semibold text-[#0f0f11] transition cursor-pointer"
            >
              Sign In
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* header */}
      <header className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--panel-2)] text-[var(--accent)]">
            <Network size={18} />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight text-[var(--text)]">
              Vajra RCA <span className="text-[var(--muted)]">· Network Anomaly Root-Cause Assistant</span>
            </h1>
            <div className="flex items-center gap-2 text-[11px] text-[var(--muted)]">
              <span className={`live-dot ${connected ? "" : "!bg-[#ef4444]"}`} />
              {connected ? "live" : "reconnecting"}
              {metrics?.hot_node && <span className="mono">· watch {metrics.hot_node}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleLogout}
            className="rounded bg-[#1e293b] hover:bg-[#334155] px-3 py-2 text-xs font-semibold text-[#cfe0f2] transition cursor-pointer"
          >
            Logout
          </button>
          
          {/* Simulated Telemetry Source Toggle */}
          <button
            onClick={handleToggleReplay}
            className={`rounded px-3 py-2 text-xs font-semibold transition cursor-pointer flex items-center gap-1.5 ${
              replayActive
                ? "bg-[#065f46] text-[#a7f3d0] hover:bg-[#047857]"
                : "bg-[#1e293b] text-[#cfe0f2] hover:bg-[#334155]"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${replayActive ? "bg-[#10b981] animate-pulse" : "bg-[#64748b]"}`} />
            Simulated Telemetry: {replayActive ? "ON" : "OFF"}
          </button>

          <button
            onClick={inject}
            disabled={injecting}
            className="flex items-center gap-2 rounded-lg bg-[#7c2d12] px-3 py-2 text-xs font-semibold text-[#ffd9c2] hover:bg-[#9a3412] disabled:opacity-50 cursor-pointer"
          >
            <Zap size={14} /> {injecting ? "Injecting…" : "Inject Config Change"}
          </button>
        </div>
      </header>

      {/* live multi-agent pipeline stepper */}
      <AgentPipeline
        currentNode={agentStep?.node ?? null}
        focalNode={agentStep?.focal_node ?? runComplete?.focal ?? null}
        done={!agentStep && !!runComplete}
      />

      {/* stat tiles */}
      <div className="p-3 pb-3">
        <div className="mb-2 text-[10px] uppercase font-bold tracking-wider text-[var(--muted)]">Infrastructure Status</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile icon={<Activity size={18} />} label="Flows ingested" value={c.flows ?? 0} accent="#a1a1aa" />
          <StatTile icon={<Zap size={18} />} label="Anomalies" value={c.anomalies ?? 0} accent="#f97316" />
          <StatTile icon={<ShieldAlert size={18} />} label="Security alerts" value={c.alerts ?? 0} accent="#ef4444" />
          <StatTile icon={<Network size={18} />} label="Open incidents" value={metrics?.open_incidents ?? 0} accent="#34d399" />
        </div>
      </div>



      {/* main grid */}
      <div className="grid min-h-0 flex-1 grid-cols-12 gap-3 p-3 pt-0">
        {/* left: metrics + topology */}
        <div className="col-span-12 flex min-h-0 flex-col gap-3 lg:col-span-4">
          <Section title="Live signal rate (/s)" className="h-[210px]">
            <MetricsChart data={rates} />
          </Section>
          {topoExpanded && (
            <div
              className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm"
              onClick={() => setTopoExpanded(false)}
            />
          )}
          <Section
            title={leftTab === "topology" ? "Dependency topology" : "Grafana Observability"}
            className={topoExpanded ? "fixed inset-3 z-50 sm:inset-6" : "min-h-0 flex-1"}
            right={
              <div className="flex items-center gap-2">
                <div className="flex gap-1 bg-[var(--bg)] p-0.5 rounded-lg border border-[var(--border)]">
                  <button
                    onClick={() => setLeftTab("topology")}
                    className={`px-2 py-0.5 text-[10px] rounded font-semibold transition ${
                      leftTab === "topology"
                        ? "bg-[var(--panel-2)] text-[var(--text)]"
                        : "text-[var(--muted)] hover:text-[var(--text)]"
                    }`}
                  >
                    Topology
                  </button>
                  <button
                    onClick={() => setLeftTab("grafana")}
                    className={`px-2 py-0.5 text-[10px] rounded font-semibold transition ${
                      leftTab === "grafana"
                        ? "bg-[var(--panel-2)] text-[var(--text)]"
                        : "text-[var(--muted)] hover:text-[var(--text)]"
                    }`}
                  >
                    Grafana
                  </button>
                </div>
                <ExpandButton
                  expanded={topoExpanded}
                  onClick={() => setTopoExpanded((v) => !v)}
                  title={topoExpanded ? "Exit focus view (Esc)" : "Expand view"}
                />
              </div>
            }
          >
            {leftTab === "topology" ? (
              <TopologyGraph
                data={topo}
                focal={focalIncident?.focal_node}
                impacted={focalIncident?.blast_radius?.impacted}
              />
            ) : (
              <iframe
                src="http://localhost:3001/"
                className="w-full h-full border-0 rounded-lg bg-[var(--panel)]"
                title="Grafana Dashboard"
              />
            )}
          </Section>
        </div>

        {/* middle: incident list */}
        <div className="col-span-12 flex min-h-0 flex-col lg:col-span-3">
          <Section title={`Incidents (${incidents.length})`} className="min-h-0 flex-1">
            <ul className="space-y-2">
              {incidents.length === 0 && (
                <li className="text-xs text-[var(--muted)]">No incidents yet — streaming…</li>
              )}
              {incidents.map((it) => (
                <li key={it.incident_id}>
                  <button
                    onClick={() => setSelected(it.incident_id)}
                    className={`w-full rounded-lg border p-2.5 text-left transition ${
                      selected === it.incident_id
                        ? "border-[var(--accent-2)] bg-[var(--panel-2)]"
                        : "border-[var(--border)] bg-[var(--panel)] hover:border-[#52525b]"
                    }`}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <SeverityBadge severity={it.severity} />
                      <span className="mono text-[10px] text-[var(--muted)]">
                        {Math.round((it.top_confidence ?? 0) * 100)}%
                      </span>
                    </div>
                    <div className="line-clamp-2 text-xs font-medium text-[var(--text)]">{it.title}</div>
                    <div className="mono mt-1 text-[10px] text-[var(--muted)]">{it.focal_node}</div>
                  </button>
                </li>
              ))}
            </ul>
          </Section>
        </div>

        <div
          className={
            detailExpanded
              ? "fixed inset-0 z-50 flex flex-col overflow-y-auto bg-black/70 p-3 backdrop-blur-sm sm:p-6"
              : "col-span-12 min-h-0 lg:col-span-5"
          }
          onClick={
            detailExpanded
              ? (e) => {
                  if (e.target === e.currentTarget) setDetailExpanded(false);
                }
              : undefined
          }
        >
          <div
            className={`panel ${
              detailExpanded
                ? "mx-auto w-full max-w-[1500px] overflow-visible"
                : "h-full overflow-hidden"
            }`}
          >
            {selected ? (
              <IncidentDetail
                id={selected}
                liveBusinessImpact={metrics?.business_impact}
                wide={detailExpanded}
                expanded={detailExpanded}
                onToggleExpand={() => setDetailExpanded((v) => !v)}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
                Select an incident
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
