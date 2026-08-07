# Set Up Gantry YAML

The gantry YAML describes your machine: which gantry it is and which
instruments are mounted. Create it **before calibrating** — calibration reads
the mounted instruments from this file and writes its measurements back into
it.

Don't write one from scratch. Copy the seed config from `packages/core/configs/gantry/`
that matches your machine and instrument, rename the copy for your setup,
and adjust the instruments if needed.

## CUB vs CUB XL Seeds

CUB and CUB XL are different machine sizes, and every seed is built for one
of them (the `gantry_type` line at the top of the file). Pick a seed by
matching your machine first, then your instrument:

| Seed | Machine | Instruments |
|------|---------|-------------|
| `cub_filmetrics.yaml` | CUB | Filmetrics |
| `cub_raman.yaml` | CUB | Raman (ASMI mount) |
| `cub_sharc.yaml` | CUB | UV curing |
| `cub_xl_asmi.yaml` | CUB XL | ASMI |
| `cub_xl_sterling.yaml` | CUB XL | potentiostat + pipette |
| `cub_xl_sterling_3_instrument.yaml` | CUB XL | ASMI + potentiostat + pipette |
| `cub_xl_panda.yaml` | CUB XL | potentiostat + camera + capper |

If no seed has your instrument, copy any seed for your machine and swap the
`instruments:` entries. Never change `gantry_type` to make a seed fit — a
CUB config on a CUB XL (or vice versa) has the wrong travel limits and can
crash the gantry into the frame.

## Controller Firmware (`firmware:`)

CubOS drives two motion-controller firmware families, selected by the
optional root-level `firmware:` field:

- `firmware: grbl` (default, may be omitted) — classic GRBL 1.1 boards.
  The `grbl_settings:` block declares the expected controller `$` settings
  and is validated against the live controller at connect.
- `firmware: duet` — Duet 3 boards running RepRapFirmware 3.5+ over USB
  serial (e.g. `bear_den_duet.yaml`, a ProVerXL 4030 V2 converted to a
  Duet 3 MB6XD). Motion configuration — axis directions, steps/mm, soft
  limits, homing behavior, pull-off reserve — lives in the board's own
  `config.g` (version-controlled under `packages/core/configs/duet/`),
  so a Duet gantry YAML must **not** contain a `grbl_settings:` block;
  the schema rejects the combination. Runtime GRBL-settings reads return
  empty and writes are refused; calibration flows that program `$`
  settings are not yet supported on Duet machines.

The machine frame contract is identical for both firmwares: reported
positions match the configured `origin_policy` frame with no sign flips in
host code. On Duet, the board's `config.g` establishes that frame directly
(M208 limits equal the usable spans; homing anchors the backed-off position
to the axis maxima).

## Define Instruments

Instruments live under `instruments:` in the gantry YAML. The map key is the
name protocols use (`instrument: asmi`). A minimal entry is a type and a
vendor:

```yaml
instruments:
  asmi:
    type: asmi
    vendor: vernier
```

- **Mounting offsets are measured during [calibration](calibration.md)** —
  you don't fill them in by hand.
- **Some devices need connection settings** (a serial `port`, a
  `serial_number`, a vendor file path). The seeds already contain working
  values for their instruments — change only what your device needs.
- **Set `offline: true`** on an instrument to run without that hardware
  attached.

Supported types: `asmi`, `capper`, `filmetrics`, `pipette`, `potentiostat`,
`uv_curing`, `uvvis_ccs`, `camera`, `mounted_tool`.

Every instrument entry accepts these shared fields:

- `type` *(str, required)* — a type from `packages/core/src/cubos/instruments/registry.yaml`.
- `vendor` *(str, required)* — a vendor registered for that type. The
  `type`/`vendor` pair tells CubOS which Python driver class to load.
- `offset_x`, `offset_y`, `depth` *(float, default `0.0`)* — physical mounting
  offsets from the gantry's reference point. Calibration writes these for normal
  operator flows.

Driver-specific fields pass through to the vendor driver's constructor. Use
those fields for serial ports, serial numbers, executable paths, DLL paths, and
other vendor settings. Set `offline: true` to run a driver in its synthetic or
no-hardware mode.

