# Run Protocol UI — feature scope

Research date: 2026-08-17. Target: replace the current "click Run, watch a
pulsing banner" experience with a staged run view — preflight checks, then live
per-step progress, then a summary — modelled on the calibration wizard.

Companion doc: [Sartorius Picus 2 integration scope](2026-08-17-sartorius-picus2-integration-scope.md).
The Picus's operator-arming requirement (F-1 there) is the first real consumer
of this feature's operator-intervention path.

---

## 1. Why this is cheaper than it looks

**The engine already models everything the UI needs to show. None of it is
exposed over the API.**

| What the UI needs | Already exists | Where |
|---|---|---|
| Ordered, compiled step list | `Protocol.steps` → `ProtocolStep(index, command_name, args)` | [protocol.py:67](packages/core/src/cubos/protocol_engine/protocol.py:67) |
| Live step position | `ProtocolContext.active_step_index` / `active_step_command` / `active_substep` | [runtime.py:78](packages/core/src/cubos/protocol_engine/runtime.py:78) |
| Substep identity | `step:{i}:{command}:substep:{name}` scope string (already used for fluid operation keys) | [runtime.py:49](packages/core/src/cubos/protocol_engine/runtime.py:49) |
| Preflight phase list | `run_on_hardware`'s documented 10-phase lifecycle | [setup.py:157](packages/core/src/cubos/protocol_engine/setup.py:157) |
| Offline pre-run validation | `validate_setup` expands every command to motion targets, checks reachability / collisions / tip state | `validation/protocol_semantics.py` |
| Incremental event stream | `GET /api/v1/runs/{id}/events?after=N` | [runs.py:68](services/api/src/cubos_api/routers/runs.py:68) |
| Stepped operator UI precedent | `CalibrationWizard` (7 steps, hardware actions between them) | `apps/operator-web/src/components/gantry/CalibrationWizard.tsx` |
| Blocking confirm dialog | `ConfirmDialog` + `useConfirm` | `apps/operator-web/src/components/common/` |

What the run UI does today: `App.tsx` submits, then `pollVersionedRun` polls
`runsApi.get` every 400 ms until a terminal state and renders a single pulsing
banner ([App.tsx:73](apps/operator-web/src/App.tsx:73)). The operator cannot
see which step is running, what is about to happen, or what was skipped.

So this is largely a **plumbing and presentation** feature, not new engine
concepts. The one genuinely new engine idea is an observer seam on the step
loop.

---

## 2. The three phases

### Phase 1 — Preflight (before any motion)

A checklist the operator reads and clears *before* hardware moves. Rows come
from the existing lifecycle plus per-vendor capability declarations:

1. Config load and schema validation
2. Offline setup validation — reachability, transit collisions, safe-Z, tip
   state, fluid balance
3. Fluid-state decision — new, resume an existing ID, or stateless
4. **Operator requirements** — every instrument that declares
   `requires_operator_arming`, listed by name with the physical action needed
5. Gantry connect, startup-alarm clear, soft-limit verification
6. Instrument connect + `health_check()`, one row per instrument, live status
7. Gantry health check

"Start run" is disabled until every blocking row is green. This is the phase
that carries the most safety value: it turns "the run failed 40 minutes in
because nobody pressed a button" into "you cannot start yet, and here's why."

### Phase 2 — Execution

The compiled step list, rendered as a vertical progress list:

- **Row content** — index, command name, and a short arg summary
  (`transfer   reservoir.A1 → plate.B3   500 µL`)
- **Row states** — `pending` / `active` / `done` / `failed` / **`skipped`**
- **Substeps** nested under their parent, since `serial_transfer` emits
  `leg{N}` and `flush_pipette` emits `cycle{N}`
- **Operator gates** render **inline as a step card** with the instruction and
  Confirm / Abort — not as a modal, so the operator can see where in the run
  they are
- `GantryPositionWidget` stays pinned alongside
- Cancel routes to the existing `cancel_requested` path

