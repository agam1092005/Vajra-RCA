export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface EvidenceItem {
  kind: "confirmed" | "correlated" | "missing";
  text: string;
  source: string;
  weight_component: string;
}

export interface Recommendation {
  action: string;
  tier: "diagnostic" | "low_risk" | "high_impact";
  reason: string;
  requires_human_approval: boolean;
}

export interface Hypothesis {
  root_cause: string;
  kind: string;
  confidence: number;
  score_breakdown: Record<string, number>;
  confirmed_evidence: EvidenceItem[];
  correlated_signals: EvidenceItem[];
  missing_evidence: EvidenceItem[];
  recommendations: Recommendation[];
  rank: number;
  explanation?: string;
  signature?: {
    label: string;
    mitre_id: string;
    mitre_name: string;
    matched_features: string[];
    sentence: string;
  };
  attribution?: { feature: string; value: number; baseline: number; z: number }[];
}

export interface Attribution {
  method: "shap" | "baseline_deviation";
  features: { feature: string; contribution: number; value: number; baseline: number }[];
  signature: {
    label: string;
    mitre_id: string;
    mitre_name: string;
    matched_features: string[];
    sentence: string;
  };
}

export interface TimelineItem {
  timestamp: number;
  time: string;
  type: string;
  node: string;
  severity: Severity;
  text: string;
  source: string;
}

export interface Incident {
  incident_id: string;
  focal_node: string;
  title: string;
  severity: Severity;
  window_start: number;
  window_end: number;
  detected_at: number;
  summary: string;
  hypotheses: Hypothesis[];
  timeline: TimelineItem[];
  blast_radius: { impacted: string[]; count: number; depth: number; levels?: string[][] };
  signal_counts: Record<string, number>;
  status: string;
  explanation?: Explanation;
  report_url?: string;
}

export interface IncidentSummary {
  incident_id: string;
  focal_node: string;
  title: string;
  severity: Severity;
  status: string;
  detected_at: number;
  top_cause: string;
  top_confidence: number;
}

export interface Explanation {
  what?: string;
  where?: string;
  when?: string;
  why?: string;
  supporting_evidence?: string[];
  missing_evidence?: string[];
  narrative?: string;
  generated_by?: string;
}

export interface Metrics {
  ts: number;
  counters: Record<string, number>;
  rate_per_s: Record<string, number>;
  window_size: number;
  open_incidents: number;
  hot_node: string;
}

export interface AgentStep {
  node: string;
  focal_node: string;
  ts: number;
}

export interface TopologyData {
  nodes: { id: string; role: string; flows: number }[];
  edges: { source: string; target: string; flows: number; attack_flows: number; service: string }[];
}