`measurement_height` and `interwell_scan_height` are not instrument fields
anymore. CubOS rejects them in gantry YAML so they cannot be swallowed as
driver-specific extras; put those heights on the protocol `measure` or `scan`
step instead.

External instrument packages register through the
`cubos.instrument_registries` entry point group. For local overlays, set
`CUBOS_INSTRUMENT_REGISTRY_PATHS` to one or more registry YAML files separated
by the platform path separator (`:` on macOS/Linux, `;` on Windows).

Worked examples:

**`asmi` / `vernier`** — Vernier Go Direct force sensor. The `godirect` SDK
auto-detects the sensor over USB.

```yaml
instruments:
  asmi:
    type: asmi
    vendor: vernier
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    force_threshold: -50
    sensor_channels: [1]
```

**`filmetrics` / `kla`** — KLA Filmetrics thin-film measurement, driven through
a vendor executable and recipe file:

```yaml
instruments:
  filmetrics:
    type: filmetrics
    vendor: kla
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    exe_path: "C:\\Filmetrics\\Filmeasure.exe"
    recipe_name: "my_recipe"
```

**`pipette` / `opentrons`** — Opentrons pipette over a serial connection:

```yaml
instruments:
  pipette:
    type: pipette
    vendor: opentrons
    pipette_model: p300_single_gen2
    port: "COM7"
    baud_rate: 115200
    offline: true
    offset_x: 180.0
    offset_y: -25.0
    depth: 0.0
```

**`potentiostat` / `admiral`** — Admiral SquidStat, addressed by serial port and
channel number:

```yaml
instruments:
  potentiostat:
    type: potentiostat
    vendor: admiral
    port: "/dev/ttyACM1"
    channel: 0
    offline: true
    offset_x: -55.0
    offset_y: 0.0
    depth: 58.0
```

**`uv_curing` / `excelitas`** — Excelitas UV curing lamp over serial:

```yaml
instruments:
  uv_curing:
    type: uv_curing
    vendor: excelitas
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    port: "/dev/ttyACM0"
    baud_rate: 19200
    default_intensity: 100.0
    default_exposure_time: 1.0
```

**`uvvis_ccs` / `thorlabs`** — Thorlabs CCS spectrometer, addressed by device
serial number plus the vendor driver DLL path:

```yaml
instruments:
  uvvis_ccs:
    type: uvvis_ccs
    vendor: thorlabs
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
    serial_number: "M00123456"
    dll_path: "TLCCS_64.dll"
    default_integration_time_s: 0.24
```

**`camera` / `mount_only`** (or `raspberry_pi`) — a fixed-mount camera used as a
positional reference:

```yaml
instruments:
  camera:
    type: camera
    vendor: mount_only
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 32.0
```

**`capper` / `pawduino`** — an electromagnet-actuated vial capper/decapper
over the same Arduino serial link family as the `pipette`/`opentrons`
driver (see [Protocol YAML: Capper commands](protocol-yaml.md#capper-commands)
for the `decap`/`cap` motion sequence these fields parameterize):

```yaml
instruments:
  vial_capper_decapper:
    type: capper
    vendor: pawduino
    port: "COM8"
    baud_rate: 115200
    offline: true
    offset_x: 62.9
    offset_y: 5.1
    depth: 61.5
    engage_depth_mm: -15.0
    park_position: [-10.0, -10.0]
    capture_retries: 2
    capture_settle_s: 1.0
```

`engage_depth_mm`/`park_position`/`capture_retries`/`capture_settle_s` are
required, not driver defaults — every capper's decap/cap motion sequence
comes entirely from this config, never hardcoded. `vendor: mock` is an
offline-only in-memory simulation useful for dry runs without any Arduino
attached.

**`mounted_tool` / `mount_only`** — any other passive mounted tool tracked
for offsets only (no actuation, no sensor):

```yaml
instruments:
  center_lens:
    type: mounted_tool
    vendor: mount_only
    offline: true
    offset_x: 58.0
    offset_y: 0.0
    depth: 48.0
```

## Next Step

Continue to [Calibrate Gantry](calibration.md).
