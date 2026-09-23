"""OpenTelemetry for UpCheck: traces and metrics over OTLP, trace ids in the logs.

Configured entirely by the standard OTEL_* environment (the platform sets it: service name per
process type, endpoints, sampling). Without an OTLP endpoint in the environment this does nothing,
so local development and tests are unaffected.

Call ``setup()`` once per process, AFTER forking: gunicorn's post_fork hook (gunicorn.conf.py) and
Celery's worker_process_init / beat_init (project/celery.py). The SDK's batch exporters run a
background thread, and a thread started before fork() does not exist in the child.
"""

from __future__ import annotations

import logging
import os

_done = False


def enabled() -> bool:
    if os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true":
        return False
    return any(
        os.environ.get(k)
        for k in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        )
    )


def setup() -> None:
    global _done
    if _done or not enabled():
        return
    _done = True

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource.create() reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES; the sampler comes
    # from OTEL_TRACES_SAMPLER(_ARG)
    resource = Resource.create()
    if os.environ.get("OTEL_TRACES_EXPORTER", "otlp") != "none":
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
    if os.environ.get("OTEL_METRICS_EXPORTER", "otlp") != "none":
        metrics.set_meter_provider(
            MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())])
        )

    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument(enable_commenter=False)
    RedisInstrumentor().instrument()
    RequestsInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    # a record logged inside a span gets trace_id/span_id, which the JSON formatter writes out; outside
    # a span they stay unset (null), not "0", so a log line only links to a trace that exists
    LoggingInstrumentor().instrument(set_logging_format=False, log_hook=_log_hook)
    logging.getLogger(__name__).info("OpenTelemetry enabled", extra={"event": "telemetry_enabled"})


def _log_hook(span, record) -> None:
    ctx = span.get_span_context()
    record.trace_id = format(ctx.trace_id, "032x")
    record.span_id = format(ctx.span_id, "016x")
