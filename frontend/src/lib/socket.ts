"use client";
import { useEffect, useRef, useState } from "react";
import { io, Socket } from "socket.io-client";
import { API_BASE } from "./api";

type Handlers = {
  onMetrics?: (m: unknown) => void;
  onIncident?: (i: unknown) => void;
  onAlert?: (a: unknown) => void;
  onAnomaly?: (a: unknown) => void;
  onConfigChange?: (c: unknown) => void;
  onAgentStep?: (s: unknown) => void;
};

export function useSocket(handlers: Handlers) {
  const [connected, setConnected] = useState(false);
  const ref = useRef<Socket | null>(null);
  const h = useRef(handlers);
  h.current = handlers;

  useEffect(() => {
    const socket = io(API_BASE, { transports: ["websocket", "polling"] });
    ref.current = socket;
    socket.on("connect", () => setConnected(true));
    socket.on("disconnect", () => setConnected(false));
    socket.on("metrics", (d) => h.current.onMetrics?.(d));
    socket.on("incident", (d) => h.current.onIncident?.(d));
    socket.on("alert", (d) => h.current.onAlert?.(d));
    socket.on("anomaly", (d) => h.current.onAnomaly?.(d));
    socket.on("config_change", (d) => h.current.onConfigChange?.(d));
    socket.on("agent_step", (d) => h.current.onAgentStep?.(d));
    return () => {
      socket.close();
    };
  }, []);

  return { connected };
}
