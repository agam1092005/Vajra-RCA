"""OpenTelemetry Logs SDK — routes real application and system logs into
Elasticsearch through the OTel Collector.

The collector's `logs` pipeline (`infra/otel-collector.yaml`) has always
pointed `otlp -> elasticsearch (index: otel-logs)`; nothing exported to it
before this module existed, so `otel-logs` sat empty. This wires:

1. **Application logs** — an OTel `LoggingHandler` attached to Python's root
   `logging` logger, so every `logging.*` call anywhere in the backend
   (pipeline lifecycle, detector fit/load results, incident creation, config
   injection) is exported as a real OTel log record. Best-effort OTLP export
   with the same graceful-degradation pattern as tracing/metrics — a
   stdout `StreamHandler` is always attached too, so console visibility
   during development is unaffected whether or not the collector is up.
2. **System logs** — the real HDFS dataset (this project's "system logs"
   signal) is re-emitted as OTel log records as each entry is replayed, via
   `system_logger()`, tagged `source=hdfs` and severity-mapped from the
   dataset's own Level/anomaly-label fields, so they land in Elasticsearch
   as searchable, indexed documents — not just in-memory `Event` objects.
"""
from __future__ import annotations

import logging

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from .config import settings

_provider: LoggerProvider | None = None
SYSTEM_LOGGER_NAME = "vajra.system_logs"
APP_LOGGER_NAME = "vajra.app"


def setup_otel_logging() -> None:
    """Idempotent. Safe to call multiple times (e.g. under --reload)."""
    global _provider
    if _provider is not None:
        return

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console visibility, independent of the collector being reachable —
    # matches the print()-based console output this replaces at the call sites below.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        root.addHandler(stream_handler)

    if not settings.otel_enabled:
        _provider = LoggerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = LoggerProvider(resource=resource)
    try:
        exporter = OTLPLogExporter(endpoint=settings.otel_exporter_endpoint, insecure=True)
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    except Exception as exc:
        print(f"[OTel] OTLP log exporter setup skipped (collector not reachable yet): {exc}")

    set_logger_provider(provider)
    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
    root.addHandler(otel_handler)
    _provider = provider
    print(f"[OTel] Log export initialized: service={settings.otel_service_name!r} "
          f"-> otel-collector 'logs' pipeline -> Elasticsearch ('otel-logs' index)")


def system_logger() -> logging.Logger:
    """Logger for real ingested system logs (HDFS) — distinct name so they're
    filterable in Elasticsearch/Kibana from application logs."""
    return logging.getLogger(SYSTEM_LOGGER_NAME)


def app_logger() -> logging.Logger:
    """Logger for real backend application/lifecycle events (pipeline
    prepare, incidents raised, config changes injected, detector fits)."""
    return logging.getLogger(APP_LOGGER_NAME)
