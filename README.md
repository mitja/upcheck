# UpCheck

**Lightweight uptime monitoring for your sites and APIs — and a complete, deployable demo of running a Django SaaS on Kubernetes.**

UpCheck is a small but real SaaS: users sign up, add URL monitors, and Celery
workers check them on a schedule. Dashboards show response times and uptime;
each monitor can expose a public status page. Subscriptions (Free vs. Pro
tiers) are handled by [Polar.sh](https://polar.sh) via
[django-polar-sh](https://github.com/mitja/django-polar-sh).

It exists for two reasons:

1. To be genuinely useful for monitoring a handful of sites.
2. To demonstrate, end to end, how to deploy a Django SaaS (web + Celery
   worker + beat + Postgres + Redis) on Kubernetes — locally on
   [kind](https://kind.sigs.k8s.io/) and in production on a managed cluster
   such as [PAASBOX](https://paasbox.com).

## Built on SaaS Pegasus (open-source edition)

This project is built on the
[SaaS Pegasus Django boilerplate](https://github.com/saaspegasus/django-boilerplate)
(MIT) by Cory Zue / Elodin Labs — the open-source edition of
[SaaS Pegasus](https://www.saaspegasus.com/). The boilerplate provides the
foundation (Django 6, allauth authentication, HTMX + Alpine.js, Tailwind CSS 4
+ DaisyUI via Vite, DRF API, Celery, tooling); UpCheck adds the uptime-monitor
domain app, Polar.sh billing, a production Dockerfile, and Kubernetes
manifests. Upstream history is preserved in this repo (`upstream` remote), so
attribution lives in the git log as well as here.

If you're building a business-grade SaaS, look at
[SaaS Pegasus Pro](https://www.saaspegasus.com/) — it adds teams, Stripe
billing, AI tooling, one-click deploys, and more.

## Features

- **Monitors** — add HTTP(S) URLs, choose a check interval (1–60 min), pause/resume.
- **Checks** — Celery beat dispatches due checks every minute; workers record
  status, latency, and errors; results are pruned after 7 days.
- **Dashboard** — live status badges, 24h uptime, response-time charts
  (Chart.js), HTMX-refreshed tables.
- **Public status pages** — share `/s/<slug>` per monitor, no login required.
- **Plans** — Free (2 monitors, ≥5-min interval) and Pro (5 monitors, 1-min
  interval) via Polar.sh subscriptions.
- **Guardrails** — private/internal targets are refused (SSRF guard), per-plan
  monitor caps and interval floors.

## Local development

Prerequisites: Docker (or [OrbStack](https://orbstack.dev)), [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
cp .env.example .env   # adjust ports if 5432/6379/8000 are taken
make init              # start Postgres+Redis containers, migrate, npm install
make dev               # Django dev server + Vite dev server
make celery            # in a second terminal: Celery worker + beat
```

App: http://localhost:8000 (or your `DJANGO_PORT`).

Other useful targets: `make test`, `make migrate`, `make manage ARGS="..."`,
`make ruff`. Run `make` to list them all.

## Deploying on Kubernetes

See [`deploy/`](deploy/) for Kustomize manifests (CloudNativePG Postgres,
Redis, web/worker/beat Deployments, migrate Job) with overlays for local kind
and for a production cluster, plus [`scripts/kind-up.sh`](scripts/) for a
one-command local bring-up. A full walkthrough — including creating a managed
cluster on PAASBOX and going live with TLS — ships with the manifests.

## License

MIT — see [LICENSE](LICENSE). Original boilerplate copyright
Elodin Labs LLC (SaaS Pegasus); UpCheck modifications copyright Mitja Martini.
