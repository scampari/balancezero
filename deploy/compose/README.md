# Deploy: docker compose on a single tailnet host

Runs BalanceZero on one always-on Linux box (here: `samhome`, the tailnet
exit node) and publishes it at **`https://balancezero.<tailnet>.ts.net`**,
reachable only from Tailscale-joined devices. No Funnel, no public ingress,
no host ports published.

This is the lighter-weight alternative to the k3s design in
`../README.md`. Same images, same same-origin topology (nginx proxies
`/api` to the backend), same "migrations before app start" step.

| Container   | Image                          | Role                                             |
|-------------|--------------------------------|--------------------------------------------------|
| `db`        | `postgres:16`                  | App database, on the `db-data` volume            |
| `backend`   | `deploy/Dockerfile.backend`    | Flask API under gunicorn (`:5002`, internal)     |
| `frontend`  | `deploy/Dockerfile.frontend`   | nginx serving the built SPA + `/api` proxy (`:80`, internal) |
| `tailscale` | `tailscale/tailscale`          | Own tailnet node `balancezero`; `tailscale serve` terminates HTTPS -> `frontend:80` |

## Prerequisites

1. **Docker access without sudo** for your user (this box currently needs
   root for the Docker socket):
   ```sh
   sudo usermod -aG docker "$USER" && newgrp docker
   ```
   Or prefix every `docker compose` command below with `sudo`.

2. **Tailnet HTTPS certificates enabled** — admin console -> DNS ->
   *HTTPS Certificates*. (Already enabled for this tailnet during the k3s
   deploy; `tailscale serve` can't issue its cert without it.)

3. **The `balancezero` MagicDNS name must be free.** Only one tailnet
   device can hold it. If the old k3s/k3d deploy on `unions-macbook-pro`
   still owns it, tear that down first (`kubectl delete -f deploy/k8s/` or
   `k3d cluster delete balancezero`) and delete any stale `balancezero`
   device in the admin console — otherwise this node registers as
   `balancezero-1` and the Plaid redirect URI stops matching.

4. **A reusable Tailscale auth key** — admin console -> Settings -> Keys
   -> *Generate auth key*. "Reusable" on, "Ephemeral" off.

## First deploy

```sh
cd deploy/compose
cp .env.prod.example .env.prod
```

Fill in `.env.prod` (generator commands are in the file). For
`PLAID_ENCRYPTION_KEY`: generate a fresh key for production, or paste your
dev database's key if you plan to carry existing bank connections over
(see below). Back the key up offline.

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

The backend runs `flask db upgrade` before gunicorn starts, so the schema
is created on first boot. Watch it come up:

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f
```

The `tailscale` container logs will show the node authenticating and
`serve` config being applied.

## Register the Plaid redirect URI

In the Plaid dashboard (Team Settings -> API -> Allowed redirect URIs) add:

```
https://balancezero.<tailnet>.ts.net/accounts
```

exactly (no query string). Production Plaid requires `https://` — the
tailnet cert satisfies that. This value is already what `PUBLIC_ORIGIN` in
`.env.prod` derives, and what the old k3s ConfigMap used, so if it was
registered before it still applies.

## Seed the demo user / mint an invite

```sh
CO="docker compose -f docker-compose.prod.yml --env-file .env.prod"

$CO exec backend python3 seed_demo.py          # demo / demo-pw
$CO exec backend python3 mint_invite.py        # single-use signup code
```

## Carrying data over from the dev database (optional)

Keeps the connections/history in your local `dev.sh` database. Requires
`PLAID_ENCRYPTION_KEY` in `.env.prod` to be the **same** key the dev
database used (`dev.sh` default:
`Cf36XJcRZYQp9YWjLnryvcDl-SZ7D1b01e8wnS9QJAk=`), or every user re-links.

```sh
# dev database must be running (docker compose up -d dev-db from repo root)
docker exec balancezero-dev-db-1 pg_dump -U balancezero_dev --no-owner --no-privileges balancezero_dev > /tmp/bz.sql

CO="docker compose -f docker-compose.prod.yml --env-file .env.prod"
$CO exec -T db psql -U balancezero -d balancezero < /tmp/bz.sql
$CO restart backend
rm /tmp/bz.sql
```

## Verify

From another tailnet device:

```sh
curl -sS https://balancezero.<tailnet>.ts.net/api/health   # -> {"status": "ok"}
```

Then log in through the browser. Check the login/signup rate limiter isn't
bucketing every device together — if a second device gets rate-limited
immediately, `TRUSTED_PROXY_COUNT` in `docker-compose.prod.yml` is wrong
for this proxy chain (try `1`), then `up -d` again.

## SSH into the tailscale node

`TS_EXTRA_ARGS: --ssh` on the `tailscale` service enables Tailscale SSH on
the `balancezero` tailnet device, so you can get a shell without a public
port 22:

```sh
tailscale ssh balancezero        # -> root busybox shell in the tailscale container
```

Two requirements:

1. **A tailnet policy `ssh` rule.** Tailscale SSH is deny-all until the
   policy has an `ssh` block. In the admin console
   (login.tailscale.com/admin/acls) add, adjusting the users/tags to taste:

   ```json
   "ssh": [
     {
       "action": "accept",
       "src":    ["autogroup:member"],
       "dst":    ["tag:balancezero"],
       "users":  ["root"]
     }
   ]
   ```

   If the device isn't tagged, use its user (`"dst": ["autogroup:self"]`)
   or the device owner instead of `tag:balancezero`. `check` instead of
   `accept` forces re-auth per session.

2. **Recreate the container** so the new arg takes effect:

   ```sh
   cd deploy/compose
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d tailscale
   ```

   The `tailscale` container logs should then show `SSH enabled`. Verify
   from another tailnet device with `tailscale ssh balancezero true &&
   echo ok`.

This shell is a minimal Alpine/busybox environment (no app code, no
`docker`) — it's for `tailscale status` / `tailscale serve status`
diagnostics on the node itself. App containers are still reached with
`docker compose ... exec`.

## Update / redeploy

```sh
cd deploy/compose
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Rebuilds changed images and recreates only what changed. Migrations re-run
automatically on backend start.

## Backups (not automated here)

Before real reliance: schedule `pg_dump` off-box and keep
`PLAID_ENCRYPTION_KEY` backed up separately from the database.

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  exec -T db pg_dump -U balancezero --no-owner balancezero | gzip > "bz-$(date +%F).sql.gz"
```

## Stop / tear down

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod down          # keep data
docker compose -f docker-compose.prod.yml --env-file .env.prod down -v       # also delete the db + tailscale state volumes
```
