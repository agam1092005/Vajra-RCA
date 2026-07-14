"use client";
import { useMemo } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { TopologyData } from "@/lib/types";

const ROLE_COLOR: Record<string, string> = {
  web: "#a1a1aa",
  dns: "#a78bfa",
  database: "#f472b6",
  cache: "#f59e0b",
  mail: "#34d399",
  ssh: "#71717a",
  ftp: "#94a3b8",
  router: "#eab308",
  host: "#64748b",
};

function layout(
  data: TopologyData,
  focal?: string,
  impacted?: Set<string>
): { nodes: Node[]; edges: Edge[] } {
  const ids = data.nodes.map((n) => n.id);
  const focalIdx = focal ? ids.indexOf(focal) : -1;
  const R = 300;
  const cx = 340;
  const cy = 230;

  const pos = new Map<string, { x: number; y: number }>();
  // focal at center, impacted on inner ring, rest on outer ring
  const inner = data.nodes.filter((n) => impacted?.has(n.id) && n.id !== focal);
  const outer = data.nodes.filter((n) => !impacted?.has(n.id) && n.id !== focal);
  inner.forEach((n, i) => {
    const a = (i / Math.max(1, inner.length)) * Math.PI * 2;
    pos.set(n.id, { x: cx + Math.cos(a) * R * 0.42, y: cy + Math.sin(a) * R * 0.42 });
  });
  outer.forEach((n, i) => {
    const a = (i / Math.max(1, outer.length)) * Math.PI * 2 + 0.3;
    pos.set(n.id, { x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R });
  });
  if (focal) pos.set(focal, { x: cx, y: cy });

  const maxFlows = Math.max(1, ...data.nodes.map((n) => n.flows));
  const nodes: Node[] = data.nodes.map((n) => {
    const isFocal = n.id === focal;
    const isImpacted = impacted?.has(n.id);
    const size = 26 + Math.round((n.flows / maxFlows) * 22);
    const base = ROLE_COLOR[n.role] ?? ROLE_COLOR.host;
    const border = isFocal ? "#ef4444" : isImpacted ? "#f59e0b" : "#22304a";
    return {
      id: n.id,
      position: pos.get(n.id) ?? { x: Math.random() * 600, y: Math.random() * 400 },
      data: { label: `${n.id.split(".").slice(-2).join(".")}` },
      style: {
        width: size,
        height: size,
        borderRadius: "50%",
        background: `color-mix(in oklab, ${base} 26%, #0e141f)`,
        border: `2px solid ${border}`,
        color: "#cfe0f2",
        fontSize: 9,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: isFocal
          ? "0 0 0 4px rgba(239,68,68,.18)"
          : isImpacted
          ? "0 0 0 3px rgba(245,158,11,.15)"
          : "none",
      },
    };
  });
  void focalIdx;

  const edges: Edge[] = data.edges.map((e, i) => {
    const attack = e.attack_flows > 0;
    const inBlast = impacted?.has(e.source) || e.source === focal || e.target === focal;
    return {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      animated: attack || Boolean(inBlast),
      style: {
        stroke: attack ? "#ef4444" : inBlast ? "#f59e0b" : "#1f2c40",
        strokeWidth: attack ? 1.6 : 1,
        opacity: attack || inBlast ? 0.9 : 0.4,
      },
    };
  });
  return { nodes, edges };
}

export function TopologyGraph({
  data,
  focal,
  impacted,
}: {
  data: TopologyData;
  focal?: string;
  impacted?: string[];
}) {
  const impactedSet = useMemo(() => new Set(impacted ?? []), [impacted]);
  const { nodes, edges } = useMemo(
    () => layout(data, focal, impactedSet),
    [data, focal, impactedSet]
  );

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.2}
      >
        <Background color="#16202f" gap={22} />
        <Controls showInteractive={false} className="!bg-[#0e141f] !border-[#1e293b]" />
      </ReactFlow>
    </div>
  );
}
