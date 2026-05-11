# SHARC 80 mm SBS Wellplate Holder

Reusable definition for the SHARC UV 80 mm holder that seats an SBS-format
well plate.

- Holder footprint: 127.76 x 85.47 mm
- Holder body height: 80.0 mm
- Physical support/seat plane: 75.15 mm above holder bottom
- Nested plate surface/rim reference: 89.5 mm above holder bottom

The plate surface reference is `75.15 + 14.35`, using the standard SBS plate
outer height. Deck YAML should set the holder `location.z` to the deck-frame
holder bottom/base Z.
