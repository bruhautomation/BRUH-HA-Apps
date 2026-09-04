"""A yes becomes an automation, and it can be taken back.

This is the first code in the add-on that changes the house **without a
Claude run and without somebody pressing Fix it**, so it is deliberately
the narrowest thing that can do the job. Everything else that writes to
`/config` is a person's press on a specific finding, driven by a model
that read the file first. This appends one automation somebody accepted,
to one file, in one shape.

**Snapshot first, append never rewrite.** The snapshot goes into the same
edit journal `scripts/brain-edit-snapshot.py` writes for every Claude
edit, in the same line shape, so `brain undo` reverts this exactly as it
reverts one — there is no second undo mechanism to keep true. And the
append is text: `automations.yaml` is somebody's file, with their
ordering, their comments and their quoting, and a writer that
re-serialised the whole list would hand back a diff nobody asked for on
every accept. What is added is one `yaml.safe_dump` of one entry at the
end.

**Four refusals, and each is a sentence rather than a guess.**

*A protected entity.* `protected_entities` is enforced at the MCP
server's `call_service`, which is the chokepoint every Claude path
reaches the house through — and a YAML file written by the panel is not
one of them. So this path has to ask itself, and it asks the same
question the same way: an exact id, a `domain.*`, or `*`. An action
naming an **area or a device** is refused outright while the list is
non-empty, because resolving one needs the registries and this has none —
the conservatism `_meta_call_denied` already applies.

*No `automation: !include automations.yaml`.* A house with packages, or
`automation manual:`, or a split config keeps its automations somewhere
this cannot find, and appending to a file Home Assistant does not read
would be a change that silently does nothing. The refusal names the line
that was looked for rather than guessing at another file.

*A file that is not a list of automations.* An empty or missing file is
created — Home Assistant does the same — but only where the include line
says Core reads it. Anything else is somebody's file in a shape this
does not understand.

*A duplicate `id` or `alias`.* Two automations with one id is a config
Core refuses to load, and two with one alias is a house where nobody can
tell which is which.

**Reloading is the server's, and so is verifying.** Nothing here touches
the network: a module that both edits a file and calls Core is a module
whose failure modes cannot be told apart. `apply` returns what it wrote
and what it wrote it over; `revert` puts the file back from that.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

import atomic_write

CONFIG_DIR = os.environ.get("BRAIN_CONFIG_DIR", "/config")

# The same journal `scripts/brain-edit-snapshot.py` writes and `brain
# undo` reads, honouring the same override so a test (and a dev
# checkout) can point both halves somewhere else.
JOURNAL_DIR = Path(os.environ.get("BRAIN_EDIT_JOURNAL", "/data/.brain/edits"))
SNAP_DIR = JOURNAL_DIR / "snapshots"
INDEX = JOURNAL_DIR / "index.jsonl"
# What the journal line says did the edit. `brain undo` does not care
# which tool, but somebody reading the index does: an entry that says
# `Write` about a file no Claude run touched is a lie about who changed
# the house.
TOOL = "brain-panel"

AUTOMATIONS_FILE = "automations.yaml"
CONFIGURATION_FILE = "configuration.yaml"

# `automation: !include automations.yaml`, however it is spaced and
# whether or not the filename is quoted. Matched against the raw text
# rather than the parsed YAML because HA's `!include` is a tag, and every
# loader that tolerates HA's tags — `checks.snapshot.load_yaml_file`
# included — reads one as `None`, which cannot be told from an absent key.
INCLUDE_RE = re.compile(
    r"^\s*automation:\s*!include\s+['\"]?automations\.yaml['\"]?\s*$",
    re.MULTILINE)

# An id nothing else in the house is going to pick, and one that says
# where it came from when somebody opens the file in six months.
ID_PREFIX = "brain_"


def _fail(reason: str) -> dict:
    return {"ok": False, "error": reason}


# ---------------------------------------------------------------------------
# Protected entities — asked here because the chokepoint cannot see a file
# ---------------------------------------------------------------------------

def protected_patterns(explicit=None) -> list[str]:
    """`BRAIN_PROTECTED_ENTITIES`, or whatever a caller handed in.

    Parsed exactly as `ha_mcp_server` parses it, because a second reading
    of the same option is a second answer to "is this entity protected".
    """
    if explicit is not None:
        raw = explicit if isinstance(explicit, (list, tuple, set)) \
            else str(explicit).split(",")
    else:
        raw = os.environ.get("BRAIN_PROTECTED_ENTITIES", "").split(",")
    return [str(p).strip().lower() for p in raw if str(p).strip()]


def is_protected(entity_id: str, patterns: list[str]) -> bool:
    target = str(entity_id or "").strip().lower()
    if not target:
        return False
    domain = target.split(".", 1)[0]
    return any(p in (target, f"{domain}.*", "*") for p in patterns)


def _protected_refusal(config: dict, patterns: list[str]) -> str | None:
    """Why this automation may not be written, or None."""
    if not patterns:
        return None
    import shadow  # noqa: PLC0415 — panel-local, and only needed here

    for call in shadow.would_do(config):
        if call.get("area_id") or call.get("device_id"):
            return ("this automation targets an area or a device, and while "
                    "protected entities are set brAIn will not write one it "
                    "cannot expand — it has no registry to expand it with")
        entity = call.get("entity_id")
        ids = [entity] if isinstance(entity, str) else list(entity or [])
        for eid in ids:
            if is_protected(str(eid), patterns):
                return (f"{eid} is on the protected entities list, so brAIn "
                        "will not write an automation that acts on it")
    return None


# ---------------------------------------------------------------------------
# Reading what is there
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _existing(path: Path):
    """`(rows, "")` or `(None, why)`. A missing or empty file is `[]`."""
    text = _read_text(path)
    if text is None:
        # Home Assistant creates this file itself the first time somebody
        # saves an automation in the UI, so creating it is not a change
        # of kind — but only where the include line says Core reads it,
        # which the caller has already checked.
        return [], ""
    if not text.strip():
        return [], ""
    try:
        from checks import snapshot as ha_yaml  # noqa: PLC0415
        rows = ha_yaml.load_yaml_file(str(path))
    except ImportError:                            # pragma: no cover
        return None, "brAIn could not read automations.yaml"
    if rows is None:
        unreadable = ("automations.yaml could not be parsed — brAIn will not "
                      "append to a file it cannot read")
        return None, unreadable
    if not isinstance(rows, list) or not all(
            isinstance(r, dict) for r in rows):
        wrong_shape = ("automations.yaml is not a list of automations, so "
                       "this install keeps them somewhere else — brAIn will "
                       "not guess where")
        return None, wrong_shape
    return rows, ""


# ---------------------------------------------------------------------------
# The journal — the same shape `brain undo` already reads
# ---------------------------------------------------------------------------

def snapshot(path: Path, now: float | None = None) -> dict:
    """Copy the file aside and append one index line. Raises on failure.

    Deliberately not best-effort, unlike the PreToolUse hook it shares a
    journal with: that one must never block an edit, where this one has
    no business making a change it could not take back. The line's shape
    is the hook's, field for field, because `brain undo` reads both.
    """
    now = time.time() if now is None else now
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    existed = path.is_file()
    name = ""
    if existed:
        digest = hashlib.sha256(str(path).encode()).hexdigest()[:10]
        name = f"{int(now)}-{digest}-{path.name}"
        shutil.copy2(path, SNAP_DIR / name)
    entry = {"ts": now, "path": str(path), "tool": TOOL,
             "snapshot": name, "existed": existed}
    with INDEX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


# ---------------------------------------------------------------------------
# Writing it
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Home Assistant's own object id for an automation's alias."""
    out = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return out or "automation"


