"""Safe, portable metadata for experiment records."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

_SECRET = re.compile(r'password|passwd|secret|token|credential|authorization|cookie|private.?key|api.?key', re.I)
_REDACTED = '[redacted]'


def sanitize(value: Any) -> Any:
    """Exclude credentials and opaque objects without invoking arbitrary reprs."""
    return _sanitize(value, set())


def _sanitize(value: Any, seen: set[int]) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return _sanitize(value.value, seen)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        if '://' in value:
            try:
                parsed = urlsplit(value)
                if parsed.scheme and parsed.netloc:
                    host = parsed.netloc.rsplit('@', 1)[-1]
                    query = urlencode([(k, _REDACTED if _SECRET.search(k) else sanitize(v))
                                       for k, v in parse_qsl(parsed.query, keep_blank_values=True)])
                    return urlunsplit((parsed.scheme, host, parsed.path, query,
                                       _REDACTED if parsed.fragment else ''))
            except ValueError:
                return '[omitted URL]'
        return value
    if id(value) in seen:
        return '[omitted cycle]'
    seen.add(id(value))
    try:
        if isinstance(value, dict):
            return {str(k): _REDACTED if _SECRET.search(str(k)) else _sanitize(v, seen)
                    for k, v in value.items() if isinstance(k, (str, int, float))}
        if isinstance(value, (list, tuple)):
            return [_sanitize(v, seen) for v in value]
        if is_dataclass(value) and type(value).__module__.startswith('cubos.'):
            return _sanitize({f.name: getattr(value, f.name) for f in fields(value)}, seen)
        from pydantic import BaseModel
        if isinstance(value, BaseModel) and type(value).__module__.startswith('cubos.'):
            return _sanitize({name: getattr(value, name) for name in type(value).model_fields}, seen)
        return '[omitted object]'
    finally:
        seen.discard(id(value))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(sanitize(value), sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def error_details(exc: BaseException, *, stage: str = 'execution') -> dict[str, Any]:
    # Exception messages can contain driver credentials or complete input values.
    return {'kind': 'error', 'type': type(exc).__name__, 'stage': stage,
            'message_omitted': True}


def software_identity() -> dict[str, Any]:
    identity: dict[str, Any] = {'cubos_version': None, 'commit': None, 'dirty': None}
    try:
        identity['cubos_version'] = version('cubos')
    except PackageNotFoundError:
        pass
    for root in Path(__file__).resolve().parents:
        if (root / '.git').exists():
            try:
                identity['commit'] = subprocess.check_output(
                    ['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True,
                    stderr=subprocess.DEVNULL, timeout=2).strip()
                identity['dirty'] = bool(subprocess.check_output(
                    ['git', '-C', str(root), 'status', '--porcelain'],
                    text=True, stderr=subprocess.DEVNULL, timeout=2).strip())
            except (OSError, subprocess.SubprocessError):
                pass
            break
    return identity
