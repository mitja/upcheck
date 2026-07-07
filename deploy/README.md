# Deploying UpCheck on Kubernetes

One image (`ghcr.io/mitja/upcheck`, amd64+arm64) runs four roles via command
overrides: **web** (gunicorn + WhiteNoise), **worker** (Celery), **beat**
(scheduler, single replica), and the one-off **migrate** Job. Postgres runs
via the [CloudNativePG](https://cloudnative-pg.io) operator (it generates the
`pg-app` Secret whose `uri` key becomes `DATABASE_URL`); Redis is a plain
single-instance Deployment.

```
deploy/
  base/                 shared manifests (namespace, config, CNPG, redis, web, worker, beat)
  overlays/kind/        local development on kind (plain HTTP via port-forward)
  overlays/paasbox/     production: ingress + TLS at upcheck.paasbox.com, hcloud volumes
  cluster-issuer.yaml   Let's Encrypt ClusterIssuer (apply once per cluster)
```

The migrate Job is deliberately **not** part of the kustomizations — Jobs are
immutable, so it's applied explicitly per release (delete, then apply; see the
per-overlay `migrate-job.yaml`). It runs `manage.py migrate` and
`manage.py bootstrap_celery_tasks` (which registers the beat schedule).

## Local: kind

```bash
./scripts/kind-up.sh     # cluster -> CNPG operator -> build+load image -> deploy -> migrate
kubectl -n upcheck port-forward svc/web 8080:8000
open http://localhost:8080
./scripts/kind-down.sh   # tear down
```

After code changes, re-run `./scripts/kind-up.sh` — it rebuilds the image,
reloads it into kind, re-runs migrations, and restarts the deployments.

## Production: a managed cluster on PAASBOX

[PAASBOX](https://paasbox.com) provides managed Gardener-based Kubernetes on
Hetzner Cloud. Any conformant cluster with a cloud LoadBalancer works the same
way — only step 1 is PAASBOX-specific.

### 1. Create the cluster

In the PAASBOX portal ([console.paasbox.com](https://console.paasbox.com)):
sign up → add a payment method → **Composer → Create cluster**. Pick region
`nbg1`, Kubernetes 1.35, and one worker pool (a `cpx32` / 4 vCPU / 8 GB worker
is plenty for UpCheck). Wait for the cluster to become **Ready**, then
**download the kubeconfig** (admin kubeconfigs are short-lived — 8h — so
re-download for later maintenance sessions):

```bash
export KUBECONFIG=~/Downloads/upcheck-demo.kubeconfig
kubectl get nodes -o wide   # sanity check
```

### 2. Install the cluster add-ons (once)

```bash
# CloudNativePG operator
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.30/releases/cnpg-1.30.0.yaml

# ingress-nginx — the Service of type LoadBalancer gets a Hetzner LB
# provisioned automatically by the cloud-controller-manager
helm upgrade --install ingress-nginx ingress-nginx \
  --repo https://kubernetes.github.io/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.annotations."load-balancer\.hetzner\.cloud/location"=nbg1

# cert-manager + Let's Encrypt issuer
helm upgrade --install cert-manager cert-manager \
  --repo https://charts.jetstack.io \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true
kubectl apply -f deploy/cluster-issuer.yaml   # edit the email first
```

### 3. DNS

Get the load balancer's IP and point your host at it (the overlay uses
`upcheck.paasbox.com` — change the host in `overlays/paasbox/` for your own
domain):

```bash
kubectl -n ingress-nginx get svc ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
# create an A record: upcheck.example.com -> <that IP>
```

### 4. Secrets

Created out-of-band, never committed. The Polar values are optional — leave
them out to run without billing (all monitors on the Free plan rules):

```bash
kubectl create namespace upcheck
kubectl -n upcheck create secret generic upcheck-secrets \
  --from-literal=SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  --from-literal=POLAR_ACCESS_TOKEN="..." \
  --from-literal=POLAR_WEBHOOK_SECRET="..." \
  --from-literal=POLAR_PRODUCT_ID_PRO="..." \
  --from-literal=POLAR_CHECKOUT_URL_PRO="..."
```

### 5. Deploy

```bash
kubectl apply -k deploy/overlays/paasbox

# wait for Postgres, then run migrations
kubectl -n upcheck wait --for=condition=Ready cluster/pg --timeout=420s
kubectl -n upcheck delete job upcheck-migrate --ignore-not-found
kubectl apply -f deploy/overlays/paasbox/migrate-job.yaml
kubectl -n upcheck wait --for=condition=complete job/upcheck-migrate --timeout=300s

kubectl -n upcheck get pods
curl -I https://upcheck.paasbox.com   # valid Let's Encrypt cert + 200
```

The Let's Encrypt certificate is issued automatically via the
`cert-manager.io/cluster-issuer` annotation on the Ingress (HTTP-01 — DNS must
resolve before the challenge can pass).

### 6. Polar webhook (if billing is enabled)

In the Polar dashboard (sandbox or production), point a webhook endpoint at
`https://<your-host>/polar/webhook/` with the same secret as
`POLAR_WEBHOOK_SECRET`.

### Releases

CI pushes `ghcr.io/mitja/upcheck:latest` and `:sha-<commit>` on every commit
to main. For reproducible deploys, pin `newTag` in
`overlays/paasbox/kustomization.yaml` (and the image in its `migrate-job.yaml`)
to a `sha-` tag, then:

```bash
kubectl apply -k deploy/overlays/paasbox
kubectl -n upcheck delete job upcheck-migrate --ignore-not-found
kubectl apply -f deploy/overlays/paasbox/migrate-job.yaml
kubectl -n upcheck rollout restart deploy/web deploy/worker deploy/beat
```
