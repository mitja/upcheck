from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from apps.utils.models import BaseModel

# Checks land a few seconds after the minute boundary; without this grace a
# 1-minute monitor would only be picked up every second dispatcher run.
DISPATCH_GRACE = timedelta(seconds=30)


class Monitor(BaseModel):
    class Interval(models.IntegerChoices):
        EVERY_MINUTE = 1, "every minute"
        EVERY_5_MINUTES = 5, "every 5 minutes"
        EVERY_15_MINUTES = 15, "every 15 minutes"
        EVERY_HOUR = 60, "every hour"

    class Status(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        UNKNOWN = "unknown", "Unknown"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="monitors")
    name = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    interval_minutes = models.PositiveSmallIntegerField(choices=Interval.choices, default=Interval.EVERY_5_MINUTES)
    timeout_seconds = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=False, help_text="Expose a public status page for this monitor.")
    slug = models.SlugField(unique=True, editable=False)

    # Denormalized from the latest CheckResult so list views need no aggregate queries.
    last_status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNKNOWN)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_response_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:40] or "monitor"
            self.slug = f"{base}-{get_random_string(6).lower()}"
        super().save(*args, **kwargs)

    def is_due(self, now=None) -> bool:
        if not self.is_active:
            return False
        if self.last_checked_at is None:
            return True
        now = now or timezone.now()
        return now >= self.last_checked_at + timedelta(minutes=self.interval_minutes) - DISPATCH_GRACE

    def uptime_24h(self) -> float | None:
        """Percentage of successful checks in the last 24h, or None without data."""
        since = timezone.now() - timedelta(hours=24)
        stats = self.results.filter(checked_at__gte=since).aggregate(
            total=models.Count("id"),
            ok=models.Count("id", filter=models.Q(ok=True)),
        )
        if not stats["total"]:
            return None
        return 100.0 * stats["ok"] / stats["total"]


class CheckResult(models.Model):
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE, related_name="results")
    checked_at = models.DateTimeField(default=timezone.now)
    ok = models.BooleanField()
    status_code = models.SmallIntegerField(null=True, blank=True)
    response_ms = models.IntegerField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["monitor", "-checked_at"])]

    def __str__(self):
        return f"{self.monitor} @ {self.checked_at:%Y-%m-%d %H:%M} ({'ok' if self.ok else 'fail'})"
