# Camera Calibration UI

## Current behavior

The gantry calibration UI supports registered non-contact `camera` instruments
in the normal multi-instrument calibration flow. When the active instrument is a
camera, Zoo shows a required distance-from-calibration-block input before
allowing the operator to record the camera position.

Zoo still uses the normal connected `GantrySession` path. There is no committed
mock-gantry runtime switch in this branch.

## Future mock-gantry activation

For UI-only calibration walkthroughs without hardware, the tested temporary
shape was:

```bash
PYTHONPATH=../CubOS/src ZOO_CONFIG_DIR=../BU-Configs/configs ZOO_MOCK_GANTRY=1 python -m zoo
```

The corresponding Zoo implementation was a `ZooSettings.mock_gantry` boolean
and a router session factory branch equivalent to:

```python
GantrySession(gantry_factory=lambda **kwargs: Gantry(**kwargs, offline=True))
```

That allowed `/api/gantry/connect` to create a CubOS offline gantry, so the
existing Connect, Home, Jog, work-coordinate, and calibration endpoints could
drive the real UI without opening the YAML `serial_port`.
