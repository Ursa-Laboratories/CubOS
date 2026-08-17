# Step-by-step execution UI — build spec

Build-ready spec for the **execution phase only** of the
[Run Protocol UI](2026-08-17-run-protocol-ui-scope.md). Written to be
implemented as-is.

---

## 0. Scope boundary

**In scope**

1. Engine: a step observer seam + structured step events, exception-isolated.
2. Engine: per-command summary formatters.
3. API: `GET /api/v1/runs/{run_id}/plan` — the compiled step list.
4. API: `RunEvent` gains `kind` + `data`; step events written to the stream.
5. API: fix `RunStore.append_event`'s O(n²) sequence computation.
6. UI: a live step list — pending / active / done / failed / skipped, with
   nested substeps, driven entirely by `plan + events`.
7. UI: cancel, failure display, and correct behavior on page refresh mid-run.

**Explicitly out of scope** (separate features, unblocked by this one)

- Preflight checklist — needs lifecycle phase events from `run_on_hardware`.
- Summary screen with reconciliation warnings.
- `OperatorGate` / `awaiting_operator` / operator-ack endpoint (the Picus F-1
  path). This spec deliberately leaves a slot for it: an unknown event `kind`
  must render as a generic row rather than throw, so adding it later is
  additive.

---

## 1. Two decisions needed before building

### D1 — Which submission path does the step UI serve?

`App.tsx` has **two** run paths today
([App.tsx:440](apps/operator-web/src/App.tsx:440)):

- **Legacy synchronous** `POST /protocol/run` — used when no fluid-state choice
  was made. Returns only when the run finishes. **No `run_id`, no event
  stream** — the step UI structurally cannot work on it.
- **Versioned async** `POST /api/v1/runs` — used when a fluid state is
  selected. Has `run_id`, events, cancel.

| | Option A — versioned only | Option B — route everything through versioned |
|---|---|---|
| Step UI available | only when a fluid state is selected | always |
| Legacy branch | kept in the UI | removed from the UI (endpoint stays for API clients) |
| Risk | two different run experiences, permanently | changes the stateless path, which a code comment says is *"byte-identical to the pre-Feature-07 stateless flow"* |

**Recommendation: B.** The versioned resource already accepts a stateless
submission (`state` omitted), so behavior is preserved; and shipping a run view
that only appears half the time is worse than the migration risk. The legacy
endpoint stays available for API consumers either way.

### D2 — Where does the step list live?

| | Option A — in the Workflow tab | Option B — new top-level "Run" view |
|---|---|---|
| Replaces | the pulsing `runStatusBanner` | nothing; adds a 5th view |
| Navigation | operator stays where they launched | operator is moved on submit |

**Recommendation: A.** The run is the culmination of the Workflow tab; sending
the operator elsewhere on submit loses the config context they may need to
re-read. The step list persists after the run ends until a new run starts.

---

## 2. Data model

### 2.1 Event contract

`RunEvent` gains two fields, both defaulted, so events already on disk parse
unchanged.

```python
# services/api/src/cubos_api/models/runs.py
RunEventKind = Literal["lifecycle", "step"]

class RunEvent(BaseModel):
    sequence: int
    timestamp: float
    state: RunState          # run state at emit time; step events carry "running"
    message: str             # prose, unchanged
    kind: RunEventKind = "lifecycle"
    data: dict[str, Any] | None = None
```

Step-event `data` payload:

```python
class StepEventData(BaseModel):
    index: int                  # ProtocolStep.index
    command: str                # e.g. "transfer"
    substep: str | None         # e.g. "leg2" or "cycle0:fill"; None for the step itself
    outcome: Literal["started", "completed", "failed", "skipped"]
    duration_s: float | None = None   # completed/failed only
    error: str | None = None          # failed only
    reason: str | None = None         # skipped only
```

### 2.2 Plan endpoint