`skipped` deserves its own state because resumed fluid-state runs legitimately
no-op already-applied operations (the engine logs *"Skipping already-applied
fluid operation"*). Without a distinct visual, operators will read a resumed
run as having done less than it did.

### Phase 3 — Summary

Terminal state, per-step outcomes, measurements written, artifacts to download
and — the important one — **reconciliation warnings**. When a fluid or tip
operation ends `reconciliation_required`, that fact currently lives only in
SQLite and is invisible in the UI. It should be the loudest thing on the
summary screen, because it means physical state and recorded state may disagree.

---

## 3. What has to be built

### Engine

**A step observer seam.** `Protocol.execute` currently loops and logs. Add an
optional observer that receives `step_started` / `step_completed` /
`step_failed` / `step_skipped` with structured fields (index, command, substep,
error).

> **Hard requirement:** the observer must be exception-isolated. A UI or
> transport error inside a callback must be caught and logged, never propagated
> into the step loop. An observability feature that can abort a hardware run
> mid-liquid-transfer is worse than no observability.

**Per-command arg summaries.** Register a display formatter next to each
`@protocol_command` so the UI gets readable rows for free. If summarization
lives in the UI, it rots the moment someone adds a command.

**Structured substep identity.** Emit `index`, `command`, and `substep` as
separate fields rather than making the UI parse
`step:3:transfer:substep:leg2`.

### API

- `POST /api/v1/runs/plan` — compile a bundle and return the step list without
  executing. Backed entirely by existing `compile_protocol` + `Protocol.steps`.
- `RunState` gains `awaiting_operator`.
- `RunEvent` gains `data: dict | None = None` for structured step payloads.
  `message` stays prose for backwards compatibility.
- `POST /api/v1/runs/{run_id}/operator-ack` with
  `{action, decision: "confirm" | "abort"}`.
- Preflight rows exposed as phase events so the UI renders one code path for
  preflight and execution.

### UI

- `RunWizard` — the three-phase container.
- `PreflightChecklist` — rows with pass / fail / blocked-on-operator status.
- `StepList` + `StepRow` — virtualized; protocols can be hundreds of steps.
- `OperatorGateCard` — inline blocking card with instruction and actions.
- `RunSummary` — outcomes, artifacts, reconciliation warnings.

---

## 4. Flags

### 🚩 R-1 — Wizard state must be derived, not local (HIGH)

The current UI holds run state in React (`isRunning`, `runResult`,
`activeRunId`). A stepped view built the same way loses everything on a page
refresh — unacceptable for runs that last hours.

*Requirement:* the entire view must be reconstructible from `run_id` + the
event stream alone. Any UI state that cannot be rebuilt from the server is a
bug. This is the single biggest architectural constraint on the feature.

### 🚩 R-2 — The observer must not be able to kill a run (HIGH)

See the hard requirement in §3. Worth a dedicated test: an observer that raises
on every callback must not change run outcome.

### 🚩 R-3 — `RunState` is a closed `Literal` (MEDIUM)

Adding `awaiting_operator` breaks any client that matches exhaustively, in a
file whose docstring says *"Versioned CubOS run-resource request and response
models."* Needs a version note and a check on the SDK
(`sdk/python`) for exhaustive matches.

### 🚩 R-4 — Polling granularity (MEDIUM)

400 ms polling is fine for a 2-minute run and wasteful for a 6-hour one. The
events endpoint is already incremental (`?after=N`), so switch to it and back
off the interval when no events arrive. SSE or WebSocket is the right long-term
answer but should not block v1.

### 🚩 R-5 — Preflight must not be advisory (MEDIUM)

If "Start run" is clickable while a row is red, the feature has added a
checklist people learn to ignore. Blocking rows must actually block, and the
server must re-check rather than trusting the client — a UI that only *displays*
a gate is not a gate.

### 🚩 R-6 — Skipped-step semantics need care (MEDIUM)

`skipped` can mean "already applied on resume" or "no-op by design"
(`clear_well` with nothing to remove). Those are different facts and should read
differently, or operators will mistrust the display.

### 🚩 R-7 — Mock mode should drive the same UI (LOW — upside)

`--mock` / `mock_mode: true` runs already exercise the full engine path. Wiring
them to the same wizard gives operators a rehearsal mode for free, and gives us
a way to demo the UI with no hardware attached.

---

## 5. Where human intervention fits

The operator gate designed for the Picus (F-1) is **not** a Picus special case —
it is the first consumer of a general capability. Two distinct touchpoints:

**Declared in preflight.** `requires_operator_arming`, declared per vendor in
`instruments/registry.yaml` alongside the existing `calibration_mode` metadata,
surfaces as a preflight row: *"Sartorius Picus 2 — remote control must be
allowed on the device."* The operator sees the requirement before starting, so
it is never a mid-run surprise.

**Satisfied during connect, not mid-run.** Arming happens inside the Picus
`connect()`, which is lifecycle phase 7 (`connect_instruments`) — still inside
**preflight**. So for the Picus the prompt appears on the checklist and the
step list never blocks. That is the important consequence of scoping arming to
`connect()`: it costs one press at the start of a session, not one per command.

**The inline gate is for the future.** `OperatorGateCard` in the step list is
the general mechanism for genuinely mid-run interventions — reload a tip rack,
swap a plate, inspect a well. Nothing needs it today. It comes almost free once
the plumbing exists, and it is the natural home for those protocol commands
when someone wants them.

**Which also fixes an existing bug.** The current `breakpoint` command
([pause.py:35](packages/core/src/cubos/protocol_engine/commands/pause.py:35))
reads stdin and *silently continues* when `stdin` is not a TTY. Under this
feature it should be reimplemented on top of the operator gate, so a headless
run either has a real acknowledgement channel or fails closed. Today it fails
open, which is the wrong default in a codebase that fails closed everywhere
else.

---

## 6. Work breakdown

| Phase | Work | Est. |
|---|---|---|
| 1 | Step observer seam + structured step events + exception isolation | 1 d |
| 2 | Per-command arg summary formatters | 0.5 d |
| 3 | `POST /runs/plan` compiled-step endpoint | 0.5 d |
| 4 | `awaiting_operator` state, `RunEvent.data`, operator-ack endpoint | 0.5 d |
| 5 | Preflight phase events from `run_on_hardware` | 0.5 d |
| 6 | `RunWizard` + `PreflightChecklist` + `StepList` | 2 d |
| 7 | `OperatorGateCard` + `RunSummary` with reconciliation warnings | 1 d |
| 8 | Tests — engine observer, API contract, UI state reconstruction (R-1) | 1.5 d |

**Total ≈ 1.5 weeks.** Phases 1–5 are independently useful: they make runs
observable over the API even before the UI lands, which is worth shipping on
its own.

Suggested sequencing against the Picus work: land phases 1–5 first, so the
Picus driver has a real operator channel to target rather than a stub. The
Picus's `DeniedOperatorGate` default means it fails closed in the meantime,
which is the correct interim behavior.
