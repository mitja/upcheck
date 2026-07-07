from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.monitors.forms import MonitorForm
from apps.monitors.models import Monitor
from apps.monitors.plans import FREE, PRO, plan_for


def form_data(**overrides):
    data = {
        "name": "Example",
        "url": "https://example.com/",
        "interval_minutes": 5,
        "timeout_seconds": 10,
        "is_active": "on",
    }
    data.update(overrides)
    return data


@mock.patch("apps.monitors.forms.ensure_allowed_target")  # tested separately, avoid real DNS
class PlanGatingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="u@example.com", email="u@example.com")

    def test_default_plan_is_free(self, _guard):
        self.assertEqual(plan_for(self.user), FREE)

    def test_free_plan_rejects_one_minute_interval(self, _guard):
        form = MonitorForm(form_data(interval_minutes=1), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("interval_minutes", form.errors)

    def test_free_plan_monitor_cap(self, _guard):
        for i in range(FREE.max_monitors):
            Monitor.objects.create(user=self.user, name=f"m{i}", url="https://example.com/")
        form = MonitorForm(form_data(), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("Upgrade to add more", str(form.errors))

    def test_pro_plan_allows_one_minute_and_more_monitors(self, _guard):
        for i in range(FREE.max_monitors):
            Monitor.objects.create(user=self.user, name=f"m{i}", url="https://example.com/")
        with mock.patch("apps.monitors.plans.Subscription.tier_for", return_value="pro"):
            form = MonitorForm(form_data(interval_minutes=1), user=self.user)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(plan_for(self.user), PRO)

    def test_editing_existing_monitor_not_blocked_by_cap(self, _guard):
        monitors = [
            Monitor.objects.create(user=self.user, name=f"m{i}", url="https://example.com/")
            for i in range(FREE.max_monitors)
        ]
        form = MonitorForm(form_data(name="renamed"), instance=monitors[0], user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
