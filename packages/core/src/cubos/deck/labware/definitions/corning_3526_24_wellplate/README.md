# Corning 3526 24-Well Plate

Corning 3526 24-well flat-bottom microplate. The footprint and well
positions conform to the ANSI SLAS 1-2004 and SLAS 4-2004 standards, so
the plate seats in any SBS-compatible holder. Unlike the generic
`sbs_96_wellplate` template, this definition also declares per-well
lateral geometry via `well_geometry`.

Maps to `cubos.deck.labware.well_plate.WellPlate`.

## Files

| File | Purpose |
| --- | --- |
| `Corning3526_24WellPlate.yaml` | Class-attribute template consumed by the definitions registry. |

## Standard dimensions

| Attribute | Value | Notes |
| --- | --- | --- |
| Outer footprint | 127.76 × 85.47 mm | ANSI SLAS 1-2004 |
| Plate height (outer) | 20.02 mm | Rim → underside of plate |
| Well depth (inside) | 17.4 mm | Rim → inside floor; vendor-specific, verify |
| Well grid | 4 × 6 (A1 – D6) | Letters are rows, numbers are columns |
| Well pitch | 19.3 mm in both x and y | ANSI SLAS 4-2004 |
| A1 offset from plate corner | (15.13, 13.67) mm | Template placeholder in `calibration.a1` |
| Well shape | Circular, flat bottom | `well_geometry.shape` / `.bottom` |
| Well inner diameter | 15.6 mm | Vendor drawing, verify |
| Default capacity | 3400 µL | |
| Default working volume | 1900 µL | |

SLAS standardizes the footprint and well *positions*, not well diameter
or depth. Verify `well_geometry.diameter` and `well_depth` against your
plate's drawing before running hardware.

## Usage

Reference the definition from a deck YAML via `load_name`, then override
at least `calibration.a1` and `calibration.a2` with real deck coordinates:

```yaml
labware:
  my_plate:
    load_name: corning_3526_24_wellplate
    calibration:
      a1: { x: -17.88, y: -42.23, z: -20.0 }
      a2: { x: 1.42, y: -42.23, z: -20.0 }
    x_offset: 19.3   # positive spacing magnitude; A1/A2 determine direction
    y_offset: 19.3
```

`well_geometry` is optional on `WellPlate` in general — plates that omit
it stay fully addressable. It is declared here because the per-well
cross-section is known for this catalog part. Consumers should read
`well_cross_section_area_mm2` / `well_inscribed_radius_mm` rather than
branching on `well_geometry.shape`.

## Compatibility

- Any deck supported by PANDA-BEAR / cubos that has room for a 127.76 ×
  85.47 mm footprint.
- Not a printable part — this is a catalog definition for a commercially
  manufactured consumable, so there is no STL/GLB.
