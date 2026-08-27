#!/usr/bin/env bash
# Deploy/smoke verification for spec/self-hosted-deploy.md — asserts the
# spec's Done-when criteria against a real k3s-over-Tailscale deployment.
#
# This is NOT a pytest file: it verifies infrastructure (cluster reachable
# only over the tailnet, pods Ready, data survives a pod restart, secrets
# protected at rest), not application behavior — see that spec's Notes on
# why a shell script fits this contract better than the project's usual
# pytest+Postgres convention.
#
# Run from a Tailscale-joined machine, with kubectl pointed at the target
# k3s cluster. Exits non-zero on the first failed check, with a message
# naming which Done-when criterion failed.
#
# Before the cluster/manifests exist (pre-auto-build), every check below is
# expected to fail — that's this script's "confirmed red" state, the
# infra-verification equivalent of a 404 on a not-yet-implemented route.
set -euo pipefail

TAILNET_HOSTNAME="${TAILNET_HOSTNAME:?Set TAILNET_HOSTNAME, e.g. balancezero.your-tailnet.ts.net}"
NAMESPACE="${NAMESPACE:-balancezero}"
POSTGRES_STATEFULSET="${POSTGRES_STATEFULSET:-postgres}"
# Setup parameterization (was hardcoded to the local dev database's
# balancezero_dev credentials — a setup bug, the deployed cluster uses
# its own user/db): overridable, defaulting to deploy/k8s/postgres.yaml's.
DB_USER="${DB_USER:-balancezero}"
DB_NAME="${DB_NAME:-balancezero}"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

echo "== 1. Pods Ready in namespace '$NAMESPACE' =="
if ! kubectl get pods -n "$NAMESPACE" >/dev/null 2>&1; then
  fail "cannot reach cluster / namespace '$NAMESPACE' doesn't exist yet — nothing deployed"
fi
POD_LIST=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null || true)
if [ -z "$POD_LIST" ]; then
  fail "no pods found in namespace '$NAMESPACE' — nothing deployed yet"
fi
NOT_READY=$(echo "$POD_LIST" | grep -v "Running\|Completed" || true)
if [ -n "$NOT_READY" ]; then
  fail "pods not Ready:
$NOT_READY"
fi
echo "OK — all pods Ready."

echo ""
echo "== 2. App reachable over the tailnet at https://$TAILNET_HOSTNAME/api/health =="
HEALTH_RESPONSE=$(curl -sf --max-time 10 "https://$TAILNET_HOSTNAME/api/health" || true)
if [ "$HEALTH_RESPONSE" != '{"status":"ok"}' ]; then
  fail "GET https://$TAILNET_HOSTNAME/api/health did not return {\"status\":\"ok\"} (got: '$HEALTH_RESPONSE')"
fi
echo "OK — health check passed."

echo ""
echo "== 3. NOT publicly resolvable (best-effort negative check) =="
# MagicDNS hostnames only resolve via Tailscale's own DNS (100.100.100.100)
# or a tailnet-joined client's injected resolver — a public resolver should
# have no record at all. This doesn't prove the app is unreachable from the
# public internet by itself (that also depends on no Funnel being enabled),
# but a public A/AAAA record existing would be a real red flag worth
# stopping on.
if command -v dig >/dev/null 2>&1; then
  PUBLIC_RECORD=$(dig +short "@1.1.1.1" "$TAILNET_HOSTNAME" A 2>/dev/null || true)
  if [ -n "$PUBLIC_RECORD" ]; then
    fail "public DNS (1.1.1.1) resolved $TAILNET_HOSTNAME to $PUBLIC_RECORD — expected no record. Check whether Funnel got enabled by mistake."
  fi
  echo "OK — no public DNS record (as expected for a private-tailnet-only deploy)."
else
  echo "SKIPPED — 'dig' not available, can't check public DNS resolution."
fi

echo ""
echo "== 4. Postgres data survives a pod restart =="
MARKER_BEFORE=$(kubectl exec -n "$NAMESPACE" "$POSTGRES_STATEFULSET-0" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT count(*) FROM \"user\" WHERE is_demo = true;" 2>/dev/null || true)
if [ "$MARKER_BEFORE" != "1" ]; then
  fail "expected exactly 1 demo user before restart (found: '$MARKER_BEFORE') — is the app seeded?"
