# Contributing to CubOS

CubOS controls real hardware, so contributions should keep operator workflows
clear and validation-first.

## Start Here

1. Read [Getting Started](getting-started.md) to understand the operator flow.
2. Install development dependencies with [Development Setup](development.md).
3. Use the contributor pages for implementation details:
   - [Gantry Internals](gantry.md)
   - [Deck Internals](deck-internals.md)
   - [Python Protocols](protocol-python.md)
   - [YAML File Overview](configuration.md)
4. Use the [API Reference](reference/index.md) for generated module docs.

## Contribution Rules

- Keep user-facing setup docs short and task-oriented.
- Put implementation details in the contributing section or API reference.
- Run the smallest meaningful validation first, then broaden when the change
  touches shared behavior.
- Cover the lines you add or change with tests: CI enforces a 90% diff-coverage
  gate on every PR (see the repository `CONTRIBUTING.md` for the local
  commands).
- For hardware-facing changes, report offline validation and the physical
  validation still required.

## Common Checks

```bash
python -m pytest -q
python -m mkdocs build --strict
```
