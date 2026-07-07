# Set Up Gantry YAML

The gantry YAML describes your machine: which gantry it is and which
instruments are mounted. Create it **before calibrating** — calibration reads
the mounted instruments from this file and writes its measurements back into
it.

Don't write one from scratch. Copy the seed config from `configs/gantry/`
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

Supported types: `asmi`, `filmetrics`, `pipette`, `potentiostat`,
`uv_curing`, `uvvis_ccs`, `camera`, `mounted_tool`.

## Next Step

Continue to [Calibrate Gantry](calibration.md).
