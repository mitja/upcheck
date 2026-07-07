"""Production settings: env-driven, container-friendly.

Everything security-relevant is explicit here; the base settings' permissive
defaults (DEBUG=True, ALLOWED_HOSTS=*) never reach production. TLS terminates
at the ingress, so HTTPS handling keys off X-Forwarded-Proto —
SECURE_SSL_REDIRECT stays env-toggleable for plain-HTTP environments
(local kind via port-forward).
"""

from .settings import *  # noqa: F403

DEBUG = False

SECRET_KEY = env("SECRET_KEY")  # noqa: F405 — required, no insecure fallback
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # noqa: F405
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
# In-cluster Prometheus scrapes hit /metrics over plain HTTP on the pod IP (no
# X-Forwarded-Proto, Host = pod IP). Exempt it so SecurityMiddleware neither
# 301-redirects to HTTPS nor calls get_host() (which would 400 on the pod IP);
# the endpoint is protected by its own bearer token instead.
SECURE_REDIRECT_EXEMPT = [r"^metrics$"]
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
# Increase once you're confident everything works (https://stackoverflow.com/a/49168623/8207)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600) if SECURE_SSL_REDIRECT else 0  # noqa: F405
USE_HTTPS_IN_ABSOLUTE_URLS = SECURE_SSL_REDIRECT

# The base settings evaluate `if DEBUG:` at import time with the env default
# (True), which pulls in dev-only pieces. Strip them — the packages aren't
# installed in the production image.
if "django_browser_reload" in INSTALLED_APPS:  # noqa: F405
    INSTALLED_APPS.remove("django_browser_reload")  # noqa: F405
if "django_browser_reload.middleware.BrowserReloadMiddleware" in MIDDLEWARE:  # noqa: F405
    MIDDLEWARE.remove("django_browser_reload.middleware.BrowserReloadMiddleware")  # noqa: F405
# (underscore names don't survive `import *` — restate the cached loaders)
TEMPLATES[0]["OPTIONS"]["loaders"] = [  # type: ignore[index]  # noqa: F405
    (
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    )
]

# Static files: WhiteNoise straight from gunicorn — no nginx sidecar.
# collectstatic runs at image build time (see Dockerfile).
MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
STORAGES["staticfiles"]["BACKEND"] = "whitenoise.storage.CompressedManifestStaticFilesStorage"  # noqa: F405

# Vite assets are prebuilt into the image; never talk to a dev server.
DJANGO_VITE["default"]["dev_mode"] = False  # noqa: F405

CACHES = {"default": REDIS_CACHE}  # noqa: F405

PROJECT_METADATA["URL"] = env("PROJECT_URL", default="https://upcheck.paasbox.com")  # noqa: F405

# Console email unless Mailjet credentials are provided.
# See https://github.com/anymail/django-anymail for other providers.
if env("MAILJET_API_KEY", default=""):  # noqa: F405
    EMAIL_BACKEND = "anymail.backends.mailjet.EmailBackend"
    ANYMAIL = {
        "MAILJET_API_KEY": env("MAILJET_API_KEY"),  # noqa: F405
        "MAILJET_SECRET_KEY": env("MAILJET_SECRET_KEY"),  # noqa: F405
    }
