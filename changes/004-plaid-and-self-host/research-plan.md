# Research: build-plan pass (Plaid sync mechanics + Tailscale k8s operator)

> Date: 2026-08-26
> Why: the grill (`grill-findings.md`) interrogated the pivot at the
> architecture level. Writing the actual plan+specs surfaced two more
> load-bearing facts that needed verification before locking constraints —
> both corrected `context/plaid-integration.md` in place rather than being
> restated here.

## Plaid `/transactions/sync` — cursor model, not date windowing
Source: https://plaid.com/docs/api/products/transactions/#transactionssync

- No `start-date`/`end-date`. First call omits `cursor` → full history (90-day
  default). Every later call passes `next_cursor` → only what changed.
- Response: `added`, `modified`, `removed` (`transaction_id` + `account_id`
  per entry — an explicit deletion signal, not an absence inference),
  `next_cursor`, `has_more`.
- **Changes a resolution from `grill-findings.md`**: that grill resolved
  "never delete a local Transaction based on absence from a sync response,"
  reasoned specifically around SimpleFIN's windowed-absence ambiguity. Plaid's
  `removed` array is authoritative, not an absence inference — deleting on
  Plaid's explicit signal is correct and safe. Recorded as its own finding in
  `plan.md`'s Grill rather than silently overriding the earlier one.

## Plaid rate limits
Source: https://plaid.com/docs/errors/rate-limit-exceeded/ (via search,
cross-referenced against community reports)

- Production `/transactions/sync`: 50 requests/minute per Item, 2,500/minute
  per client. Not a daily cap. For a single-user on-demand app, unreachable
  under normal use — the SimpleFIN-style client-side rate-limiter (rolling
  window counter on `User`) is dropped for Plaid, not carried over.

## Tailscale Kubernetes Operator
Sources: https://tailscale.com/docs/kubernetes-operator/ingress,
https://tailscale.com/docs/kubernetes-operator/ingress/expose-workload-to-tailnet-l3,
https://tailscale.com/docs/kubernetes-operator/quickstart

- Installed via Helm into the cluster; authenticates using a Tailscale OAuth
  client (scoped to a tag, e.g. `tag:k8s-operator`).
- Two exposure layers: L7 (HTTP/HTTPS, via a Kubernetes `Ingress` with the
  `tailscale` `ingressClassName`) or L3 (TCP/UDP, via a `Service` with
  `loadBalancerClass: tailscale`).
- L7 Ingress gets automatic HTTPS and a stable MagicDNS hostname
  (`<name>.<tailnet>.ts.net`) — the right fit for a web app (HTTP API +
  SPA), not L3.
- Known limitation as of this research (tracked upstream, July 2026): an
  Ingress and a Service can't currently share one tailnet identity — not a
  blocker here since this deploy only needs one Ingress-fronted entry point.

## k3s defaults relevant to this deploy
- Ships with `local-path-provisioner` as the default `StorageClass` — usable
  for a single-node Postgres `PersistentVolumeClaim` without installing
  anything extra.
- Default datastore is embedded SQLite (not etcd) for a single-node
  cluster — HA/etcd only matters if this becomes multi-node, which isn't in
  scope.
- Secrets are NOT encrypted at rest by default; `--secrets-encryption` is an
  install-time flag. Given this app stores a bank-access credential, this is
  a real constraint, not a nice-to-have — see `plan.md`.
