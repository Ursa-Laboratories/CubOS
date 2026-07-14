# Conductive Wellplate Holder

A 3D-printed holder for seating a wellplate on the PANDA-BEAR **Cub-XL** deck.
This is a separate physical part from `../ursa_wellplate_holder/`; it shares the
same Python class (`WellPlateHolder`) but uses different dimensions
(originally modeled on the `SlideHolder_Top` geometry).

## Files

| File | Purpose |
| --- | --- |
| `WellplateHolder.yaml` | Labware config mapping to `cubos.src.deck.labware.well_plate_holder.WellPlateHolder`. |

## Compatibility

- Deck: PANDA-BEAR **Cub-XL only** (does not fit the Cub deck)
- For the Cub variant see `../ursa_wellplate_holder/`.
