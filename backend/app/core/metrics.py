"""Prometheus-format `/metrics` endpoint.

Exposes a snapshot of REAL runtime state — event counters, detector reports,
topology size, business-impact KPIs, OTel span buffer depth — as Prometheus
gauges/counters, computed fresh at scrape time from `Pipeline.metrics_snapshot()`
and friends. No values here are synthetic: everything mirrors what the
dashboard's `/api/metrics` and `/api/status` endpoints already report; this is
the same state in Prometheus' text exposition format so Grafana/Prometheus can
scrape it (the `vajra-backend` job in `infra/prometheus.yml` already points at
this service — before this endpoint existed, that scrape 404'd).

Not an ML input: the Isolation Forest and Kitsune detectors train on the real
UNSW-NB15 dataset (see `pipeline.py::prepare`), not on Prometheus metrics —
this endpoint is a downstream observability view of the pipeline's state, not
an upstream data source for detection.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from . import tracing

if TYPE_CHECKING:
    from ..pipeline import Pipeline


class VajraCollector:
    """A prometheus_client custom collector: pulls a fresh snapshot of the
    pipeline's real state on every scrape rather than requiring counters to
    be incremented from call sites scattered across the codebase."""

    def __init__(self, pipeline: "Pipeline") -> None:
        self.pipeline = pipeline

    def collect(self):
        with tracing.span("metrics.collect_prometheus"):
            snap = self.pipeline.metrics_snapshot()

            events_total = CounterMetricFamily(
                "vajra_events_total", "Total events observed by type, this process lifetime",
                labels=["event_type"],
            )
            for event_type, count in snap["counters"].items():
                events_total.add_metric([event_type], count)
            yield events_total

            event_rate = GaugeMetricFamily(
                "vajra_event_rate_per_second", "Live event rate by type (10s rolling window)",
                labels=["event_type"],
            )
            for event_type, rate in snap["rate_per_s"].items():
                event_rate.add_metric([event_type], rate)
            yield event_rate

            yield GaugeMetricFamily("vajra_correlation_window_size", "Events currently held in the sliding correlation window", value=snap["window_size"])
            yield GaugeMetricFamily("vajra_open_incidents_total", "Incidents raised this process lifetime", value=snap["open_incidents"])

            bi = snap["business_impact"]
            yield GaugeMetricFamily("vajra_upi_success_rate_pct", "Live UPI payment success rate", value=bi["upi_success_rate"])
            yield GaugeMetricFamily("vajra_card_success_rate_pct", "Live card payment success rate", value=bi["card_success_rate"])
            yield GaugeMetricFamily("vajra_api_checkout_latency_ms", "Live API checkout latency", value=bi["api_latency_ms"])
            yield GaugeMetricFamily("vajra_revenue_loss_per_min_usd", "Estimated revenue loss per minute", value=bi["revenue_loss_per_min"])
            yield GaugeMetricFamily("vajra_business_impact_degraded", "1 if an incident is actively degrading business KPIs", value=1.0 if bi["status"] == "degraded" else 0.0)

            pi = bi["protocol_impact"]
            yield GaugeMetricFamily("vajra_tcp_packet_loss_pct", "Real TCP packet loss computed from flow sloss/dloss", value=pi["tcp_loss_pct"])
            yield GaugeMetricFamily("vajra_udp_packet_loss_pct", "Real UDP packet loss computed from flow sloss/dloss", value=pi["udp_loss_pct"])
            yield GaugeMetricFamily("vajra_tcp_buffer_delay_ms", "Average TCP RTT-derived buffer delay", value=pi["tcp_buffer_delay_ms"])
            yield GaugeMetricFamily("vajra_udp_jitter_ms", "Average UDP jitter (sjit+djit)", value=pi["udp_jitter_ms"])
            yield GaugeMetricFamily("vajra_tcp_window_size_bytes", "Average TCP window size", value=pi["avg_tcp_window_size"])

            kit = snap["kitsune"]
            yield GaugeMetricFamily("vajra_kitsune_enabled", "1 if the Kitsune online detector is active", value=1.0 if kit.get("enabled") else 0.0)
            yield GaugeMetricFamily("vajra_kitsune_packets_seen_total", "Packets processed by Kitsune this process lifetime", value=kit.get("packet_count", 0))
            yield GaugeMetricFamily("vajra_kitsune_anomalies_total", "Anomalies flagged by Kitsune this process lifetime", value=kit.get("anomaly_count", 0))
            yield GaugeMetricFamily("vajra_kitsune_warmed_up", "1 once Kitsune has cleared its grace-period warmup", value=1.0 if kit.get("warmed_up") else 0.0)

            topo_stats = self.pipeline.topology.stats
            yield GaugeMetricFamily("vajra_topology_nodes", "Nodes in the real Neo4j dependency graph", value=topo_stats.get("nodes", 0))
            yield GaugeMetricFamily("vajra_topology_edges", "Edges in the real Neo4j dependency graph", value=topo_stats.get("edges", 0))

            report = self.pipeline.detector_report
            if report is not None:
                yield GaugeMetricFamily("vajra_iforest_trained_rows", "Rows the Isolation Forest was fit on (real UNSW-NB15 flows)", value=report.trained_rows)
                if report.anomaly_rate is not None:
                    yield GaugeMetricFamily("vajra_iforest_anomaly_rate", "Isolation Forest anomaly rate on its last validation pass", value=report.anomaly_rate)
                if report.precision is not None:
                    yield GaugeMetricFamily("vajra_iforest_precision", "Isolation Forest precision vs real dataset labels", value=report.precision)
                if report.recall is not None:
                    yield GaugeMetricFamily("vajra_iforest_recall", "Isolation Forest recall vs real dataset labels", value=report.recall)
                if report.f1 is not None:
                    yield GaugeMetricFamily("vajra_iforest_f1", "Isolation Forest F1 vs real dataset labels", value=report.f1)

            yield GaugeMetricFamily("vajra_otel_span_buffer_size", "Real OTel spans currently held in the in-process ring buffer", value=tracing.ring_buffer.count)
            yield GaugeMetricFamily("vajra_replay_active", "1 if live dataset replay is currently streaming", value=1.0 if self.pipeline.replay_active else 0.0)


def build_registry(pipeline: "Pipeline") -> CollectorRegistry:
    registry = CollectorRegistry()
    registry.register(VajraCollector(pipeline))
    return registry
