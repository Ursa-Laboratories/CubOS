"""Observed method-call provenance without additional instrument I/O."""

from contextlib import nullcontext
from datetime import datetime, timezone
import time


def active_step(context):
    value = getattr(context, "active_step_execution_id", None)
    return value if isinstance(value, str) else None


def traced(context):
    return getattr(context, "trace_recording_active", None) is True or bool(active_step(context))


def record_resolved(context, **values):
    if traced(context):
        try:
            context.record_resolved(**values)
        except Exception as exc:
            context.recording_error(exc)


def recording_error(context, exc):
    if traced(context):
        context.recording_error(exc)


def well_scope(context, parameters, index):
    if traced(context):
        return context.trace_scope("scan.well", parameters, iteration_index=index)
    return nullcontext()


def invoke(context, instrument, method, kwargs, *, position, action_xyz):
    """Return the original result and observed call metadata."""
    if not traced(context):
        return method(**kwargs), {}
    from cubos.data.record_metadata import sanitize

    stored = getattr(instrument, "__dict__", {})
    configured = {"class": type(instrument).__name__, "module": type(instrument).__module__}
    for key in ("name", "serial_number", "_serial_number"):
        value = stored.get(key)
        if isinstance(value, (str, int, float, bool)):
            configured[key.lstrip("_")] = value
    try:
        safe_kwargs = sanitize({k: v for k, v in kwargs.items() if k != "gantry"})
    except Exception as exc:
        recording_error(context, exc)
        safe_kwargs = {"unavailable": True}
    metadata = {
        "instrument": {"configured": configured, "reported": None,
                       "offline": stored.get("_offline", stored.get("offline"))},
        "method_kwargs": safe_kwargs,
        "instrument_name": configured.get("name"),
        "method_name": getattr(method, "__name__", None),
        "position": position,
        "action_xyz": list(action_xyz),
    }
    record_resolved(context, position=position, action_xyz=list(action_xyz),
                    method_kwargs=metadata["method_kwargs"])
    started_at = datetime.now(timezone.utc).isoformat()
    started_ns = time.monotonic_ns()
    try:
        result = method(**kwargs)
    finally:
        timing = {"started_at": started_at,
                  "ended_at": datetime.now(timezone.utc).isoformat(),
                  "duration_ns": time.monotonic_ns() - started_ns,
                  "clock": "time.monotonic_ns"}
        metadata["method_call"] = timing
    return result, metadata


def persistence_kwargs(context, metadata, measurement, target, contents):
    if not traced(context):
        return {}
    from cubos.data.record_metadata import sanitize

    metadata = dict(metadata)
    metadata["schema_version"] = 1
    metadata["result_metadata"] = measurement.metadata
    metadata["acquisition"] = measurement.metadata["acquisition"]
    metadata["instrument_name"] = measurement.metadata.get("instrument_name")
    metadata["method_name"] = measurement.metadata.get("method_name")
    metadata["measurement_type"] = measurement.measurement_type.value
    metadata["units"] = measurement.metadata.get("units", "unknown")
    metadata["processing"] = measurement.metadata.get("processing", "unknown")
    metadata["instrument"] = dict(metadata["instrument"])
    metadata["instrument"]["reported"] = measurement.metadata.get("instrument_identity")
    metadata["sample"] = {"labware_key": target.labware_key,
                          "labware_name": target.labware_name,
                          "well_id": target.location_id,
                          "contents": contents}
    return {"step_execution_id": active_step(context), "metadata": sanitize(metadata)}
