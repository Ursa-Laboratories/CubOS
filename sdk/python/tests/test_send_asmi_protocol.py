from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "asmi"))

import send_asmi_protocol as asmi_sender  # noqa: E402


def test_protocol_wells_expands_scan_plate_from_deck_shape():
    protocol_yaml = """
protocol:
  - scan:
      plate: plate
      instrument: asmi
      method: indentation
"""
    deck_yaml = """
labware:
  plate:
    type: well_plate
    rows: 2
    columns: 3
"""

    assert asmi_sender.protocol_wells(protocol_yaml, deck_yaml) == [
        "A1",
        "A2",
        "A3",
        "B1",
        "B2",
        "B3",
    ]


def test_csv_rows_assigns_scan_wells_to_payloads():
    response = {
        "results": {
            "A": {
                "measurements": [
                    {
                        "timestamp": 1.0,
                        "z_mm": 17.4,
                        "raw_force_n": 0.68,
                        "corrected_force_n": 0.0,
                    }
                ]
            },
            "B": {
                "measurements": [
                    {
                        "timestamp": 2.0,
                        "z_mm": 17.3,
                        "raw_force_n": 0.69,
                        "corrected_force_n": 0.01,
                    }
                ]
            },
        }
    }

    rows = asmi_sender.csv_rows(response, run_id="scan-indent-001", wells=["A1", "A2"])

    assert [row["well"] for row in rows] == ["A1", "A2"]
