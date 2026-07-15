# Instruments

Each subdirectory defines a generic instrument type plus one or more vendor
implementations. Gantry YAML still uses `type` and `vendor`; the registry uses
that pair to choose the concrete class.

| Type folder | Built-in vendor | Instrument | Notes |
|-------------|-----------------|------------|-------|
| `asmi/` | `vernier` | GoDirect Force Sensor | Force measurement via USB (GoDirect SDK) |
| `camera/` | `mount_only`, `raspberry_pi` | Mounted camera | `mount_only` is calibration-only; `capture()` is intentionally not implemented |
| `capper/` | `mock`, `pawduino` | Vial capper/decapper | Electromagnet capture/release + line-break sensor confirm via Arduino serial (Pawduino firmware); `mock` is an offline in-memory simulation |
| `filmetrics/` | `kla` | F-Series (via FilmetricsTool.exe) | Thin-film thickness measurement via spectral reflectance |
| `mounted_tool/` | `mount_only` | Mounted non-instrumented tool | Calibration-only stand-in for physical tools without control code |
| `pipette/` | `opentrons` | OT-2 / Flex pipettes | Pipette control via Arduino serial (Pawduino firmware) |
| `potentiostat/` | `admiral` | Admiral potentiostat | Squidstat Python SDK |
| `uv_curing/` | `excelitas` | OmniCure S1500 PRO | UV curing system via RS-232 serial |
| `uvvis_ccs/` | `thorlabs` | CCS100 / CCS175 / CCS200 | Compact CCD spectrometer for UV-Vis spectroscopy |

## Structure convention

Every instrument folder follows the same layout:

```
<instrument>/
├── __init__.py       # Public exports
├── interface.py      # Generic type interface (extends BaseInstrument)
├── models.py         # Frozen dataclasses for measurement results
├── exceptions.py     # Instrument-specific exception hierarchy
└── vendors/
    ├── __init__.py
    └── <vendor>.py   # Concrete vendor implementation
```

Drivers support an `offline=True` constructor flag for dry runs: no serial I/O,
synthetic return values where the operation can be simulated. The gantry
instrument loader passes `offline=True` automatically when `mock_mode=True`.

## Adding a new instrument

1. Choose an existing type interface when possible, such as `ASMIInstrument`,
   `CameraInstrument`, or `PipetteInstrument`.
2. If the type is genuinely new, create `interface.py` under a new type folder
   and subclass `BaseInstrument`.
3. Put CubOS-supported vendor code in `vendors/<vendor>.py`. Subclass the type
   interface and implement `connect()`, `disconnect()`, `health_check()`, plus
   the type-specific methods.
4. Keep proprietary SDK imports lazy, inside `connect()` or the method that needs
   the SDK. Importing the driver module must not connect hardware or require a
   private SDK.
5. Guard hardware I/O with `if self._offline: ...` branches where synthetic data
   is meaningful.
6. Register the vendor in `registry.yaml` under the type's `vendors:` mapping.
7. Update tests and this README with the vendor and instrument info.

## External proprietary drivers

Customer or integration packages do not need to merge private drivers into
CubOS. They can ship a registry contribution and make the class importable.

Package entry point example:

```toml
[project.entry-points."cubos.instrument_registries"]
customer_instruments = "customer_cubos.registry:get_registry"
```

The entry point can return a registry mapping:

```python
def get_registry():
    return {
        "instruments": {
            "camera": {
                "vendors": {
                    "customer_camera": {
                        "module": "customer_cubos.camera",
                        "class_name": "CustomerCamera",
                    }
                }
            }
        }
    }
```

Operators may also point CubOS at explicit overlay YAML files:

```bash
export CUBOS_INSTRUMENT_REGISTRY_PATHS=/path/to/customer_registry.yaml
```

Overlay entries add vendors by default. To replace a built-in vendor or type
metadata, set `override: true` on that vendor or type entry.
