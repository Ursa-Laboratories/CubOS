# Development Setup

Use this page when you are changing CubOS itself.

Run these commands from the repository root. The activation command below is
for macOS/Linux; see [Getting Started](getting-started.md#installation) for
Windows activation and prerequisites.

## Install

```bash
git clone https://github.com/Ursa-Laboratories/CubOS.git
cd CubOS
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e "packages/core[dev,docs]"
```

Install vendor-specific extras only when you need that built-in driver:

```bash
python -m pip install -e "packages/core[asmi-vernier]"
python -m pip install -e "packages/core[potentiostat-admiral]"
```

Private or customer drivers should live in a separate installable package. Expose
that package through the `cubos.instrument_registries` entry point group, or set
`CUBOS_INSTRUMENT_REGISTRY_PATHS` to one or more overlay YAML files during local
development.

## Run Tests

```bash
python -m pytest packages/core/tests -q
```

For focused changes, run the relevant focused tests first. Examples:

```bash
python -m pytest packages/core/tests/deck/test_deck_loader.py packages/core/tests/deck/test_holder_labware.py -q
python -m pytest packages/core/tests/protocol_engine -q
```

The API, Python client, and SiLA service have separate development dependencies
and test suites. With Python 3.11+, install and test the components you are
changing:

```bash
python -m pip install -e "services/api[dev]"
python -m pytest services/api/tests -q
python -m pip install -e "sdk/python[dev]"
python -m pytest sdk/python/tests -q
python -m pip install -e "services/sila[dev]"
python -m pytest services/sila/tests -q
```

For Operator's Node.js setup and build, see
[Getting Started](getting-started.md#build-the-operator-ui-browser-app).

## Build Docs

```bash
python -m mkdocs build --strict
```

Use `mkdocs serve` for local review, and restart the server after changing
`mkdocs.yml` because navigation changes may not hot-reload.
