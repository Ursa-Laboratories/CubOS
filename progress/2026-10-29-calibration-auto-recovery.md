# Automatic calibration limit recovery

This main-based PR isolates recovery from the dipper0 integration release.
Its driver, Gantry wrapper, session, helper and API implementation match
`b6b625009d2069810b239db23f2d9e26ba7e50d3`; unrelated hardware geometry,
station configuration, draft/trough features and static-cache changes are excluded.
The PR branch has not been deployed.

User-authorized remote bench tests on dipper0 used the actual served gantry
calibration wizard and the connected H.264 USB camera. Four individual +Y
0.25 mm UI jogs approached the rear Y switch from reported Y399.730; the
normal-jog Y rate was temporarily capped at 100 mm/min. Hard limits stayed on;
calibration temporarily disabled soft limits through the existing workflow.
At 12:24:11.309 EDT on 29 October, exactly one automatic Y−5 mm command at
100 mm/min cleared the switch. The driver logged its own acknowledgement at
12:24:11.324, the API returned 200, and fresh readback was Idle with no pins.
No Pull off button or direct recovery POST was used. The UI required Home afterward.
Cleanup, explicit homing and a normal 0.5 mm jog passed; limits and the recorded
Y rate were restored, saved configs were unchanged, and the integration was left
homed/Idle without warnings.

Logs and screenshots are retained locally as `second-api-segment.log`,
`second-auto-mill_control.log`, `second-camera-motion.json`,
`automatic-recovery-complete.png` and `final_position.json`.
Camera feature displacement corroborated movement, not calibrated distance.
Labware-view automatic triggering is tested offline. X/Z switch contact,
fluid handling and the new main-based integration have not been physically tested.

Offline validation for this extraction is recorded in the PR description.
