# Contributing to CubOS

CubOS controls real lab hardware. Contributions are welcome, but changes need
to preserve the safety and abstraction boundaries that make the system usable
across gantries, instruments, labware, and protocols.

For installation, local setup, and project orientation, start with
[README.md](README.md). This guide covers contribution expectations.

## Pull Requests

- Open pull requests against `main`.
- Keep each PR focused on one behavior, bug fix, driver, workflow, or docs
  change.
- Explain the problem, the approach, and any user-facing behavior changes.
- Add or update tests for the behavior you changed.
- Keep documentation in sync when you change public CLI behavior, YAML schema,
  protocol semantics, hardware setup, calibration, or cross-repo interfaces.
- Do not include unrelated formatting, generated files, or cleanup in the same
  PR unless the PR is specifically for that work.

All CI checks should pass before a PR is merged. You do not need to run the
entire test suite locally for every small change, but run the smallest useful
tests while developing and make sure the PR is not relying on untested behavior.

## Hardware-Facing Changes

Hardware-facing changes require hardware validation before merge. This includes
changes to gantry motion, calibration, setup scripts, protocol execution,
labware coordinate resolution, instrument drivers, vendor integrations, and
commands that actuate instruments.

In the PR description, state exactly:

- What hardware the change can affect.
- What offline validation you ran.
- What physical hardware you tested.
- The exact command, protocol, or script you ran.
- The specific actions you observed on hardware.
- Any hardware behavior you did not test.

Be concrete. For example, a pipette change should say which pipette hardware was
connected, which protocol or script was run, and whether aspirate, dispense,
tip pickup/drop, movement, and error paths were exercised. A gantry change
should say how homing, jog direction, bounds, travel height, and any relevant
protocol movement were checked.

Do not summarize hardware testing as "tested on hardware" without the details
above.

## Tests

Install development dependencies with the commands in [README.md](README.md).

Use focused tests while iterating, for example:

```bash
python -m pytest tests/instruments -q
python -m pytest tests/protocol_engine -q
python -m pytest tests/deck -q
```

For hardware-adjacent configuration or protocol changes, also run the relevant
offline setup validation:

```bash
PYTHONPATH=src python setup/validate_setup.py \
  configs/gantry/<gantry>.yaml \
  configs/deck/<deck>.yaml \
  configs/protocol/<protocol>.yaml
```

For documentation changes, run:

```bash
mkdocs build --strict
```

## Instrument and Vendor Abstractions

Follow the existing instrument layout:

```text
src/instruments/<type>/
  interface.py
  models.py
  exceptions.py
  vendors/<vendor>.py
```

Keep the boundary clear:

- Generic instrument behavior belongs in the type interface, shared models,
  shared exceptions, registry metadata, or protocol engine code.
- Vendor SDK calls, serial details, command translations, and device-specific
  quirks belong in `vendors/<vendor>.py`.
- Do not put vendor-specific behavior into protocol code or generic
  interfaces.
- Do not make the core package import proprietary or optional SDKs at module
  import time. Vendor SDK imports should be lazy and tied to connection or the
  method that needs them.
- New vendor dependencies should be optional extras in `pyproject.toml`, not
  required core dependencies.
- Drivers should support `offline=True` when a meaningful dry-run behavior is
  possible.
- Register new built-in vendors in `src/instruments/registry.yaml`.
- External or proprietary drivers should use the instrument registry entry
  point or `CUBOS_INSTRUMENT_REGISTRY_PATHS` overlay mechanism instead of
  merging private code into CubOS.

If a change feels like it needs to special-case one vendor in a shared layer,
re-check the abstraction before opening the PR.

## Commit and Branch Names

Use descriptive branch names:

```text
fix/pipette-aspirate-timeout
feat/uvvis-calibration-command
docs/getting-started-windows
```

Use conventional commits for commit messages:

```text
fix(pipette): handle aspirate timeout
feat(instruments): add thorlabs ccs health check
docs(calibration): clarify homing preflight
test(protocol): cover scan height validation
```

Common types are `fix`, `feat`, `docs`, `test`, `refactor`, `chore`, and
`ci`.

## PR Checklist

Include this checklist in hardware-facing PRs, and use the relevant parts for
all other PRs:

```markdown
## Summary
- 

## Tests
- [ ] Added or updated test coverage
- [ ] Ran focused tests:
- [ ] Ran offline setup validation, if relevant:
- [ ] CI is expected to pass

## Hardware validation
- [ ] This PR does not affect hardware
- [ ] Hardware affected:
- [ ] Hardware tested:
- [ ] Exact commands/protocols run:
- [ ] Actions observed:
- [ ] Hardware behavior not tested:

## Abstractions
- [ ] Instrument/vendor boundaries are preserved
- [ ] Optional vendor dependencies remain optional
- [ ] Public docs/config examples were updated, if needed
```
