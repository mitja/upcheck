from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import cache_page

from .forms import MonitorForm
from .models import Monitor
from .plans import PRO, plan_for

CHART_WINDOW = timedelta(hours=24)
CHART_MAX_POINTS = 500


@login_required
def monitor_list(request):
    monitors = request.user.monitors.all()
    plan = plan_for(request.user)
    return render(
        request,
        "monitors/monitor_list.html",
        {
            "active_tab": "dashboard",
            "page_title": _("Monitors"),
            "monitors": monitors,
            "plan": plan,
            "can_add": monitors.count() < plan.max_monitors,
        },
    )


@login_required
def monitor_create(request):
    form = MonitorForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        monitor = form.save(commit=False)
        monitor.user = request.user
        monitor.save()
        messages.success(request, _("Monitor created. The first check runs within a minute."))
        return redirect("monitors:detail", pk=monitor.pk)
    return render(
        request,
        "monitors/monitor_form.html",
        {"active_tab": "dashboard", "page_title": _("New monitor"), "form": form},
    )


@login_required
def monitor_edit(request, pk):
    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    form = MonitorForm(request.POST or None, instance=monitor, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Monitor updated."))
        return redirect("monitors:detail", pk=monitor.pk)
    return render(
        request,
        "monitors/monitor_form.html",
        {"active_tab": "dashboard", "page_title": _("Edit monitor"), "form": form, "monitor": monitor},
    )


@login_required
def monitor_delete(request, pk):
    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    if request.method == "POST":
        monitor.delete()
        messages.success(request, _("Monitor deleted."))
        return redirect("monitors:list")
    return render(
        request,
        "monitors/monitor_confirm_delete.html",
        {"active_tab": "dashboard", "page_title": _("Delete monitor"), "monitor": monitor},
    )


@login_required
def monitor_detail(request, pk):
    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    return render(
        request,
        "monitors/monitor_detail.html",
        {
            "active_tab": "dashboard",
            "page_title": monitor.name,
            "monitor": monitor,
            "results": monitor.results.all()[:25],
            "uptime": monitor.uptime_24h(),
        },
    )


@login_required
def monitor_results_partial(request, pk):
    """HTMX-polled fragment: status card + latest results table."""
    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    return render(
        request,
        "monitors/components/results_panel.html",
        {"monitor": monitor, "results": monitor.results.all()[:25], "uptime": monitor.uptime_24h()},
    )


def _chart_payload(monitor):
    since = timezone.now() - CHART_WINDOW
    results = monitor.results.filter(checked_at__gte=since).order_by("checked_at")[:CHART_MAX_POINTS]
    return {
        "monitor": monitor.name,
        "results": [{"t": r.checked_at.isoformat(), "ms": r.response_ms, "ok": r.ok} for r in results],
    }


@login_required
def monitor_data(request, pk):
    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    return JsonResponse(_chart_payload(monitor))


@cache_page(30)
def public_status(request, slug):
    monitor = get_object_or_404(Monitor, slug=slug, is_public=True)
    return render(
        request,
        "monitors/public_status.html",
        {
            "page_title": monitor.name,
            "monitor": monitor,
            "uptime": monitor.uptime_24h(),
        },
    )


@cache_page(30)
def public_status_data(request, slug):
    monitor = get_object_or_404(Monitor, slug=slug, is_public=True)
    return JsonResponse(_chart_payload(monitor))


@login_required
def upgrade(request):
    return render(
        request,
        "monitors/upgrade.html",
        {
            "active_tab": "upgrade",
            "page_title": _("Plan & Billing"),
            "plan": plan_for(request.user),
            "pro": PRO,
        },
    )
