# Analytical Sales 96 Aluminum Vial Well Plate

Definition for the Analytical Sales & Services aluminum vial well plate
shown in drawing `101960_rev6f_PUBLIC`, Rev 6F. The workspace source file
is `pdfs/aluminum vial well plate.pdf`.

Maps to `cubos.src.deck.labware.well_plate.WellPlate`.

## Files

| File | Purpose |
| --- | --- |
| `AluminumVialWellPlate.yaml` | Class-attribute template consumed by the definitions registry. |

## Source dimensions

| Attribute | Value | Source note |
| --- | --- | --- |
| Footprint | 127.8 x 85.5 mm | Drawing dimensions 5.030 in and 3.365 in |
| Height | 46.2 mm | Drawing label "height with vials" |
| Well grid | 8 x 12 (A1-H12) | Drawing row/column labels |
| Well pitch | 9.0 mm in both x and y | Drawing "vial pitch" callouts |
| A1 drawing offset | 14.4 x / 11.2 y mm | Drawing dimensions 0.566 in and 0.443 in |
| Vials | 8 mm x 30 mm, 1 mL | Drawing note for part #884001 |
| Capacity | 1000 uL per position | From the 1 mL vial note |

`well_depth` is intentionally omitted because the drawing does not specify
the inside sample-floor depth from the calibrated access surface. Override
`well_depth` in a deck YAML after measuring the actual vial/sample-floor
reference used by the protocol.

## Usage

Reference the definition from a deck YAML via `load_name`, then override
`calibration.a1` and `calibration.a2` with real deck coordinates:

```yaml
labware:
  vial_plate:
    load_name: analytical_sales_96_aluminum_vial_well_plate
    calibration:
      a1: { x: 100.0, y: 80.0, z: 35.0 }
      a2: { x: 109.0, y: 80.0, z: 35.0 }
```

The pitch fields are positive spacing magnitudes; the A1 to A2 calibration
delta determines the actual column direction on the deck.
