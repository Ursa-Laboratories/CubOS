import copy
import functools
from pathlib import Path

import pytest

from cubos import yaml_utils


@pytest.fixture(autouse=True)
def _cached_deck_yaml(monkeypatch):
    """Parse each distinct deck YAML text once; the matrix loads it thousands of times."""
    @functools.lru_cache(maxsize=16)
    def parsed(text: str):
        return parse_text(text)

    def parse_text(text: str):
        import yaml

        return yaml.load(text, Loader=yaml_utils.CubosSafeLoader)

    def load(path):
        return copy.deepcopy(parsed(Path(path).read_text(encoding="utf-8")))

    monkeypatch.setattr("cubos.deck.loader.load_yaml_file", load)
    monkeypatch.setattr("cubos.data.fluid_state.load_yaml_file", load)
