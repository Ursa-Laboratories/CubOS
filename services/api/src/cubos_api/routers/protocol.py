"""Protocol router: CRUD for protocol YAML files + command registry.

Commands are introspected from CubOS's CommandRegistry at runtime,
so any new @protocol_command in CubOS is automatically available.
"""

from __future__ import annotations

import logging
import types
from typing import Any, Dict, List
from typing import Union, get_args, get_origin

from fastapi import APIRouter, HTTPException
from cubos.gantry.session import (
    CalibrationBlockedError,
    GantryNotConnectedError,
    GantrySessionError,
    GantrySessionHealthCheckError,
    InterruptFeedHoldTimeoutError,
)
from pydantic import BaseModel
from pydantic import ValidationError
from cubos.protocol_engine.registry import CommandRegistry
from cubos.protocol_engine.setup_validator import run_setup_validation
from cubos.protocol_engine.yaml_schema import ProtocolYamlSchema
from cubos.validation.errors import SetupValidationError

# Side-effect import: triggers @protocol_command registration.
import cubos.protocol_engine.commands  # noqa: F401

from cubos_api.config import get_settings
from cubos_api.models.protocol import (
    CommandArg,
    CommandInfo,
    ProtocolConfig,
    ProtocolResponse,
    ProtocolSetupValidationRequest,
    ProtocolSetupValidationResponse,
    ProtocolStepConfig,
    ProtocolValidationResponse,
)
from cubos_api.services.yaml_io import delete_config, list_configs, read_yaml, resolve_config_path, write_yaml

router = APIRouter(prefix="/api/v1/protocol", tags=["protocol"])


def _type_name(annotation: Any) -> str:
    """Convert a Python type annotation to a simple string for the frontend."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return " | ".join(
            "None" if arg is type(None) else _type_name(arg)
            for arg in get_args(annotation)
        )
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return str(annotation)


def _build_command_info(name: str) -> CommandInfo:
    """Build a CommandInfo from a registered CubOS command."""
    registry = CommandRegistry.instance()
    cmd = registry.get(name)
    args = []
    for field_name, field_info in cmd.schema.model_fields.items():
        args.append(
            CommandArg(
                name=field_name,
                type=_type_name(field_info.annotation),
                required=field_info.is_required(),
                default=None if field_info.is_required() else field_info.default,
                description=field_info.description or "",
            )
        )
    return CommandInfo(
        name=cmd.name,
        description=(cmd.handler.__doc__ or "").strip(),
        args=args,
    )


def _protocol_schema_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the CubOS-owned protocol fields while leaving sidecar keys alone."""
    payload: Dict[str, Any] = {}
    if "positions" in data:
        payload["positions"] = data["positions"]
    if "protocol" in data:
        payload["protocol"] = data["protocol"]
    return payload


def _validate_protocol_schema(data: Dict[str, Any]) -> ProtocolYamlSchema:
    return ProtocolYamlSchema.model_validate(_protocol_schema_payload(data))


def _step_to_yaml(step: ProtocolStepConfig) -> Dict[str, Any]:
    args = dict(step.args)
    if step.command == "repeat" and isinstance(args.get("steps"), list):
        args["steps"] = [
            _step_to_yaml(child if isinstance(child, ProtocolStepConfig) else ProtocolStepConfig.model_validate(child))
            for child in args["steps"]
        ]
    return {step.command: args or None}


def _reject_nested_repeats(steps: List[ProtocolStepConfig]) -> None:
    pending = [(step, False) for step in steps]
    while pending:
        step, inside_repeat = pending.pop()
        if inside_repeat and step.command == "repeat":
            raise ValueError("nested repeat blocks are not supported.")
        children = step.args.get("steps") if step.command == "repeat" else None
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict) and child.get("command") == "repeat":
                    raise ValueError("nested repeat blocks are not supported.")
                if isinstance(child, dict):
                    pending.append((ProtocolStepConfig.model_validate(child), True))


