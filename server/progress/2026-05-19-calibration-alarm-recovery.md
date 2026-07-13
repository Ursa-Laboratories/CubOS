# Calibration Alarm Recovery

## Context

During Zoo calibration, a Z-down jog can trip a GRBL alarm. The calibration
modal previously showed only a generic jog error, while the main gantry-panel
unlock affordance was hidden behind the modal.

## Changes

- `/api/gantry/jog` now surfaces alarm-like jog failures with a 409 response
  instead of returning `ok`.
- `CalibrationWizard` stops repeated jogs on alarm-like errors, disables jog
  controls, and shows an inline `Unlock alarm` prompt.
- The operator is told to unlock, then jog Z+ away from the limit before
  lowering again.

## Verification

- `pytest tests/test_gantry_router.py -q`
- `npm run test -- CalibrationWizardAlarm.test.tsx CalibrationWizard.test.ts App.test.tsx`
- `npm run lint`
- `npm run build`
- Hardware check on the gantry: operator confirmed the alarm prompt/unlock flow
  looked good after testing.