fi
kubectl delete pod -n "$NAMESPACE" "$POSTGRES_STATEFULSET-0" >/dev/null
# There's a window between the old pod vanishing and the StatefulSet
# creating its replacement where `kubectl wait` errors NotFound instead of
# waiting (hit in practice on the first real run) — poll until the new pod
# object exists, then wait for Ready.
for _ in $(seq 1 30); do
  kubectl get pod -n "$NAMESPACE" "$POSTGRES_STATEFULSET-0" >/dev/null 2>&1 && break
  sleep 2
done
kubectl wait --for=condition=Ready pod -n "$NAMESPACE" "$POSTGRES_STATEFULSET-0" --timeout=120s >/dev/null
MARKER_AFTER=$(kubectl exec -n "$NAMESPACE" "$POSTGRES_STATEFULSET-0" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT count(*) FROM \"user\" WHERE is_demo = true;" 2>/dev/null || true)
if [ "$MARKER_AFTER" != "1" ]; then
  fail "demo user missing after Postgres pod restart — data isn't persisting via the PVC (found: '$MARKER_AFTER')"
fi
echo "OK — data survived pod restart, PVC is doing its job."

echo ""
echo "== 5. Secrets protected on the raw k3s datastore file (not just via kubectl RBAC) =="
# --secrets-encryption protects the datastore file on disk from someone
# bypassing the Kubernetes API entirely — kubectl access is gated by RBAC
# regardless of this flag, so this check deliberately does NOT use
# `kubectl get secret`. Uses `kubectl debug node` to inspect the host's
# datastore file without needing separate SSH access.
#
# Positive assertion: count the aescbc encryption envelopes k3s writes
# ("k8s:enc:aescbc:v1:<keyname>:" prefixes every stored Secret value and
# every retained revision). An earlier version instead grepped the
# datastore for the *plaintext* strings "PLAID_SECRET"/"plaid_access_...";
# that needle was embedded in the debug pod's own command, which k3s then
# persisted as a pod object in state.db, so the check matched its own probe
# and every re-run piled up another false "plaintext hit". A healthy
# encrypted cluster shows dozens of envelopes; the probe pod's own command
# string contributes at most a handful of stray matches, hence the
# threshold rather than a bare >0.
NODE_NAME="${NODE_NAME:-$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)}"
ENVELOPE_MIN="${ENVELOPE_MIN:-10}"
if [ -z "$NODE_NAME" ]; then
  echo "SKIPPED — couldn't determine node name; set NODE_NAME to check secrets-at-rest."
else
  # Default k3s embedded datastore path for single-node (SQLite, not etcd).
  ENVELOPE_HITS=$(kubectl debug "node/$NODE_NAME" -q -it --image=busybox --profile=general -- \
    sh -c "strings /host/var/lib/rancher/k3s/server/db/state.db 2>/dev/null | grep -c 'k8s:enc:aescbc:' || true" 2>/dev/null | tr -dc '0-9' || echo "")
  # The debugger pod is not auto-removed; drop it so repeat runs don't pile up.
  for p in $(kubectl get pod -n default -o name 2>/dev/null | grep node-debugger || true); do
    kubectl delete "$p" -n default --wait=false >/dev/null 2>&1 || true
  done

  if [ -z "$ENVELOPE_HITS" ]; then
    echo "SKIPPED — couldn't inspect the node's datastore file (permissions or debug-pod support). Verify --secrets-encryption manually."
  elif [ "$ENVELOPE_HITS" -lt "$ENVELOPE_MIN" ]; then
    fail "only $ENVELOPE_HITS aescbc encryption envelope(s) in the raw datastore (expected >= $ENVELOPE_MIN) — --secrets-encryption may not be enabled"
  else
    echo "OK — $ENVELOPE_HITS aescbc encryption envelopes in the datastore; secrets are encrypted at rest."
  fi
fi

echo ""
echo "All checks passed."
