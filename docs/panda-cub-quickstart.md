# PANDA-CUB Quickstart: Out-of-the-Box Instrument Test Harness

This runbook takes a fresh clone to a complete, state-tracked pipetting run:
pick up a tip from the rack, aspirate water from one vial, dispense into
another vial, and drop the tip in the disposal — with fluid and tip state
durably tracked and verifiably correct throughout.

Everything below runs offline in mock mode. The hardware path and its one
known blocker are documented at the end.

## 1. Setup from a fresh clone

```bash
git clone <repo> CubOS && cd CubOS
python -m venv .venv
source .venv/bin/activate
pip install -e packages/core
```

No hardware, serial device, or external service is required for mock mode.

## 2. The config files

| File | What it is |
| --- | --- |
| `packages/core/configs/gantry/cub_xl_panda_home_origin_full.yaml` | GENERATED. Real PANDA machine envelope + calibrated instrument offsets (pipette/potentiostat/capper/camera), produced by the PANDA-BEAR importer. |
| `packages/core/configs/deck/panda_imported_deck.yaml` | GENERATED. Real production labware (6 stock vials, 3 waste vials, e-bath vial, ITO-PAMA 3x4 plate, 2x12 tip rack, disposal) with `role:`/`solution:` identity from the production DB. |
| `packages/core/configs/deck/panda_initial_fluids.yaml` | GENERATED. Fluid seed from the surviving production vials (s1 = 6500 uL water, etc.). |
| `packages/core/configs/gantry/cub_xl_panda_pipetting_mock.yaml` | MOCK-ONLY gantry variant used by the runnable protocols below (see section 6 for why). |
| `packages/core/configs/deck/panda_imported_deck_pipetting_mock.yaml` | MOCK-ONLY deck variant: identical labware identities/roles/solutions/capacities, placeholder motion Z values. |
| `packages/core/configs/protocol/panda/vial_transfer_acceptance.yaml` | The acceptance harness: tip -> 200 uL s1->w1 -> 400 uL s1->w3 (auto-split into 2 strokes) -> drop tip. |
| `packages/core/configs/protocol/panda/well_rinse_water.yaml` | Production-shaped well-rinse port (water substitution) using automatic stock/waste selection. See section 5. |

Regenerate the three GENERATED files (plus `protocol/panda/position_tour.yaml`
and `panda_import_report.json`) from the read-only production snapshot with:

```bash
PYTHONPATH=packages/core/src .venv/bin/python -m cubos.tools.import_panda_bear \
  /Users/alexchan/Documents/Ursa/PANDA-CUB/panda_prod_db.db
```

The import is deterministic (double-run produces byte-identical files) and
never writes to the source DB (sha256 `209d085b…f811ab21f` must be unchanged
after).

## 3. Validate, then run (mock mode)

Offline validation first (PASS/FAIL, no hardware; the 4th argument enables
static liquid-volume simulation against the seed):

```bash
PYTHONPATH=packages/core/src .venv/bin/python -m cubos.tools.validate_setup \
  packages/core/configs/gantry/cub_xl_panda_pipetting_mock.yaml \
  packages/core/configs/deck/panda_imported_deck_pipetting_mock.yaml \
  packages/core/configs/protocol/panda/vial_transfer_acceptance.yaml \
  packages/core/configs/deck/panda_initial_fluids.yaml
```

The acceptance run (verified working; ~1 s):

```bash
PYTHONPATH=packages/core/src .venv/bin/python -m cubos.tools.run_protocol \
  --mock \
  --database /tmp/panda-acceptance.db \
  --initial-fluids packages/core/configs/deck/panda_initial_fluids.yaml \
  packages/core/configs/gantry/cub_xl_panda_pipetting_mock.yaml \
  packages/core/configs/deck/panda_imported_deck_pipetting_mock.yaml \
  packages/core/configs/protocol/panda/vial_transfer_acceptance.yaml
```

The well-rinse run (verified working):

```bash
PYTHONPATH=packages/core/src .venv/bin/python -m cubos.tools.run_protocol \
  --mock \
  --database /tmp/panda-well-rinse.db \
  --initial-fluids packages/core/configs/deck/panda_initial_fluids.yaml \
  packages/core/configs/gantry/cub_xl_panda_pipetting_mock.yaml \
  packages/core/configs/deck/panda_imported_deck_pipetting_mock.yaml \
  packages/core/configs/protocol/panda/well_rinse_water.yaml
```

