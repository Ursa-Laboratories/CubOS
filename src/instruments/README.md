# Instruments

Each subdirectory contains a self-contained instrument driver that implements `BaseInstrument`.

| Folder | Vendor | Instrument | Description |
|--------|--------|------------|-------------|
| `asmi/` | **Vernier** | GoDirect Force Sensor | Force measurement via USB (GoDirect SDK) |
| `filmetrics/` | **KLA / Filmetrics** | F-Series (via FilmetricsTool.exe) | Thin-film thickness measurement via spectral reflectance |
| `pipette/` | **Opentrons** | OT-2 / Flex pipettes | Pipette control via Arduino serial (Pawduino firmware) |
| `uv_curing/` | **Excelitas** | OmniCure S1500 PRO | UV curing system via RS-232 serial |
| `uvvis_ccs/` | **Thorlabs** | CCS100 / CCS175 / CCS200 | Compact CCD spectrometer for UV-Vis spectroscopy (3648-pixel) |

## Structure convention

Every instrument folder follows the same layout:

```
<instrument>/
├── __init__.py       # Public exports
├── driver.py         # Hardware driver (extends BaseInstrument, supports offline=True)
├── models.py         # Frozen dataclasses for measurement results
└── exceptions.py     # Instrument-specific exception hierarchy
```

Drivers support an `offline=True` constructor flag for dry runs — no serial I/O, synthetic return values. The gantry instrument loader passes `offline=True` automatically when `mock_mode=True`.

## Adding a new instrument

1. Create a new folder under `src/instruments/`.
2. Subclass `BaseInstrument` and implement `connect()`, `disconnect()`, `health_check()`.
3. Guard all I/O with `if self._offline: ...` branches that return synthetic data.
4. Define a frozen dataclass in `models.py` for measurement results.
5. Create an exception hierarchy rooted in `InstrumentError`.
6. Register the instrument in `registry.yaml` (type, module, class_name, vendors).
7. Update this README with the vendor and instrument info.
