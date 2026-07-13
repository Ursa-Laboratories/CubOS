# Generic Installer Seeds

Issue: CubOS #226 asked for Zoo installs to stop preloading named gantry YAMLs
such as `cub_filmetrics` and `cub_xl_asmi`.

Change:

- Added `configs/gantry/cub_seed.yaml` and `configs/gantry/cub_xl_seed.yaml`
  as generic gantry starting points with no mounted instruments.
- Added `configs/deck/cub_deck_example.yaml` and
  `configs/deck/cubxl_deck_example.yaml` as generic deck examples.
- Changed the Windows launcher to seed only those generic gantry and deck
  templates into a fresh operator config directory.
- Left instrument selection in the gantry editor: operators load a seed, add
  the mounted instruments they need, then save the edited YAML.
- Added a gantry-editor empty state that directs operators to choose mounted
  instruments when a seed has none.

Validation:

- The gantry seed files validate through CubOS `GantryYamlSchema`, and the deck
  examples load through CubOS `load_deck_from_yaml`.
- A Windows installer regression test checks that launcher seeding no longer
  reads bundled CubOS named configs.
- A Gantry editor test checks the empty-instrument guidance.
