import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from opentelemetry import metrics

from .checks import perform_check
from .models import CheckResult, Monitor

RESULT_RETENTION = timedelta(days=7)

logger = logging.getLogger(__name__)
# a no-op until project/telemetry.py sets a meter provider (then exported over OTLP)
_checks = metrics.get_meter("upcheck.monitors").create_counter(
    "upcheck.checks", unit="{check}", description="Checks run, by outcome"
)


@shared_task
def dispatch_checks() -> int:
    """Enqueue a check for every active monitor whose interval has elapsed.

    Runs every minute via celery beat. Due-ness is evaluated in Python — the
    monitor count stays small enough that a per-row filter beats a database
    expression, and a slow in-flight check duplicating one result is harmless.
    """
    now = timezone.now()
    dispatched = 0
    for monitor in Monitor.objects.filter(is_active=True).only(
        "id", "is_active", "interval_minutes", "last_checked_at"
    ):
        if monitor.is_due(now):
            run_check.delay(monitor.pk)
            dispatched += 1
    return dispatched


@shared_task(time_limit=60)
def run_check(monitor_id: int) -> bool | None:
    try:
        monitor = Monitor.objects.get(pk=monitor_id)
    except Monitor.DoesNotExist:
        return None

    ok, status_code, response_ms, error = perform_check(monitor.url, monitor.timeout_seconds)
    _checks.add(1, {"outcome": "up" if ok else "down"})
    was = monitor.last_status
    now_status = Monitor.Status.UP if ok else Monitor.Status.DOWN
    if was in (Monitor.Status.UP, Monitor.Status.DOWN) and was != now_status:
        logger.info(
            "monitor went %s",
            now_status,
            extra={"event": "monitor_up" if ok else "monitor_down", "monitor_id": monitor.pk},
        )
    checked_at = timezone.now()
    CheckResult.objects.create(
        monitor=monitor,
        checked_at=checked_at,
        ok=ok,
        status_code=status_code,
        response_ms=response_ms,
        error=error,
    )
    Monitor.objects.filter(pk=monitor.pk).update(
        last_status=now_status,
        last_checked_at=checked_at,
        last_response_ms=response_ms,
    )
    return ok


@shared_task
def prune_results() -> int:
    """Delete check results older than the retention window. Runs daily."""
    cutoff = timezone.now() - RESULT_RETENTION
    deleted, _ = CheckResult.objects.filter(checked_at__lt=cutoff).delete()
    return deleted
