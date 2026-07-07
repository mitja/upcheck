"""Business-KPI metrics for UpCheck in Prometheus text exposition format.

Everything is computed FRESH from the database on each scrape into a
per-request ``CollectorRegistry``. Nothing is kept in module/process state, so
this is safe under multi-worker gunicorn (no cross-worker registry drift, no
double-counting) — every gunicorn worker answers a scrape with the same live
numbers.

The endpoint is bearer-token gated (see ``metrics_view``); it is never public.
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Aggregate, Count, FloatField, Q
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from polar_django.models import Subscription
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from .models import CheckResult, Monitor

# Unit economics (docs/77): a Pro sub is €5/mo gross; Polar fees leave ≈€4.21 net.
PRO_PRICE_EUR = 5.0
PRO_NET_EUR = 4.21

# The plan slug a paying subscriber resolves to (POLAR.PLANS key; see plans.py).
PRO_PLAN = "pro"


class PercentileCont(Aggregate):
    """Postgres ordered-set aggregate: ``PERCENTILE_CONT(p) WITHIN GROUP (ORDER BY expr)``."""

    function = "PERCENTILE_CONT"
    name = "percentilecont"
    template = "%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()

    def __init__(self, expression, percentile, **extra):
        super().__init__(expression, percentile=percentile, **extra)


def _collect(registry: CollectorRegistry) -> None:
    """Populate ``registry`` with the current UpCheck business KPIs."""
    User = get_user_model()
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # --- Users & plans -----------------------------------------------------
    total_users = User.objects.count()
    # Pro = distinct users with an active subscription on the Pro plan
    # (mirrors Subscription.tier_for: active status → sub.plan).
    pro_user_ids = (
        Subscription.objects.filter(status__in=Subscription.ACTIVE_STATUSES, plan=PRO_PLAN)
        .values_list("subject_id", flat=True)
        .distinct()
    )
    pro_users = pro_user_ids.count()
    free_users = max(total_users - pro_users, 0)

    g_users = Gauge("upcheck_users_total", "Registered users by plan", ["plan"], registry=registry)
    g_users.labels(plan="free").set(free_users)
    g_users.labels(plan="pro").set(pro_users)

    g_new = Gauge("upcheck_users_new", "New user signups within a rolling window", ["window"], registry=registry)
    g_new.labels(window="24h").set(User.objects.filter(date_joined__gte=day_ago).count())
    g_new.labels(window="7d").set(User.objects.filter(date_joined__gte=week_ago).count())
    g_new.labels(window="30d").set(User.objects.filter(date_joined__gte=month_ago).count())

    # --- Subscriptions -----------------------------------------------------
    active_subs = Subscription.objects.filter(status__in=Subscription.ACTIVE_STATUSES)
    g_active = Gauge("upcheck_subscriptions_active_total", "Active subscriptions", registry=registry)
    g_active.set(active_subs.count())

    g_canceling = Gauge(
        "upcheck_subscriptions_canceling_total",
        "Active subscriptions set to cancel at period end",
        registry=registry,
    )
    g_canceling.set(active_subs.filter(cancel_at_period_end=True).count())

    churned = Subscription.objects.filter(
        status__in=[Subscription.Status.CANCELED, Subscription.Status.REVOKED]
    ).filter(Q(canceled_at__gte=month_ago) | Q(ended_at__gte=month_ago))
    g_churned = Gauge(
        "upcheck_subscriptions_churned",
        "Subscriptions canceled or revoked within a rolling window",
        ["window"],
        registry=registry,
    )
    g_churned.labels(window="30d").set(churned.count())

    # --- MRR ---------------------------------------------------------------
    g_mrr_gross = Gauge("upcheck_mrr_gross_eur", "Monthly recurring revenue, gross (EUR)", registry=registry)
    g_mrr_gross.set(pro_users * PRO_PRICE_EUR)
    g_mrr_net = Gauge("upcheck_mrr_net_eur", "Monthly recurring revenue, net of Polar fees (EUR)", registry=registry)
    g_mrr_net.set(pro_users * PRO_NET_EUR)

    # --- Monitors ----------------------------------------------------------
    g_monitors = Gauge("upcheck_monitors_total", "Monitors by last observed status", ["status"], registry=registry)
    counts_by_status = dict(
        Monitor.objects.values_list("last_status").annotate(n=Count("id")).values_list("last_status", "n")
    )
    for status in (Monitor.Status.UP, Monitor.Status.DOWN, Monitor.Status.UNKNOWN):
        g_monitors.labels(status=status.value).set(counts_by_status.get(status.value, 0))

    g_mon_active = Gauge("upcheck_monitors_active_total", "Active (scheduled) monitors", registry=registry)
    g_mon_active.set(Monitor.objects.filter(is_active=True).count())
    g_mon_public = Gauge("upcheck_monitors_public_total", "Monitors with a public status page", registry=registry)
    g_mon_public.set(Monitor.objects.filter(is_public=True).count())

    # --- Check volume ------------------------------------------------------
    checks_24h = CheckResult.objects.filter(checked_at__gte=day_ago)
    g_checks = Gauge("upcheck_checks_total", "Checks recorded within a rolling window", ["window"], registry=registry)
    g_checks.labels(window="24h").set(checks_24h.count())
    g_checks_failed = Gauge(
        "upcheck_checks_failed_total", "Failed checks within a rolling window", ["window"], registry=registry
    )
    g_checks_failed.labels(window="24h").set(checks_24h.filter(ok=False).count())

    # Scheduled check rate: sum(1/interval) over active monitors. Grouped by
    # interval so this is one cheap aggregate regardless of monitor count.
    g_load = Gauge(
        "upcheck_check_load_per_minute",
        "Scheduled checks per minute across active monitors (sum of 1/interval_minutes)",
        registry=registry,
    )
    load = 0.0
    for row in Monitor.objects.filter(is_active=True).values("interval_minutes").annotate(n=Count("id")):
        interval = row["interval_minutes"] or 1
        load += row["n"] / interval
    g_load.set(load)

    # --- Response-time percentiles (last 24h) ------------------------------
    # NOTE: this scans the 24h CheckResult window. The (monitor, -checked_at)
    # index leads with `monitor`, so a monitor-agnostic time-range percentile
    # cannot use it — at high volume add a plain index on `checked_at` (or
    # sample). Cheap at launch scale; guarded by the scrape-duration metric.
    quantiles = checks_24h.filter(response_ms__isnull=False).aggregate(
        p50=PercentileCont("response_ms", 0.5),
        p95=PercentileCont("response_ms", 0.95),
    )
    g_resp = Gauge(
        "upcheck_check_response_ms",
        "Check HTTP response time percentiles over the last 24h (ms)",
        ["quantile"],
        registry=registry,
    )
    g_resp.labels(quantile="0.5").set(quantiles["p50"] or 0.0)
    g_resp.labels(quantile="0.95").set(quantiles["p95"] or 0.0)


def render_metrics() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the Prometheus exposition response."""
    registry = CollectorRegistry()
    started = time.perf_counter()
    _collect(registry)
    Gauge(
        "upcheck_metrics_scrape_duration_seconds",
        "Wall-clock time spent computing this /metrics response",
        registry=registry,
    ).set(time.perf_counter() - started)
    return generate_latest(registry), CONTENT_TYPE_LATEST


def metrics_view(request):
    """Bearer-token-gated Prometheus endpoint.

    - ``METRICS_TOKEN`` unset  -> 404 (endpoint invisible, fail safe).
    - wrong / missing bearer   -> 403.
    - correct bearer           -> 200 text/plain exposition.
    """
    token = getattr(settings, "METRICS_TOKEN", "") or ""
    if not token:
        return HttpResponseNotFound()
    provided = request.headers.get("Authorization", "")
    if not constant_time_compare(provided, f"Bearer {token}"):
        return HttpResponseForbidden()
    body, content_type = render_metrics()
    return HttpResponse(body, content_type=content_type)
