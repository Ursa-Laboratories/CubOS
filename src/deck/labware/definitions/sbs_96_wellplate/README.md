# SBS 96-Well Plate

Generic SBS ANSI-standard 96-well microplate template. Conforms to the
ANSI SLAS 1-2004 footprint and SLAS 4-2004 well-position standards, so it
should fit any standard 96-well plate (Corning, Greiner, Thermo, etc.)
that advertises SBS/ANSI compliance.

Maps to `cubos.src.deck.labware.well_plate.WellPlate`.

## Files

| File | Purpose |
| --- | --- |
| `SBS96WellPlate.yaml` | Class-attribute template consumed by the definitions registry. |

## Standard dimensions

| Attribute | Value | Notes |
| --- | --- | --- |
| Outer footprint | 127.76 × 85.47 mm | ANSI SLAS 1-2004 |
| Plate height (outer) | 14.35 mm | Rim → underside of plate; override for deep wells |
| Well depth (inside) | 10.67 mm | Rim → inside floor; flat-bottom shallow SBS96 |
| Well grid | 8 × 12 (A1 – H12) | Letters are rows, numbers are columns |
| Well pitch | 9.0 mm in both x and y | ANSI SLAS 4-2004 |
| A1 offset from plate corner | (14.38, 11.24) mm | Template placeholder in `calibration.a1` |
| Default capacity | 200 µL | Override for deep-well or other variants |
| Default working volume | 150 µL | Override as needed |

## Usage

Reference the definition from a deck YAML via `load_name`, then override
at least `calibration.a1` and `calibration.a2` with real deck coordinates:

```yaml
labware:
  my_plate:
    load_name: sbs_96_wellplate
    calibration:
      a1: { x: -17.88, y: -42.23, z: -20.0 }
      a2: { x: -17.88, y: -51.23, z: -20.0 }
    x_offset: 9.0    # positive spacing magnitude; A1/A2 determine direction
    y_offset: 9.0
```

Vendor-specific variants (e.g. Corning 360 µL round-bottom, deep-well
2 mL, skirt height differences) should override the relevant fields
(`height`, `well_depth`, `capacity_ul`, `working_volume_ul`) in
the deck YAML. The pair `(height, well_depth)` is intentionally
separate: `height` is the outer dimension (rim → underside),
`well_depth` is the inside (rim → sample floor). Analysis pipelines
use `a1.z - well_depth` to compute sample thickness.

## Compatibility

- Any deck supported by PANDA-BEAR / cubos that has room for a 127.76 ×
  85.47 mm footprint.
- Not a printable part — this is a catalog definition for a commercially
  manufactured consumable, so there is no STL/GLB.
