#!/usr/bin/env bash
# Tear down the local kind cluster created by kind-up.sh.
set -euo pipefail
kind delete cluster --name "${KIND_CLUSTER:-upcheck}"
