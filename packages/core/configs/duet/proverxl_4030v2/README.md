# Duet 3 MB6XD — Genmitsu ProVerXL 4030 V2

RepRapFirmware 3.5+ standalone configuration for the ProVerXL 4030 V2 gantry after the
stock GRBL control box was replaced with a Duet 3 Mainboard 6XD. The V2's integrated
closed-loop NEMA 23 steppers take step/dir/enable directly from the 6XD's external-driver
channels. Spindle intentionally unconfigured (lab gantry; CubOS issues no M3/M5).

Machine coordinates equal the CubOS deck frame: FLB origin, +X right, +Y back, +Z up;
homed corner = (Xmax, Ymax, Zmax). The 3 mm homing pull-off is reserve, not usable
coordinate space (M208 spans = usable range; homing files `G92` the backed-off position).

## Record (fill in at bring-up)

| Item | Value |
|---|---|
| Firmware version (`M115`) | RRF 3.6.1 (2025-08-25) |
| Board revision (`M122` / silkscreen) | Duet 3 MB6XD v1.02 or later (no external pull-ups needed) |
| En_Pol jumper position | not separately verified — enable works via `M569 R1` in practice |
| Motor DIP microstep setting | not read directly; steps/mm confirmed correct via homed-position match |
| Harness note | Y channels are crossed vs. driver-connector labels: physical Y2 on driver 0.1, physical Y1 on driver 0.2 (see M584 comment in config.g) |
| Measured clearance beyond M208 minima (2026-07-31) | X: ~10 mm, Y: ~15 mm, Z: ~7 mm before switch contact — nominal 400/300/110 spans confirmed safe, no M208 change needed |
| Soft limits | verified refused at both ends of all three axes (`G1 X-1`/`X401` etc. → "target position outside machine limits") |
| Repeatability (ruler precision) | X 4/4, Y 3/3, Z 3/3 hits on target after repeated home+move — no detectable scatter |
| Tuned motion values (2026-07-31) | X: 2400 mm/min / 450 mm/s² accel / 400 jerk. Y: 1800 mm/min (see resonance note below) / 450 accel / 400 jerk. Z: left at bring-up values (900/150/120), untuned. |
| Y resonance band | Repeatable shudder (both sides, throughout the move) found ~2100–2400 mm/min; clears below and above. 1800 is the proven ceiling — not investigated further. Candidate causes: gantry/coupling stiffness. Revisit before pushing Y speed higher. |
| Z tuning | Not attempted — this axis had a screw jam and a flaky signal connector during bring-up (both resolved). Recommend a mechanical inspection before raising Z speed/accel past bring-up values. |

## Wiring

Per-motor signal cable (stock harness wire → 6XD driver connector):

| Stock wire | 6XD pin | Note |
|---|---|---|
| PUL | `D#_STEP_NEG` | active-high at motor; 6XD idles high, pulses low — OK |
| DIR | `D#_DIR_NEG` | direction sense fixed with `M569 S` only |
| GND | `D#_GND` | signal return |
| EN | `D#_EN_NEG` | motor is enabled-when-grounded; see enable check below |

Channels and IO:

| RRF driver | Motor | | Pin | Function |
|---|---|---|---|---|
| 0.0 | X | | io0.in | X limits (min+max NO switches in parallel, to GND) |
| 0.1 | Y2 (harness crossed) | | io1.in | Y limits |
| 0.2 | Y1 (harness crossed) | | io2.in | Z limits |
| 0.3 | Z | | io3.in | E-stop switch (soft path) |
| 0.4/0.5 | spare | | io4.in | Reset button → `M999` |
| | | | io5.in | Pause button → pause.g |
| | | | io6.in | Resume button → `M24` |

Power: 24 V rail → 6XD VIN; 48 V rail → motor power, **with an NC e-stop contact in the
48 V feed (hard path — mandatory)**. Star-common the 48 V−, 24 V−, and 6XD GND at the PSU.

Safety consequences of this switch topology (differs from stock GRBL hard limits):
RRF only watches endstops during homing moves, so min-end protection is soft limits only
(`M564 S1 H1` — no motion before homing). NO switches are not fail-safe: a broken switch
wire is silent. Homing aborts if an axis switch is already closed (shared min/max channel
means the firmware cannot tell which end is pressed).

## Deployment

Copy `sys/` → the Duet SD card `/sys/` (or upload via DWC System page, which prompts to
restart). Never hand-edit files on the SD card without back-porting here; keep everything
declarative (no `config-override.g`, no `M500`).

## Bring-up checklist (staged; stop at each gate)

1. **Pre-power (meter, nothing energized):** VIN polarity at the 6XD; no short between
   48 V and 24 V rails or from either rail to signal lines; limit switch polarity at both
   ends of each axis (expect NO-to-ground); board rev (≤1.01 needs external 10K pull-ups
   on STEP/DIR/EN to +5V; v1.02+ doesn't); record DIP positions.
2. **Logic-only (24 V + USB/Ethernet, no 48 V):** `M115`, `M122` clean; `M98 P"config.g"`
   runs with zero errors; DWC reachable. Enable check: EN_NEG high at boot, low after
   `M17`, high after `M18` — flip `M569 R` (not wiring/jumper) if backwards.
3. **Inputs:** `M119` per axis at both ends; e-stop fires trigger 0 AND (metered) opens
   the 48 V path; pause/resume/reset buttons fire their triggers. — **GATE: confirm
   before motor power.**
4. **Single motor (X) on 48 V:** `G91 G1 X10 F300` moves exactly 10.0 mm (confirms
   M92 vs DIPs); rough/no motion → strengthen pull-ups (~470 Ω–1 K to 5V_EXT) or relax
   `M569 T`.
5. **All motors:** +X right, +Y back, +Z up (fix with `M569 S`); Y pair moves in unison
   without racking. — **GATE: confirm before homing.**
6. **Homing:** `G28 Z`, then `G28 X`, `G28 Y`, then full `G28` from mid-travel, hand on
   e-stop; `M114` reads (400, 300, 110). — **GATE: confirm before limits/tuning.**
7. **Travel measurement:** find true usable span per axis; update `M208` maxima and the
   homing `G92` values (switch = usable max + 3 mm); verify soft limits refuse
   out-of-range moves at both ends.
8. **Repeatability ×5** (scatter ≪0.05 mm), then tuning ladder: raise `M203` in
   500 mm/min steps toward 3000–4000 (watch screw whip on the 400 mm X screw and
   closed-loop fault LEDs), `M201` toward 600–800, keep `M566` ≤ ~M203/5; re-check
   repeatability after each rung.

## Out of scope / future

- CubOS still speaks GRBL (`src/gantry/gantry_driver/driver.py`); a DuetDriver (USB
  serial `ok` handshake + `M409` object-model status) is a separate effort. Nothing here
  precludes it: USB is unclaimed, machine coords = deck frame, G54 identity.
- Optional: motor ALM outputs → `D#_STOP` inputs for closed-loop fault halts.
- Spindle, if ever wanted: `M950 R0` + `M563` + PWM→0-10V/DC-driver on a spare `out` pin.
