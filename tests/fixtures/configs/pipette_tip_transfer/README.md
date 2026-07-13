# Pipette Tip Transfer Simulation Fixture

Offline-only Cub XL fixture for replaying pipette tip pickup, attached-tip
height, transfer, blowout, drop-tip, and home behavior.

Files:

- `gantry.yaml` - simulated Cub XL gantry with an offline Opentrons P300.
- `deck.yaml` - well plate, tip rack, and tip disposal positions inside the
  simulated reach envelope.
- `protocol.yaml` - six-step protocol used by `digital-sim` examples.

Validate without hardware:

```bash
python setup/validate_setup.py \
  tests/fixtures/configs/pipette_tip_transfer/gantry.yaml \
  tests/fixtures/configs/pipette_tip_transfer/deck.yaml \
  tests/fixtures/configs/pipette_tip_transfer/protocol.yaml
```
