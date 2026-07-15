"""OpenTelemetry SDK instrumentation.

Every ingestion, detection, topology, RCA, and LangGraph-agent operation emits
a REAL OTel span — no simulated latencies. Two sinks receive finished spans:

1. An in-process ring-buffer exporter (`ring_buffer`) — always active,
   zero I/O. This is what `agents/nodes.py::trace_node` reads from, so the
   Trace Agent has genuine captured span data even when the OTel Collector
   container isn't running (Docker infra is intentionally out of scope here).
2. An OTLP/gRPC exporter pointed at `otel-collector:4317` — best-effort. If
   the collector is unreachable, export failures are swallowed (same
   graceful-degradation pattern as the Kafka/Neo4j/Qdrant clients elsewhere
   in this codebase) and the ring buffer keeps working regardless.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from threading import Lock
from typing import Any, Iterator, Sequence

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from .config import settings


class RingBufferSpanExporter(SpanExporter):
    """In-memory sink for the last N finished spans, queryable by the Trace Agent.

    Exported via a SimpleSpanProcessor (synchronous, no batching delay) since
    appending to a deque is cheap — the Trace Agent needs spans available the
    moment they finish, not after a multi-second batch export interval.
    """

    def __init__(self, maxlen: int) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            for s in spans:
                self._buffer.append(_span_to_dict(s))
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # pragma: no cover - nothing to flush
        return None

    def recent(
        self, focal_node: str | None = None, since: float | None = None, limit: int = 40
    ) -> list[dict[str, Any]]:
        with self._lock:
            spans = list(self._buffer)
        if focal_node:
            spans = [
                s for s in spans
                if s["attributes"].get("focal_node") == focal_node
                or s["attributes"].get("node") == focal_node
            ]
        if since is not None:
            spans = [s for s in spans if (s["end_time"] or 0) >= since]
        return spans[-limit:]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._buffer)


def _span_to_dict(span: ReadableSpan) -> dict[str, Any]:
    ctx = span.get_span_context()
    start = span.start_time / 1e9 if span.start_time else None
    end = span.end_time / 1e9 if span.end_time else None
    return {
        "span_id": format(ctx.span_id, "016x") if ctx else None,
        "trace_id": format(ctx.trace_id, "032x") if ctx else None,
        "name": span.name,
        "start_time": start,
        "end_time": end,
        "duration_ms": round((end - start) * 1000.0, 3) if start is not None and end is not None else None,
        "status": span.status.status_code.name if span.status else "UNSET",
        "attributes": dict(span.attributes or {}),
    }


ring_buffer = RingBufferSpanExporter(maxlen=settings.otel_span_buffer_size)
_tracer: trace.Tracer | None = None


def setup_tracing() -> trace.Tracer:
    """Initialize the OTel SDK once (idempotent). Call at process startup."""
    global _tracer
    if _tracer is not None:
        return _tracer

    if not settings.otel_enabled:
        _tracer = trace.get_tracer(settings.otel_service_name)
        return _tracer

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    # Sink 1: ring buffer — synchronous, always on, feeds the real Trace Agent.
    provider.add_span_processor(SimpleSpanProcessor(ring_buffer))

    # Sink 2: OTLP -> otel-collector — batched, best-effort. Export failures
    # are swallowed by the BatchSpanProcessor's background worker, so a
    # missing collector never blocks or crashes the app (Docker stays optional).
    try:
        otlp_exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    except Exception as exc:
        print(f"[OTel] OTLP exporter setup skipped (collector not reachable yet): {exc}")

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(settings.otel_service_name)
    print(f"[OTel] Tracing initialized: service={settings.otel_service_name!r} "
          f"otlp_endpoint={settings.otel_exporter_endpoint!r}")
    return _tracer


def get_tracer() -> trace.Tracer:
    return _tracer or setup_tracing()


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Start a real OTel span named `name` with the given attributes attached.

    Any exception raised inside the block is recorded on the span (status +
    exception event) and re-raised — tracing must never swallow errors.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as current_span:
        for key, value in attributes.items():
            if value is not None:
                current_span.set_attribute(key, value)
        try:
            yield current_span
        except Exception as exc:
            current_span.record_exception(exc)
            current_span.set_status(trace.StatusCode.ERROR, str(exc))
            raise


def recent_spans(
    focal_node: str | None = None, since: float | None = None, limit: int = 40
) -> list[dict[str, Any]]:
    """Real finished spans captured by the ring buffer — consumed by the Trace Agent."""
    return ring_buffer.recent(focal_node=focal_node, since=since, limit=limit)
