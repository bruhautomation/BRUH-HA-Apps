"""The suite's own guards in tests/conftest.py, driven rather than trusted.

A guard that is only ever exercised by the failure it exists to catch is a
guard nobody can tell is still wired up.
"""

import os
import sys
from pathlib import Path


TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS))

import conftest  # noqa: E402


class TestTheRealDataGuard:
    def test_the_snapshot_sees_a_new_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(conftest, "_REAL_DATA", tmp_path)
        before = conftest._data_snapshot()
        (tmp_path / "journal.jsonl").write_text("x")
        after = conftest._data_snapshot()
        assert before != after
        assert "journal.jsonl" in after

    def test_a_missing_directory_is_no_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(conftest, "_REAL_DATA", tmp_path / "absent")
        assert conftest._data_snapshot() is None

    def test_strict_mode_is_the_env_var(self):
        # Pinned so the switch's name in CLAUDE.md and here cannot drift.
        src = (TESTS / "conftest.py").read_text()
        assert 'os.environ.get("BRAIN_STRICT_DATA") == "1"' in src
        assert os.environ.get("BRAIN_STRICT_DATA") in (None, "", "0", "1")
