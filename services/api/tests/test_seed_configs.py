"""Every seed gantry config shipped with the API must satisfy the schema.

These files are copied verbatim onto customer devices (Docker config-seed,
Windows installer), so a seed that fails validation bricks first boot.
"""

from pathlib import Path

import pytest
import yaml

from cubos.gantry.yaml_schema import GantryYamlSchema

SEED_GANTRY_DIR = Path(__file__).resolve().parents[1] / "configs" / "gantry"
SEED_GANTRY_FILES = sorted(SEED_GANTRY_DIR.glob("*.yaml"))


def test_seed_gantry_dir_is_populated() -> None:
    assert SEED_GANTRY_FILES, f"No seed gantry configs found in {SEED_GANTRY_DIR}"


@pytest.mark.parametrize(
    "seed_path", SEED_GANTRY_FILES, ids=lambda path: path.name
)
def test_seed_gantry_config_is_valid(seed_path: Path) -> None:
    with seed_path.open() as handle:
        data = yaml.safe_load(handle)
    schema = GantryYamlSchema.model_validate(data)

    volume = schema.working_volume
    assert volume.x_min < volume.x_max
    assert volume.y_min < volume.y_max
    assert volume.z_min < volume.z_max
