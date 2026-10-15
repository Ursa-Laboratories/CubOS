"""Generate a run record using synthetic spectra and an offline gantry only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from cubos.data import DataStore
from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.well_plate import WellPlate
from cubos.gantry import Gantry, InstrumentedGantry
from cubos.instruments.uvvis_ccs.vendors.thorlabs import ThorlabsUVVisCCS
from cubos.protocol_engine.commands.measure import measure
from cubos.protocol_engine.protocol import Protocol
from cubos.protocol_engine.runtime import ProtocolContext, ProtocolStep


class ExampleFailure(RuntimeError):
    pass


def software_failure(context):
    raise ExampleFailure("Intentional offline example failure after the first measurement")


def generate(output: Path, fail_after_measurement: bool = False) -> None:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    database = output.with_suffix(".sqlite")
    if output == database:
        raise ValueError("Choose an output filename ending in .json")
    controller = Gantry(offline=True)
    instrument = ThorlabsUVVisCCS(name="uvvis", offline=True)
    gantry = InstrumentedGantry(controller, {"uvvis": instrument}, safe_z=30.)
    plate = WellPlate(
        name="example_plate", model_name="offline_example", length=30., width=20.,
        height=10., rows=1, columns=2,
        wells={"A1": Coordinate3D(x=10., y=10., z=10.),
               "A2": Coordinate3D(x=20., y=10., z=10.)},
        capacity_ul=100., working_volume_ul=90.,
    )
    first = ProtocolStep(0, "measure", measure, {
        "instrument": "uvvis", "position": "plate.A1", "measurement_height": 2.})
    second = (ProtocolStep(1, "software_failure", software_failure, {})
              if fail_after_measurement else ProtocolStep(1, "measure", measure, {
                  "instrument": "uvvis", "position": "plate.A2", "measurement_height": 2.}))
    store = DataStore(database)
    context = ProtocolContext(gantry=gantry, deck=Deck({"plate": plate}), data_store=store)
    controller.connect()
    instrument.connect()
    try:
        try:
            Protocol([first, second]).execute(context)
        except ExampleFailure:
            if not fail_after_measurement:
                raise
        run = store.execution_records.get_run(context.run_id)
        steps = store.execution_records.list_steps(context.run_id)
    finally:
        instrument.disconnect()
        controller.disconnect()
        store.close()
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        measurements = [dict(row) for row in connection.execute(
            "SELECT m.*,e.well_id,e.labware_key,e.contents AS contents_json FROM uvvis_measurements m "
            "JOIN experiments e ON e.id=m.experiment_id "
            "JOIN step_executions s ON s.step_execution_id=m.step_execution_id "
            "WHERE s.run_id=? ORDER BY m.id", (context.run_id,))]
    for row in measurements:
        for key in list(row):
            if key in {"wavelengths", "intensities"}:
                row[key] = json.loads(row[key])
            elif key.endswith("_json") and row[key] is not None:
                row[key[:-5]] = json.loads(row.pop(key))
    output.write_text(json.dumps({"run": run, "steps": steps, "measurements": measurements},
                                 indent=2, allow_nan=False) + "\n")
    print(f"SQLite: {database}\nJSON export: {output}\nRun: {context.run_id} ({run['status']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="JSON export path; SQLite uses the same basename")
    parser.add_argument("--fail-after-measurement", action="store_true",
                        help="Record an intentional software failure after preserving the first spectrum")
    args = parser.parse_args()
    generate(args.output, args.fail_after_measurement)
