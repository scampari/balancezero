# Slicing: theme picker + full light mode

> Date: 2026-08-27
> Status: built
> Branch: changes/010-theme-picker

## What & Why
The UI was a single hardcoded dark palette with a high-saturation emerald
accent ("looks like it came from the matrix"). The user wants a calmer
default and a theme selector, including a real light mode.

Every component already reads `--color-*` tokens through Tailwind v4's
`bg-(--color-x)` arbitrary syntax, so re-valuing tokens is cheap. The work
is: a calmer palette, a provider + `<html data-theme>` mechanism, per-theme
override blocks, a picker, and fixing the handful of dark-only assumptions
that a light theme exposes.

## Spec changes
- `spec/frontend-app.md` — modified — new "Theme selection" section (options,
  `localStorage` persistence, `System` follows `prefers-color-scheme`, real
  light mode, what e2e asserts). Status stays `built`.

## Context changes
- `context/tech-stack.md` — new "Theming" bullet: CSS custom properties +
  `html[data-theme]` blocks, `ThemeContext` writes `data-theme` +
  `color-scheme`, choice persisted to `localStorage['bz.theme']`,
  explicitly contrasted with the JWT no-storage rule.

## Constraints
- **Keep the 12 token names; add a 13th, `--color-on-accent`.** Primary
  buttons were `text-(--color-bg)` on `bg-(--color-accent)` — only legible
  because the bg was dark. `--color-on-accent` makes the on-accent text
  color explicit and per-theme. All 6 occurrences (LoginPage, SignupPage,
  BudgetPage ×2, AccountsPage, ConnectBankButton) switched.
- **Runtime palettes are `html[data-theme='x']` blocks** after the `@theme`
  block. `html[...]` specificity `(0,1,1)` beats the `@theme`-generated
  `:root` `(0,1,0)` regardless of source order — a bare `[data-theme]`
  would tie and be fragile.
- **Themes:** calmer default dark (soft indigo accent), `dark-dim` (muted
  sage), `dark-ocean` (deep navy + sky blue), `light` (warm-neutral +
  deeper indigo). Each block redefines all 13 tokens and sets
  `color-scheme`. Light bumps `--color-accent-bg` / `--color-accent-border`
  alpha up so tints/focus rings show on white.
- **No FOUC:** a pre-paint `<script>` in `index.html` reads
  `localStorage['bz.theme']` (or `matchMedia` for `system`) and sets
  `data-theme` + `color-scheme` before first paint. `ThemeContext` takes
  over on mount.
- **`ThemeProvider` is the outermost wrapper** in `App.tsx` (above
  `AuthProvider`) so the login and loading screens are themed.
- **`localStorage` for the theme is fine** — a display preference, not a
  credential. `AuthContext`'s no-storage rule targets the JWT only;
  documented in `context/tech-stack.md`.
- **Picker is a `<select aria-label="Theme">`** in the `AppShell` header.
  `combobox`/"Theme" collides with no existing `link`/`button` accessible
  name, so the nav-by-name e2e specs are unaffected.

## Non-Goals
- No per-component color props or overrides — everything flows through the
  13 tokens.
- No theme-aware images/illustrations (there are none).
- No high-contrast / reduced-motion themes (possible follow-up).
- No server-side persistence of the choice — per browser only.

## Slices
- **010-A** `frontend/src/index.css` (retheme + `--color-on-accent` + 4
  `html[data-theme]` blocks), `frontend/index.html` (pre-paint script),
  `frontend/src/theme/` (`themes.ts`, `ThemeContext.tsx`),
  `components/ThemePicker.tsx`, `App.tsx` (ThemeProvider), `AppShell.tsx`
  (picker in header), the 6 `text-(--color-on-accent)` swaps.
- **010-B** e2e `theme.spec.ts`; `spec/frontend-app.md` +
  `context/tech-stack.md` docs.

## Incidental fix (surfaced here, belongs to 007)
The `changes/007` login rate limit (10 / 15 min per IP) trips mid-run
during the serial Playwright suite, which logs in from `127.0.0.1` many
times. Made the max counts config (`LOGIN_RATE_LIMIT_MAX` /
`SIGNUP_RATE_LIMIT_MAX`, defaults 10 / 5) and set them high in
`frontend/playwright.config.ts`. The `429` behavior itself stays covered by
`tests/test_signup.py` (which uses the defaults).

## Verification
- `cd frontend && npm run build && npm run lint` clean (2 pre-existing
  `only-export-components` warnings — `AuthContext` + the new
  `ThemeContext`, same established pattern).
- `npm run test:e2e` full suite green (17: 14 prior + 3 theme).
- `venv/bin/pytest` full suite green (149 / 9 skipped) — auth_api rate-limit
  refactor didn't regress.
- Manual (Chrome MCP): cycled default dark / light / dark-ocean; light and
  dark-ocean render correctly (button contrast, borders, money colors);
  `data-theme` + `bz.theme` persist across a full reload with no flash.