```python
class PlanStep(BaseModel):
    index: int
    command: str
    summary: str                 # from the per-command formatter
    args: dict[str, Any]

class RunPlanResponse(BaseModel):
    run_id: str
    steps: list[PlanStep]
```

`GET /api/v1/runs/{run_id}/plan` compiles `run_dir/protocol.yaml` with
`compile_protocol` and maps `Protocol.steps`. Deliberately keyed on `run_id`
rather than a pre-submission body: it is deterministic, and it still works
after a page refresh **or** after the run has finished, which §4.3 requires.
404 if the run does not exist. Compilation errors → 422 with the message.

---

## 3. Engine changes

### 3.1 Observer seam

New `packages/core/src/cubos/protocol_engine/observer.py`:

```python
class StepObserver(Protocol):
    def step_started(self, *, index: int, command: str, substep: str | None) -> None: ...
    def step_completed(self, *, index: int, command: str, substep: str | None,
                       duration_s: float) -> None: ...
    def step_failed(self, *, index: int, command: str, substep: str | None,
                    duration_s: float, error: str) -> None: ...
    def step_skipped(self, *, index: int, command: str, substep: str | None,
                     reason: str) -> None: ...
```

Carried on the context, not passed to `execute()`:

```python
# runtime.py — ProtocolContext
step_observer: StepObserver | None = None
```

Rationale: `ProtocolContext` is already threaded through both execution paths
(`GantrySession.run_protocol` and `_mock_execute`) and into every command
handler, so compound commands can emit substep events without new plumbing.
It sits alongside the existing optional `data_store` / `campaign_id` /
`fluid_state_id` fields.

### 3.2 Emission points

| Event | Emitted from | Note |
|---|---|---|
| step started / completed / failed | `ProtocolStep.execute` ([runtime.py:70](packages/core/src/cubos/protocol_engine/runtime.py:70)) | already sets/restores `active_step_*`; wrap the `try/finally` |
| substep started / completed | `_substep_scope` ([pipette.py:928](packages/core/src/cubos/protocol_engine/commands/pipette.py:928)) | one context manager covers `serial_transfer`, `flush_pipette`, `rinse_well`, `clear_well` |
| step skipped | the four existing *"Skipping already-applied…"* log sites in `commands/pipette.py` | transfer stroke, mix, `pick_up_tip`, `_transfer_or_skip` |

### 3.3 Exception isolation — hard requirement

Every observer call goes through one helper:

```python
def _notify(observer, hook: str, **kwargs) -> None:
    if observer is None:
        return
    try:
        getattr(observer, hook)(**kwargs)
    except Exception:
        logger.warning("Step observer %s failed; continuing run", hook, exc_info=True)
```

**No observer exception may reach the step loop.** An observability feature
that can abort a run mid-liquid-transfer is worse than no observability.
Dedicated test in §6.

### 3.4 Summary formatters

`protocol_command` gains an optional formatter; `RegisteredCommand.__slots__`
gains `summary`.

```python
def protocol_command(
    name: str | None = None,
    summary: Callable[[dict[str, Any]], str] | None = None,
) -> Callable: ...
```

```python
@protocol_command(
    "transfer",
    summary=lambda a: f"{a['source']} → {a['destination']}   {a['volume_ul']} µL",
)
```

Formatters live next to the command so new commands ship their own display.
Fallback when `summary` is absent or raises: a generic
`", ".join(f"{k}={v}" for k, v in args.items())`, truncated. **No
command-specific rendering in the UI** — that is what rots.

Minimum set to write formatters for: `transfer`, `serial_transfer`,
`aspirate`, `blowout`, `mix`, `pick_up_tip`, `drop_tip`, `move`, `measure`,
`scan`, `home`, `pause`. Everything else takes the fallback.

### 3.5 Wiring the observer in

`setup_protocol` gains `step_observer=None` and sets it on the context. Both
API execution paths pass one:

- `RunManager._execute` → `_mock_execute(..., step_observer=...)`
- `RunManager._execute` → `run_protocol_on_session(..., step_observer=...)` →
  `GantrySession.run_protocol` → `setup_protocol`

