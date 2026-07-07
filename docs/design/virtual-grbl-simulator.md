# Virtual GRBL Simulator

!!! warning "Design proposal - NOT implemented"
    This page is a design proposal for a future virtual GRBL simulator. CubOS
    does not currently ship the `backend` or `sim_profile` gantry YAML fields,
    the `gantry.simulator` Python package, or the `simulator_viewer/` frontend.
    Current gantry connections always use the physical/offline paths implemented
    in `src/gantry/gantry_driver/driver.py` and the current gantry YAML schema.

## Proposed Gantry Connection Path

CubOS currently finds and talks to physical GRBL controllers in
`src/gantry/gantry_driver/driver.py`.

A simulator implementation could add a backend selection layer at the low-level
connection boundary. In that proposal:

- Serial scan/probe code would remain responsible for the real-controller path.
- The real path would continue to expose a pyserial-style object stored on
  `Mill.ser_mill`.
- A simulator path could instantiate a serial-like
  `gantry.simulator.connection.SimGrblSerialConnection`.
- `Gantry`, `GantrySession`, protocol execution, and Zoo would continue to call
  normal CubOS APIs.

## Proposed Backend Model

A future gantry YAML schema could accept:

```yaml
backend: real_serial  # default
# or:
backend: sim_grbl
sim_profile: cub      # cub or cub_xl; defaults from gantry_type
```

`real_serial` would open a physical controller with the existing pyserial scan.
`sim_grbl` would create a virtual GRBL 1.1-style controller under the same
connection slot. The only behavioral branch for connection selection should live
in the low-level connection layer.

## Proposed Virtual Controller Boundary

`gantry.simulator.controller.VirtualGrblController` would own simulated
controller state:

- parser modal state: G90, feed, active WCS, G92 clear state
- machine state: Idle, Run, Jog, Hold, Home, Alarm
- deterministic MPos/WPos and work coordinate offsets
- GRBL settings used by CubOS: `$10`, `$20`, `$21`, `$22`, `$23`, `$24`, `$25`,
  `$26`, `$27`, `$100-$102`, `$110-$112`, `$120-$122`, `$130-$132`
- soft-limit, hard-limit, homing-lock, unlock, status, feed-hold, jog-cancel,
  and soft-reset behavior
- trace events for every accepted motion block

Unsupported commands should intentionally return GRBL-like errors. The simulator
would not implement spindle, coolant, arcs, dwell, probing, G0 rapids, unit
toggles, or check mode unless the feature scope expands.

## Proposed Machine Profiles

`gantry.simulator.profiles` could define first-class profiles for:

- `cub`: Genmitsu 3018-PROVer V2-derived Cub, 290 x 180 x 40 mm work area,
  moving Y table/spoilboard, X/Z gantry carriage, passive spindle/collet tool
  geometry.
- `cub_xl`: Genmitsu PROVerXL 4030 V2-derived CubXL, 400 x 300 x 110 mm work
  area, fixed deck/spoilboard, moving Y gantry, X carriage, passive Z stack.

Each profile would carry physical metadata, render metadata, simple AABB
collision volumes, GRBL settings, and explicit calibration placeholders. Real
controller `$$` values, switch positions, backlash, deck origin, and measured
transforms would remain calibration gaps until measured from hardware.

## Proposed Trace Event Contract

Each accepted motion event would be emitted as a dictionary with:

- `sequence`
- `command`
- `kind`
- `start_mpos`, `end_mpos`
- `start_wpos`, `end_wpos`
- `feed`
- `estimated_duration_s`
- `controller_state`
- `planner_state`
- `limits_checked`
- `warnings`
- `machine_profile`
- `render_geometry`
- `collision_volumes`

The trace would be authoritative for visualization and replay. Renderers could
interpolate between the event start/end poses over the event duration, but they
should not infer controller semantics from G-code.

## Proposed Render/Replay Frontend

A future `simulator_viewer/` static frontend could contain:

- `index.html`
- `src/styles.css`
- `src/app.js`

It could load a trace JSON file or fetch a trace endpoint, animate near-real-time
motion from CubOS trace events, pause/play, seek, and replay deterministically.
It should own no GRBL parser, no limit checking, and no machine state
transitions. It should draw profile and collision metadata from the trace
itself.

Visual references that could inform profile metadata:

- `docs/images/orientation.webp`
- `docs/images/calibration-block-marker.webp`
- `docs/images/center-calibration-block.webp`
- `docs/images/single-instrument-calibration-block.webp`
- `../projects/landing-page/assets/asmi_indent.png`

## Proposed Zoo Boundary

Zoo should remain a thin API/UI layer over CubOS. Its gantry routes should
continue to delegate to `GantrySession`. Sim selection, if implemented, should be
data in the gantry YAML that CubOS consumes; Zoo should not parse GRBL,
duplicate machine dimensions, or own simulator physics.
