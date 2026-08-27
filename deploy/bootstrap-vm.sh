#!/usr/bin/env bash
# One-shot: stand BalanceZero up on a fresh tailnet-joined Linux VM
# (built for Oracle Cloud Free Tier arm64 / Ubuntu 22.04, works on any k3s host).
#
#   1. Launch the VM, note nothing else — no ports opened.
#   2. Fill in the CONFIG block below.
#   3. scp this repo to the VM (or `git clone` it there), then:  bash deploy/bootstrap-vm.sh
#   4. `shred -u deploy/bootstrap-vm.sh` afterwards — it holds secrets while you edit it.
#
# Idempotent-ish: safe to re-run; skips installs that are already present.
# Full rationale: deploy/README.md.
set -euo pipefail

# ============================== CONFIG ======================================
# Your tailnet's MagicDNS suffix, e.g. tailbae83d  (the app becomes
# balancezero.<TAILNET_NAME>.ts.net). Must match ALLOWED_ORIGIN in
# deploy/k8s/backend.yaml — this script rewrites that file if it differs.
TAILNET_NAME="tailbae83d"

# Tailscale auth key for THIS node (admin console -> Settings -> Keys ->
# Generate auth key; reusable/ephemeral both fine). Leave blank to auth
# interactively via a browser URL instead.
TS_AUTHKEY=""

# Kubernetes operator OAuth client (admin console -> Settings -> OAuth
# clients; scopes Devices Core + Auth Keys write, tag tag:k8s-operator).
TS_OAUTH_CLIENT_ID=""
TS_OAUTH_CLIENT_SECRET=""

# Plaid PRODUCTION credentials (dashboard -> Team Settings -> Keys).
PLAID_CLIENT_ID=""
PLAID_SECRET=""

# Fernet key that encrypts stored Plaid access tokens. Leave blank to
# generate a fresh one (every user re-links). To CARRY the connections
# already in your dev.sh database, paste that key here AND set DEV_DB_DUMP.
PLAID_ENCRYPTION_KEY=""

# Optional: path (on this VM) to a `pg_dump` of your dev database to
# restore after deploy. Produce it on the dev box with:
#   docker exec balancezero-dev-db-1 pg_dump -U balancezero_dev balancezero_dev > bz.sql
DEV_DB_DUMP=""
# ===========================================================================

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || die "run this on the Linux VM, not your dev machine"
[[ -f deploy/k8s/backend.yaml ]] || die "run from the repo root (or via deploy/bootstrap-vm.sh)"
for v in TAILNET_NAME TS_OAUTH_CLIENT_ID TS_OAUTH_CLIENT_SECRET PLAID_CLIENT_ID PLAID_SECRET; do
  [[ -n "${!v}" ]] || die "CONFIG: $v is empty"
done

# --- 1. Tailscale --------------------------------------------------------------
if ! command -v tailscale >/dev/null; then
  log "Installing Tailscale"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale status >/dev/null 2>&1; then
  log "Bringing this node onto the tailnet"
  if [[ -n "$TS_AUTHKEY" ]]; then sudo tailscale up --authkey "$TS_AUTHKEY" --ssh
  else sudo tailscale up --ssh; fi
fi

# --- 2. k3s ------------------------------------------------------------------
if ! command -v k3s >/dev/null; then
  log "Installing k3s (single node, secrets encryption on)"
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_EXEC="--secrets-encryption --write-kubeconfig-mode 644" sh -
fi
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl() { command k3s kubectl "$@"; }

# --- 3. Oracle Ubuntu iptables fix ----------------------------------------
# Oracle's images block pod/service traffic -> CoreDNS never goes Ready.
log "Allowing k3s cluster CIDRs through the host firewall"
for cidr in 10.42.0.0/16 10.43.0.0/16; do
  sudo iptables -C INPUT -s "$cidr" -j ACCEPT 2>/dev/null || \
    sudo iptables -I INPUT 1 -s "$cidr" -j ACCEPT
done
command -v netfilter-persistent >/dev/null && sudo netfilter-persistent save || \
  sudo sh -c 'iptables-save > /etc/iptables/rules.v4' 2>/dev/null || true

log "Waiting for the node and CoreDNS to be Ready"
kubectl wait --for=condition=Ready node --all --timeout=180s
kubectl -n kube-system rollout status deploy/coredns --timeout=180s

