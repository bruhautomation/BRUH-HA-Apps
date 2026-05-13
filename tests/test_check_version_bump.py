"""Unit tests for .github/scripts/check-version-bump.sh.

Strategy: spin up a tiny git repo per test, commit a fake addon, branch,
make changes, then invoke the script and assert on exit code + stderr.
Each test is fully isolated via pytest's tmp_path so no global git state
leaks.

We test against the *real* script — not a Python port — because the
script is what CI actually runs. A Python port would let CI silently
diverge from the test suite.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".github" / "scripts" / "check-version-bump.sh"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _git(*args: str, cwd: Path) -> None:
    """Run a git command, raise on failure. Helper to keep tests readable."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: {result.stderr or result.stdout}"
        )


@pytest.fixture
def addon_repo(tmp_path: Path) -> Path:
    """Initialise a fake addon at tmp_path/addon with version 1.0.0 on `main`.

    The fixture also creates a `feature` branch checked out, so individual
    tests can immediately make changes and the diff has somewhere to point
    at.
    """
    _git("init", "-q", "--initial-branch=main", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    _git("config", "commit.gpgsign", "false", cwd=tmp_path)

    addon = tmp_path / "addon"
    addon.mkdir()
    (addon / "config.yaml").write_text('version: "1.0.0"\nname: "Test Addon"\n')
    (addon / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (addon / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0\n\nInitial.\n")
    (addon / "README.md").write_text("# Test Addon\n")

    _git("add", ".", cwd=tmp_path)
    _git("commit", "-qm", "initial", cwd=tmp_path)
    _git("checkout", "-qb", "feature", cwd=tmp_path)
    return tmp_path


def test_passes_when_no_addon_changes(addon_repo: Path) -> None:
    """No commits on the feature branch → no diff → no bump required."""
    result = _run([str(SCRIPT), "main", "addon"], cwd=addon_repo)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "No version-relevant changes" in result.stdout


def test_passes_when_only_changelog_changed(addon_repo: Path) -> None:
    """CHANGELOG-only edits don't need a bump (they document the bump itself).
    Without this exclusion, contributors would hit a chicken-and-egg loop."""
    (addon_repo / "addon" / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 1.0.0\n\nUpdated description.\n"
    )
    _git("commit", "-aqm", "changelog tweak", cwd=addon_repo)
    result = _run([str(SCRIPT), "main", "addon"], cwd=addon_repo)
    assert result.returncode == 0, result.stderr or result.stdout


def test_passes_when_only_readme_changed(addon_repo: Path) -> None:
    """README is pure docs; doesn't ship to HA, doesn't need a bump."""
    (addon_repo / "addon" / "README.md").write_text("# Test Addon\n\nMore docs.\n")
    _git("commit", "-aqm", "readme tweak", cwd=addon_repo)
    result = _run([str(SCRIPT), "main", "addon"], cwd=addon_repo)
    assert result.returncode == 0, result.stderr or result.stdout


def test_fails_when_run_sh_changed_without_bump(addon_repo: Path) -> None:
    """The headline case: real addon code changed but version stayed put.
    This is what slipped through pre-2.0.1."""
    (addon_repo / "addon" / "run.sh").write_text("#!/bin/sh\necho new behaviour\n")
    _git("commit", "-aqm", "behaviour change", cwd=addon_repo)
    result = _run([str(SCRIPT), "main", "addon"], cwd=addon_repo)
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "Bump the version" in combined
    assert "run.sh" in combined


def test_passes_when_run_sh_changed_with_bump(addon_repo: Path) -> None:
    """The happy path: behaviour change + version bump together."""
    (addon_repo / "addon" / "run.sh").write_text("#!/bin/sh\necho new behaviour\n")
    (addon_repo / "addon" / "config.yaml").write_text(
        'version: "1.0.1"\nname: "Test Addon"\n'
    )
    _git("commit", "-aqm", "behaviour change with bump", cwd=addon_repo)
    result = _run([str(SCRIPT), "main", "addon"], cwd=addon_repo)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "Version bumped" in result.stdout
    assert "1.0.0" in result.stdout
    assert "1.0.1" in result.stdout


def test_fails_when_config_only_changed_without_version_bump(addon_repo: Path) -> None:
    """Editing config.yaml itself (e.g. adding a new option) without bumping
    version should still fail — the change is shipped to users and they
    need the new image."""
    (addon_repo / "addon" / "config.yaml").write_text(
        'version: "1.0.0"\nname: "Test Addon"\nnew_option: true\n'
    )
    _git("commit", "-aqm", "config tweak no bump", cwd=addon_repo)
    result = _run([str(SCRIPT), "main", "addon"], cwd=addon_repo)
    assert result.returncode == 1
    assert "Bump the version" in (result.stdout + result.stderr)


def test_fails_with_usage_when_args_missing(tmp_path: Path) -> None:
    """No base ref + no addon dir → clean exit code 2, not a crash."""
    result = _run([str(SCRIPT)], cwd=tmp_path)
    assert result.returncode == 2
    assert "usage" in (result.stderr + result.stdout).lower()


def test_fails_cleanly_when_addon_dir_missing(addon_repo: Path) -> None:
    """If we point at a nonexistent dir, fail with a clear message, not
    a confusing git error."""
    result = _run([str(SCRIPT), "main", "no-such-addon"], cwd=addon_repo)
    assert result.returncode == 2
    assert "does not exist" in (result.stderr + result.stdout)


def test_handles_new_addon_without_base_config(addon_repo: Path) -> None:
    """A brand-new addon (not present on base branch) still needs a version
    declared — and since `base_version` is empty and `head_version` is set,
    they differ, so the check passes. We're testing that the script doesn't
    crash trying to `git show` a nonexistent file."""
    new_addon = addon_repo / "new-addon"
    new_addon.mkdir()
    (new_addon / "config.yaml").write_text('version: "0.1.0"\nname: "New"\n')
    (new_addon / "run.sh").write_text("#!/bin/sh\n")
    _git("add", ".", cwd=addon_repo)
    _git("commit", "-qm", "new addon", cwd=addon_repo)
    result = _run([str(SCRIPT), "main", "new-addon"], cwd=addon_repo)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "Version bumped" in result.stdout


def test_real_repo_paths_resolve(addon_repo: Path) -> None:
    """The script is found at the expected path and is executable —
    catches a forgotten `chmod +x` on a fresh clone."""
    assert SCRIPT.exists(), f"missing: {SCRIPT}"
    assert SCRIPT.stat().st_mode & 0o111, "script is not executable"
