from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.monitors.models import CheckResult, Monitor
from apps.monitors.tasks import dispatch_checks, prune_results, run_check


class DispatchChecksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="u@example.com", email="u@example.com")

    def make_monitor(self, **kwargs):
        defaults = {"user": self.user, "name": "m", "url": "https://example.com/", "interval_minutes": 5}
        defaults.update(kwargs)
        return Monitor.objects.create(**defaults)

    @mock.patch("apps.monitors.tasks.run_check.delay")
    def test_never_checked_monitor_is_dispatched(self, delay):
        monitor = self.make_monitor()
        self.assertEqual(dispatch_checks(), 1)
        delay.assert_called_once_with(monitor.pk)

    @mock.patch("apps.monitors.tasks.run_check.delay")
    def test_recently_checked_monitor_is_not_dispatched(self, delay):
        self.make_monitor(last_checked_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(dispatch_checks(), 0)
        delay.assert_not_called()

    @mock.patch("apps.monitors.tasks.run_check.delay")
    def test_overdue_monitor_is_dispatched(self, delay):
        self.make_monitor(last_checked_at=timezone.now() - timedelta(minutes=6))
        self.assertEqual(dispatch_checks(), 1)

    @mock.patch("apps.monitors.tasks.run_check.delay")
    def test_paused_monitor_is_not_dispatched(self, delay):
        self.make_monitor(is_active=False)
        self.assertEqual(dispatch_checks(), 0)

    @mock.patch("apps.monitors.tasks.run_check.delay")
    def test_grace_window_keeps_one_minute_monitors_on_cadence(self, delay):
        # Checked 45s ago with a 1-minute interval: within the 30s grace, so due.
        self.make_monitor(interval_minutes=1, last_checked_at=timezone.now() - timedelta(seconds=45))
        self.assertEqual(dispatch_checks(), 1)


class RunCheckTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="u@example.com", email="u@example.com")
        cls.monitor = Monitor.objects.create(user=cls.user, name="m", url="https://example.com/")

    @mock.patch("apps.monitors.tasks.perform_check", return_value=(True, 200, 123, ""))
    def test_successful_check_records_result_and_denormals(self, _perform):
        self.assertTrue(run_check(self.monitor.pk))
        result = self.monitor.results.get()
        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 200)
        self.monitor.refresh_from_db()
        self.assertEqual(self.monitor.last_status, Monitor.Status.UP)
        self.assertEqual(self.monitor.last_response_ms, 123)
        self.assertIsNotNone(self.monitor.last_checked_at)

    @mock.patch("apps.monitors.tasks.perform_check", return_value=(False, None, None, "connection failed"))
    def test_failed_check_marks_monitor_down(self, _perform):
        self.assertFalse(run_check(self.monitor.pk))
        self.monitor.refresh_from_db()
        self.assertEqual(self.monitor.last_status, Monitor.Status.DOWN)

    def test_missing_monitor_is_a_noop(self):
        self.assertIsNone(run_check(999999))


class PruneResultsTests(TestCase):
    def test_prunes_only_old_results(self):
        user = get_user_model().objects.create_user(username="u@example.com", email="u@example.com")
        monitor = Monitor.objects.create(user=user, name="m", url="https://example.com/")
        old = CheckResult.objects.create(monitor=monitor, ok=True, checked_at=timezone.now() - timedelta(days=8))
        fresh = CheckResult.objects.create(monitor=monitor, ok=True, checked_at=timezone.now() - timedelta(days=1))
        self.assertEqual(prune_results(), 1)
        self.assertFalse(CheckResult.objects.filter(pk=old.pk).exists())
        self.assertTrue(CheckResult.objects.filter(pk=fresh.pk).exists())
