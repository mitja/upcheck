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

## Deploy on Vaicoa

[`deploy/vaicoa/`](deploy/vaicoa/) is an environment directory for a
[Vaicoa](https://vaicoa.com) Podman host: the hub polls this repository's
branch every minute and sends the directory's files to the host, whose agent
renders one Quadlet `.kube` unit per file. It is not Kubernetes; the format is
Vaicoa's [environment format](https://vaicoa.com/docs/reference/environment-format/).

| file | runs |
| --- | --- |
| `postgres.yaml` | PostgreSQL 17, data in the claim `upcheck-postgres` (replaces CloudNativePG) |
| `redis.yaml` | Redis, AOF in the claim `upcheck-redis` |
| `web.yaml` | gunicorn; its init container runs `migrate` and `bootstrap_celery_tasks` before every start |
| `worker.yaml`, `beat.yaml` | the Celery worker and beat |
| `caddy.yaml` | Caddy on the host's ports 80 and 443: TLS with an automatic certificate for the environment's URL |
| `config.yaml` | the settings, and `vaicoa-env.sh`, which web, worker and beat source before their command |
| `.vaicoa/web.yaml` | the entry point a twin's proxy uses (port 80) |

How it differs from the Kubernetes manifests:

- **Names.** The environment must be called `upcheck`: the YAML names the
  agent's ConfigMap `upcheck-vaicoa` and the secret `upcheck-secrets`. Pods
  reach each other by pod name (`postgres-pod`, `redis-pod`, `web-pod`), since
  Podman ignores Services.
- **Migrations** run in web's init container, not as a Job: on a Podman host a
  Job is a pod that ends, which the agent counts as unhealthy.
- **Hosts and TLS** come from the agent's ConfigMap: `vaicoa-env.sh` derives
  `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `PROJECT_URL` from `VAI_BASE_URL`,
  and `DATABASE_URL` from `POSTGRES_PASSWORD`. With `VAI_TLS=self` Caddy gets
  the certificate for `VAI_BASE_URL` (its DNS record must point at the host);
  a twin (`VAI_TLS=hub`) serves plain HTTP on port 80 behind the hub, and Django
  does not redirect to HTTPS there.
- **Images** are pinned by digest: the agent refuses a tag. A new release is a
  commit that changes the digests (`ghcr.io/mitja/upcheck@sha256:…`, the image
  CI pushes as `sha-<commit>`).
- **Health** is a `livenessProbe` with `exec`: Podman runs probes inside the
  container, and the image has no curl.

### 1. Point a host at the directory

```text
$ vai host create upcheck-1 --env production
$ vai api PUT /clusters/<host id>/environment '{"name": "upcheck", "repository": "https://github.com/mitja/upcheck.git", "branch": "main", "path": "deploy/vaicoa"}'
```

### 2. Encrypt the secrets

`secrets.prod.enc.env.example` lists the keys. Fill in a copy outside the
repository and encrypt it to the recipients the hub made for the environment:

```text
$ vai api GET /clusters/<host id>/environment      # recipients.cluster and recipients.twins
$ sops --encrypt --age <recipients.cluster> --input-type dotenv --output-type dotenv secrets.prod.env > deploy/vaicoa/secrets.prod.enc.env
$ sops --encrypt --age <recipients.twins>   --input-type dotenv --output-type dotenv secrets.twin.env > deploy/vaicoa/secrets.twin.enc.env
```

Commit only the `.enc.env` files. Use a different `POSTGRES_PASSWORD` and
`SECRET_KEY` for twins.

### 3. DNS and the first start

Point the environment's host name at the server and commit. Within about a
minute the host pulls the images, starts Postgres and Redis, migrates, and
Caddy fetches the certificate. `vai api GET /clusters/<host id>/environment`
shows the revision and each unit's health.

There is no `.vaicoa/seed.yaml`: a seed Job runs before any unit starts, on an
empty data volume, so Postgres is not running and the schema does not exist
yet. A twin without a seed starts with an empty database and migrates it.

### Server size

Measured on a Vaicoa Podman host (2026-10-24): a **cpx12** (1 vCPU, 2 GB).
The pods hold ~530 MiB idle, with 50 monitors checked every minute, and
~595 MiB at peak. The host kept ~870 MiB available, with no swap and no OOM
kill. The cached public status page served 300 req/s at p95 65 ms. The
logged-in monitor list, rendered on every request, saturated the vCPU at
~33 req/s (p95 0.9 s). A cpx02 (1 GB) is too small for this stack. For more
uncached throughput, take a cpx22 (2 vCPU).

## Observability

Everything is off by default, and turned on by environment variables alone:

- **Traces and metrics (OpenTelemetry).** Set the standard `OTEL_*` variables with an OTLP/HTTP
  endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`, or `..._TRACES_ENDPOINT` / `..._METRICS_ENDPOINT`), and
  `OTEL_SERVICE_NAME`. [`project/telemetry.py`](project/telemetry.py) then instruments Django,
  psycopg, Redis, requests and Celery. The trace context travels from beat through the queue to the
  worker. Set up once per process after the fork: gunicorn's `post_fork`
  ([`gunicorn.conf.py`](gunicorn.conf.py)) and Celery's `worker_process_init`/`beat_init`. Besides
  the instrumentations' own metrics there is `upcheck.checks` (by outcome). Without an endpoint,
  nothing is set up.
- **Structured logs.** `LOG_FORMAT=json` writes one JSON object per line: `time`, `level`, `logger`,
  `message`, and inside a span `trace_id`/`span_id`, so a log line links to its trace.
- **Events.** Business events are log fields: `monitor_created`, `monitor_deleted`, `monitor_up`,
  `monitor_down`, logged as `extra={"event": ...}`. A log pipeline can count them into metrics
  without a code change. The paasbox platform turns them into `saas_app_events`.

The paasbox `SaaSApplication` sets all of this with `telemetry: {otlp: true}` and
`env: [{name: LOG_FORMAT, value: json}]`.

## License

MIT — see [LICENSE](LICENSE). Original boilerplate copyright
Elodin Labs LLC (SaaS Pegasus); UpCheck modifications copyright Mitja Martini.
