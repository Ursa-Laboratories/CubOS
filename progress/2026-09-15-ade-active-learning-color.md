# ADE active-learning color matching

Status: focused offline validation passed on branch `ADE`; no Pi deployment or physical run.

Implemented:

- General campaign editor controls for DOE seed points, GP kernel, constraints, sequences, and nested bindings.
- Matérn 5/2 optimizer option and ordered initial design points.
- Center-ROI median RGB to CIE Lab and CIEDE2000 analysis.
- Zero-motion `measure_color` protocol command returning a numeric campaign objective.
- Color-matching preset and reference campaign/protocol.
- Integrated color setup that reads a selected target well and generates the complete campaign draft in the Active Learning view.

Safety boundaries:

- The development branch was created from the 2026-09-14 checkpoint.
- Live Pi configs have not been edited and no hardware command has been issued.
- The station's `$27=0.5` versus config `2` mismatch remains unresolved.

Focused validation:

- 53 core optimizer/color/camera-command tests passed.
- 46 focused API campaign/route tests passed.
- 7 campaign UI tests passed; TypeScript, ESLint, and production build passed.
- The station-specific candidate protocol passed setup validation with 33 targets and 32 immutable routing plans.
- The full 18-trial campaign specification passed server campaign preflight in offline mode; its first point was 200/50/50 µL.

Pending physical validation:

- Supervised target-image calibration and single-trial hardware validation before any campaign.
