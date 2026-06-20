# Home

CubOS is a Python control layer for CNC-based lab automation. It combines a
GRBL gantry, mounted instruments, deck labware, YAML protocols, offline motion
validation, and local SQLite data storage into one workflow.

CubOS is used to:

- define machine, deck, and protocol state in versioned YAML files
- calibrate the gantry into a front-left-bottom deck frame
- validate reach, motion bounds, command semantics, and collision constraints
- execute protocols against real hardware
- persist experiment state and instrument measurements for later analysis

## Contents

| Section | Use it for |
| --- | --- |
| [Set Up and Use CubOS](getting-started.md) | Install CubOS, calibrate hardware, set up labware, and run YAML protocols. |
| [Contributing to CubOS](contributing.md) | Work on CubOS source, docs, tests, and implementation details. |
| [API Reference](reference/index.md) | Inspect generated Python API docs. |
