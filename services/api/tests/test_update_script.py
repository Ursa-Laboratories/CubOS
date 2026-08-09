"""Integration tests for deploy/pi/update.sh.

The script runs against a throwaway git repo with pip, npm, sudo, systemctl,
and curl replaced by stubs on PATH — no packages are installed, no services
restarted, no network touched. The curl stub reports healthy only at the
revision named in the control file, which is how tests steer the update into
the success, rollback, and rollback-failure paths.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = REPO_ROOT / "deploy" / "pi" / "update.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture()
def sandbox(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    repo = tmp_path / "CubOS"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    _git(repo, "config", "user.email", "test@cubos")
    _git(repo, "config", "user.name", "test")

    (repo / "packages" / "core").mkdir(parents=True)
    (repo / "services" / "api").mkdir(parents=True)
    (repo / "apps" / "operator-web").mkdir(parents=True)
    (repo / "packages" / "core" / "core.py").write_text("v1\n")
    (repo / "apps" / "operator-web" / "app.js").write_text("v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "prev")
    prev_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "packages" / "core" / "core.py").write_text("v2\n")
    (repo / "apps" / "operator-web" / "app.js").write_text("v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "target")
    target_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "push", "-q", "origin", "HEAD:main")
    _git(repo, "checkout", "-q", "--detach", prev_sha)

    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    stub_log = ctrl / "calls.log"
    stub_log.touch()

    stubs = tmp_path / "stubs"
    stubs.mkdir()

    def stub(name: str, body: str) -> None:
        path = stubs / name
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)

    stub("sudo", 'echo "sudo $*" >> "$CTRL/calls.log"\nexec "$@"\n')
    stub(
        "systemctl",
        'echo "systemctl $* @ $(git -C "$CUBOS_REPO" rev-parse HEAD)" >> "$CTRL/calls.log"\n'
        '[[ -f "$CTRL/systemctl_fail" ]] && exit 1\nexit 0\n',
    )
    stub(
        "npm",
        'echo "npm $* @ $(git rev-parse HEAD)" >> "$CTRL/calls.log"\nexit 0\n',
    )
    stub(
        "curl",
        'if [[ -f "$CTRL/healthy_sha" ]] && '
        '[[ "$(git -C "$CUBOS_REPO" rev-parse HEAD)" == "$(cat "$CTRL/healthy_sha")" ]]; then\n'
        "  exit 0\nfi\nexit 7\n",
    )

    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    pip = venv / "bin" / "pip"
    pip.write_text(
        "#!/usr/bin/env bash\n"
        'echo "pip $* @ $(git rev-parse HEAD)" >> "$CTRL/calls.log"\n'
        'if [[ -f "$CTRL/pip_fail_once" ]]; then rm "$CTRL/pip_fail_once"; exit 7; fi\n'
        "exit 0\n"
    )
    pip.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "CTRL": str(ctrl),
        "CUBOS_REPO": str(repo),
        "CUBOS_VENV": str(venv),
        "CUBOS_HEALTH_URL": "http://stub/health",
        "CUBOS_HEALTH_ATTEMPTS": "2",
        "CUBOS_HEALTH_INTERVAL": "0",
    }
    return {
        "repo": repo,
        "ctrl": ctrl,
        "env": env,
        "prev": prev_sha,
        "target": target_sha,
        "calls": stub_log,
    }


def _run_update(sandbox, target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(UPDATE_SCRIPT), target],
        env=sandbox["env"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_successful_update(sandbox):
    (sandbox["ctrl"] / "healthy_sha").write_text(sandbox["target"])

    result = _run_update(sandbox, sandbox["target"])

    assert result.returncode == 0, result.stdout
    assert f"Update to {sandbox['target']} succeeded" in result.stdout
    assert _git(sandbox["repo"], "rev-parse", "HEAD") == sandbox["target"]
    calls = sandbox["calls"].read_text()
    assert f"pip install -e packages/core -e services/api @ {sandbox['target']}" in calls
    assert f"npm run build @ {sandbox['target']}" in calls
    assert "sudo systemctl restart cubos" in calls


def test_rollback_reports_real_exit_code_and_rebuilds_frontend(sandbox):
    (sandbox["ctrl"] / "pip_fail_once").touch()
    (sandbox["ctrl"] / "healthy_sha").write_text(sandbox["prev"])

    result = _run_update(sandbox, sandbox["target"])

    assert result.returncode == 1, result.stdout
    # The ERR trap must surface pip's status (7), not the trap's own test's.
    assert "failed with exit code 7" in result.stdout
    assert f"rollback to {sandbox['prev']} completed and CubOS is healthy" in result.stdout
    assert _git(sandbox["repo"], "rev-parse", "HEAD") == sandbox["prev"]
    # The frontend changed between the revisions, so rollback must rebuild it
    # at the previous revision, not leave the target bundle in place.
    assert f"npm run build @ {sandbox['prev']}" in sandbox["calls"].read_text()


def test_failed_rollback_is_reported_not_masked(sandbox):
    (sandbox["ctrl"] / "pip_fail_once").touch()
    # No healthy_sha: the service never comes back at any revision.

    result = _run_update(sandbox, sandbox["target"])

    assert result.returncode == 2, result.stdout
    assert "ROLLBACK FAILED" in result.stdout
    assert "completed and CubOS is healthy" not in result.stdout


def test_concurrent_update_is_rejected(sandbox):
    lock = sandbox["repo"] / ".cubos-update.lock"
    lock.mkdir()
    (lock / "pid").write_text(str(os.getpid()))

    result = _run_update(sandbox, sandbox["target"])

    assert result.returncode == 3, result.stdout
    assert "Another update is already in progress" in result.stdout
    assert _git(sandbox["repo"], "rev-parse", "HEAD") == sandbox["prev"]
    assert lock.is_dir(), "a live holder's lock must not be removed"


def test_stale_lock_is_reclaimed(sandbox):
    lock = sandbox["repo"] / ".cubos-update.lock"
    lock.mkdir()
    (lock / "pid").write_text("99999999")
    (sandbox["ctrl"] / "healthy_sha").write_text(sandbox["target"])

    result = _run_update(sandbox, sandbox["target"])

    assert result.returncode == 0, result.stdout
    assert "Removing stale update lock" in result.stdout
    assert not lock.exists()
