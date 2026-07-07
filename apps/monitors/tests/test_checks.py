from unittest import mock

from django.test import SimpleTestCase

from apps.monitors.checks import (
    BlockedTarget,
    TargetResolutionError,
    ensure_allowed_target,
    perform_check,
)


def fake_addrinfo(ip):
    return [(2, 1, 6, "", (ip, 0))]


class EnsureAllowedTargetTests(SimpleTestCase):
    def test_rejects_non_http_schemes(self):
        for url in ["ftp://example.com/", "file:///etc/passwd", "gopher://example.com/"]:
            with self.assertRaises(BlockedTarget):
                ensure_allowed_target(url)

    def test_rejects_unusual_ports(self):
        with self.assertRaises(BlockedTarget):
            ensure_allowed_target("http://example.com:6443/healthz")

    def test_rejects_credentials_in_url(self):
        with self.assertRaises(BlockedTarget):
            ensure_allowed_target("http://user:pass@example.com/")

    def test_rejects_private_and_internal_addresses(self):
        blocked_ips = [
            "127.0.0.1",  # loopback
            "10.96.0.1",  # cluster service CIDR territory
            "192.168.1.1",  # RFC1918
            "169.254.169.254",  # link-local / metadata
            "100.96.1.5",  # shared address space (Gardener pod CIDR)
            "::1",  # IPv6 loopback
            "fd00::1",  # IPv6 ULA
        ]
        for ip in blocked_ips:
            with (
                mock.patch("socket.getaddrinfo", return_value=fake_addrinfo(ip)),
                self.assertRaises(BlockedTarget, msg=f"{ip} should be blocked"),
            ):
                ensure_allowed_target("https://internal.example.com/")

    def test_rejects_ip_literal_private_targets(self):
        with self.assertRaises(BlockedTarget):
            ensure_allowed_target("http://10.0.0.1/")

    def test_allows_public_addresses(self):
        with mock.patch("socket.getaddrinfo", return_value=fake_addrinfo("93.184.216.34")):
            ensure_allowed_target("https://example.com/")  # must not raise

    def test_unresolvable_host_raises_resolution_error(self):
        import socket as socket_module

        with (
            mock.patch("socket.getaddrinfo", side_effect=socket_module.gaierror),
            self.assertRaises(TargetResolutionError),
        ):
            ensure_allowed_target("https://does-not-exist.invalid/")


class PerformCheckTests(SimpleTestCase):
    def test_blocked_target_is_reported_not_requested(self):
        with mock.patch("apps.monitors.checks.requests.get") as get:
            ok, status, ms, error = perform_check("http://127.0.0.1/", 5)
        self.assertFalse(ok)
        self.assertIn("blocked target", error)
        get.assert_not_called()

    def test_http_error_status_is_a_failed_check(self):
        response = mock.Mock(status_code=503)
        with (
            mock.patch("apps.monitors.checks.ensure_allowed_target"),
            mock.patch("apps.monitors.checks.requests.get", return_value=response),
        ):
            ok, status, ms, error = perform_check("https://example.com/", 5)
        self.assertFalse(ok)
        self.assertEqual(status, 503)
        self.assertEqual(error, "HTTP 503")

    def test_successful_check(self):
        response = mock.Mock(status_code=200)
        with (
            mock.patch("apps.monitors.checks.ensure_allowed_target"),
            mock.patch("apps.monitors.checks.requests.get", return_value=response),
        ):
            ok, status, ms, error = perform_check("https://example.com/", 5)
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertIsNotNone(ms)
        self.assertEqual(error, "")
