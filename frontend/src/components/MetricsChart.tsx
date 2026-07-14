"use client";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface RatePoint {
  t: number;
  flows: number;
  anomalies: number;
  alerts: number;
}

export function MetricsChart({ data }: { data: RatePoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={150}>
      <AreaChart data={data} margin={{ top: 6, right: 6, left: -22, bottom: 0 }}>
        <defs>
          <linearGradient id="gFlows" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#a1a1aa" stopOpacity={0.4} />
            <stop offset="100%" stopColor="#a1a1aa" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gAnom" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f97316" stopOpacity={0.6} />
            <stop offset="100%" stopColor="#f97316" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="t" hide />
        <YAxis stroke="#4b5563" fontSize={10} tickLine={false} axisLine={false} width={34} />
        <Tooltip
          contentStyle={{
            background: "var(--panel)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            fontSize: 12,
          }}
          labelFormatter={() => ""}
        />
        <Area
          type="monotone"
          dataKey="flows"
          stroke="#a1a1aa"
          strokeWidth={1.5}
          fill="url(#gFlows)"
          name="flows/s"
          isAnimationActive={false}
        />
        <Area
          type="monotone"
          dataKey="anomalies"
          stroke="#f97316"
          strokeWidth={1.5}
          fill="url(#gAnom)"
          name="anomalies/s"
          isAnimationActive={false}
        />
        <Area
          type="monotone"
          dataKey="alerts"
          stroke="#ef4444"
          strokeWidth={1.5}
          fillOpacity={0}
          name="alerts/s"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
