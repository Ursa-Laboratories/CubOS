"""YAML loading helpers shared by CubOS config readers."""

from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from io import StringIO
from typing import Any

import yaml


_SOURCES = ContextVar("cubos_yaml_sources", default={})


def read_yaml_source(path: str | Path) -> bytes:
    resolved = str(Path(path).resolve())
    captured = _SOURCES.get().get(resolved)
    return captured if captured is not None else Path(path).read_bytes()


@contextmanager
def frozen_yaml_sources(sources):
    values = {**_SOURCES.get(), **{str(Path(k).resolve()): v.encode("utf-8") if isinstance(v, str) else v
                                for k, v in sources.items()}}
    token = _SOURCES.set(values)
    try:
        yield
    finally:
        _SOURCES.reset(token)


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
    stream = StringIO(read_yaml_source(resolved).decode("utf-8"))
    stream.name = str(resolved)
    return yaml.load(stream, Loader=CubosSafeLoader)
