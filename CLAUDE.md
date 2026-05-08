Read `AGENTS.md` first. It is the source of truth for retrieval, hardware-safety handoff order, progress notes, and validation gates.

Use TDD for implementation unless `AGENTS.md` debugging mode applies. Keep code clean, run focused tests as you work, and delete temporary files before finalizing.

In planning mode, ask follow-up questions and wait for plan review before executing.

Update durable docs only when public CLI/workflow, YAML schema/config, coordinate/motion/calibration semantics, protocol behavior, or cross-repo interfaces change. Update `AGENTS.md` only when agent retrieval or hardware-safety workflow changes.
