# Runtime light/dark theme toggle

## Status

complete

## Goal

Ship both designs (PR #63 light "instrument panel", PR #64 dark "Mission
Control") behind a runtime toggle instead of choosing one.

## How it works

- `frontend/src/index.css` defines every themed value as a CSS custom
  property twice: `:root, :root[data-theme="dark"]` (Mission Control) and
  `:root[data-theme="light"]` (instrument panel).
- `frontend/src/theme.ts` token values are `var(--z-...)` references, so
  identical markup renders either theme. `color.danger` stays a literal
  `#dc2626` (test-pinned, theme-invariant).
- New token groups: `categorical` (instrument/command identity colors),
  `viz` (deck schematic palette), `chrome` (header, brand glow, segment
  highlight, telemetry glow, dialog backdrop).
- Header sun/moon button (aria-label "Toggle theme") flips
  `document.documentElement.dataset.theme`; persisted in localStorage
  `zoo-theme`, falls back to `prefers-color-scheme`, initialized in
  `main.tsx` before first paint.

## Also fixed

A latent race in the App test "reconnects after saving calibrated output
to a different gantry filename": it clicked "Set origin and continue"
without waiting for the button to enable (silent no-op on disabled
buttons), unlike its sibling test which waits for enabled + the
"Origin set." text. The toggle's render-timing shift exposed it.

## Verification

lint/tsc/build clean; 174/174 tests; both themes and localStorage
persistence verified end-to-end with Playwright screenshots.
