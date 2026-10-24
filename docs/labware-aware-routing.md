# Labware-aware motion planning

CubOS can plan protocol movement around registered labware and all mounted
tools. The same immutable segments are used for offline validation and
execution. Decks without `motion_planning` keep their existing movement behavior.

## Enable routing

Add `motion_planning: {clearance_mm: 2}` at the top level of the deck YAML.
Every fixture must declare a `motion.box`, and every mounted instrument must
have a `motion_envelope` in the gantry YAML. For example, an ordinary calibrated
plate can declare:

```yaml
motion:
  box:
    anchor: A1
    offset: {x: -10, y: -10, z: -15}
    size: {x: 128, y: 86, z: 15}
```

These dimensions are illustrative; measure the actual fixture. `A1` uses the
calibrated A1/A2 frame. Scalar labware such as waste uses `anchor: location`.
The box offset registers the physical lower corner relative to the anchor;
labware height alone does not establish its position. V1 supports flat,
axis-aligned placements at multiples of 90 degrees.

Instrument envelopes are relative to the bare tool's calibrated TCP. Positive
Z points upward. An attached tip extends below the nozzle and changes the
collision geometry. `motion_envelope.additional_boxes` can represent a narrow
nozzle and wider body. The planner checks every mounted tool, including inactive
tools, against every registered fixture. Carriage bounds and tool clearance are
separate checks.

## Supported commands

Routing supports `move`, `pick_up_tip`, `transfer`, `mix`, `drop_tip`,
`aspirate`, `dispense`, `blowout`, timed `pause`, and non-moving camera `capture`.
Unsupported commands fail before protocol movement. `pause` preserves the pose;
`capture` records an image without moving the camera. A camera-target `move`
aligns the camera over that target at the carriage travel ceiling.

Standalone pipetting respects each command's labware-relative `height` and
requires an attached tip. Standalone aspiration, dispensing and blowout cannot
account for source/destination inventory and are rejected with durable fluid
tracking in routed runs. Use `transfer` for tracked liquid handling. Tracked tip occupancy is
included in the collision scene; uncertain operations still require operator
reconciliation. `transfer.require_uncapped` is not supported by routing v1.

## Access and execution

Ordinary target access is vertical. Permissions apply only to the target's
access corridor and active tool; they never permit crossing neighboring
fixtures. Transit first tries a clear XY diagonal, then direct axis orders and
obstacle-edge detours. It is a conservative finite search, so it can reject a
complex route that might be physically possible.

For an open-ended tip rack, declare:

```yaml
motion:
  box:
    anchor: A1
    offset: {x: -7, y: -78, z: -70}
    size: {x: 124, y: 84, z: 63}
  occupied_tip_radius_mm: 2.5
  access:
    pick_up_tip:
      strategy: side_exit
      lift_mm: 30
      exit_edge: x_min
      clearance_mm: 8
```

Again, these are example dimensions. The planner checks approach, engagement,
tip attachment, lift and exit before pickup. `exit_edge` is in the labware-local
frame. Other loaded tips can block withdrawal; consume tips from the exposed
edge inward. The lift is carriage displacement, not lift plus tip length.

Runtime planning uses the observed carriage position and requires an idle
controller. Each segment checks the actual starting pose and attached-tool
state before execution. Planned segments use a dedicated straight-move driver
path, so a diagonal is not silently expanded into X-then-Y motion. Ordinary
unplanned moves retain their existing axis order. A failure does not trigger an
automatic retract or recovery movement.

## Validate and test

Run offline validation with the intended, calibrated files:

```sh
python -m cubos.tools.validate_setup gantry.yaml deck.yaml protocol.yaml
```

The output reports bounds, semantics and the number of collision-aware plans.
Offline plans state their assumed starting pose; they do not establish physical
clearance or actual tip occupancy. Operator import, calibration and save flows
preserve the routing metadata.

Before using a new setup, measure the envelopes and verify the corridors against
the physical deck. Have an operator supervise a clear-space route, dry tip pickup
and small water transfer. Record clearance, tip pickup/disposal and liquid
behavior. Reconcile any interrupted operation before another run.