def _step_from_schema(step: Any) -> ProtocolStepConfig:
    args = dict(step.args)
    if step.command == "repeat":
        args["steps"] = [
            _step_from_schema(ProtocolYamlSchema.model_validate({"protocol": [child]}).protocol[0]).model_dump()
            for child in args["steps"]
        ]
    return ProtocolStepConfig(command=step.command, args=args)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/commands")
def get_commands() -> List[CommandInfo]:
    """Return all registered protocol commands with their argument schemas."""
    registry = CommandRegistry.instance()
    return [_build_command_info(name) for name in registry.command_names]


@router.get("/commands/{name}")
def get_command(name: str) -> CommandInfo:
    """Return schema for a single protocol command."""
    registry = CommandRegistry.instance()
    if name not in registry.command_names:
        raise HTTPException(404, f"Unknown command '{name}'")
    return _build_command_info(name)


@router.get("/configs")
def list_protocol_configs() -> List[str]:
    return list_configs(get_settings().configs_dir, "protocol")


class RunStatusResponse(BaseModel):
    active: bool
    protocol_file: str | None = None


@router.get("/run-status")
def get_run_status() -> RunStatusResponse:
    """Report whether a protocol run is currently in progress.

    Registered before the catch-all ``GET /{filename}`` route below so the
    literal path ``run-status`` isn't swallowed as a filename lookup.
    """
    from cubos_api.routers import gantry as gantry_router

    return RunStatusResponse(**gantry_router.run_status())


@router.get("/{filename}")
def get_protocol(filename: str) -> ProtocolResponse:
    try:
        path = resolve_config_path(get_settings().configs_dir, "protocol", filename)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not path.is_file():
        raise HTTPException(404, f"Protocol file not found: {filename}")
    try:
        data = read_yaml(path)
        schema = _validate_protocol_schema(data)
    except (ValueError, ValidationError) as e:
        raise HTTPException(400, str(e)) from e

    steps = [_step_from_schema(step) for step in schema.protocol]

    return ProtocolResponse(filename=filename, positions=schema.positions, steps=steps)


