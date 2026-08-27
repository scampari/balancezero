# Deploy: k3s over Tailscale (spec/self-hosted-deploy.md)

Self-hosted, private-tailnet-only deployment. The app is reachable at
`https://balancezero.<tailnet>.ts.net` from Tailscale-joined devices and
nowhere else — no Funnel, no public ingress.

Current host: k3d (the real k3s distribution, run in Docker) on the
development Mac. Moving to a small always-on Linux box (a cloud VM joined
to the tailnet, then a home server) — see **Dedicated Linux host** below;
the manifests are the same, only the cluster/image steps differ.

## Dedicated Linux host (k3s on a VM)

An interim step off the laptop: a tiny tailnet-joined VM (2 GB RAM /
1 vCPU / 20 GB disk is enough — Hetzner CX22, a DO/Vultr/Linode 2 GB
instance, or Oracle Cloud's always-free ARM). No public inbound ports —
Tailscale dials out — so lock the provider firewall to deny all inbound
(SSH over Tailscale too).

### Oracle Cloud Free Tier (arm64) — the $0 interim host

- **Shape:** `VM.Standard.A1.Flex`, 2 OCPU / 12 GB, Ubuntu 22.04. Always
  free. The free ARM pool is often "Out of host capacity" — retry, or
  switch Availability Domain / region.
- **Cloud firewall:** leave the default Security List as-is (SSH only, or
  drop SSH and use Tailscale SSH). Nothing needs opening.
- **Host firewall gotcha:** Oracle's Ubuntu images ship restrictive
  `iptables` rules that block k3s pod/CNI traffic (CoreDNS never goes
  ready). After installing k3s, allow the cluster CIDRs and persist:
  ```sh
  sudo iptables -I INPUT 1 -s 10.42.0.0/16 -j ACCEPT   # pods
  sudo iptables -I INPUT 1 -s 10.43.0.0/16 -j ACCEPT   # services
  sudo netfilter-persistent save
  ```
- **Images: build on the VM** (it's arm64 — don't copy images or
  `node_modules` from an x86/mac dev box):
  ```sh
  git clone https://github.com/<you>/balancezero && cd balancezero
  docker build -f deploy/Dockerfile.backend  -t balancezero-backend  .
  docker build -f deploy/Dockerfile.frontend -t balancezero-frontend .
  docker save balancezero-backend balancezero-frontend | sudo k3s ctr images import -
  ```
  (If `npm ci` errors on a rollup platform binary: `rm frontend/package-lock.json`
  and let `npm install` regenerate it on-host.) Every Dockerfile base
  (`python:3.13-slim`, `node:22-slim`, `nginx:1.27-alpine`, `postgres:16`)
  publishes arm64, so no Dockerfile changes.
- k3s and Tailscale both ship arm64 installers — the commands below are
  unchanged.

1. **Tailscale on the VM**
   ```sh
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up            # authenticate to the SAME tailnet as the OAuth client
   ```

2. **k3s (single node)**
   ```sh
   curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--secrets-encryption --write-kubeconfig-mode 644" sh -
   export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
   ```
   `--secrets-encryption` is required, same reason as the k3d flag — this
   cluster stores a real bank-access credential.

3. **Free the MagicDNS name first.** Only one `balancezero` Ingress can
   exist per tailnet. On the dev Mac: `kubectl delete -f deploy/k8s/ingress.yaml`
   (or `k3d cluster delete balancezero`) *before* applying on the VM, or
   the VM's Ingress registers as `balancezero-1.<tailnet>.ts.net` and
   `ALLOWED_ORIGIN` / `PLAID_REDIRECT_URI` no longer match.

4. **Images — no `k3d image import` here.** Either:
   - build on the VM (needs Docker/buildkit) and
     `docker save balancezero-backend balancezero-frontend | sudo k3s ctr images import -`, then re-run after each build; or
   - push to a registry (e.g. `ghcr.io/<you>/balancezero-backend`), set
     the two `image:` fields + `imagePullPolicy: Always`, add an
     `imagePullSecrets` if the package is private.

5. **Operator + secrets + deploy** — steps 4–6 of *One-time setup* below,
   unchanged. In step 5 use the **Production** `PLAID_CLIENT_ID`/`SECRET`
   (the ConfigMap now sets `PLAID_ENV: production` and
   `PLAID_REDIRECT_URI`). Verify `PLAID_REDIRECT_URI` is a registered
   "Allowed redirect URI" in the Plaid dashboard.

6. **Carrying existing data (optional).** To keep the connections/history
   already in your local `dev.sh` database:
   ```sh
   # from the dev machine
   docker exec balancezero-dev-db-1 pg_dump -U balancezero_dev balancezero_dev > bz.sql
   kubectl -n balancezero cp bz.sql "$(kubectl -n balancezero get pod -l app=postgres -o name | cut -d/ -f2):/tmp/bz.sql"
   kubectl -n balancezero exec -it statefulset/postgres -- psql -U balancezero balancezero -f /tmp/bz.sql
   ```
   The stored Plaid tokens only decrypt with the **same
   `PLAID_ENCRYPTION_KEY`** — put your dev key in the Secret, or expect
   every user to re-link. (Rotate to a fresh key once the home server is
   the real home.)

7. **Verify** with `./scripts/verify-deploy.sh` (below), then hit the app
   from another tailnet device and check the login/signup rate limiter
   isn't keying every device to one bucket (adjust `TRUSTED_PROXY_COUNT`
   in the ConfigMap if so).

