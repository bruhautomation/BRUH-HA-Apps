"""Unit tests for .github/scripts/check-changelog-version.sh.

The check exists because Home Assistant offers whatever `version:` in
config.yaml says — a CHANGELOG entry announcing a release that
config.yaml doesn't carry means users read about "2.3.0" while the
store still offers something older, and nothing fails.

Strategy mirrors test_check_version_bump.py: build a fake addon dir per
test and invoke the *real* script — not a Python port — because the
script is what CI actually runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".github" / "scripts" / "check-changelog-version.sh"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _make_addon(
    tmp_path: Path,
    config_version: str = "1.0.0",
    changelog: str = "# Changelog\n\n## 1.0.0\n\nInitial.\n",
) -> Path:
    addon = tmp_path / "addon"
    addon.mkdir(parents=True)
    (addon / "config.yaml").write_text(
        f'---\nname: "Test Addon"\nversion: "{config_version}"\nslug: "test"\n'
    )
    (addon / "CHANGELOG.md").write_text(changelog)
    return tmp_path


def test_passes_when_versions_match(tmp_path: Path) -> None:
    repo = _make_addon(tmp_path)
    result = _run([str(SCRIPT), "addon"], cwd=repo)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "matches shipped version" in result.stdout


def test_fails_when_changelog_ahead_of_config(tmp_path: Path) -> None:
    """The headline case: changelog announces a release config.yaml never
    shipped — users read about 1.1.0 while the HA store offers 1.0.0."""
    repo = _make_addon(
        tmp_path,
        config_version="1.0.0",
        changelog="# Changelog\n\n## 1.1.0\n\nShiny new stuff.\n\n## 1.0.0\n\nInitial.\n",
    )
    result = _run([str(SCRIPT), "addon"], cwd=repo)
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "1.1.0" in combined
    assert "1.0.0" in combined
    assert "doesn't match" in combined


def test_fails_when_config_bumped_without_changelog_entry(tmp_path: Path) -> None:
    """The inverse: version bumped but the changelog top entry is stale."""
    repo = _make_addon(
        tmp_path,
        config_version="1.1.0",
        changelog="# Changelog\n\n## 1.0.0\n\nInitial.\n",
    )
    result = _run([str(SCRIPT), "addon"], cwd=repo)
    assert result.returncode == 1


def test_first_heading_wins_not_highest(tmp_path: Path) -> None:
    """Latest entry = topmost heading. Older entries below don't confuse it."""
    repo = _make_addon(
        tmp_path,
        config_version="2.0.0",
        changelog="# Changelog\n\n## 2.0.0\n\nNew.\n\n## 1.9.9\n\nOld.\n",
    )
    result = _run([str(SCRIPT), "addon"], cwd=repo)
    assert result.returncode == 0, result.stderr or result.stdout


def test_accepts_keep_a_changelog_format(tmp_path: Path) -> None:
    """`## [1.2.3] - 2026-01-01` and `## v1.2.3` are both parsed."""
    repo = _make_addon(
        tmp_path,
        config_version="1.2.3",
        changelog=(
            "# Changelog\n\nAll notable changes documented here, following "
            "Keep a Changelog.\n\n## [1.2.3] - 2026-01-01\n\nStuff.\n"
        ),
    )
    result = _run([str(SCRIPT), "addon"], cwd=repo)
    assert result.returncode == 0, result.stderr or result.stdout

    repo2 = _make_addon(
        tmp_path / "v2",
        config_version="1.2.3",
        changelog="# Changelog\n\n## v1.2.3\n\nStuff.\n",
    )
    repo2_result = _run([str(SCRIPT), "addon"], cwd=repo2)
    assert repo2_result.returncode == 0, repo2_result.stderr or repo2_result.stdout


def test_ignores_non_version_headings_in_preamble(tmp_path: Path) -> None:
    """Section headings like `## Unreleased ideas` before the first release
    entry must not be mistaken for a version (minecraft-style preamble)."""
    repo = _make_addon(
        tmp_path,
        config_version="1.0.0",
        changelog=(
            "# Changelog\n\nPreamble text.\n\n## About this file\n\nBlah.\n\n"
            "## 1.0.0\n\nInitial.\n"
        ),
    )
    result = _run([str(SCRIPT), "addon"], cwd=repo)
    assert result.returncode == 0, result.stderr or result.stdout


def test_fails_when_changelog_has_no_version_heading(tmp_path: Path) -> None:
    repo = _make_addon(
        tmp_path, changelog="# Changelog\n\nNothing released yet.\n"
    )
    result = _run([str(SCRIPT), "addon"], cwd=repo)
    assert result.returncode == 1
    assert "No version heading" in (result.stdout + result.stderr)


def test_usage_error_without_args(tmp_path: Path) -> None:
    result = _run([str(SCRIPT)], cwd=tmp_path)
    assert result.returncode == 2
    assert "usage" in (result.stdout + result.stderr).lower()


def test_missing_files_exit_2(tmp_path: Path) -> None:
    result = _run([str(SCRIPT), "no-such-addon"], cwd=tmp_path)
    assert result.returncode == 2

    addon = tmp_path / "addon"
    addon.mkdir()
    (addon / "config.yaml").write_text('version: "1.0.0"\n')
    result = _run([str(SCRIPT), "addon"], cwd=tmp_path)
    assert result.returncode == 2
    assert "changelog does not exist" in (result.stdout + result.stderr)


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.exists(), f"missing: {SCRIPT}"
    assert SCRIPT.stat().st_mode & 0o111, "script is not executable"


@pytest.mark.parametrize(
    "addon_dir", ["bruh-claude-terminal", "bruh-minecraft-server"]
)
def test_real_addons_changelog_matches_shipped_version(addon_dir: str) -> None:
    """The real repo must always pass: the latest CHANGELOG entry of each
    add-on documents exactly the version config.yaml ships. This is the
    guard that fails a PR which writes release notes without delivering
    the release (or vice versa)."""
    result = _run([str(SCRIPT), addon_dir], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr or result.stdout