What the operator should see, in order: the full `Protocol Setup Validation`
report ending `RESULT: PASS`, then `Running protocol in explicit offline mock
mode...`, then `Protocol complete — 6 steps executed.` (7 for well-rinse), the
SQLite path, `Linked fluid state ID: 1`, and three exported result CSVs. A
non-zero exit or `reconciliation` message means the durable journal needs
operator review — see `docs/fluid-state.md`.

## 4. Expected final state

Inspect with `sqlite3 /tmp/panda-acceptance.db "SELECT labware_key,
location_id, current_volume_ul, composition_json FROM fluid_containers ORDER
BY labware_key"` (or via the API/UI, section 7).

`vial_transfer_acceptance.yaml` — seed deltas only; every other container is
unchanged from `panda_initial_fluids.yaml`, and all 12 plate wells stay 0:

| Container | Start (uL) | End (uL) | End composition (uL) |
| --- | --- | --- | --- |
| s1 (stock, water) | 6500 | 5900 | water 5900 |
| w1 (waste) | 3600 | 3800 | dmfc 3600, water 200 |
| w3 (waste) | 11700 | 12100 | acn 3600, dmf 8100, water 400 |
| tip_rack.A1 | available | consumed | — |
| pipette attachment | none | none | — |

The 400 uL transfer is exactly two durable 200 uL stroke operations
(p300_single_gen2 `max_volume` = 200): operation keys
`campaign:1:step:3:transfer:substep:stroke0:transfer` and `…stroke1…`, both
`applied`.

`well_rinse_water.yaml` — automatic selection resolves `solution: water` to
s1 and waste to w1 (first of w1/w2/w3 in sorted key order with headroom):

| Container | Start (uL) | End (uL) | End composition (uL) |
| --- | --- | --- | --- |
| s1 (stock, water) | 6500 | 5700 | water 5700 |
| w1 (waste) | 3600 | 4400 | dmfc 3600, water 800 |
| ito_pama_plate.A1 | 0 | 0 | — (filled/emptied 3x at 200 uL) |
| tip_rack.A2 | available | consumed | — |
| pipette attachment | none | none | — |

Journal: 7 applied transfers (3x rinse fill + 3x rinse remove + 1 flush);
`clear_well` is a documented no-op because exact mock transfers leave A1 at
0 uL.

Both traces — including a crash-mid-protocol restart that resumes the same
DB/campaign without repeating liquid — are locked down by
`packages/core/tests/configs/test_panda_workflow_acceptance.py`.

## 5. What the well-rinse port is (and is not)

`well_rinse_water.yaml` is a production-SHAPED port, evidenced from local
read-only PANDA-BEAR source (never imported):

| Legacy step (PANDA-BEAR source, path:lines) | CubOS command |
| --- | --- |
| `replace_tip(...)` before liquid handling (`panda_experiment_protocols/dmfc_cv_protocol.py:102-105`) | `pick_up_tip: tip_rack.A2` |
| `rinse_well` cycle: fill well from solution-selected stock, then remove same volume to `waste_selector(...)`, x count (`src/panda_lib/actions/pipetting.py:533-593`, live 3x loop shape at `dmfc_cv_protocol.py:203-218`) | `rinse_well: {well: ito_pama_plate.A1, volume_ul: 200, cycles: 3, solution: water}` |
| `flush_pipette`: named solution straight to waste, 200 uL x 1 default (`pipetting.py:596-641`; call shape `pama_ca_drying_protocol.py:159-164`) | `flush_pipette: {volume_ul: 200, cycles: 1, solution: water}` |
| residual clear via `_pipette_action` well->waste (`pama_ca_drying_protocol.py:217-222`, `dmfc_cv_protocol.py:220-226`) | `clear_well: {well: ito_pama_plate.A1, solution: water}` |
| (tip returned/dropped at end of experiment lifecycle) | `drop_tip: tip_disposal.discard` |

