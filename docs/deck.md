# Set Up Deck and Labware

Use this guide when labware is moved, recalibrated, or replaced.

1. **Complete gantry calibration first.**

    The gantry calibration establishes the deck coordinate frame that all
    labware positions use.

2. **Secure the labware on the deck.**

    Place the labware in its holder or fixture so it cannot shift during the
    run. The holder or deck placement must be repeatable.

3. **Choose which instrument records the labware position.**

    In a single-instrument setup, use the mounted instrument.

    In a multi-instrument setup, use the leftmost/reference instrument selected
    during gantry calibration. This instrument defines the shared deck origin.

4. **Jog to the labware calibration points.**

    Use Zoo, UGS, or another G-code controller to jog the instrument to the
    physical points that define the labware position.

    For a 96-well plate, jog to A1 and record the displayed position. Then jog
    to A2 and record the displayed position.

5. **Enter those points in the deck YAML.**

    ```yaml
    labware:
      plate:
        load_name: sbs_96_wellplate
        name: asmi_96_well_deck_origin
        model_name: asmi_96_well_deck_origin
        calibration:
          a1:
            x: 347.0
            y: 42.0
            z: 30.0
          a2:
            x: 338.0
            y: 42.0
            z: 30.0
        x_offset: 9.0
        y_offset: 9.0
    ```

6. **Fill in the remaining labware values.**

    For a 96-well plate, `x_offset` and `y_offset` are the well spacing
    magnitudes. Standard SBS 96-well plates usually use `9.0` mm in both
    directions. The measured A1 and A2 points define the plate orientation on
    the deck.

    By default, CubOS keeps the legacy convention: when columns advance in +X,
    rows advance in -Y; when columns advance in +Y, rows advance in +X. If your
    physical plate uses the opposite row side, set `row_direction: positive` or
    `row_direction: negative` to choose the signed deck axis for row B from A1.

    The `z` value on `calibration.a1` and `calibration.a2` is the labware
    reference surface for those wells, not the physical plate height.

7. **Validate before running hardware.**

    ```bash
    PYTHONPATH=src python setup/validate_setup.py \
      configs/gantry/cub_xl_asmi.yaml \
      configs/deck/asmi_deck.yaml \
      configs/protocol/asmi/indentation.yaml
    ```

    Replace the example paths with the gantry, deck, and protocol YAML files
    for your setup.
