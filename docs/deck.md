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

    The key directly below `labware:` is the stable instance ID. In this
    example it is `plate`, so protocols address wells as `plate.A1`,
    `plate.B2`, and so on. Choose a short name that describes the labware's
    role in this deck.

    `load_name` selects a predefined physical layout; it is not the instance
    ID. An optional `label` is display text and can be changed without changing
    protocol addresses. Renaming the top-level key changes the labware identity
    used by protocols and saved experiment state.

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

## Vials In A Grid

Use `vial_grid` when several vials share a regular layout. The predefined
layout supplies the row and column count, spacing, vial model, optional outer
dimensions, and volume defaults. The deck file supplies the measured A1 and A2
coordinates because those values belong to this physical setup.

```yaml
labware:
  reagents:                         # Stable instance ID
    load_name: ursa_9_vial_grid
    label: Reagent Vials            # Display text only
    calibration:
      a1: {x: 10.0, y: 20.0, z: 40.0}
      a2: {x: 10.0, y: 53.0, z: 40.0}
    aliases:
      buffer: A1
      catalyst: A2
```

The generated vial IDs use the same grid notation as a plate: `A1` through
`A9` for this definition. These addresses all identify the same two example
positions:

- `reagents.A1` and `reagents.buffer`
- `reagents.A2` and `reagents.catalyst`

Aliases map a human name to a generated position ID. They improve protocol
readability but do not create additional vials or database rows. Use the
generated ID when an alias is not helpful.

Values from a definition are defaults. Override a value in the deck entry only
when the physical labware differs. For example, a different vial product may
override `vial_model_name`, `vial_height`, `vial_diameter`, `capacity_ul`, or
`working_volume_ul`. Calibration remains deck-specific even when every other
value comes from the definition.

## Existing Nested Deck Files

Existing deck YAML files do not need to be rewritten. CubOS continues to load
the holder and its nested labware, and all existing protocol addresses keep
working. It also assigns a flat canonical ID internally:

| Existing address | Canonical address |
| --- | --- |
| `plate_holder.plate.A1` | `plate_holder__plate.A1` |
| `vial_holder.vial_1` | `vial_holder__vials.vial_1` |

The holder object and its old address remain available for holder geometry,
slots, and existing protocols. New deck files should use a top-level plate or
`vial_grid` when the holder does not need to be directly addressed. Saved
liquid state uses only the canonical ID, so an old alias and its canonical
address cannot create duplicate containers.

## Surface Z And Outer Geometry

Grid movement is determined by calibration and spacing, not by outer
dimensions:

- `calibration.a1.z` is the plate surface or vial-rim reference used by
  protocol commands.
- Plate `length`, `width`, `height`, and `well_depth` are optional physical
  metadata. Plate height is not used as a motion Z value, and the current plate
  bounding box carries the XY footprint rather than an outer Z height.
- Vial `height` and `diameter` are optional physical metadata. If they are
  omitted, the vial remains fully addressable and its outer bounding-box fields
  remain unset. Existing direct and holder-nested vials that specify these
  dimensions continue to load unchanged.
- Legacy holder definitions retain their fixture geometry and seat/surface
  offsets. Those offsets continue to determine nested labware Z for existing
  deck files.

7. **Validate before running hardware.**

    ```bash
    PYTHONPATH=src python setup/validate_setup.py \
      configs/gantry/cub_xl_asmi.yaml \
      configs/deck/asmi_deck.yaml \
      configs/protocol/asmi/indentation.yaml
    ```

    Replace the example paths with the gantry, deck, and protocol YAML files
    for your setup.
