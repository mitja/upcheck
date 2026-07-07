#!/usr/bin/env bash
# Bring up UpCheck on a local kind cluster, end to end:
# cluster -> CNPG operator -> image build+load -> manifests -> migrate -> ready.
# Idempotent: safe to re-run after code changes (rebuilds + reloads the image).
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER="${KIND_CLUSTER:-upcheck}"
CNPG_MANIFEST="${CNPG_MANIFEST:-https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.30/releases/cnpg-1.30.0.yaml}"

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER"
else
  echo "kind cluster '$CLUSTER' already exists"
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

echo "==> Installing CloudNativePG operator"
kubectl apply --server-side -f "$CNPG_MANIFEST"
kubectl -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=180s

echo "==> Building and loading the app image"
docker build -t upcheck:dev .
kind load docker-image upcheck:dev --name "$CLUSTER"

echo "==> Applying manifests (overlays/kind)"
kubectl apply -k deploy/overlays/kind

echo "==> Waiting for Postgres (first CNPG bootstrap pulls the operand image — can take a few minutes)"
kubectl -n upcheck wait --for=condition=Ready cluster/pg --timeout=420s

echo "==> Running migrations"
kubectl -n upcheck delete job upcheck-migrate --ignore-not-found
kubectl apply -f deploy/overlays/kind/migrate-job.yaml
kubectl -n upcheck wait --for=condition=complete job/upcheck-migrate --timeout=300s

echo "==> Restarting deployments to pick up the fresh image, waiting for rollout"
kubectl -n upcheck rollout restart deploy/web deploy/worker deploy/beat
kubectl -n upcheck rollout status deploy/web deploy/worker deploy/beat --timeout=300s

echo
echo "UpCheck is up. Open it with:"
echo "  kubectl -n upcheck port-forward svc/web 8080:8000"
echo "  open http://localhost:8080"
