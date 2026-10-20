"""Independent SiLA client for the CubOS appliance features."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

from sila.client import Client, ClientConfig
from sila.framework import SiLAError


NAMESPACE = "ai.ursalabs/cubos.appliance"


def command(client: Client, feature: str, name: str):
    return client.get_command(f"{NAMESPACE}/{feature}/v1/Command/{name}")


def show(value) -> None:
    print(json.dumps(value, indent=2, default=str), flush=True)


async def observe_status(execution) -> None:
    async for info in await execution.subscribe_status():
        show({"execution_status": info.status.name, "progress": info.progress})


async def observe_progress(execution) -> None:
    async for response in await execution.subscribe_intermediate_responses():
        show(response)


async def run(args: argparse.Namespace) -> None:
    client = Client(ClientConfig(
        hostname=args.host,
        port=args.port,
        tls=args.ca is not None,
        root_certificates=args.ca.read_bytes() if args.ca else None,
        default_timeout=10_000,
    ))
    async with client:
        if args.action == "inspect":
            show({"name": await client.get_server_name(), "uuid": await client.get_server_uuid()})
            features = await client.get_implemented_features()
            show({"features": features})
            for name in ("SoftwareVersion", "ServiceAvailable", "HardwareConnectionState", "ExecutionState", "ActiveRunId"):
                value = await client.get_property(f"{NAMESPACE}/CubStatus/v1/Property/{name}").read()
                show({name: value})
            show(await command(client, "ProtocolExecution", "ListProtocols").execute())
            if args.feature_dir:
                args.feature_dir.mkdir(parents=True, exist_ok=True)
                for identifier in features:
                    filename = identifier.replace("/", "_") + ".sila.xml"
                    (args.feature_dir / filename).write_text(await client.get_feature_definition(identifier), encoding="utf-8")
        elif args.action == "execute":
            run_id = args.run_id or str(uuid4())
            show({"run_id": run_id, "protocol": args.protocol})
            execution = await command(client, "ProtocolExecution", "ExecuteProtocol").execute({
                "ProtocolName": args.protocol, "RunId": run_id,
            })
            show({"execution_uuid": execution.command_execution_uuid})
            await asyncio.gather(observe_progress(execution), observe_status(execution))
            show(await execution.get_responses())
        elif args.action == "get-run":
            response = await command(client, "RunResults", "GetRun").execute({"RunId": args.run_id})
            show(json.loads(response["RunJson"]))
        elif args.action == "artifacts":
            show(await command(client, "RunResults", "GetArtifacts").execute({"RunId": args.run_id}))
        elif args.action == "download":
            response = await command(client, "RunResults", "GetArtifact").execute({
                "RunId": args.run_id, "ArtifactName": args.artifact,
            })
            args.output.write_bytes(response["Content"])
            show({"saved": str(args.output), "bytes": len(response["Content"])})
        elif args.action == "cancel":
            show(await command(client, "ProtocolExecution", "CancelRun").execute({"RunId": args.run_id}))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=50051)
    result.add_argument("--ca", type=Path, help="Trust this PEM certificate and use TLS")
    actions = result.add_subparsers(dest="action", required=True)
    inspect = actions.add_parser("inspect", help="Read identity, status, presets, and feature definitions")
    inspect.add_argument("--feature-dir", type=Path)
    execute = actions.add_parser("execute", help="Run a preset and observe status and intermediate responses")
    execute.add_argument("protocol", nargs="?", default="mock-measurement")
    execute.add_argument("--run-id", help="Persist this ID before submitting; retrieve it after a disconnect")
    for action in ("get-run", "artifacts", "cancel"):
        actions.add_parser(action).add_argument("run_id")
    download = actions.add_parser("download")
    download.add_argument("run_id")
    download.add_argument("artifact")
    download.add_argument("output", type=Path)
    return result


def main() -> int:
    try:
        asyncio.run(run(parser().parse_args()))
    except (SiLAError, OSError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Observation ended. Retrieve the original run ID to check its state.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