The observer implementation lives in the API layer
(`RunStoreStepObserver`), writing to `RunStore.append_event`. `cubos` core
stays free of API imports — the boundary test enforces this.

---

## 4. API changes

### 4.1 Fix `append_event` before adding step events — required

```python
def append_event(self, run_id, *, state, message) -> RunEvent:
    events = self.events(run_id)                 # reads + parses the WHOLE file
    event = RunEvent(sequence=len(events) + 1, ...)
```

Currently ~4 events per run, so nobody noticed. A 500-step protocol emits
~1,000+ events, making this O(n²): ~500,000 line parses per run, on the
hardware thread, between motion commands.

Fix: an in-memory `dict[str, int]` of last sequence on `RunStore`, seeded
lazily from the file on first append for that run (so crash-recovery and
restarts stay correct). The file remains the source of truth.

### 4.2 Endpoints

- `GET /runs/{run_id}/plan` → `RunPlanResponse` (§2.2).
- `GET /runs/{run_id}/events?after=N` — already exists, already incremental.
  No change beyond the new fields flowing through.

### 4.3 Client

`runsApi` gains `plan(runId)` and `events(runId, after)`. Types added to
`src/types/index.ts` mirroring §2.

---

## 5. UI

### 5.1 State derivation — the core of the feature

One **pure function**, no React, fully unit-testable:

```ts
export function deriveStepViews(
  plan: PlanStep[],
  events: RunEvent[],
): StepView[]

interface StepView {
  index: number;
  command: string;
  summary: string;
  status: "pending" | "active" | "done" | "failed" | "skipped";
  durationS: number | null;
  error: string | null;
  reason: string | null;          // skipped
  substeps: SubstepView[];
}
```

**This satisfies R-1.** The entire view is a function of `(plan, events)`, both
fetched from the server by `run_id`. Nothing about which step is running lives
in React state, so a page refresh mid-run reconstructs the exact view. Any
component state that cannot be rebuilt from the server is a bug.

Derivation rules:

- start from `plan`, all `pending`
- `outcome: "started"` with `substep === null` → that index becomes `active`
- `completed` → `done` + `durationS`; `failed` → `failed` + `error`;
  `skipped` → `skipped` + `reason`
- substep events append to the parent index's `substeps`, keyed by the
  `substep` string; the nesting separator is `:`
- a terminal run state with steps still `pending` leaves them `pending` (they
  were never reached) — **do not** repaint them as skipped; §5.3
- unknown `kind` or unknown `outcome` → ignore, never throw (forward
  compatibility with the operator-gate work)

### 5.2 Components

```
RunPanel                      // replaces runStatusBanner in the Workflow tab
├── RunHeader                 // run id, state pill, elapsed, Cancel
├── StepList                  // virtualized; protocols can be hundreds of steps
│   └── StepRow               // index · command · summary · status · duration
│       └── SubstepRow[]      // indented, same shape
└── RunErrorPanel             // failure message + failing step, when failed
```

Styling from `src/theme.ts` tokens (`color.*`), matching `StatePanel.tsx`
conventions — inline `CSSProperties`, no new CSS framework. Status colors:
`textMuted` pending, `accent` active, `textSecondary` done, `danger` failed,
`warning` skipped.

### 5.3 Rendering rules

- **Auto-scroll** to the active step, but stop following once the operator
  scrolls manually. Resume on the next run.
- **Skipped needs a reason string**, not just a color — it means
  "already applied on resume" or "no-op by design", and those read
  differently. Never conflate with "not reached".
- **Duration** shown on completed steps, tabular numerals.
- **Active step** gets an indeterminate progress affordance; steps have no
  internal progress to report.
- Long protocols: virtualize. Do not render 500 rows.

### 5.4 Polling

Replace `pollVersionedRun`'s "poll the whole record every 400 ms" with an
events cursor:

