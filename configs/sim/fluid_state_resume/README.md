# Persistent Fluid-State Resume Example

This offline-only Cub XL example uses one deck-linked SQL fluid state across
two separate protocol runs. The deck names its two volume-bearing labware
items `reagents` and `assay_plate`. The predefined `ursa_9_vial_grid` owns the
vial spacing and dimensions; this deck supplies its calibrated A1/A2 anchors
and the readable aliases `buffer` and `dye`.

The first protocol loads buffer into assay wells A1 and A2. The second resumes
the same SQL state, adds dye, and mixes each well. Protocols may use the vial
aliases (`reagents.buffer` and `reagents.dye`), while persistence stores their
canonical positions (`reagents.A1` and `reagents.A2`).

The seed starts with 1000 uL buffer and 200 uL dye. After both runs, the
expected state is:

| Location | Total | Composition |
|---|---:|---|
| `reagents.A1` (`reagents.buffer`) | 820 uL | 820 uL buffer |
| `reagents.A2` (`reagents.dye`) | 160 uL | 160 uL dye |
| `assay_plate.A1` | 120 uL | 100 uL buffer + 20 uL dye |
| `assay_plate.A2` | 100 uL | 80 uL buffer + 20 uL dye |

The other reagent-grid positions and assay wells remain empty.

Choose a local simulation database and run the first protocol with the seed
file. CubOS creates the deck-linked state as part of the protocol run and
prints its numeric ID:

```bash
python setup/run_protocol.py \
  configs/sim/fluid_state_resume/gantry.yaml \
  configs/sim/fluid_state_resume/deck.yaml \
  configs/sim/fluid_state_resume/01_load_plate.yaml \
  --mock \
  --database /tmp/cubos-fluid-state-resume.db \
  --initial-fluids configs/sim/fluid_state_resume/initial_fluids.yaml
```

Resume the printed state ID in the second protocol run:

```bash
python setup/run_protocol.py \
  configs/sim/fluid_state_resume/gantry.yaml \
  configs/sim/fluid_state_resume/deck.yaml \
  configs/sim/fluid_state_resume/02_add_dye.yaml \
  --mock \
  --database /tmp/cubos-fluid-state-resume.db \
  --fluid-state-id ID
```

`--mock` is required for this example. It constructs offline gantry and
instrument drivers and does not connect to hardware.

If a pipette action fails after its journal entry starts, CubOS blocks resume
until the physical result is reconciled through the core `DataStore` fluid
state API. CubOS does not guess whether liquid moved after an interrupted
hardware action.

The files are simulation fixtures, not hardware calibration. Validate each
gantry/deck/protocol triple with `setup/validate_setup.py` before adapting it.
