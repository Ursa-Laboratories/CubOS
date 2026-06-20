# Deck Internals

This page is for contributors who need to change deck loading, labware
definitions, or validation behavior. Operators should use
[Set Up Deck and Labware](deck.md).

## Labware Definitions

Common labware is described under `src/deck/labware/definitions/`. A deck YAML
can use `load_name:` to start from one of those definitions and override the
placement-specific fields.

```yaml
labware:
  plate:
    load_name: sbs_96_wellplate
    name: asmi_96_well
    model_name: asmi_96_well
    calibration:
      a1: { x: 347.0, y: 42.0, z: 30.0 }
      a2: { x: 338.0, y: 42.0, z: 30.0 }
```

`load_name:` is shallow-merged with user fields. Dict-valued fields such as
`calibration:` are replaced whole, so deck YAML must supply both `a1` and `a2`.

## Available Definitions

| `load_name:` | Class | Notes |
| --- | --- | --- |
| `analytical_sales_96_aluminum_vial_well_plate` | `WellPlate` | Analytical Sales & Services 8 x 12 aluminum vial plate. |
| `sbs_96_wellplate` | `WellPlate` | Generic ANSI SLAS 96-well microplate. |
| `ursa_tip_rack` | `TipRack` | Ursa pipette tip rack. |
| `ursa_vial_holder` | `VialHolder` | 9-position tight-fit 20 mL vial holder. |
| `ursa_wellplate_holder` | `WellPlateHolder` | Tall wellplate holder. |
| `ursa_wellplate_holder_conductive` | `WellPlateHolder` | Conductive wellplate holder. |
| `sharc_80mm_sbs_wellplate_holder` | `WellPlateHolder` | SHARC 80 mm SBS holder. |

## Coordinate And Z Semantics

- Well plates and tip racks use two-point calibration: `calibration.a1` and
  `calibration.a2`.
- A2 must be one adjacent column step from A1 and must share either X or Y with
  A1.
- `x_offset` and `y_offset` are positive pitch magnitudes. The A1 to A2 delta
  determines orientation.
- Well plate and tip rack surface Z comes from `calibration.a1.z` and
  `calibration.a2.z`.
- Vials and holders use `location.z`.
- `height` is a physical outer dimension, not a Z reference.

## Labware Types

| Type | Purpose |
| --- | --- |
| `well_plate` | Multi-well plate addressed as `plate.A1`, `plate.B2`, and so on. |
| `tip_rack` | Tip pickup locations plus per-tip occupancy and `tip_length`. |
| `vial` | Single fixed vial location. |
| `vial_holder` | Holder that can seat nested vials. |
| `well_plate_holder` | Holder that can seat one nested well plate. |
| `tip_disposal` | Used-tip disposal fixture. |
| `wall` | Rectangular obstacle from two opposite corners. |

## Add A New Definition

1. Create `src/deck/labware/definitions/<new_name>/`.
2. Add a YAML file that lists the labware class fields directly, without a
   top-level `labware:` wrapper.
3. Register it in `src/deck/labware/definitions/registry.yaml`.
4. Add a short README in the new definition folder with dimensions and
   compatibility notes.

Run the focused deck tests after changing definitions:

```bash
python -m pytest tests/deck/test_deck_loader.py tests/deck/test_holder_labware.py -q
```
