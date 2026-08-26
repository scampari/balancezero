---
status: planned
depends_on: [frontend-app.md, budget-api.md]
---

# Self-hosted deploy: k3s over Tailscale

## Does
Runs the app on a self-hosted k3s cluster, reachable only over the user's
own Tailscale network (private tailnet, no Funnel, no public ingress) via
the Tailscale Kubernetes Operator's L7 Ingress. Replaces the never-built
AWS EKS deploy target.

## Done when
- [Placeholder — auto-test-planning will fill this in]

## Integration test contract
[Placeholder — auto-test-planning will fill this in. Likely shaped as
deploy/smoke verification rather than a pytest integration test: cluster
up, Ingress reachable at the MagicDNS hostname from a tailnet-joined
client, health check passes, Postgres data survives a pod restart.]

## Tests
No test exists yet — auto-test-planning will produce the contract,
auto-test-writer will produce the test.

## Notes
- Created by auto-plan-grill from `changes/004-plaid-and-self-host/plan.md`
  — read that plan's `## Grill` and `research-plan.md` before writing the
  contract.
- k3s single-node cluster. Tailscale Kubernetes Operator installed via
  Helm, authenticated with a tag-scoped Tailscale OAuth client
  (`tag:k8s-operator`).
- Exposure via a Kubernetes `Ingress` with `ingressClassName: tailscale`
  (L7, not the L3 `loadBalancerClass: tailscale` Service form) — gets
  automatic HTTPS and a stable MagicDNS hostname
  (`balancezero.<tailnet>.ts.net`).
- Whether frontend + API share one hostname in production (Ingress
  path-routing `/api/*` vs `/*`, collapsing dev's two-origin CORS setup) is
  a medium-confidence assumption — see
  `changes/004-plaid-and-self-host/open-questions.md`, "Single-hostname,
  same-origin production topology."
- Postgres via a StatefulSet + PVC using k3s's built-in
  `local-path-provisioner` — no extra storage class needed.
- `--secrets-encryption` must be enabled at k3s install time — not the
  default, and this app stores a real bank-access credential
  (`plaid_access_token_encrypted`). Treat as a required step, not optional
  hardening.
- This spec's MagicDNS hostname is what `spec/plaid-connect.md` needs as
  the registered OAuth redirect URI for real (non-Sandbox) institution
  linking — see that spec's Notes.
- CI/CD automation of deploys to this cluster is explicitly out of scope
  for this spec (see plan's Non-Goals) — this spec covers the cluster and
  manifests existing and being reachable, not an automated pipeline.
