# Run a Protocol with Python

Python-authored protocols help when loops, shared constants, or helper functions
make a protocol clearer than repeated YAML. Build one with
`ProtocolBuilder.with_setup(...)` so it carries its own gantry/deck pairing, then
validate and run it directly — the same compile, validation, and hardware
lifecycle as [YAML](protocol-yaml.md).

## High-level workflow

The Python path has three user-facing steps:

1. **Build** a `Protocol` with `ProtocolBuilder`.
2. **Validate** it offline with `protocol.validate()`.
3. **Run** it on hardware with `protocol.run()`.

The sections below cover that workflow first. Detailed builder-method arguments
come later in [Builder method arguments](#builder-method-arguments).

## Build a protocol

`with_setup(...)` records the gantry and deck the protocol belongs to, so the
built `Protocol` can validate and run itself. Use file-relative paths so it works
from any working directory, then add steps with explicit `add_*` methods:

```python
from pathlib import Path

from protocol_engine.builder import ProtocolBuilder

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


def build_protocol():
    protocol_builder = ProtocolBuilder.with_setup(
        gantry_path=CONFIG_DIR / "gantry" / "cub_xl_asmi.yaml",
        deck_path=CONFIG_DIR / "deck" / "asmi_deck.yaml",
    )
    protocol_builder.add_home()
    protocol_builder.add_move(instrument="asmi", position="plate.A1")
    protocol_builder.add_home()
    return protocol_builder.build(source_path=__file__)
```

Each `add_*` call appends one protocol step; see
[Builder method arguments](#builder-method-arguments) for full arguments.

`build(source_path=...)` is optional. Pass it when you want the resulting
`Protocol` to remember the Python source that produced it.

## Validate offline

`protocol.validate()` runs the full gantry, deck, instrument-mount,
motion-bounds, and semantic validation offline — it never connects to hardware or
executes steps:

```python
protocol = build_protocol()
protocol.validate()
```

It raises a clear error if the protocol has no setup metadata. Always validate
before a hardware run; Python protocols do not bypass bounds validation, semantic
validation, setup checks, or physical clearance requirements. Offline validation
reduces risk, but it does not prove real-world clearance; confirm physical
fixture, cable, tool, and sample clearance before running.

## Run on hardware

`protocol.run()` performs the full hardware lifecycle — connect the gantry, clear
any startup alarm, connect instruments, health-check, execute the steps, and
disconnect in cleanup — and returns the step results:

```python
protocol = build_protocol()
protocol.validate()   # offline preflight
protocol.run()        # connect, run, disconnect
```

To save measurements, name a campaign. `run()` creates the campaign for you —
recording the protocol's own gantry and deck paths from its setup metadata —
writes the run into it, and closes the data store automatically:

```python
protocol.run(campaign="ASMI indentation run")
```

| `run(...)` argument | Effect |
| --- | --- |
| *(none)* | Execute on hardware; persist nothing. |
| `campaign="..."` | Create a campaign and save measurements to the default data store. |
| `data_store=DataStore("runs/my.db")` | Save to a specific store (you own its lifecycle). Requires `campaign`. |
| `protocol_config="..."` | Record the source that built the protocol on the campaign. Requires `campaign`. |

Passing a persistence argument without `campaign` raises a clear error.

## Builder method arguments

Each `add_*` method appends the matching protocol command; argument meanings —
deck targets, the labware-relative height convention, and `method_kwargs` — are
exactly as documented in the
[YAML command reference](protocol-yaml.md#protocol-command-reference). Optional arguments
are materialized into the step only when you pass them; omit one and the command's
default applies at run time (the builder never bakes defaults into the step).

Most builder methods return the builder, so short protocols can be chained:

```python
protocol = (
    ProtocolBuilder.with_setup(gantry_path=GANTRY, deck_path=DECK)
    .add_home()
    .add_move(instrument="asmi", position="plate.A1")
    .add_home()
    .build(source_path=__file__)
)
```

### `add_home()`

Append a `home` step. No arguments.

### `add_move(*, instrument, position, travel_z=...)`

- `instrument` *(str, required)* — instrument registered on the gantry.
- `position` *(required)* — a named position, an `[x, y, z]` list, or a
  deck-target string.
- `travel_z` *(float, optional)* — transit Z; literal/named XYZ targets only.

### `add_measure(*, instrument, position, measurement_height, method=..., indentation_limit_height=..., method_kwargs=...)`

- `instrument` *(str, required)* — instrument registered on the gantry.
- `position` *(str, required)* — deck target to measure at.
- `measurement_height` *(float, required)* — labware-relative action plane.
- `method` *(str, optional)* — instrument method to call (default `"measure"`).
- `indentation_limit_height` *(float, optional)* — deepest descent plane for
  closed-loop methods; at or below `measurement_height`.
- `method_kwargs` *(dict, optional)* — forwarded verbatim to the instrument
  method (instrument-method-specific keys; not schema-validated).

### `add_scan(*, plate, instrument, method, measurement_height, interwell_scan_height, indentation_limit_height=..., delay_s=..., method_kwargs=...)`

- `plate` *(str, required)* — deck key resolving to a `WellPlate`.
- `instrument` *(str, required)* — instrument registered on the gantry.
- `method` *(str, required)* — method to call per well.
- `measurement_height` *(float, required)* — labware-relative action plane.
- `interwell_scan_height` *(float, required)* — between-well travel offset; at or
  above `measurement_height`.
- `indentation_limit_height` *(float, optional)* — deepest plane for ASMI
  indentation; at or below `measurement_height`.
- `delay_s` *(float, optional)* — seconds to pause between wells (default `0.0`).
- `method_kwargs` *(dict, optional)* — forwarded to the method per well.

### `add_pause(seconds, *, reason=...)`

- `seconds` *(float, required, positional)* — duration to pause.
- `reason` *(str, optional)* — logged with the pause message.

### `add_position(name, coordinates)`

Define one named position (added to the protocol's `positions`, not a step). Use
named positions as `add_move` targets.

- `name` *(str)* — position name.
- `coordinates` *(iterable of float)* — `[x, y, z]`.

### `add_positions(mapping)`

Define several named positions at once.

- `mapping` *(dict)* — `{name: [x, y, z], ...}`.

### `build(*, source_path=...)`

Compile the accumulated positions and command steps into a `Protocol`.

- `source_path` *(str or Path, optional)* — source identifier stored on the
  protocol for logs and campaign metadata.

### `add_command(command, args=None, **kwargs)`

Append any registered command by name — use this for commands without a typed
`add_*` wrapper, such as `breakpoint` and the pipette operations (`aspirate`,
`transfer`, `mix`, `pick_up_tip`, …). Pass arguments as a dict or as keywords:

```python
protocol_builder.add_command("breakpoint", message="Load the next plate")
protocol_builder.add_command("aspirate", position="reservoir.A1", volume_ul=50.0)
```

Argument names and defaults match the
[command reference](protocol-yaml.md#protocol-command-reference).

### `wells(plate, *, rows, columns)`

Helper (also in `protocol_engine.builder`) that returns row-major well targets
such as `plate.A1` through `plate.D6` — handy for building scans in a loop:

```python
from protocol_engine.builder import wells

for target in wells("plate", rows="A:D", columns=range(1, 7)):
    protocol_builder.add_measure(
        instrument="asmi",
        position=target,
        measurement_height=-1.0,
    )
```
