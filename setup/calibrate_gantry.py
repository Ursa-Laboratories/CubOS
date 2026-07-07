"""Safe user entrypoint for gantry calibration.

Examples:

    python setup/calibrate_gantry.py ../BU-Configs/configs/gantry/cub_xl_asmi.yaml

    python setup/calibrate_gantry.py \
      ../BU-Configs/configs/gantry/cub_xl_sterling_3_instrument.yaml \
      --output-gantry ../BU-Configs/configs/gantry/cub_xl_sterling_3_instrument_calibrated.yaml

The script reads the input gantry YAML, counts mounted instruments, and chooses
single- or multi-instrument calibration. If no output path is provided, it asks
for confirmation before overwriting the input gantry YAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from setup.calibration.single_instrument_calibration import (  # noqa: E402
    DeckOriginCalibrationResult,
    run_calibration,
)
from setup.calibration.multi_instrument_calibration import (  # noqa: E402
    MultiInstrumentCalibrationResult,
    run_multi_instrument_calibration,
)


InstrumentInfo = tuple[str, str | None]


def _load_gantry_config(gantry_path: Path) -> dict[str, Any]:
    if not gantry_path.exists():
        raise ValueError(f"Input gantry YAML does not exist: {gantry_path}")
    with gantry_path.open(encoding="utf-8") as handle:
        raw: Any = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Input gantry YAML is empty or invalid: {gantry_path}")
    return raw


def _instrument_info(raw_config: dict[str, Any]) -> tuple[InstrumentInfo, ...]:
    instruments = raw_config.get("instruments")
    if not isinstance(instruments, dict) or not instruments:
        raise ValueError("Input gantry YAML must define at least one mounted instrument.")
    info: list[InstrumentInfo] = []
    for name, config in instruments.items():
        instrument_type = config.get("type") if isinstance(config, dict) else None
        info.append((str(name), str(instrument_type) if instrument_type else None))
    return tuple(info)


def _validate_gantry_config(raw_config: dict[str, Any], *, output_path: Path) -> None:
    missing = [key for key in ("serial_port", "cnc", "working_volume", "instruments") if key not in raw_config]
    if missing:
        raise ValueError("Input gantry YAML is missing required section(s): " + ", ".join(missing))

    working_volume = raw_config.get("working_volume")
    if not isinstance(working_volume, dict):
        raise ValueError("Input gantry YAML must contain a working_volume mapping.")
    for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"):
        if key not in working_volume:
            raise ValueError(f"Input gantry YAML working_volume is missing {key}.")
    for low, high in (("x_min", "x_max"), ("y_min", "y_max"), ("z_min", "z_max")):
        if float(working_volume[high]) <= float(working_volume[low]):
            raise ValueError(f"Input gantry YAML has invalid working_volume {low}/{high}.")

    output_parent = output_path.resolve().parent
    if not output_parent.exists():
        raise ValueError(f"Output directory does not exist: {output_parent}")
    if not output_parent.is_dir():
        raise ValueError(f"Output parent is not a directory: {output_parent}")


def _format_instruments(instruments: tuple[InstrumentInfo, ...]) -> list[str]:
    lines: list[str] = []
    for index, (name, instrument_type) in enumerate(instruments, start=1):
        suffix = f" ({instrument_type})" if instrument_type else ""
        lines.append(f"  {index}. {name}{suffix}")
    return lines


def _confirm(prompt: str, *, input_reader: Callable[[str], str]) -> bool:
    return input_reader(prompt).strip().lower() in {"y", "yes"}


def _preflight(
    *,
    input_path: Path,
    output_path: Path,
    overwrite_input: bool,
    instruments: tuple[InstrumentInfo, ...],
    flow_name: str,
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> None:
    output("")
    output("Calibration preflight")
    output("=====================")
    output(f"Input gantry YAML:       {input_path}")
    output(f"Output calibrated YAML:  {output_path}")
    output(f"Detected instruments:    {len(instruments)}")
    for line in _format_instruments(instruments):
        output(line)
    output(f"Chosen flow:             {flow_name}")
    output("")
    output("Before continuing:")
    output("  - Keep E-stop reachable.")
    output("  - Clear the deck and mounted tools' travel path.")
    output("  - Have a calibration reference ready: the calibration block, or a rigid")
    output("    deck feature of known height above the deck (e.g. a well plate).")
    output("  - Use slow, careful jogs near fixtures, samples, and limits.")
    output("  - Do not run protocols from the output YAML until validation passes.")
    output("")

    if overwrite_input:
        if not _confirm(
            f"No --output-gantry was provided; calibration will overwrite {input_path}. Continue? [y/N]: ",
            input_reader=input_reader,
        ):
            raise RuntimeError("Calibration cancelled before hardware connection.")

    if input_reader("Press ENTER to connect to hardware and start calibration, or Ctrl-C to abort: ") != "":
        output("Starting calibration...")


def _print_end_summary(
    result: Any,
    *,
    output_path: Path,
    output: Callable[[str], None],
) -> None:
    output("")
    output("Calibration complete")
    output("====================")
    output(f"Calibrated YAML written to: {output_path}")

    if isinstance(result, DeckOriginCalibrationResult):
        x_max, y_max, z_max = result.measured_working_volume
        output(f"Calibrated working volume: X 0..{x_max:.3f}, Y 0..{y_max:.3f}, Z {result.z_min_mm:.3f}..{z_max:.3f} mm")
        output(f"Factory Z travel safety bound preserved: {result.factory_z_travel_mm:.3f} mm")
        if result.block_height_mm is not None and result.block_touch_wpos_z_mm is not None:
            output(
                "Block touch home-to-block inference: "
                f"block={result.block_height_mm:.3f} mm, "
                f"touch WPos Z={result.block_touch_wpos_z_mm:.3f} mm, "
                f"travel={result.home_to_block_travel_mm:.3f} mm, "
                f"lowest reachable height above deck={result.reachable_z_min_mm:.3f} mm"
            )
        if result.grbl_max_travel is not None:
            gx, gy, gz = result.grbl_max_travel
            output(f"Calibration-managed GRBL max travel: X={gx:.3f}, Y={gy:.3f}, Z={gz:.3f} mm")
        if result.instrument_name:
            output(f"Calibrated instrument: {result.instrument_name}")

    elif isinstance(result, MultiInstrumentCalibrationResult):
        x_max, y_max, z_max = result.measured_working_volume
        output(f"Calibrated working volume: X 0..{x_max:.3f}, Y 0..{y_max:.3f}, Z 0..{z_max:.3f} mm")
        gx, gy, gz = result.grbl_max_travel
        output(f"Calibration-managed GRBL max travel: X={gx:.3f}, Y={gy:.3f}, Z={gz:.3f} mm")
        output(f"Reference/left-most instrument: {result.reference_instrument}")
        output(f"Lowest instrument: {result.lowest_instrument}")
        output("Instrument calibration values:")
        for name, values in result.instrument_calibrations.items():
            output(
                f"  {name}: offset_x={values['offset_x']:.3f}, "
                f"offset_y={values['offset_y']:.3f}, depth={values['depth']:.3f}"
            )

    output("")
    output("Next offline validation:")
    output("  python setup/validate_setup.py <calibrated-gantry.yaml> <deck.yaml> <protocol.yaml>")
    output("Do not run protocols until validation passes and hardware motion is sanity-checked.")


def run_auto_calibration(
    gantry_path: Path,
    *,
    output_gantry_path: Path | None = None,
    output: Callable[[str], None] = print,
    input_reader: Callable[[str], str] = input,
):
    """Run calibration and write a calibrated gantry YAML.

    If ``output_gantry_path`` is omitted, the input gantry YAML is overwritten
    after an explicit operator confirmation.
    """
    gantry_path = gantry_path.resolve()
    overwrite_input = output_gantry_path is None
    resolved_output_path = (
        gantry_path if output_gantry_path is None else output_gantry_path.resolve()
    )
    raw_config = _load_gantry_config(gantry_path)
    instruments = _instrument_info(raw_config)
    _validate_gantry_config(raw_config, output_path=resolved_output_path)

    flow_name = (
        "single-instrument deck-origin calibration"
        if len(instruments) == 1
        else "multi-instrument gantry calibration"
    )
    _preflight(
        input_path=gantry_path,
        output_path=resolved_output_path,
        overwrite_input=overwrite_input,
        instruments=instruments,
        flow_name=flow_name,
        input_reader=input_reader,
        output=output,
    )

    if len(instruments) == 1:
        instrument_name = instruments[0][0]
        output(f"Using single-instrument flow for {instrument_name!r}.")
        result = run_calibration(
            gantry_path,
            instrument_name=instrument_name,
            z_reference_mode="block",
            write_gantry_yaml=True,
            output_gantry_path=resolved_output_path,
            output=output,
            input_reader=input_reader,
        )
    else:
        output(f"Using multi-instrument flow for {len(instruments)} mounted instruments.")
        result = run_multi_instrument_calibration(
            gantry_path,
            write_gantry_yaml=True,
            output_gantry_path=resolved_output_path,
            output=output,
            input_reader=input_reader,
        )

    _print_end_summary(result, output_path=resolved_output_path, output=output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate a gantry YAML in place or write a calibrated copy.",
        epilog=(
            "Examples:\n"
            "  PYTHONPATH=src python setup/calibrate_gantry.py "
            "../BU-Configs/configs/gantry/cub_xl_asmi.yaml\n"
            "  PYTHONPATH=src python setup/calibrate_gantry.py "
            "../BU-Configs/configs/gantry/cub_xl_sterling_3_instrument.yaml "
            "--output-gantry ../BU-Configs/configs/gantry/cub_xl_sterling_3_instrument_calibrated.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("gantry", type=Path, help="Input gantry YAML to calibrate.")
    parser.add_argument(
        "--output-gantry",
        type=Path,
        default=None,
        help=(
            "Optional output path for calibrated gantry YAML. If omitted, "
            "the input gantry YAML is overwritten after confirmation."
        ),
    )
    args = parser.parse_args()

    try:
        run_auto_calibration(args.gantry, output_gantry_path=args.output_gantry)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
