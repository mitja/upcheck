from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from polar_django.models import Subscription

from apps.monitors.models import CheckResult, Monitor

TOKEN = "s3cr3t-metrics-token"


@override_settings(METRICS_TOKEN=TOKEN)
class MetricsContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        now = timezone.now()
        day_ago = now - timedelta(hours=24)

        # 4 users: 2 pro (active subs), 1 free, 1 churned (joined 10d ago).
        cls.u_pro1 = User.objects.create_user(username="p1@x.com", email="p1@x.com")
        cls.u_pro2 = User.objects.create_user(username="p2@x.com", email="p2@x.com")
        cls.u_free = User.objects.create_user(username="f@x.com", email="f@x.com")
        cls.u_churn = User.objects.create_user(
            username="c@x.com", email="c@x.com", date_joined=now - timedelta(days=10)
        )

        # Two active Pro subs (one flagged to cancel at period end) + one churned.
        Subscription.objects.create(
            subject=cls.u_pro1, plan="pro", status=Subscription.Status.ACTIVE, polar_subscription_id="sub_active"
        )
        Subscription.objects.create(
            subject=cls.u_pro2,
            plan="pro",
            status=Subscription.Status.ACTIVE,
            cancel_at_period_end=True,
            polar_subscription_id="sub_canceling",
        )
        Subscription.objects.create(
            subject=cls.u_churn,
            plan="pro",
            status=Subscription.Status.CANCELED,
            canceled_at=now - timedelta(days=1),
            polar_subscription_id="sub_churned",
        )

        # Monitors: one per status; mixed active/public; intervals 5 and 1.
        m_up = Monitor.objects.create(
            user=cls.u_free,
            name="up",
            url="https://example.com/",
            last_status=Monitor.Status.UP,
            is_active=True,
            is_public=True,
            interval_minutes=5,
        )
        m_down = Monitor.objects.create(
            user=cls.u_free,
            name="down",
            url="https://example.com/",
            last_status=Monitor.Status.DOWN,
            is_active=True,
            is_public=False,
            interval_minutes=1,
        )
        Monitor.objects.create(
            user=cls.u_free,
            name="unknown",
            url="https://example.com/",
            last_status=Monitor.Status.UNKNOWN,
            is_active=False,
            is_public=False,
            interval_minutes=15,
        )

        # Checks in the last 24h: 100, 200 (ok) on m_up; 300 (fail) on m_down.
        CheckResult.objects.create(monitor=m_up, ok=True, response_ms=100)
        CheckResult.objects.create(monitor=m_up, ok=True, response_ms=200)
        CheckResult.objects.create(monitor=m_down, ok=False, response_ms=300)
        # One old check (2 days ago) — must be excluded from the 24h windows.
        CheckResult.objects.create(monitor=m_up, ok=True, response_ms=9999, checked_at=day_ago - timedelta(days=1))

    def _scrape(self):
        return self.client.get("/metrics", HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    def test_scrape_ok_and_content_type(self):
        resp = self._scrape()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp["Content-Type"])

    def test_user_and_plan_gauges(self):
        body = self._scrape().content.decode()
        self.assertIn('upcheck_users_total{plan="free"} 2.0', body)
        self.assertIn('upcheck_users_total{plan="pro"} 2.0', body)
        self.assertIn('upcheck_users_new{window="24h"} 3.0', body)
        self.assertIn('upcheck_users_new{window="30d"} 4.0', body)

    def test_subscription_gauges(self):
        body = self._scrape().content.decode()
        self.assertIn("upcheck_subscriptions_active_total 2.0", body)
        self.assertIn("upcheck_subscriptions_canceling_total 1.0", body)
        self.assertIn('upcheck_subscriptions_churned{window="30d"} 1.0', body)

    def test_mrr_gauges(self):
        body = self._scrape().content.decode()
        self.assertIn("upcheck_mrr_gross_eur 10.0", body)
        self.assertIn("upcheck_mrr_net_eur 8.42", body)

    def test_monitor_gauges(self):
        body = self._scrape().content.decode()
        self.assertIn('upcheck_monitors_total{status="up"} 1.0', body)
        self.assertIn('upcheck_monitors_total{status="down"} 1.0', body)
        self.assertIn('upcheck_monitors_total{status="unknown"} 1.0', body)
        self.assertIn("upcheck_monitors_active_total 2.0", body)
        self.assertIn("upcheck_monitors_public_total 1.0", body)

    def test_check_volume_and_load(self):
        body = self._scrape().content.decode()
        self.assertIn('upcheck_checks_total{window="24h"} 3.0', body)
        self.assertIn('upcheck_checks_failed_total{window="24h"} 1.0', body)
        # active monitors: 1/5 + 1/1 = 1.2 (the inactive 15-min monitor excluded)
        self.assertIn("upcheck_check_load_per_minute 1.2", body)

    def test_response_time_percentiles(self):
        body = self._scrape().content.decode()
        # median of {100,200,300} = 200; PERCENTILE_CONT(0.95) = 290
        self.assertIn('upcheck_check_response_ms{quantile="0.5"} 200.0', body)
        self.assertIn('upcheck_check_response_ms{quantile="0.95"} 290.0', body)

    def test_scrape_duration_self_metric_present(self):
        body = self._scrape().content.decode()
        self.assertIn("upcheck_metrics_scrape_duration_seconds", body)

    @override_settings(ALLOWED_HOSTS=["upcheck.paasbox.com", "web.upcheck.svc.cluster.local"])
    def test_scrapeable_via_internal_service_host(self):
        # The in-cluster scrape presents the internal Service DNS as its Host
        # (the VMServiceScrape rewrites __address__ to it); that name is in
        # ALLOWED_HOSTS, so Django's host check passes over plain HTTP.
        resp = self.client.get(
            "/metrics", HTTP_AUTHORIZATION=f"Bearer {TOKEN}", HTTP_HOST="web.upcheck.svc.cluster.local:8000"
        )
        self.assertEqual(resp.status_code, 200)


class MetricsAuthTests(TestCase):
    @override_settings(METRICS_TOKEN="")
    def test_404_when_token_unset(self):
        self.assertEqual(self.client.get("/metrics").status_code, 404)

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_403_without_authorization_header(self):
        self.assertEqual(self.client.get("/metrics").status_code, 403)

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_403_with_wrong_token(self):
        resp = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer nope")
        self.assertEqual(resp.status_code, 403)

    @override_settings(METRICS_TOKEN=TOKEN)
    def test_200_with_correct_token(self):
        resp = self.client.get("/metrics", HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
        self.assertEqual(resp.status_code, 200)