- poll `events(runId, after=lastSequence)` every 400 ms while active
- back off to 2 s after 10 consecutive empty responses, reset on any event
- stop on terminal state; fetch the record once more for `result` / `error`
- fetch `plan` **once** per `run_id`

---

## 6. Tests

**Engine**

- observer receives started/completed in order for a 3-step protocol
- `step_failed` carries the exception message; the exception still propagates
- **an observer raising on every hook does not change run results or state** —
  the R-2 guard
- `_substep_scope` emits nested substep names for `serial_transfer`
- skipped emission on a resumed fluid state
- no observer (`None`) → zero behavior change; existing suites must pass

**API**

- `GET /runs/{id}/plan` matches the compiled step count and summaries
- step events round-trip `kind` + `data` through `events.jsonl`
- **old events without `kind`/`data` still parse** (backwards compatibility)
- `append_event` sequence stays correct across a simulated process restart
- an append-heavy run stays linear (assert parse count, not wall clock)

**UI**

- `deriveStepViews` unit tests: empty events, partial run, failure mid-run,
  substeps, out-of-order events, unknown kind ignored
- **reconstruction test**: given the same `(plan, events)`, a freshly mounted
  component renders identically to one that watched the run live — this is the
  R-1 regression guard
- cancel during execution
- 500-step plan renders without blowing up

---

## 7. File-by-file change list

**New**

| File | |
|---|---|
| `packages/core/src/cubos/protocol_engine/observer.py` | `StepObserver` protocol + `_notify` |
| `services/api/src/cubos_api/services/step_observer.py` | `RunStoreStepObserver` |
| `apps/operator-web/src/components/run/RunPanel.tsx` | |
| `apps/operator-web/src/components/run/StepList.tsx` | |
| `apps/operator-web/src/components/run/StepRow.tsx` | |
| `apps/operator-web/src/components/run/deriveStepViews.ts` | pure reducer |
| `apps/operator-web/src/hooks/useRunSteps.ts` | plan + events polling |
| tests mirroring §6 | |

**Modified**

| File | Change |
|---|---|
| `protocol_engine/runtime.py` | `step_observer` field; emit from `ProtocolStep.execute` |
| `protocol_engine/registry.py` | `summary` on decorator + `RegisteredCommand` |
| `protocol_engine/commands/*.py` | summary formatters; substep + skip emission |
| `protocol_engine/setup.py` | thread `step_observer` through `setup_protocol` |
| `gantry/session.py` | `run_protocol(step_observer=...)` |
| `cubos_api/models/runs.py` | `kind`, `data`, `StepEventData`, `PlanStep`, `RunPlanResponse` |
| `cubos_api/services/run_store.py` | sequence cache; `kind`/`data` passthrough |
| `cubos_api/services/run_manager.py` | construct + pass the observer |
| `cubos_api/routers/runs.py` | plan endpoint |
| `operator-web/src/api/client.ts` | `plan`, `events` |
| `operator-web/src/types/index.ts` | new types |
| `operator-web/src/App.tsx` | mount `RunPanel`; D1/D2 outcome |

---

## 8. Estimate

| | Work | Est. |
|---|---|---|
| 1 | Observer seam, emission points, exception isolation, engine tests | 1 d |
| 2 | Summary formatters for the 12 core commands | 0.5 d |
| 3 | `append_event` sequence fix + test | 0.25 d |
| 4 | Event model, step observer, plan endpoint, API tests | 0.75 d |
| 5 | `deriveStepViews` + its unit tests | 0.5 d |
| 6 | `RunPanel` / `StepList` / `StepRow` + polling hook | 1.5 d |
| 7 | `App.tsx` integration (D1/D2), UI tests | 1 d |

**Total ≈ 5.5 days.** Phases 1–4 are shippable on their own: they make runs
observable over the API before any UI exists.

Build order: 1 → 3 → 4 → 2 → 5 → 6 → 7. The `append_event` fix lands before
step events start flowing, so the O(n²) path is never exercised at volume.
