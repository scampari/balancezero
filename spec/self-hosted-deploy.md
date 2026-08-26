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
- The app's pods (Flask API, Postgres, static frontend) are all `Ready` on
  a single-node k3s cluster.
- The app is reachable over HTTPS at its MagicDNS hostname
  (`balancezero.<tailnet>.ts.net`) from a Tailscale-joined client, with a
  Tailscale-issued cert (no manual cert management).
- The app is NOT reachable from outside the tailnet — no public ingress,
  no Funnel, DNS for the MagicDNS hostname only resolves for tailnet
  members. This is the core security property of the deploy target and
  gets an explicit negative test, not just an implicit absence.
- Postgres data survives a pod restart (PVC persistence, not
  emptyDir/ephemeral storage).
- Secrets (`PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENCRYPTION_KEY`,
  `SECRET_KEY`, `DATABASE_URL`) are Kubernetes Secrets, never baked into
  images or checked into manifests; k3s's `--secrets-encryption` is
  verified enabled.

## Integration test contract

This is a deploy/smoke contract, not an application-behavior one — no new
Flask route is being tested, the existing `GET /api/health` (already
built, `app.py`) is reused as the observable signal. Likely executed as a
deploy-verification script rather than pytest — see Notes.

### Health check reachable over the tailnet

**Setup:** k3s cluster deployed per this spec's manifests; Tailscale
Kubernetes Operator installed and authenticated (`tag:k8s-operator`); app
manifests applied and pods `Ready`.
**Action:** From a Tailscale-joined test client, `GET
https://balancezero.<tailnet>.ts.net/api/health`.
**Input:** None.
**Expected output:** `200`, `{"status": "ok"}`.
**Side effects:** None (read-only).

### Data persistence across pod restart

**Setup:** Cluster running, a known row exists in Postgres (e.g. a test
user via the existing seed pattern).
**Action:** Delete the Postgres pod; wait for the StatefulSet to
reschedule it.
**Expected output:** The pod comes back `Ready`.
**Side effects:** The known row still exists after restart — proves the
PVC, not ephemeral pod storage, is where data actually lives.

#### Error cases
- **When the same hostname is requested from a client NOT joined to the
  tailnet (no Tailscale, or a different tailnet), Then** the request fails
  to resolve/connect — no fallback public path exists. This is the
  spec's core negative test.
- **When `kubectl get secret -o yaml` is inspected without cluster admin
  access, Then** raw secret values aren't recoverable — verifies
  `--secrets-encryption` is actually in effect, not just documented as a
  step that was supposedly taken.

## Tests
No test exists yet — auto-test-writer will produce these as a
deploy-verification script (see Notes on why this likely isn't pytest),
auto-build implements the k3s manifests/Helm values against it.

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
- **Single-hostname, same-origin production topology — confirmed as the
  contract (medium confidence, proceeding).** One Ingress, path-routed:
  `/api/*` → Flask Service, `/*` → a small static/nginx Service serving
  the React build. Dev (`dev.sh`, two servers, CORS via `ALLOWED_ORIGIN`)
  stays unchanged — this is production-only. Still marked medium
  confidence in `open-questions.md` (not raised to high) — it's a
  reasoned design call, not something verified against an external
  source the way the Plaid facts in `plaid-connect.md`/`plaid-sync.md`
  were.
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
- **Test mechanism**: this project's existing test conventions
  (`context/testing.md`) are pytest + real Postgres + Playwright for
  browser flows — none of those directly fit "verify a Kubernetes cluster
  is up and privately reachable." Likely shape: a shell/Python
  verification script (`scripts/verify-deploy.sh` or similar) that
  `auto-build` runs post-deploy, asserting the Done-when criteria above,
  rather than a pytest file. Left to `auto-build`'s judgment on exact
  tooling — the Done-when criteria are the actual contract, not the
  mechanism.

## Changes
- 004 (2026-08-26) — integration test contract landed by auto-test-planning,
  medium confidence throughout (first infra spec in this project, no prior
  pattern to copy) — proceeding to auto-test-writer per the "most decisions
  can be assumed at medium confidence" guidance, not blocking.
