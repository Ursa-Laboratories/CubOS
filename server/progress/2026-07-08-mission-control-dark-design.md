# "Mission Control" dark design variant

## Status

complete

## Goal

A second, bolder take on the Zoo UI (branch `design/mission-control`,
stacked on `design/ui-redesign-2026-07`): a dark lab-ops console whose UX
makes running the next experiment feel exciting — deep space-navy canvas
with a faint cyan aurora, glassy panels, an electric-cyan accent, and a
cyan→violet "launch gradient" reserved for primary actions.

## What changed (styling only — no behavior/API/CubOS changes)

Because the previous pass routed all component styling through
`frontend/src/theme.ts`, this redesign is mostly a token swap plus targeted
flourishes:

- **`theme.ts`** — dark token set: navy surfaces, cyan accent,
  `color.launchGradient`, `shadow.glow`, translucent semantic tints
  (indicator-light feel). `color.danger` stays `#dc2626` (test-pinned).
- **`index.css`** — dark foundation: aurora radial-gradient body background,
  `color-scheme: dark`, brighten-on-hover buttons, cyan focus rings, dark
  scrollbars, and a `zoo-pulse` keyframe class used by the run-status pill.
- **App shell** — pulsing amber run pill, glowing brand tile, lit segmented
  view switcher, translucent header with a cyan hairline.
- **Deck visualization** — radar look: #0a101f canvas, faint grid, cyan
  wells/gantry crosshair, emerald tip racks, amber vials as lit slots; all
  SVG label halos switched from white to the dark canvas color.
- **Gantry widget** — live X/Y/Z digits glow cyan (`accentText` +
  text-shadow) when connected; Advanced pressed state uses accent tint.
- **Editors/results** — categorical instrument/command colors brightened
  for dark backgrounds (#059669→#34d399, #d97706→#fbbf24, #7c3aed→#a78bfa,
  #2563eb→#60a5fa, #64748b→#94a3b8) in both GantryEditor and the deck
  InstrumentRenderer so editor headings still match deck markers.

## Process note

Implementation was delegated to four parallel `codex exec` workers
(OpenAI Codex CLI) with disjoint file scopes; Claude planned the tasks,
wrote the specs, and verified the results.

## Verification

- `cd frontend && npm run lint` — clean; `npx tsc --noEmit` — clean.
- `npx vitest run` — 16 files, 174/174 passed.
- `npm run build` — clean.
- Visual: drove Gantry/Deck/Protocol/Results with Playwright against
  `python -m zoo` and inspected screenshots of every surface.

## Risks / Next Steps

- This is an alternative design to PR #63's light theme; both are pure
  token-layer variants. Picking one (or adding a theme toggle that swaps
  the token set) is a follow-up decision.
