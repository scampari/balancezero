# Deploy: k3s over Tailscale (spec/self-hosted-deploy.md)

Self-hosted, private-tailnet-only deployment. The app is reachable at
`https://balancezero.<tailnet>.ts.net` from Tailscale-joined devices and
nowhere else — no Funnel, no public ingress.

Current host: k3d (the real k3s distribution, run in Docker) on the
development Mac — see `spec/self-hosted-deploy.md`'s Notes for why, and
what changes (nothing in these manifests) when this moves to a dedicated
Linux box later.

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
