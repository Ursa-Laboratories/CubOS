# Side-exit tip racks

A long tip may need to leave an open-ended rack horizontally because available
Z travel cannot clear the rack vertically. Prefer [collision-aware
routing](labware-aware-routing.md) for protocols that move among surrounding
labware: it checks all mounted tools, the rack body and occupied tip slots.

An existing deck without routing can specify a fixed legacy pickup path:

```yaml
tip_length: 70
side_exit:
  lift_mm: 30
  exit_x: 140
```

These are example dimensions, not a calibrated setup. `exit_x` is an absolute
tool X coordinate beyond the opening. The lift must be at least 30 mm. Pickup
requires an explicit slot, a bare pipette, sufficient carriage bounds, and a
clear exit lane. Consume the exposed slots before moving inward.

The legacy path approaches at `slot.z + lift_mm`, engages at `slot.z`, attaches
the tip, lifts the carriage by exactly `lift_mm`, then withdraws along X. After
attachment the tool-tip target is lower by `tip_length`; that offset must not
increase the carriage lift. Setup validation checks the same endpoints.
Failure retains attached-tip/consumed-slot state, and durable tracking marks an
uncertain pickup for reconciliation.

The fixed legacy exit path does not provide general collision avoidance for
subsequent moves. Verify the exit and onward corridor physically, or enable
routing with registered fixture/tool geometry. With routing enabled, its
`motion.access.pick_up_tip` policy determines the checked pickup/departure path.

Before hardware use, an operator must verify slot positions, nozzle depth, tip
extension, usable Z range and the open corridor. Supervise a dry pickup from the
exposed edge and check the lift and X withdrawal before a water transfer. Do not
infer clearance from a rendered mesh or nominal dimensions.
