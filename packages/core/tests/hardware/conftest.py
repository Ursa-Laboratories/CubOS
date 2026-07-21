"""Hardware tests require a physical CNC connection — skip in CI."""

collect_ignore = ["test_wpos_enforcement.py"]
