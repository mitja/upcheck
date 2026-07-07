from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.monitors.models import Monitor


class MonitorViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username="u@example.com", email="u@example.com", password="pw")
        cls.other = User.objects.create_user(username="o@example.com", email="o@example.com", password="pw")
        cls.monitor = Monitor.objects.create(user=cls.user, name="Mine", url="https://example.com/")

    def test_list_requires_login(self):
        response = self.client.get(reverse("monitors:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response.url)

    def test_list_shows_own_monitors(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("monitors:list"))
        self.assertContains(response, "Mine")

    def test_detail_of_another_users_monitor_is_404(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("monitors:detail", args=[self.monitor.pk]))
        self.assertEqual(response.status_code, 404)

    def test_authenticated_home_redirects_to_monitors(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertRedirects(response, reverse("monitors:list"))

    def test_data_endpoint_returns_results_json(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("monitors:data", args=[self.monitor.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())


class PublicStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user(username="u@example.com", email="u@example.com")
        cls.public = Monitor.objects.create(user=user, name="Pub", url="https://example.com/", is_public=True)
        cls.private = Monitor.objects.create(user=user, name="Priv", url="https://example.com/")

    def test_public_page_renders_logged_out(self):
        response = self.client.get(reverse("monitors:public_status", args=[self.public.slug]))
        self.assertContains(response, "Pub")

    def test_private_monitor_public_page_is_404(self):
        response = self.client.get(reverse("monitors:public_status", args=[self.private.slug]))
        self.assertEqual(response.status_code, 404)

    def test_public_data_endpoint(self):
        response = self.client.get(reverse("monitors:public_status_data", args=[self.public.slug]))
        self.assertEqual(response.status_code, 200)
