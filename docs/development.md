# Development Setup

Use this page when you are changing CubOS itself.

## Install

```bash
git clone https://github.com/Ursa-Laboratories/CubOS.git
cd CubOS
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,docs]"
```

Install instrument-specific extras only when you need that driver:

```bash
pip install -e ".[asmi]"
pip install -e ".[potentiostat]"
```

## Run Tests

```bash
python -m pytest -q
```

For focused changes, run the relevant focused tests first. Examples:

```bash
python -m pytest tests/deck/test_deck_loader.py tests/deck/test_holder_labware.py -q
python -m pytest tests/protocol_engine -q
```

## Build Docs

```bash
python -m mkdocs build --strict
```

Use `mkdocs serve` for local review, and restart the server after changing
`mkdocs.yml` because navigation changes may not hot-reload.