@router.put("/{filename}")
def save_protocol(filename: str, body: ProtocolConfig) -> dict:
    try:
        path = resolve_config_path(get_settings().configs_dir, "protocol", filename)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    # Convert to YAML-native format while keeping authored repeat blocks intact.
    try:
        _reject_nested_repeats(body.protocol)
        protocol_list = [_step_to_yaml(step) for step in body.protocol]
    except (TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        data: Dict[str, Any] = read_yaml(path) if path.is_file() else {}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if body.positions is not None:
        data["positions"] = body.positions
    else:
        data.pop("positions", None)
    data["protocol"] = protocol_list
    try:
        _validate_protocol_schema(data)
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc

    write_yaml(path, data)
    return {"status": "ok", "filename": filename}


@router.delete("/{filename}")
def delete_protocol(filename: str) -> dict:
    from cubos_api.routers import gantry as gantry_router

    if gantry_router.run_active():
        raise HTTPException(409, "Cannot delete a protocol while a protocol run is active")
    try:
        delete_config(get_settings().configs_dir, "protocol", filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(404, f"Config not found: {filename}")
    return {"status": "deleted", "filename": filename}


@router.post("/validate")
def validate_protocol(body: ProtocolConfig) -> ProtocolValidationResponse:
    """Validate a protocol against CubOS's command schemas."""
    from cubos.protocol_engine.compiler import CommandCall, compile_protocol

    try:
        _reject_nested_repeats(body.protocol)
        raw_steps = [_step_to_yaml(step) for step in body.protocol]
        schema = ProtocolYamlSchema.model_validate({
            "protocol": raw_steps,
            **({"positions": body.positions} if body.positions is not None else {}),
        })
        compile_protocol([
            CommandCall(command=step.command, args=step.args)
            for step in schema.protocol
        ], positions=schema.positions or {})
    except Exception as exc:
        error = str(exc)
        if isinstance(exc, ValidationError) and exc.errors():
            details = []
            for item in exc.errors():
                location = ".".join(str(part) for part in item.get("loc", ()))
                message = str(item.get("msg", error)).replace(
                    "Unknown protocol command", "Unknown command",
                )
                details.append(f"{location}: {message}" if location else message)
            error = "; ".join(details)
        return ProtocolValidationResponse(valid=False, errors=[error])
    return ProtocolValidationResponse(valid=True)


@router.post("/validate-setup")
def validate_protocol_setup(
    body: ProtocolSetupValidationRequest,
) -> ProtocolSetupValidationResponse:
    """Run full CubOS gantry/deck/protocol setup validation."""
    settings = get_settings()
    try:
        gantry_path = resolve_config_path(settings.configs_dir, "gantry", body.gantry_file)
        deck_path = resolve_config_path(settings.configs_dir, "deck", body.deck_file)
        protocol_path = resolve_config_path(settings.configs_dir, "protocol", body.protocol_file)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        result = run_setup_validation(
            str(gantry_path),
            str(deck_path),
            str(protocol_path),
        )
    except Exception as exc:
        logging.exception("Setup validation failed unexpectedly")
        raise HTTPException(500, f"Setup validation failed: {exc}") from exc

    return ProtocolSetupValidationResponse(
        valid=result.passed,
        errors=list(result.errors),
        output=result.output,
    )


class RunProtocolRequest(BaseModel):
    gantry_file: str
    deck_file: str
    protocol_file: str


@router.post("/cancel")
def cancel_protocol_run() -> dict:
    """Request immediate feed hold for the active protocol run."""
    from cubos_api.routers import gantry as gantry_router

    try:
        gantry_router.request_feed_hold_interrupt()
    except InterruptFeedHoldTimeoutError as exc:
        logging.warning(
            "Protocol cancel feed hold timed out after being sent: %s",
            exc,
        )
        return gantry_router.translate_interrupt_timeout(exc)
    except HTTPException:
        raise
    except GantryNotConnectedError as exc:
        raise HTTPException(400, "Gantry is not connected") from exc
    except Exception as exc:
        logging.exception("Protocol cancel failed")
        raise HTTPException(500, f"Cancel failed: {exc}") from exc
    return {"status": "cancel_requested"}


@router.post("/run")
def run_protocol_endpoint(body: RunProtocolRequest) -> dict:
    """Run a protocol through the persistent CubOS gantry session.

    Legacy synchronous run surface, kept for compatibility. It has no
    ``fluid_state_id``/``initial_state`` parameter and creates no durable
    run record, so it structurally cannot select or persist fluid-state
    linkage (Feature 07) — that requires the versioned, addressable
    ``POST /api/v1/runs`` resource (``cubos_api.routers.runs``), which is
    the sole hardware owner for stateful protocol execution.
    """
    from cubos_api.routers import gantry as gantry_router

    settings = get_settings()
    try:
        gantry_path = resolve_config_path(settings.configs_dir, "gantry", body.gantry_file)
        deck_path = resolve_config_path(settings.configs_dir, "deck", body.deck_file)
        protocol_path = resolve_config_path(settings.configs_dir, "protocol", body.protocol_file)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    gantry_router.begin_run(protocol_file=body.protocol_file)
    try:
        try:
            result = gantry_router.run_protocol_on_session(
                gantry_path=str(gantry_path),
                deck_path=str(deck_path),
                protocol_path=str(protocol_path),
                gantry_file=body.gantry_file,
                deck_file=body.deck_file,
                protocol_file=body.protocol_file,
                db_path=settings.data_db_path,
            )
        except HTTPException:
            raise
        except (GantryNotConnectedError, GantrySessionHealthCheckError) as exc:
            raise HTTPException(400, "Gantry is not connected") from exc
        except CalibrationBlockedError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SetupValidationError as exc:
            raise HTTPException(400, str(exc)) from exc
        except GantrySessionError as exc:
            raise HTTPException(500, f"Execution failed: {exc}") from exc
        except Exception as exc:
            logging.exception("Protocol execution failed")
            raise HTTPException(500, f"Execution failed: {exc}") from exc
    finally:
        gantry_router.end_run()

    return {
        "status": result.status,
        "steps_executed": result.steps_executed,
        "campaign_id": result.campaign_id,
    }
