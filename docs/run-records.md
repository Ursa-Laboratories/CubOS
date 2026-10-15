# Run and step records

CubOS saves protocol execution records alongside measurements in its SQLite
[database](data.md). A run records what was attempted and its outcome. Each
entered command gets a step record; `scan.well` records identify individual
wells beneath their scan step. Measurement rows link to the exact step through
`step_execution_id`.

## Try it without hardware

From the repository root, using the installed CubOS environment:

```bash
python packages/core/examples/run_records.py /tmp/run-record.json
python packages/core/examples/run_records.py /tmp/partial-run-record.json --fail-after-measurement
```

The example explicitly constructs `Gantry(offline=True)` and
`ThorlabsUVVisCCS(offline=True)`. It has no hardware mode. Its plate coordinates
and heights belong only to this synthetic example.

The first command measures two wells. The second preserves one spectrum, then
records an intentional software failure. Both print their run ID and paths.
The `.sqlite` file is the source of truth; the JSON file exports its run, steps,
and full spectra for inspection. Repeating the command appends a new run to the
database and replaces the JSON export with that run.

## What records mean

Runs can be `queued`, `running`, `completed`, `failed`, `cancelled`, or
`interrupted`. Steps can be `running`, `completed`, `failed`, `cancelled`,
`interrupted`, or `skipped`. A command that explicitly reports a skip records its
reason and ends as `skipped`; a successful command returning `None` is still
`completed`. Steps never reached after a failure have no execution record. A durable start
records dispatch intent immediately before invoking the handler; process loss
in that gap cannot establish whether the handler or physical action began.

Run metadata includes software version, available checkout commit and dirty
state, protocol source/hash, and available setup snapshots and execution mode.
Hardware mode requires an observed owned connection lifecycle; a prepared
context with only offline=false flags remains unknown. Connection observations
describe software lifecycle completion, never proof of successful physical action.
A programmatically constructed protocol has a sanitized plan hash; YAML-loaded
protocols can retain the captured source snapshot and hash. Source locations
identify the command in its protocol. Sequence numbers order entered steps and
terminal transitions, including nested steps; timestamps alone do not establish
that order.

| Timing field | Meaning |
| --- | --- |
| Run/step `started_at`, `ended_at` | Observed UTC wall-clock boundaries. |
| Run/step `duration_ns` | Elapsed time from a monotonic clock, independent of wall-clock adjustment. |
| Measurement `method_call` | Observed instrument-method call boundaries and monotonic duration. Includes driver waiting and processing. |
| Measurement `acquisition` | Instrument-result timing only. Missing values are `null` with source `unknown`. |
| UVVis `integration_time_s` | The integration setting returned by the result; it is not an acquisition timestamp or method-call duration. |

Measurement metadata includes `schema_version`, normalized type, declared units,
processing known or unknown, actual method kwargs with runtime objects omitted,
resolved action coordinates, and the target labware/well and contents snapshot.
Configured instrument identity is separate from identity reported in the result.
Offline synthetic UVVis spectra are explicitly labeled. No additional instrument
queries run solely to collect metadata. A partial/aborted result returned by a
driver retains its returned arrays and metadata; an exception does not invent a
partial result.

Older measurements and direct legacy writes may have a null step link or absent
metadata. These are not evidence of a particular run. Database measurement
`timestamp` fields describe row creation and do not replace acquisition timing.
Campaign status and protocol-run status describe separate records.

## Read records in Python

```python
from cubos.data import DataStore

store = DataStore("/tmp/run-record.sqlite")
try:
    records = store.execution_records
    runs = records.list_runs(limit=20, offset=0)
    run = records.get_run(runs[0]["run_id"])
    steps = records.list_steps(run["run_id"], after_sequence=0, limit=100)
    # Next page: use the last returned step's sequence, not the page length.
    next_steps = records.list_steps(
        run["run_id"], after_sequence=steps[-1]["sequence"], limit=100
    ) if steps else []
finally:
    store.close()
```

