# CubOS SiLA 2 server

This optional service exposes CubOS protocol presets and recorded run artifacts
to SiLA 2 clients. The existing CubOS HTTP API remains the sole owner of the
gantry and mounted instruments.

See [the SiLA guide](../../docs/sila.md) for installation, the complete local
mock demonstration, feature definitions, deployment settings, recovery, and
operator-led physical validation.

From the repository root:

```bash
python -m pip install -e packages/core -e services/api -e sdk/python -e services/sila
python -m cubos_sila --config services/sila/examples/config.yaml
python services/sila/examples/client.py inspect
```

The CubOS API must already be listening on `127.0.0.1:8742`. The example binds
SiLA to `127.0.0.1:50051`, disables discovery, and permits only a mock preset.
The [example client](examples/client.py) discovers the live SiLA feature
definitions; it does not import the server implementation.
