# UpCheck production image. One image serves four roles via command overrides:
#   web:     gunicorn (default CMD)
#   worker:  celery -A project worker
#   beat:    celery -A project beat
#   migrate: python manage.py migrate (one-off Job)

# ---- Stage 1: frontend (Vite/Tailwind) ----
FROM node:22-alpine AS frontend
WORKDIR /code
COPY package.json package-lock.json ./
RUN npm ci
COPY vite.config.ts tailwind.config.js tsconfig.json ./
COPY assets ./assets
# Tailwind 4 scans templates for class names — without them the CSS ships empty.
COPY templates ./templates
COPY static ./static
RUN npm run build

# ---- Stage 2: application ----
FROM python:3.14-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

WORKDIR /code

# git: needed by uv for the django-polar-sh git dependency (drop once it's on PyPI).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer first for build caching. --no-install-project: the app is
# a plain Django tree, not an installable package.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group prod --no-install-project

ENV PATH="/code/.venv/bin:$PATH"

COPY . .
# Vite writes bundles + manifest into static/ (see vite.config.ts outDir).
COPY --from=frontend /code/static ./static

# collectstatic needs importable settings, not a live database or real secret.
RUN DJANGO_SETTINGS_MODULE=project.settings_production \
    SECRET_KEY=build-only-dummy \
    ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 django && chown -R django:django /code
USER django

EXPOSE 8000

CMD ["gunicorn", "project.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