def entry_for(row: dict, now: float | None = None) -> dict:
    """The automation, as it goes into the file.

    The `alias` is added **here** rather than in `routines.to_config`,
    which deliberately carries none: that config is what
    `proposals.key_for` hashes, and a title holds the entity's name and
    the time, either of which can move without the change moving. It is a
    write-time fact, not part of what was proposed.
    """
    now = time.time() if now is None else now
    config = row.get("config") or {}
    entry = {
        "id": f"{ID_PREFIX}{int(row.get('ts') or 0)}",
        "alias": str(row.get("title") or "brAIn automation")[:255],
        "description": (
            "Proposed by brAIn from what you do by hand; accepted on "
            f"{time.strftime('%Y-%m-%d', time.localtime(now))}."),
    }
    for key in ("trigger", "triggers", "condition", "conditions",
                "action", "actions", "mode"):
        if key in config:
            entry[key] = config[key]
    return entry


def _dump(entry: dict) -> str:
    import yaml  # noqa: PLC0415 — the image ships py3-yaml; the tests
                 # install pyyaml. Asserted separately, because they are
                 # two different installs of the same package.
    return yaml.safe_dump([entry], sort_keys=False, allow_unicode=True,
                          default_flow_style=False)


def apply(row: dict, *, config_dir: str | None = None,
          now: float | None = None, protected=None) -> dict:
    """Write an accepted proposal into `automations.yaml`.

    Returns `{"ok": True, ...}` or `{"ok": False, "error": <sentence>}`.
    An expected refusal never raises: the caller has a person waiting on
    a press, and a traceback is not an answer they can act on.
    """
    now = time.time() if now is None else now
    root = Path(config_dir or CONFIG_DIR)
    config = row.get("config")
    if not isinstance(config, dict):
        return _fail("this proposal has no automation behind it")
    has_trigger = config.get("trigger") or config.get("triggers")
    has_action = config.get("action") or config.get("actions")
    if not has_trigger or not has_action:
        return _fail("an automation needs both a trigger and an action, and "
                     "this proposal is missing one")

    refusal = _protected_refusal(config, protected_patterns(protected))
    if refusal:
        return _fail(refusal)

    configuration = _read_text(root / CONFIGURATION_FILE)
    if configuration is None or not INCLUDE_RE.search(configuration):
        return _fail(
            "brAIn looked in configuration.yaml for the line "
            "`automation: !include automations.yaml` and did not find it, so "
            "it cannot tell where this house keeps its automations. Add that "
            "line, or add the automation yourself from the proposal's YAML")

    target = root / AUTOMATIONS_FILE
    rows, why = _existing(target)
    if rows is None:
        return _fail(why)

    entry = entry_for(row, now)
    for existing in rows:
        if str(existing.get("id") or "") == entry["id"]:
            return _fail("an automation with this proposal's id is already "
                         "in automations.yaml — it looks like this was "
                         "accepted before")
        if str(existing.get("alias") or "") == entry["alias"]:
            return _fail(
                f"automations.yaml already has one called \"{entry['alias']}\""
                " — brAIn will not add a second automation under the same "
                "name")

    try:
        block = _dump(entry)
    except Exception as exc:  # noqa: BLE001 — a config that will not
        # serialise is a refusal, not a crash on somebody's press.
        return _fail(f"this automation could not be written as YAML: {exc}")

    # The snapshot goes down BEFORE the file is touched. A snapshot taken
    # after the write records the change rather than what it replaced,
    # which is an undo that restores the thing it was undoing.
    try:
        journalled = snapshot(target, now)
    except OSError as exc:
        return _fail(f"brAIn could not snapshot automations.yaml first, so "
                     f"it did not write to it: {exc}")

    original = _read_text(target) or ""
    if original and not original.endswith("\n"):
        original += "\n"
    try:
        atomic_write.write_text(target, original + block)
    except OSError as exc:
        return _fail(f"brAIn could not write automations.yaml: {exc}")

    return {
        "ok": True,
        "automation_id": entry["id"],
        "alias": entry["alias"],
        "entity_id": f"automation.{slugify(entry['alias'])}",
        "path": str(target),
        "snapshot": journalled["snapshot"],
        "journal_ts": journalled["ts"],
        "existed": journalled["existed"],
    }


