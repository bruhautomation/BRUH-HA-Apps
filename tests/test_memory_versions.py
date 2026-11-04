"""Versioned memory (plan 2.2 and 2.4, section 0: no human in the loop).

What is driven, through the real consolidator script with a stand-in
`claude` and through `panel/memory_history.py` directly:

  * every pass writes `memory.next.md` and a structured diff, and an applied
    pass is kept as a version in the history folder with that diff;
  * the deterministic check refuses a pass that drops or rewords a line a
    person gave, feeds the reason back once, and keeps the document and the
    inbox when the second answer is no better;
  * a line from another add-on is filed "(unverified)" whatever the model
    wrote, and the check refuses an answer that takes that mark off
    without a person saying the same thing;
  * a document still over its cap after the model's own retry has old
    lines EVICTED (unverified first, never a person's) instead of the
    inbox stalling, and the eviction is undoable;
  * `brain memory undo` restores the previous version as a NEW version,
    `brain memory history` lists them, and only 30 are kept;
  * the nightly self-check rolls a bad machine version back one, and never
    a person's own edit;
  * `--remove` (the clean-up's applied removals) takes exact lines out as
    one version and refuses a person's line.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "brain" / "scripts"
PANEL = REPO / "brain" / "panel"
CONSOLIDATOR = SCRIPTS / "brain-memory-consolidate.sh"
MEMORY_CLI = SCRIPTS / "brain-memory.sh"
sys.path.insert(0, str(PANEL))

import memory_history as mh  # noqa: E402

pytestmark = pytest.mark.slow

HEAD = "# Home Memory\n\n## Preferences\n"
VOICE = "-----VOICE-----\n- 'the beacon' = light.office_lamp\n"


def fake_claude(tmp: Path, *answers: str) -> Path:
    """A stand-in CLI answering each call with the next answer (the last
    one repeats), logging every prompt it was given."""
    for i, body in enumerate(answers):
        (tmp / f"answer{i}.txt").write_text(body)
    script = tmp / "fake_claude.sh"
    script.write_text(
        "#!/bin/bash\n"
        'n=$(cat "$FAKE_N" 2>/dev/null || echo 0)\n'
        'cat >> "$FAKE_PROMPTS"; printf "\\n=====\\n" >> "$FAKE_PROMPTS"\n'
        f'last={len(answers) - 1}\n'
        '[ "$n" -gt "$last" ] && n=$last\n'
        f'cat "{tmp}/answer$n.txt"\n'
        'echo $((n + 1)) > "$FAKE_N"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def run(memory_dir: Path, claude: Path | None, *args: str, **env):
    tmp = memory_dir.parent
    full = dict(os.environ, BRAIN_MEMORY_DIR=str(memory_dir),
                BRAIN_SHARE_INBOX=str(tmp / "share"),
                BRAIN_PANEL_DIR=str(PANEL),
                BRAIN_CONTEXT_GEN=str(tmp / "no-gen"),
                FAKE_N=str(tmp / "n"), FAKE_PROMPTS=str(tmp / "prompts.txt"))
    full.pop("BRAIN_MEMORY_HISTORY_DIR", None)
    if claude is not None:
        full["BRAIN_CLAUDE_BIN"] = str(claude)
    full.update(env)
    return subprocess.run(["bash", str(CONSOLIDATOR), *args], env=full,
                          capture_output=True, text=True, timeout=60)


def queue(memory_dir: Path, source: str, fact: str, name: str = "") -> None:
    inbox = memory_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / (name or f"{time.time_ns()}-{source}.jsonl")).write_text(
        json.dumps({"ts": int(time.time()), "source": source, "fact": fact,
                    "confidence": "high"}) + "\n")


def pending(memory_dir: Path) -> int:
    return len(list((memory_dir / "inbox").glob("*.jsonl")))


def history(memory_dir: Path) -> list[dict]:
    return mh.versions(memory_dir / "history")


@pytest.fixture
def mem(tmp_path):
    d = tmp_path / "memory"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# A pass is a version with its diff
# ---------------------------------------------------------------------------


def test_a_pass_writes_the_proposal_its_diff_and_a_version(mem, tmp_path):
    (mem / "memory.md").write_text(HEAD + "- The hall light is on a timer\n")
    queue(mem, "insights", "The office lamp is called the beacon")
    claude = fake_claude(tmp_path, HEAD + "- The hall light is on a timer\n"
                         "- The office lamp is called the beacon\n" + VOICE)
    res = run(mem, claude, "--once")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "kept as memory version" in res.stdout
    assert (mem / "memory.next.md").read_text().endswith(
        "- The office lamp is called the beacon\n")
    diff = json.loads((mem / "memory.next.diff.json").read_text())["diff"]
    assert diff["added"] == [{"line": "- The office lamp is called the beacon",
                              "class": "machine", "sources": ["insights"]}]
    kinds = [v["kind"] for v in history(mem)]
    assert kinds == ["baseline", "consolidation"]
    assert history(mem)[-1]["diff"]["added"][0]["sources"] == ["insights"]
    assert pending(mem) == 0


# ---------------------------------------------------------------------------
# A person's lines
# ---------------------------------------------------------------------------


def _person_line_document(mem: Path, tmp_path: Path) -> str:
    """A document whose porch line came from a correction, as a version."""
    doc = HEAD + "- The porch sensor reads on continuously by design\n"
    (mem / "memory.md").write_text(HEAD)
    queue(mem, "correction", "The porch sensor reads on continuously by design")
    res = run(mem, fake_claude(tmp_path, doc + VOICE), "--once")
    assert res.returncode == 0, res.stdout
    (tmp_path / "n").unlink()
    return doc


def test_a_reworded_person_line_is_refused_then_asked_again(mem, tmp_path):
    doc = _person_line_document(mem, tmp_path)
    queue(mem, "insights", "The garage door closes at night")
    reworded = (HEAD + "- Porch sensor: always on (observed 2026-11-04)\n"
                "- The garage door closes at night\n" + VOICE)
    kept = doc + "- The garage door closes at night\n" + VOICE
    (tmp_path / "prompts.txt").write_text("")
    res = run(mem, fake_claude(tmp_path, reworded, kept), "--once")
    assert res.returncode == 0, res.stdout
    assert "the memory check refused the pass" in res.stdout
    prompts = (tmp_path / "prompts.txt").read_text().split("=====")
    # The person's line is in the first prompt as protected, and the second
    # prompt carries the measured reason.
    assert "PROTECTED LINES" in prompts[0]
    assert "- The porch sensor reads on continuously by design" in prompts[0]
    assert "a line a person gave was dropped or reworded" in prompts[1]
    assert "- The porch sensor reads on continuously by design" in \
        (mem / "memory.md").read_text()


def test_a_second_bad_answer_keeps_the_document_and_the_inbox(mem, tmp_path):
    doc = _person_line_document(mem, tmp_path)
    queue(mem, "insights", "The garage door closes at night")
    reworded = HEAD + "- Porch sensor: always on\n" + VOICE
    res = run(mem, fake_claude(tmp_path, reworded), "--once")
    assert res.returncode == 1
    assert "REFUSED by the memory check" in res.stdout
    assert (mem / "memory.md").read_text() == doc
    assert pending(mem) == 1
    assert mh.rejections(mem / "history"), "the refusal was not recorded"


def test_a_newer_correction_may_replace_a_person_line(mem, tmp_path):
    _person_line_document(mem, tmp_path)
    queue(mem, "correction",
          "The porch sensor no longer reads on continuously, it was rewired")
    new = HEAD + "- The porch sensor was rewired and reads normally now\n"
    res = run(mem, fake_claude(tmp_path, new + VOICE), "--once")
    assert res.returncode == 0, res.stdout
    assert history(mem)[-1]["diff"]["superseded"] == [
        "- The porch sensor reads on continuously by design"]


def test_a_line_typed_into_the_document_is_a_persons(mem, tmp_path):
    _person_line_document(mem, tmp_path)
    with (mem / "memory.md").open("a") as fh:
        fh.write("- We never heat the loft\n")
    queue(mem, "insights", "The garage door closes at night")
    dropped = HEAD + "- The porch sensor reads on continuously by design\n" \
        "- The garage door closes at night\n" + VOICE
    res = run(mem, fake_claude(tmp_path, dropped), "--once")
    assert res.returncode == 1
    assert "We never heat the loft" in res.stdout
    kinds = [v["kind"] for v in history(mem)]
    assert "person-edit" not in kinds   # nothing applied, nothing recorded


def test_a_hand_edit_is_kept_as_its_own_version_before_the_next(mem, tmp_path):
    _person_line_document(mem, tmp_path)
    with (mem / "memory.md").open("a") as fh:
        fh.write("- We never heat the loft\n")
    edited = (mem / "memory.md").read_text()
    queue(mem, "insights", "The garage door closes at night")
    res = run(mem, fake_claude(
        tmp_path, edited + "- The garage door closes at night\n" + VOICE),
        "--once")
    assert res.returncode == 0, res.stdout
    kinds = [v["kind"] for v in history(mem)]
    assert kinds[-2:] == ["person-edit", "consolidation"]
    # Undo goes back to the person's edit, not past it.
    res = run(mem, None, "--undo")
    assert res.returncode == 0, res.stdout
    assert (mem / "memory.md").read_text() == edited


# ---------------------------------------------------------------------------
# Untrusted text (plan 2.3)
# ---------------------------------------------------------------------------


def test_another_add_ons_fact_is_filed_unverified(mem, tmp_path):
    (mem / "memory.md").write_text(HEAD)
    share = tmp_path / "share"
    share.mkdir()
    (share / "1-insights.jsonl").write_text(json.dumps({
        "ts": 1, "source": "insights", "fact": "The apple tree is sprayed weekly",
        "confidence": "high"}) + "\n")
    res = run(mem, fake_claude(
        tmp_path, HEAD + "- The apple tree is sprayed weekly (observed 2026-11-01)\n"
        + VOICE), "--once")
    assert res.returncode == 0, res.stdout
    assert "- The apple tree is sprayed weekly (unverified) (observed 2026-11-01)" \
        in (mem / "memory.md").read_text()
    prompt = (tmp_path / "prompts.txt").read_text()
    assert "UNVERIFIED FACTS" in prompt
    assert "The apple tree is sprayed weekly" in prompt
    assert list((mem / "inbox" / "processed").glob("share-*"))


def test_the_mark_may_not_be_taken_off_by_a_machine(mem, tmp_path):
    (mem / "memory.md").write_text(HEAD)
    queue(mem, "gardenrx", "The apple tree is sprayed weekly")
    marked = HEAD + "- The apple tree is sprayed weekly (unverified)\n"
    assert run(mem, fake_claude(tmp_path, marked + VOICE), "--once").returncode == 0
    (tmp_path / "n").unlink()
    queue(mem, "insights", "The pump runs at dawn")
    plain = HEAD + "- The apple tree is sprayed weekly\n- The pump runs at dawn\n"
    res = run(mem, fake_claude(tmp_path, plain + VOICE), "--once")
    assert res.returncode == 1
    assert "(unverified) mark was taken off" in res.stdout
    (tmp_path / "n").unlink()
    # A person saying the same thing is the confirmation.
    queue(mem, "correction", "Yes, the apple tree is sprayed every week")
    res = run(mem, fake_claude(tmp_path, plain + VOICE), "--once")
    assert res.returncode == 0, res.stdout
    assert history(mem)[-1]["diff"]["corroborated"] == [
        "- The apple tree is sprayed weekly"]


# ---------------------------------------------------------------------------
# A full document evicts instead of stalling (plan 2.4)
# ---------------------------------------------------------------------------


def _full_document(mem: Path, tmp_path: Path) -> str:
    lines = [f"- Machine note number {i} about the boiler and the pump\n"
             for i in range(30)]
    doc = (HEAD + "- The porch sensor reads on continuously by design\n"
           + "- The apple tree is sprayed weekly (unverified)\n" + "".join(lines))
    (mem / "memory.md").write_text(HEAD)
    queue(mem, "correction", "The porch sensor reads on continuously by design")
    queue(mem, "gardenrx", "The apple tree is sprayed weekly")
    queue(mem, "insights", "Machine note about the boiler and the pump")
    res = run(mem, fake_claude(tmp_path, doc + VOICE), "--once")
    assert res.returncode == 0, res.stdout
    (tmp_path / "n").unlink()
    return doc


def test_a_full_document_evicts_the_lowest_value_lines(mem, tmp_path):
    doc = _full_document(mem, tmp_path)
    queue(mem, "insights", "The garage door closes at ten every night")
    grown = doc + "- The garage door closes at ten every night\n" + VOICE
    res = run(mem, fake_claude(tmp_path, grown), "--once",
              BRAIN_MEMORY_MAX_KB="1", BRAIN_MEMORY_SIZE_ATTEMPTS="1")
    assert len(doc) > 1024, "the fixture must exceed the 1 KB cap"
    assert res.returncode == 0, res.stdout
    assert "evicted" in res.stdout
    after = (mem / "memory.md").read_text()
    assert len(after.rstrip("\n")) <= 1024
    assert "- The porch sensor reads on continuously by design" in after
    assert "- The garage door closes at ten every night" in after
    assert "apple tree" not in after, "unverified lines go first"
    evicted = history(mem)[-1]["diff"]["evicted"]
    assert evicted[0]["why"] == "unverified"
    assert all("porch" not in e["line"] for e in evicted)
    assert pending(mem) == 0
    # Undoable.
    assert run(mem, None, "--undo").returncode == 0
    assert "apple tree" in (mem / "memory.md").read_text()


def test_nothing_evictable_still_names_the_setting(mem, tmp_path):
    (mem / "memory.md").write_text(HEAD)
    big = HEAD + "".join(f"- brand new fact {i} about the house and garden\n"
                         for i in range(60))
    queue(mem, "insights", "brand new fact about the house")
    res = run(mem, fake_claude(tmp_path, big + VOICE), "--once",
              BRAIN_MEMORY_MAX_KB="1")
    assert res.returncode == 1
    assert "memory_max_kb" in res.stdout
    assert (mem / "memory.md").read_text() == HEAD
    assert pending(mem) == 1


# ---------------------------------------------------------------------------
# History, undo, the nightly check, removals
# ---------------------------------------------------------------------------


def test_undo_is_itself_a_version_and_undoable(mem, tmp_path):
    (mem / "memory.md").write_text(HEAD + "- one\n")
    queue(mem, "insights", "Two is the second fact")
    res = run(mem, fake_claude(tmp_path, HEAD + "- one\n- Two is the second fact\n"
                               + VOICE), "--once")
    assert res.returncode == 0
    after_pass = (mem / "memory.md").read_text()
    assert run(mem, None, "--undo").returncode == 0
    assert (mem / "memory.md").read_text() == HEAD + "- one\n"
    assert run(mem, None, "--undo").returncode == 0
    assert (mem / "memory.md").read_text() == after_pass
    assert [v["kind"] for v in history(mem)] == [
        "baseline", "consolidation", "undo", "undo"]


def test_the_cli_lists_and_undoes(mem, tmp_path):
    (mem / "memory.md").write_text(HEAD + "- one\n")
    queue(mem, "insights", "Two is the second fact")
    run(mem, fake_claude(tmp_path, HEAD + "- one\n- Two is the second fact\n"
                         + VOICE), "--once")
    env = dict(os.environ, BRAIN_MEMORY_DIR=str(mem), BRAIN_PANEL_DIR=str(PANEL))
    env.pop("BRAIN_MEMORY_HISTORY_DIR", None)
    out = subprocess.run(["bash", str(MEMORY_CLI), "history"], env=env,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "consolidation" in out.stdout and "[insights]" in out.stdout
    out = subprocess.run(["bash", str(MEMORY_CLI), "undo"], env=env,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "previous version" in out.stdout
    assert "Two is" not in (mem / "memory.md").read_text()


def test_only_thirty_versions_are_kept(tmp_path):
    hist = tmp_path / "h"
    for i in range(35):
        mh.add_version(f"# v{i}\n", kind="consolidation", hist=hist, now=1000 + i)
    have = mh.versions(hist)
    assert len(have) == mh.KEEP_VERSIONS
    assert have[0]["seq"] == 6 and have[-1]["seq"] == 35
    assert len(list(hist.glob("*.md"))) == mh.KEEP_VERSIONS


def test_the_nightly_check_rolls_a_bad_version_back(mem, tmp_path):
    _person_line_document(mem, tmp_path)
    good = (mem / "memory.md").read_text()
    # A version that should never have landed (an older build, a tampered
    # file): the person's line is gone and nothing excused it.
    bad = HEAD + "- something else\n"
    (mem / "memory.md").write_text(bad)
    mh.record(good, bad, kind="consolidation", check_result={"diff": {}},
              mem=mem, hist=mem / "history")
    res = run(mem, None, "--selfcheck")
    assert res.returncode == 0
    assert "rolled back one version" in res.stdout
    assert (mem / "memory.md").read_text() == good
    assert history(mem)[-1]["kind"] == "rollback"


def test_the_nightly_check_never_rolls_back_a_persons_edit(mem, tmp_path):
    _person_line_document(mem, tmp_path)
    (mem / "memory.md").write_text(HEAD + "- I rewrote all of this myself\n")
    res = run(mem, None, "--selfcheck")
    assert res.returncode == 0
    assert (mem / "memory.md").read_text() == HEAD + "- I rewrote all of this myself\n"
    assert history(mem)[-1]["kind"] == "person-edit"


def test_remove_takes_exact_lines_and_refuses_a_persons(mem, tmp_path):
    before = _person_line_document(mem, tmp_path)
    lamp = "- The lamp was on at 9pm on Tuesday"
    (mem / "memory.md").write_text(before + lamp + "\n")
    mh.record(before, before + lamp + "\n", kind="consolidation",
              check_result={"attribution": {lamp: {"class": "machine",
                                                   "sources": ["insights"]}}},
              mem=mem, hist=mem / "history")
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps([
        {"text": "The lamp was on at 9pm on Tuesday", "why": "stale: one evening"},
        {"text": "The porch sensor reads on continuously by design", "why": "wrong"}]))
    res = run(mem, None, "--remove", str(lines))
    assert res.returncode == 0, res.stdout
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["removed"] == ["- The lamp was on at 9pm on Tuesday"]
    assert out["refused"] == ["- The porch sensor reads on continuously by design"]
    doc = (mem / "memory.md").read_text()
    assert "9pm" not in doc and "porch sensor" in doc
    assert history(mem)[-1]["kind"] == "cleanup"
    assert history(mem)[-1]["diff"]["dropped"][0]["why"] == "stale: one evening"


def test_history_folder_for_a_test_memory_is_never_the_real_data(tmp_path):
    assert mh.history_dir(tmp_path / "memory") == tmp_path / "memory" / "history"
    os.environ["BRAIN_MEMORY_HISTORY_DIR"] = str(tmp_path / "elsewhere")
    try:
        assert mh.history_dir(tmp_path / "memory") == tmp_path / "elsewhere"
    finally:
        del os.environ["BRAIN_MEMORY_HISTORY_DIR"]


def test_the_brain_dispatcher_announces_history():
    text = (SCRIPTS / "brain.sh").read_text()
    assert "      history [n]" in text
    assert "brain memory history" in MEMORY_CLI.read_text()


def test_a_correction_filed_before_versioning_is_protected(mem, tmp_path):
    """The first pass after an upgrade has no ledger: a line the facts store
    says a person gave is a person's from that first pass."""
    doc = HEAD + "- The cupboard contact never moves, that is normal\n"
    (mem / "memory.md").write_text(doc)
    (mem / "facts.json").write_text(json.dumps({"facts": [{
        "id": "a1", "text": "The cupboard contact never moves, that is normal",
        "source": "correction", "subject": "house"}]}))
    queue(mem, "insights", "The garage door closes at night")
    res = run(mem, fake_claude(
        tmp_path, HEAD + "- The garage door closes at night\n" + VOICE), "--once")
    assert res.returncode == 1
    assert "cupboard contact" in res.stdout
    assert (mem / "memory.md").read_text() == doc
