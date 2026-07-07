"""Target validation and check execution.

The worker runs inside a Kubernetes cluster, so user-supplied URLs must never
reach cluster-internal or otherwise non-public addresses (SSRF). Validation
resolves the hostname and rejects any target with a non-global IP. The check
itself re-resolves via requests, so a DNS answer that changes between
validation and request (rebinding) is not fully closed off — acceptable for
this demo, called out in the README.
"""

import ipaddress
import socket
import time
from urllib.parse import urlparse

import requests

USER_AGENT = "UpCheck/1.0 (+https://github.com/mitja/upcheck)"
ALLOWED_SCHEMES = {"http", "https"}
# Keep the demo from being used as a port scanner for arbitrary public hosts.
ALLOWED_PORTS = {80, 443, 8000, 8080, 8443}


class BlockedTarget(Exception):
    """The URL violates target policy (scheme, port, or non-public address)."""


class TargetResolutionError(Exception):
    """The hostname did not resolve."""


def ensure_allowed_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedTarget("only http and https URLs are allowed")
    if not parsed.hostname:
        raise BlockedTarget("URL has no hostname")
    if parsed.port is not None and parsed.port not in ALLOWED_PORTS:
        raise BlockedTarget(f"port {parsed.port} is not allowed")
    if parsed.username or parsed.password:
        raise BlockedTarget("credentials in URLs are not allowed")

    try:
        addr_infos = socket.getaddrinfo(parsed.hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise TargetResolutionError(f"could not resolve {parsed.hostname}") from e

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise BlockedTarget("target resolves to a private or internal address")


def perform_check(url: str, timeout_seconds: int) -> tuple[bool, int | None, int | None, str]:
    """Run one HTTP check. Returns (ok, status_code, response_ms, error)."""
    try:
        ensure_allowed_target(url)
    except BlockedTarget as e:
        return False, None, None, f"blocked target: {e}"
    except TargetResolutionError:
        return False, None, None, "DNS resolution failed"

    started = time.monotonic()
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            allow_redirects=True,
            stream=True,  # don't download bodies; we only need the status line
            headers={"User-Agent": USER_AGENT},
        )
    except requests.exceptions.Timeout:
        return False, None, None, f"timed out after {timeout_seconds}s"
    except requests.exceptions.SSLError:
        return False, None, None, "TLS error"
    except requests.exceptions.ConnectionError:
        return False, None, None, "connection failed"
    except requests.exceptions.RequestException as e:
        return False, None, None, type(e).__name__

    elapsed_ms = int((time.monotonic() - started) * 1000)
    response.close()
    ok = 200 <= response.status_code < 400
    error = "" if ok else f"HTTP {response.status_code}"
    return ok, response.status_code, elapsed_ms, error