# --- 4. Helm + Tailscale Kubernetes operator ------------------------------
if ! command -v helm >/dev/null; then
  log "Installing helm"
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
log "Installing the Tailscale operator"
helm repo add tailscale https://pkgs.tailscale.com/helmcharts >/dev/null
helm repo update >/dev/null
helm upgrade --install tailscale-operator tailscale/tailscale-operator \
  --namespace tailscale --create-namespace \
  --set-string oauth.clientId="$TS_OAUTH_CLIENT_ID" \
  --set-string oauth.clientSecret="$TS_OAUTH_CLIENT_SECRET" \
  --wait

# --- 5. Build + import images (arm64, on-host) ----------------------------
command -v docker >/dev/null || die "install docker first:  sudo apt-get install -y docker.io && sudo usermod -aG docker \$USER  (re-login)"
log "Building images"
docker build -f deploy/Dockerfile.backend  -t balancezero-backend:latest  .
docker build -f deploy/Dockerfile.frontend -t balancezero-frontend:latest .
log "Importing images into k3s' containerd"
docker save balancezero-backend:latest balancezero-frontend:latest | sudo k3s ctr images import -

# --- 6. Hostname / config ------------------------------------------------
if [[ "$TAILNET_NAME" != "tailbae83d" ]]; then
  log "Rewriting hostname in backend.yaml to $TAILNET_NAME"
  sed -i "s/balancezero\.tailbae83d\.ts\.net/balancezero.${TAILNET_NAME}.ts.net/g" deploy/k8s/backend.yaml
fi

# --- 7. Namespace + secrets --------------------------------------------
log "Creating namespace + secrets"
kubectl apply -f deploy/k8s/namespace.yaml
enc_key="${PLAID_ENCRYPTION_KEY:-$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')}"
pgpw="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
kubectl -n balancezero delete secret balancezero-secrets --ignore-not-found
kubectl -n balancezero create secret generic balancezero-secrets \
  --from-literal=SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --from-literal=PLAID_ENCRYPTION_KEY="$enc_key" \
  --from-literal=POSTGRES_PASSWORD="$pgpw" \
  --from-literal=PLAID_CLIENT_ID="$PLAID_CLIENT_ID" \
  --from-literal=PLAID_SECRET="$PLAID_SECRET" \
  --from-literal=DATABASE_URL="postgresql://balancezero:${pgpw}@postgres:5432/balancezero"
if [[ -z "$PLAID_ENCRYPTION_KEY" ]]; then
  printf '\n\033[1;33mNEW PLAID_ENCRYPTION_KEY (back this up now, offline):\033[0m\n%s\n' "$enc_key"
fi

# --- 8. Deploy --------------------------------------------------------------
log "Applying manifests"
kubectl apply -f deploy/k8s/
kubectl -n balancezero rollout status statefulset/postgres --timeout=180s
kubectl -n balancezero rollout status deploy/backend deploy/frontend --timeout=180s

# --- 9. Optional data restore --------------------------------------------
if [[ -n "$DEV_DB_DUMP" ]]; then
  [[ -f "$DEV_DB_DUMP" ]] || die "DEV_DB_DUMP not found: $DEV_DB_DUMP"
  log "Restoring $DEV_DB_DUMP into cluster Postgres"
  kubectl -n balancezero cp "$DEV_DB_DUMP" \
    "$(kubectl -n balancezero get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}')":/tmp/bz.sql
  kubectl -n balancezero exec -i statefulset/postgres -- \
    psql -U balancezero balancezero -v ON_ERROR_STOP=1 -f /tmp/bz.sql
fi

# --- 10. Demo user + done -----------------------------------------------
log "Seeding the demo user (skips if present)"
kubectl -n balancezero exec deploy/backend -- python3 seed_demo.py || true

cat <<DONE

\033[1;32mUp.\033[0m  https://balancezero.${TAILNET_NAME}.ts.net  (tailnet devices only)

Next:
  * Register  https://balancezero.${TAILNET_NAME}.ts.net/accounts  as an
    Allowed redirect URI in the Plaid dashboard (Team Settings -> API).
  * Verify:   TAILNET_HOSTNAME=balancezero.${TAILNET_NAME}.ts.net ./scripts/verify-deploy.sh
  * Mint an invite:  kubectl -n balancezero exec deploy/backend -- python3 mint_invite.py
  * shred -u deploy/bootstrap-vm.sh
DONE
