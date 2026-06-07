Read `AGENTS.md` first. It is the source of truth for retrieval, hardware-safety handoff order, progress notes, and validation gates.

In **TDD Mode** (planning sessions, new features, cross-repo interface changes): write tests alongside implementation and update docs as you go. In **Hardware Iteration Mode** (small changes under active hardware testing): defer tests and docs to close-out, mark deferred work with `# TODO(iter)`. See `AGENTS.md` for full mode definitions.

In planning mode, ask follow-up questions and wait for plan review before executing.

Update durable docs only when public CLI/workflow, YAML schema/config, coordinate/motion/calibration semantics, protocol behavior, or cross-repo interfaces change. Update `AGENTS.md` only when agent retrieval or hardware-safety workflow changes.
