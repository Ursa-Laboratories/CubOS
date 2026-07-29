# Hold-state homing recovery

## Scope

Prevent operator-initiated homing from hanging when GRBL reports `Hold:*`,
and expose an explicit operator-controlled resume action in the CubOS UI.

## Hardware impact

- Homing status handling changes at the GRBL driver boundary.
- Resume sends GRBL realtime cycle start (`~`) only after an explicit operator action.
- No automatic resume is permitted.

## Offline validation

- `cd packages/core && ../../.venv/bin/python -m pytest tests/gantry/driver/test_gantry_driver.py tests/gantry/test_session.py -q`
  - `90 passed, 8 subtests passed`
- `cd services/api && ../../.venv/bin/python -m pytest tests/test_gantry_router.py -q`
  - `74 passed`
- `cd apps/operator-web && npm run test -- GantryPositionWidget.test.tsx --run`
  - `32 passed`

## Physical validation

Pending on a connected Cub XL:

1. Clear the deck and keep the E-stop ready.
2. Enter feed hold while stationary and confirm the UI reports `Hold:*`.
3. Confirm Home does not remain stuck at `Homing...`.
4. Use the explicit Resume control and confirm the controller returns to `Idle`.
5. Confirm Home then reaches the configured homing switches and returns `Idle`.