def revert(snapshot_entry: dict, *, config_dir: str | None = None) -> dict:
    """Put `automations.yaml` back to the bytes the snapshot holds.

    The undo half, and the failure half: the accept path calls this when
    the reload or the verification does not come back, so it has to work
    on a file that was written seconds ago and on one nobody touched.
    """
    recorded = str(snapshot_entry.get("path") or "")
    if not recorded:
        return _fail("there is nothing recorded to put back")
    target = Path(recorded)
    # The journal line carries the path that was written, which is the
    # truth about what to put back — but a caller that believes `/config`
    # is somewhere else is a caller talking about a different file, and
    # restoring over it would be this module writing outside the tree it
    # was pointed at.
    if target.parent != Path(config_dir or CONFIG_DIR):
        return _fail(f"{recorded} is not in this install's config folder")

    if not snapshot_entry.get("existed"):
        # There was no file before, so putting it back means removing it.
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            return _fail(f"could not remove {target}: {exc}")
        return {"ok": True, "path": str(target), "removed": True}

    source = SNAP_DIR / str(snapshot_entry.get("snapshot") or "")
    text = _read_text(source)
    if text is None:
        return _fail("the snapshot of automations.yaml is gone, so brAIn "
                     "cannot put the file back — the automation it added is "
                     "the last block in it")
    try:
        atomic_write.write_text(target, text)
    except OSError as exc:
        return _fail(f"could not restore {target}: {exc}")
    return {"ok": True, "path": str(target), "removed": False}


__all__ = ["AUTOMATIONS_FILE", "CONFIGURATION_FILE", "ID_PREFIX", "INCLUDE_RE",
           "INDEX", "JOURNAL_DIR", "SNAP_DIR", "TOOL", "apply", "entry_for",
           "is_protected", "protected_patterns", "revert", "slugify",
           "snapshot"]