8. **Backups** aren't in these manifests yet — before real people rely on
   it, add a `pg_dump` CronJob writing off-box, and keep
   `PLAID_ENCRYPTION_KEY` backed up separately.

## One-time setup

### 1. Tailscale OAuth client (manual, admin console)

The Kubernetes operator authenticates to your tailnet with an OAuth
client. In the [Tailscale admin console](https://login.tailscale.com/admin):

1. **ACLs** — add:
   ```json
   "tagOwners": { "tag:k8s-operator": [], "tag:k8s": ["tag:k8s-operator"] }
   ```
2. **Settings → OAuth clients → Generate** — scopes `Devices Core` (write)
   and `Auth Keys` (write), tag `tag:k8s-operator`. Keep the client
   ID/secret for step 4. Never commit them.

### 2. Cluster

```sh
# --secrets-encryption is required, not optional hardening — this cluster
# stores a real bank-access credential. See spec/self-hosted-deploy.md.
k3d cluster create balancezero --k3s-arg "--secrets-encryption@server:*"
```

No `-p` port mappings on purpose: nothing is published to the host —
tailnet traffic arrives via the operator's proxy pods, which dial *out*
to Tailscale.

### 3. Build + import images

From the repo root:

```sh
docker build -f deploy/Dockerfile.backend  -t balancezero-backend  .
docker build -f deploy/Dockerfile.frontend -t balancezero-frontend .
k3d image import -c balancezero balancezero-backend balancezero-frontend
```

### 4. Tailscale operator

```sh
helm repo add tailscale https://pkgs.tailscale.com/helmcharts
helm repo update
helm upgrade --install tailscale-operator tailscale/tailscale-operator \
  --namespace tailscale --create-namespace \
  --set-string oauth.clientId="<OAUTH_CLIENT_ID>" \
  --set-string oauth.clientSecret="<OAUTH_CLIENT_SECRET>" \
  --wait
```

### 5. App secrets

Created imperatively — never committed (see `secrets.example.yaml` for the
shape only):

```sh
kubectl apply -f deploy/k8s/namespace.yaml
kubectl create secret generic balancezero-secrets -n balancezero \
  --from-literal=SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --from-literal=PLAID_ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --from-literal=POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" \
  --from-literal=PLAID_CLIENT_ID="<your Plaid client id>" \
  --from-literal=PLAID_SECRET="<your Plaid sandbox secret>"
# DATABASE_URL references the generated password:
PGPW=$(kubectl get secret balancezero-secrets -n balancezero -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
kubectl patch secret balancezero-secrets -n balancezero -p \
  "{\"stringData\":{\"DATABASE_URL\":\"postgresql://balancezero:${PGPW}@postgres:5432/balancezero\"}}"
```

## Deploy / redeploy

```sh
kubectl apply -f deploy/k8s/
kubectl rollout status -n balancezero deploy/backend deploy/frontend
```

On app changes: rebuild + `k3d image import` (step 3), then
`kubectl rollout restart -n balancezero deploy/backend deploy/frontend`.

## Seed the demo user (first deploy)

```sh
kubectl exec -n balancezero deploy/backend -- python3 seed_demo.py
```

## Verify

From any Tailscale-joined machine:

```sh
TAILNET_HOSTNAME=balancezero.<tailnet>.ts.net ./scripts/verify-deploy.sh
```

Asserts the spec's Done-when criteria: pods Ready, health check over the
tailnet, no public DNS record, Postgres data survives a pod restart,
secrets not plaintext in the raw datastore.
