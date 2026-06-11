# API Reference

These pages are generated from the current Python package tree during the
MkDocs build. The import names below match the runtime package names; modules
under `src/` import as `deck`, `gantry`, `instruments`,
`protocol_engine`, and `validation`.

## Common Entrypoints

- `deck.load_deck_from_yaml_safe(path)`
- `gantry.load_gantry_from_yaml_safe(path)`
- `protocol_engine.load_protocol_from_yaml_safe(path)`
- `protocol_engine.setup.setup_protocol(gantry_path, deck_path, protocol_path, ...)`
- `protocol_engine.setup.run_protocol(gantry_path, deck_path, protocol_path, ...)`
- `protocol_engine.setup_validator.run_setup_validation(gantry_path, deck_path, protocol_path)`
- `data.DataStore(db_path=None)`
- `data.DataReader(db_path=..., connection=...)`

## Packages

- [data](data/index.md)
- [deck](src/deck/index.md)
- [gantry](src/gantry/index.md)
- [instruments](src/instruments/index.md)
- [protocol_engine](src/protocol_engine/index.md)
- [validation](src/validation/index.md)

## Data Modules

- [data.data_store](data/data_store.md)
- [data.data_reader](data/data_reader.md)
- [data.export_helpers](data/export_helpers.md)
- [data.analysis.uvvis](data/analysis/uvvis.md)

## Protocol Modules

- [protocol_engine.setup](src/protocol_engine/setup.md)
- [protocol_engine.setup_validator](src/protocol_engine/setup_validator.md)
- [protocol_engine.loader](src/protocol_engine/loader.md)
- [protocol_engine.protocol](src/protocol_engine/protocol.md)
- [protocol_engine.runtime](src/protocol_engine/runtime.md)
- [protocol_engine.measurements](src/protocol_engine/measurements.md)
- [protocol_engine.commands](src/protocol_engine/commands/index.md)
