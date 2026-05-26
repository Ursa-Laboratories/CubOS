# Panda SBS Wellplate Holder

CubOS labware definition for the keyed SBS 96-well plate holder in
`Cubware/labware/panda_sbs_wellplate_holder/`.

- Holder body footprint: 100.0 x 164.0 mm
- Holder body height above deck: 6.0 mm
- Plate underside seat plane: 3.0 mm above holder body bottom
- Printed side-wall height above plate seat: 3.0 mm
- Nested plate rim/surface reference: 17.35 mm above holder body bottom
- Physical key layout: four integral `9VialHolder-key.step` feet at the
  corners of a 4-by-4 PandaDeck insert block

Deck YAML should use `load_name: panda_sbs_wellplate_holder`, set the holder
`location` for the chosen PandaDeck insert block, and calibrate the nested
SBS plate wells on real hardware before running protocols.
