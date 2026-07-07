"""YAML loading helpers shared by CubOS config readers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class DuplicateKeyError(yaml.constructor.ConstructorError):
    """Raised when a YAML mapping contains the same key more than once."""


class CubosSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""

    def __init__(self, stream: Any) -> None:
        super().__init__(stream)
        self.source_name = getattr(stream, "name", "<yaml>")

    def construct_mapping(self, node: yaml.nodes.MappingNode, deep: bool = False) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found unhashable key {key!r}",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise DuplicateKeyError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"{self.source_name}: duplicate YAML key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_yaml_file(path: str | Path) -> Any:
    """Load a YAML file using CubOS duplicate-key protection."""
    resolved = Path(path)
    with resolved.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=CubosSafeLoader)
