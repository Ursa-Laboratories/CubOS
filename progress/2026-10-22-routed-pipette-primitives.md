# Standalone pipette routing — operator verification

Changes affect gantry routes and pipette aspiration, dispensing and blowout.
Offline tests verify exact planned segments, pause position, YAML dispense,
height/tip bounds, and whole-protocol rejection before movement. No physical
hardware was tested by the agent. Keep this PR in draft until operator results
are recorded.

On the Pi, with the intended gantry and deck selected:

1. Confirm calibration and current carriage/tool state. Ensure the configured
   pickup slot contains a fresh tip, the source has sufficient liquid, and the
   destination and waste can receive it. Use water for verification.
2. Validate `a1_transfer.yaml` in Operator. Confirm collision-aware validation
   succeeds with the selected gantry and deck.
3. Start the protocol manually. Observe tip pickup from C4, approach/descent to
   `10_vial_holder.A1` at height -40 mm, aspiration of 100 µL, a 300-second pause
   at that pose, departure/transit to `plate.A1`, blowout at height 0, and tip
   disposal at waste. Stop if the physical clearance disagrees with the preview.
4. To verify standalone dispense, duplicate the protocol, select a fresh
   available tip, and insert this step after the pause and before blowout:

   ```yaml
   - dispense:
       position: plate.A1
       volume_ul: 100
       speed: 50
       height: 0
   ```

   Validate the copy before starting it manually. Observe 100 µL dispensing
   at A1 followed by blowout. Account for liquid already in the destination.
5. Record gantry/deck filenames, protocol name, tip slot, observed clearances,
   delivered liquid behavior, pause duration, and any faults. An interrupted
   run requires operator reconciliation before another run; do not replay it
   automatically.

Standalone commands require runs without durable fluid inventory tracking.
Use `transfer` for tracked source/destination accounting.
