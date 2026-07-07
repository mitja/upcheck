from django.contrib import admin

from .models import CheckResult, Monitor


@admin.register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "url", "interval_minutes", "is_active", "is_public", "last_status"]
    list_filter = ["is_active", "is_public", "last_status", "interval_minutes"]
    search_fields = ["name", "url", "user__email"]
    readonly_fields = ["slug", "last_status", "last_checked_at", "last_response_ms"]


@admin.register(CheckResult)
class CheckResultAdmin(admin.ModelAdmin):
    list_display = ["monitor", "checked_at", "ok", "status_code", "response_ms", "error"]
    list_filter = ["ok"]
    date_hierarchy = "checked_at"