`get_step(step_execution_id)` reads one step. `list_runs` uses offset pagination;
`list_steps` uses an exclusive sequence cursor. Measurement tables remain the
existing typed tables (`uvvis_measurements`, `asmi_measurements`, and others).
Join their `step_execution_id` to `step_executions`, then join `run_id` to
`protocol_runs`. The example shows a SQLite read/export of UVVis values and
metadata without introducing another store.

`Protocol.execute(context)` records execution even when the caller has already
prepared the hardware. If no `DataStore` is supplied, it opens the default
configured database, creates the campaign, and closes its own store afterward.
An explicitly supplied real `DataStore` remains caller-owned. Direct command
function calls outside a recorded protocol do not automatically create a run.

## Failures and recovery

Recording failures are latched. An entered command finishes its existing
handling; the next outer command does not start, and the run reports failure.
A missing nested-step record never causes its measurement to be attributed to
the parent. Advisory UI observers do not determine durable record success.

File databases use per-run process locks. The API run manager reconciles
abandoned records when it starts. Standalone callers can call `recover_abandoned_runs(store)` from
`cubos.protocol_engine.execution_trace` after an exited local owner. It checks ownership and lock availability,
then marks abandoned active records `interrupted`. It records recovery time
without inventing an end time or duration. Recovery does not replay commands or
resume hardware. These locks protect run ownership; they are not physical
instrument interlocks or proof that a workcell is safe.

Credentials in supported metadata fields and URLs are redacted; opaque objects
are omitted. This is an execution record, not a complete instrument audit trail:
missing calibration, firmware, serial identity, acquisition times, or processing
information stay unknown. Potentiostat result settings such as duration and
sample period can reflect requested parameters rather than device readback.
Their raw `started_at`/`stopped_at` metadata brackets driver/SDK orchestration,
including simulated values offline; it is not promoted to acquisition timing. CSV/ZIP exports retain their existing formats; inspect
SQLite or the example JSON for these execution records.

## Operator validation on a configured workcell

Physical validation is pending. Use an already validated gantry/deck pair and a
UVVis instrument configured on that gantry. The operator must supply the actual
instrument key, the plate path containing `A1`, and a measurement height already
approved for that setup. Do not reuse the offline example's geometry.

1. Make a two-step protocol that measures the configured plate's `A1` twice,
   using that instrument key, `method: measure`, and the approved
   `measurement_height`. Keep its normal configured hardware lifecycle.
2. Run offline validation first:
   `python -m cubos.tools.validate_setup GANTRY.yaml DECK.yaml PROTOCOL.yaml`.
3. The operator inspects the workcell, confirms clearance and the configured
   setup, then runs:
   `python -m cubos.tools.run_protocol GANTRY.yaml DECK.yaml PROTOCOL.yaml --database runs/uvvis-record-check.sqlite`.
4. Check one completed run, two completed measurement steps, and two spectra
   linked to those exact steps. Confirm configured identity is not presented as
   reported identity, synthetic/offline flags reflect the actual driver result,
   and integration time is separate from method-call timing. Missing acquisition
   timing must remain unknown.

Use the offline failure example to check preservation after software failure;
do not introduce an intentional failure or disconnect into a physical run.

## API output readiness

For traced runs, `core_status` reports the SQLite execution outcome. While the
worker is publishing result files, API `state` stays running and
`artifacts_pending` is true. After publication it becomes succeeded, failed,
or cancelled. A result-file write error does not change a completed execution;
it appears separately in `recording_errors` with stage `api_projection`.
Step queries open SQLite read-only and do not run migrations while polling.

Custom persistence objects which do not implement the built-in DataStore remain
compatible with older integrations but do not provide these durable records.
Use DataStore for recorded runs; pass DataStore(":memory:") explicitly for
intentional ephemeral tests. Normal CLI/API runs use persistent storage.
