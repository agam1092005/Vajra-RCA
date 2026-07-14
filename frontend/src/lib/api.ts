import type { Incident, IncidentSummary, Metrics, TopologyData, Explanation, Attribution } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  status: () => j<Record<string, unknown>>("/api/status"),
  metrics: () => j<Metrics>("/api/metrics"),
  topology: (topN = 60) => j<TopologyData>(`/api/topology?top_n=${topN}`),
  incidents: () => j<IncidentSummary[]>("/api/incidents"),
  incident: (id: string) => j<Incident>(`/api/incidents/${id}`),
  attribution: (id: string) =>
    j<Attribution>(`/api/incidents/${id}/attribution`),
  audit: (id: string) =>
    j<{ ts: number; actor: string; action: string; detail: string }[]>(
      `/api/incidents/${id}/audit`
    ),
  similar: (id: string) =>
    j<{ title: string; text: string; source: string; related_nodes: string[]; upstream: string[]; downstream: string[]; blast_radius: number }[]>(
      `/api/incidents/${id}/similar`
    ),
  explain: (id: string) =>
    j<Explanation>(`/api/incidents/${id}/explain`, { method: "POST" }),
  report: (id: string) =>
    j<{ report_url: string }>(`/api/incidents/${id}/report`, { method: "POST" }),
  chat: (id: string, question: string) =>
    j<{ answer: string; generated_by: string }>(`/api/incidents/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  getReplayStatus: () =>
    j<{ active: boolean }>("/api/telemetry/replay/status"),
  toggleReplay: (active: boolean) =>
    j<{ active: boolean }>("/api/telemetry/replay/toggle", {
      method: "POST",
      body: JSON.stringify({ active }),
    }),
  setStatus: (id: string, status: string) =>
    j<{ ok: boolean }>(`/api/incidents/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  injectConfigChange: (node?: string) =>
    j<Incident>("/api/inject/config-change", {
      method: "POST",
      body: JSON.stringify({ node: node ?? null }),
    }),
};

export const SEV_COLOR: Record<string, string> = {
  info: "#64748b",
  low: "#22c55e",
  medium: "#eab308",
  high: "#f97316",
  critical: "#ef4444",
};