Water is substituted for the production dmf/acn/ipa rinse train; the
selection *mechanism* (named solution -> `role: stock` vial, automatic
`role: waste` vial) is the same one production used
(`panda_lib.actions.vessel_handling.solution_selector` matched vials by
name — the importer emits exactly that name as each vial's `solution:`).
The full line-by-line legacy trace lives in the YAML's header comment.

**Recovery blocker (documented, not reconstructed):** the exact production
protocol sources for experiments 1–84, `fc_cv_protocol.py` and
`ca_test_protocol.py`, are NOT in any reachable checkout (verified absent
from `/Users/alexchan/Documents/Ursa/projects/PANDA-BEAR`). They live only on
the offline PANDA machine at `~/github/PANDA-BEAR`. Full production parity
requires recovering those two files from that machine; nothing here was
reconstructed from their names. The locally-available
`pama_ca_drying_protocol.py` + `dmfc_cv_protocol.py` + `pipetting.py
well_rinse` are the production-shaped behavior evidence this port is built
from.

## 6. Hardware mode and the pipetting-bounds blocker

For any real hardware run, first complete the PANDA bring-up gates
(`docs/gantry-setup.md`, `AGENTS.md` hardware-safety order), set
`serial_port` in the gantry YAML to the real device (e.g. `/dev/ttyUSB0` or
`/dev/tty.usbserial-*` on macOS), and drop `--mock`.

**Blocker — real-pipette motion against the imported configs:** the
generated `cub_xl_panda_home_origin_full.yaml` + `panda_imported_deck.yaml`
pair passes validation only for zero-offset (`camera`) hover protocols like
`position_tour.yaml`. Any protocol using the real `pipette` instrument fails
bounds validation, because CubOS composes `gantry_z = target_z +
instrument.depth (+ tip_length)` while the imported deck stores
already-converted gantry-frame coordinates (PANDA-BEAR's
`gantry = tool_point + tool_offset` is baked in by the importer, by tested
design). `cnc.safe_z (-5.0) + pipette depth (100.0)` alone exceeds
`working_volume.z_max (0.0)` before any deck coordinate is involved; the
plate X additionally exceeds `x_min` once the pipette X offset is applied.
Resolving this for hardware requires either changing the importer's
coordinate convention or re-measuring safe_z/tool depths on the machine —
tracked as an open hardware bring-up task. The `*_pipetting_mock` pair
exists solely so the state-tracking acceptance bar is runnable today; do
not point it at hardware.

## 7. Operator-UI / API alternative

Start the appliance API (serves the operator web build and `/api/v1`;
default `127.0.0.1:8742` — see `services/api/README.md` for full setup):

```bash
pip install -e "services/api[dev]"
(cd apps/operator-web && npm ci && npm run build)
python -m cubos_api
```

Create a fluid state from the seed, then submit the run against it:

```bash
# 1. Create the state (fluids payload = panda_initial_fluids.yaml's mapping)
curl -s -X POST http://127.0.0.1:8742/api/v1/fluid-states \
  -H 'content-type: application/json' \
  -d '{
        "deck_file": "packages/core/configs/deck/panda_imported_deck_pipetting_mock.yaml",
        "label": "panda acceptance",
        "fluids": {
          "s1": {"volume_ul": 6500, "composition": {"water": 6500}},
          "w1": {"volume_ul": 3600, "composition": {"dmfc": 3600}},
          "w2": {"volume_ul": 19800, "composition": {"acn": 6300, "dmf": 13500}},
          "w3": {"volume_ul": 11700, "composition": {"acn": 3600, "dmf": 8100}}
        }
      }'
# -> {"id": 1, ...}

# 2. Submit the run bound to that state
curl -s -X POST http://127.0.0.1:8742/api/v1/runs \
  -H 'content-type: application/json' \
  -d '{
        "gantry_file": "packages/core/configs/gantry/cub_xl_panda_pipetting_mock.yaml",
        "deck_file": "packages/core/configs/deck/panda_imported_deck_pipetting_mock.yaml",
        "protocol_file": "packages/core/configs/protocol/panda/vial_transfer_acceptance.yaml",
        "mock_mode": true,
        "state": {"fluid_state_id": 1}
      }'
```

(`state.initial_state` with an inline `fluids` mapping is the one-call
alternative to the separate fluid-state POST.) Poll `GET /api/v1/runs/{id}`
for status; inspect `GET /api/v1/fluid-states/1/containers`, `/tips`, and
`/operations` for the same final-state tables as section 4. The operator web
UI surfaces the identical state views.

## 8. Test gates

```bash
.venv/bin/python -m pytest packages/core/tests -q
.venv-api/bin/python -m pytest services/api/tests -q
.venv/bin/python -m pytest sdk/python/tests -q
cd apps/operator-web && npm run lint && npm run test -- --run && npm run build
```
