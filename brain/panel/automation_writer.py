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
SCENES_FILE = "scenes.yaml"
CONFIGURATION_FILE = "configuration.yaml"

# `automation: !include automations.yaml`, however it is spaced and
# whether or not the filename is quoted. Matched against the raw text
# rather than the parsed YAML because HA's `!include` is a tag, and every
# loader that tolerates HA's tags — `checks.snapshot.load_yaml_file`
# included — reads one as `None`, which cannot be told from an absent key.
INCLUDE_RE = re.compile(
    r"^\s*automation:\s*!include\s+['\"]?automations\.yaml['\"]?\s*$",
    re.MULTILINE)

SCENE_INCLUDE_RE = re.compile(
    r"^\s*scene:\s*!include\s+['\"]?scenes\.yaml['\"]?\s*$",
    re.MULTILINE)

# An id nothing else in the house is going to pick, and one that says
# where it came from when somebody opens the file in six months.
ID_PREFIX = "brain_"

# Two files, and every difference between them named once.
#
# `apply` was written for automations and the scene designer needs the
# same five steps against a different file — so what varies is a table
# rather than a branch: the file, the include line Core is read through,
# the reload service, and the domain the verification waits on. A second
# `apply` would be a second answer to "snapshot, append, reload, verify,
# revert", and the one that drifts is always the copy.
TARGETS = {
    "automations": {
        "file": AUTOMATIONS_FILE,
        "include": INCLUDE_RE,
        "include_line": "automation: !include automations.yaml",
        "reload": ("automation", "reload"),
        "domain": "automation",
        "what": "automations",
    },
    "scenes": {
        "file": SCENES_FILE,
        "include": SCENE_INCLUDE_RE,
        "include_line": "scene: !include scenes.yaml",
        "reload": ("scene", "reload"),
        "domain": "scene",
        "what": "scenes",
    },
}


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


def _protected_scene_refusal(entries: list[dict],
                             patterns: list[str]) -> str | None:
    """Why these scenes may not be written, or None.

    A scene names entities directly — there is no service call to read —
    so `shadow.would_do` has nothing to say about one and this asks the
    same question of the keys instead. The producer drops a protected
    light and lists it as skipped; this is the second ask, at the writer,
    for the reason the first one is not enough: the chokepoint every
    Claude path goes through cannot see a file the panel writes.
    """
    if not patterns:
        return None
    for entry in entries:
        for eid in (entry.get("entities") or {}):
            if is_protected(str(eid), patterns):
                return (f"{eid} is on the protected entities list, so brAIn "
                        "will not write a scene that sets it")
    return None


def _scene_entries(row: dict, now: float) -> tuple[list[dict], str]:
    """`(entries, "")` or `([], why)`. The scene half of `entry_for`.

    A scene proposal's `config` is a **list**: four moods are one decision
    and one press, and offering them one at a time would be four cards
    somebody has to answer consistently for the set to mean anything.
    """
    config = row.get("config")
    if not isinstance(config, list) or not config:
        return [], "this proposal has no scenes behind it"
    stamp = int(row.get("ts") or now * 1000)
    out = []
    for i, scene in enumerate(config):
        if not isinstance(scene, dict):
            return [], "one of these scenes is not a scene"
        name = str(scene.get("name") or "").strip()
        entities = scene.get("entities")
        if not name or not isinstance(entities, dict) or not entities:
            return [], ("a scene needs a name and at least one entity, and "
                        + "one of these has neither")
        named = str(scene.get("id") or "").strip()
        entry = {
            "id": named if named.startswith(ID_PREFIX) and len(named) <= 64
                  else f"{ID_PREFIX}scene_{stamp}_{i}",
            "name": name[:255],
            "entities": entities,
        }
        out.append(entry)
    return out, ""


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


def _existing(path: Path, what: str = "automations"):
    """`(rows, "")` or `(None, why)`. A missing or empty file is `[]`."""
    text = _read_text(path)
    if text is None:
        # Home Assistant creates this file itself the first time somebody
        # saves an automation in the UI, so creating it is not a change
        # of kind — but only where the include line says Core reads it,
        # which the caller has already checked.
        return [], ""
    # A file with nothing in it but comments is an EMPTY list, not an
    # unreadable one — Home Assistant's own loader answers `None` to both
    # and cannot tell them apart, so the distinction is drawn here. A
    # `scenes.yaml` holding one header line is the ordinary case on a
    # house that has never saved a scene, and refusing it would refuse
    # the commonest first press.
    if not [line for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]:
        return [], ""
    try:
        from checks import snapshot as ha_yaml  # noqa: PLC0415
        rows = ha_yaml.load_yaml_file(str(path))
    except ImportError:                            # pragma: no cover
        return None, "brAIn could not read automations.yaml"
    if rows is None:
        unreadable = (f"{path.name} could not be parsed — brAIn will not "
                      "append to a file it cannot read")
        return None, unreadable
    if not isinstance(rows, list) or not all(
            isinstance(r, dict) for r in rows):
        wrong_shape = (f"{path.name} is not a list of {what}, so this "
                       "install keeps them somewhere else — brAIn will not "
                       "guess where")
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
    # A config may name its own id, and an emergency playbook does:
    # `brain_playbook_smoke` says what it is when somebody opens the file
    # in six months, where `brain_1757000000000` says when it was
    # accepted. It must carry the prefix — an id off the wire that could
    # be anything is an id that could collide with somebody else's, and
    # the duplicate-id refusal is what makes a stable one safe.
    named = str(config.get("id") or "").strip()
    entry = {
        "id": named if named.startswith(ID_PREFIX) and len(named) <= 64
              else f"{ID_PREFIX}{int(row.get('ts') or 0)}",
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


def _dump(entry) -> str:
    import yaml  # noqa: PLC0415 — the image ships py3-yaml; the tests
                 # install pyyaml. Asserted separately, because they are
                 # two different installs of the same package.
    rows = entry if isinstance(entry, list) else [entry]
    return yaml.safe_dump(rows, sort_keys=False, allow_unicode=True,
                          default_flow_style=False)


def apply(row: dict, *, config_dir: str | None = None,
          now: float | None = None, protected=None,
          target: str = "automations") -> dict:
    """Write an accepted proposal into `automations.yaml` or `scenes.yaml`.

    Returns `{"ok": True, ...}` or `{"ok": False, "error": <sentence>}`.
    An expected refusal never raises: the caller has a person waiting on
    a press, and a traceback is not an answer they can act on.

    `target` picks a row out of `TARGETS` and nothing else changes: the
    five steps are the five steps, and a second `apply` for the second
    file would be the copy that drifts.
    """
    now = time.time() if now is None else now
    spec = TARGETS.get(target)
    if spec is None:
        return _fail(f"brAIn does not know how to write {target}")
    root = Path(config_dir or CONFIG_DIR)

    if target == "scenes":
        entries, why = _scene_entries(row, now)
        if not entries:
            return _fail(why)
        refusal = _protected_scene_refusal(entries,
                                           protected_patterns(protected))
    else:
        config = row.get("config")
        if not isinstance(config, dict):
            return _fail("this proposal has no automation behind it")
        has_trigger = config.get("trigger") or config.get("triggers")
        has_action = config.get("action") or config.get("actions")
        if not has_trigger or not has_action:
            return _fail("an automation needs both a trigger and an action, "
                         "and this proposal is missing one")
        entries = [entry_for(row, now)]
        refusal = _protected_refusal(config, protected_patterns(protected))
    if refusal:
        return _fail(refusal)

    configuration = _read_text(root / CONFIGURATION_FILE)
    if configuration is None or not spec["include"].search(configuration):
        return _fail(
            "brAIn looked in configuration.yaml for the line "
            f"`{spec['include_line']}` and did not find it, so it cannot "
            f"tell where this house keeps its {spec['what']}. Add that "
            f"line, or add the {spec['what'][:-1]} yourself from the "
            "proposal's YAML")

    path = root / spec["file"]
    rows, why = _existing(path, spec["what"])
    if rows is None:
        return _fail(why)

    # `alias` for an automation, `name` for a scene: the same claim about
    # the same file, spelled the way each schema spells it.
    label = "alias" if target == "automations" else "name"
    for entry in entries:
        for existing in rows:
            if str(existing.get("id") or "") == entry["id"]:
                return _fail(f"something with this proposal's id is already "
                             f"in {spec['file']} — it looks like this was "
                             "accepted before")
            if str(existing.get(label) or "") == entry[label]:
                return _fail(
                    f"{spec['file']} already has one called "
                    f"\"{entry[label]}\" — brAIn will not add a second "
                    "under the same name")

    try:
        block = _dump(entries)
    except Exception as exc:  # noqa: BLE001 — a config that will not
        # serialise is a refusal, not a crash on somebody's press.
        return _fail(f"this could not be written as YAML: {exc}")

    # The snapshot goes down BEFORE the file is touched. A snapshot taken
    # after the write records the change rather than what it replaced,
    # which is an undo that restores the thing it was undoing.
    try:
        journalled = snapshot(path, now)
    except OSError as exc:
        return _fail(f"brAIn could not snapshot {spec['file']} first, so it "
                     f"did not write to it: {exc}")

    original = _read_text(path) or ""
    if original and not original.endswith("\n"):
        original += "\n"
    try:
        atomic_write.write_text(path, original + block)
    except OSError as exc:
        return _fail(f"brAIn could not write {spec['file']}: {exc}")

    domain = spec["domain"]
    ids = [f"{domain}.{slugify(e[label])}" for e in entries]
    return {
        "ok": True,
        "target": target,
        "automation_id": entries[0]["id"],
        "alias": entries[0][label],
        "entity_id": ids[0],
        # Every entity the write is claiming to have created. One for an
        # automation, four for a set of scenes — and the accept path waits
        # for all of them, because three scenes out of four is a mood
        # missing from a schedule nobody has written yet.
        "entity_ids": ids,
        "reload": list(spec["reload"]),
        "path": str(path),
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


# ---------------------------------------------------------------------------
# Editing ONE entry, leaving every other byte where it was
# ---------------------------------------------------------------------------
#
# `apply` appends and never re-serialises, for the reason its docstring
# gives: the file is somebody's, with their ordering, their comments and
# their quoting. Two producers need to change one entry that is already in
# it — a condition added to an automation somebody keeps undoing, and an
# intent removed once it has fired — and re-serialising the list to do
# that would hand back a diff nobody asked for on every one.
#
# So the edit is a **byte splice**. `yaml.compose` builds the node tree
# without constructing any of it, and every node carries `start_mark` and
# `end_mark` — character offsets into the very text that was parsed. That
# is enough to find where one sequence item begins and ends and to replace
# exactly those bytes, which is why `test_entry_edit.py`'s load-bearing
# assertion is that every byte outside the span is identical before and
# after rather than that the file still parses.
#
# Three things make the span honest, and each of them is a refusal:
#
# *The container's `end_mark` overshoots.* PyYAML ends a **block**
# collection at the start of the token that ended it, so the last item of
# a file swallows a trailing comment and an item followed by blank lines
# swallows those too — splicing over either would delete somebody's text
# from outside the entry. A **flow** collection ends at its closing brace,
# tightly. So the content end is the deepest scalar's for a block node and
# the node's own for a flow one, and only then is the line finished.
#
# *The leading `- ` is not in the node.* An item's `start_mark` is at its
# first key, so the dash has to be walked back to — across a newline,
# because `-\n  id: x` is the same item written differently — and what
# sits before the dash on its line has to be whitespace, which is also
# where the indent to re-emit with comes from.
#
# *Anything that cannot be delimited on a line boundary is refused.* Two
# entries under one id, a document that is not a top-level sequence, an
# item sharing a line with something else: each returns `None` rather than
# a span that is nearly right. A splice is bytes, and nearly right bytes
# are somebody's file with a hole in it.


def _content_end(node) -> int:
    """The last character that really belongs to this node.

    See the block above: a block collection's own `end_mark` runs on to
    whatever ended it, so the answer for one is the furthest of its
    children's. A flow collection closes with a brace and is its own.
    """
    import yaml  # noqa: PLC0415 — see `_dump`

    if isinstance(node, yaml.ScalarNode) or node.flow_style:
        return node.end_mark.index
    ends = [node.start_mark.index]
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            ends.append(_content_end(key))
            ends.append(_content_end(value))
    else:
        for value in node.value:
            ends.append(_content_end(value))
    return max(ends)


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _item_span(text: str, node) -> tuple[int, int, str] | None:
    """`(start, end, indent)` for one sequence item, or None.

    `start` is the beginning of the line the item's `- ` sits on and `end`
    is one past the newline that ends it, so the span is whole lines and
    the splice cannot leave half of one behind.
    """
    dash = node.start_mark.index - 1
    while dash >= 0 and text[dash] in " \t\n\r":
        dash -= 1
    if dash < 0 or text[dash] != "-":
        return None
    start = _line_start(text, dash)
    indent = text[start:dash]
    if indent.strip():
        return None                  # something else shares the dash's line

    end = _content_end(node)
    while end < len(text) and text[end] in " \t":
        end += 1
    if end < len(text):
        if text[end] == "\r":
            end += 1
        if end < len(text):
            if text[end] != "\n":
                return None          # something else shares the last line
            end += 1
    return start, end, indent


def locate(text: str, entry_id: str) -> tuple[int, int] | None:
    """The byte span of the top-level item whose `id` is `entry_id`.

    Includes the leading `- ` and ends on a line boundary. `None` for a
    document that is not a top-level sequence, an id that is not there,
    an id that is there twice (which of them was meant is not a question
    this may guess at), or a span that cannot be cut on line boundaries.
    """
    import yaml  # noqa: PLC0415 — see `_dump`

    wanted = str(entry_id or "")
    if not wanted:
        return None
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return None
    if not isinstance(root, yaml.SequenceNode):
        return None

    found = None
    for item in root.value:
        if not isinstance(item, yaml.MappingNode):
            continue
        for key, value in item.value:
            if (isinstance(key, yaml.ScalarNode) and key.value == "id"
                    and isinstance(value, yaml.ScalarNode)
                    and value.value == wanted):
                if found is not None:
                    return None      # two entries under one id
                found = item
                break
    if found is None:
        return None
    span = _item_span(text, found)
    if span is None:
        return None
    start, end, _indent = span
    return start, end


def _reindent(block: str, indent: str) -> str:
    if not indent:
        return block
    return "".join(indent + line if line.strip() else line
                   for line in block.splitlines(keepends=True))


def _splice(path: Path, entry_id: str, new_entry: dict | None,
            now: float | None) -> dict:
    """Replace or remove one entry, snapshotting first. The shared half."""
    now = time.time() if now is None else now
    text = _read_text(path)
    if text is None:
        return _fail(f"brAIn could not read {path.name}")

    import yaml  # noqa: PLC0415 — see `_dump`

    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        return _fail(f"{path.name} could not be parsed, so brAIn will not "
                     f"edit it: {exc}")
    if not isinstance(root, yaml.SequenceNode):
        return _fail(f"{path.name} is not a list of entries, so this install "
                     "keeps them somewhere else — brAIn will not guess where")
    located = locate(text, entry_id)
    if located is None:
        return _fail(
            f"brAIn could not find exactly one entry with the id "
            f"{entry_id} in {path.name} that it could edit without "
            "reformatting the rest of the file")
    start, end = located
    line = text[start:end]
    indent = line[:len(line) - len(line.lstrip(" \t"))]

    block = ""
    if new_entry is not None:
        try:
            block = _reindent(_dump(new_entry), indent)
        except Exception as exc:  # noqa: BLE001 — a config that will not
            # serialise is a refusal, not a crash on somebody's press.
            return _fail(f"this entry could not be written as YAML: {exc}")

    try:
        journalled = snapshot(path, now)
    except OSError as exc:
        return _fail(f"brAIn could not snapshot {path.name} first, so it did "
                     f"not write to it: {exc}")
    try:
        atomic_write.write_text(path, text[:start] + block + text[end:])
    except OSError as exc:
        return _fail(f"brAIn could not write {path.name}: {exc}")
    return {
        "ok": True,
        "automation_id": entry_id,
        "path": str(path),
        "span": [start, end],
        "snapshot": journalled["snapshot"],
        "journal_ts": journalled["ts"],
        "existed": journalled["existed"],
    }


def replace_entry(row_path, entry_id: str, new_entry: dict, *,
                  now: float | None = None, protected=None) -> dict:
    """Swap one entry for another, leaving every other byte alone.

    The protected-entity question is asked of the **new** config, for the
    same reason `apply` asks it of an appended one: a file the panel
    writes is not one of `call_service`'s callers, so this is the only
    place the answer can be given.
    """
    path = Path(row_path)
    if not isinstance(new_entry, dict):
        return _fail("there is no entry to write in place of that one")
    refusal = _protected_refusal(new_entry, protected_patterns(protected))
    if refusal:
        return _fail(refusal)
    out = _splice(path, entry_id, new_entry, now)
    if out.get("ok"):
        alias = str(new_entry.get("alias") or "")
        out["alias"] = alias
        out["entity_id"] = f"automation.{slugify(alias)}" if alias else ""
    return out


def remove_entry(row_path, entry_id: str, *,
                 now: float | None = None) -> dict:
    """Take one entry out. Nothing replaces it and nothing else moves."""
    return _splice(Path(row_path), entry_id, None, now)


def apply_edit(row: dict, *, config_dir: str | None = None,
               now: float | None = None, protected=None) -> dict:
    """Accept a proposal that CHANGES an entry rather than adding one.

    `apply`'s sibling, and deliberately not a branch inside it: an append
    invents an id, an alias and a description, where this one writes
    somebody's own automation back with one thing different — so nothing
    from `entry_for` may touch it, and the config that goes down is the
    config the card showed.

    The include line is checked here too. An automation that is running
    came from a file Core reads, so a missing line means the entry this
    is about is not the one in the house, and editing the other copy
    would be a change that silently does nothing.
    """
    now = time.time() if now is None else now
    root = Path(config_dir or CONFIG_DIR)
    entry_id = str(row.get("edits") or "")
    config = row.get("config")
    if not entry_id or not isinstance(config, dict):
        return _fail("this proposal does not say which automation it changes")
    if str(config.get("id") or "") != entry_id:
        return _fail("this proposal's automation does not carry the id it "
                     "says it edits, so brAIn will not write it")

    configuration = _read_text(root / CONFIGURATION_FILE)
    if configuration is None or not INCLUDE_RE.search(configuration):
        return _fail(
            "brAIn looked in configuration.yaml for the line "
            "`automation: !include automations.yaml` and did not find it, so "
            "it cannot tell where this house keeps its automations. Change "
            "the automation yourself from the proposal's YAML")

    out = replace_entry(root / AUTOMATIONS_FILE, entry_id, config,
                        now=now, protected=protected)
    if out.get("ok"):
        # The entity Home Assistant actually registered, which is what the
        # accept path waits for. A slug of the alias is a guess that a
        # rename has already moved.
        known = str((row.get("automation") or {}).get("entity_id") or "")
        if known:
            out["entity_id"] = known
        out["alias"] = str((row.get("automation") or {}).get("alias")
                           or config.get("alias") or out.get("alias") or "")
    return out


def remove(entry_id: str, *, config_dir: str | None = None,
           now: float | None = None) -> dict:
    """Take one automation back out of `automations.yaml`.

    The intent card's Remove press. Nothing removes an automation on its
    own — an intent that has fired stays on the list saying so until
    somebody asks for it to go — so this has exactly one caller and it is
    a button.
    """
    root = Path(config_dir or CONFIG_DIR)
    return remove_entry(root / AUTOMATIONS_FILE, entry_id, now=now)


__all__ = ["AUTOMATIONS_FILE", "CONFIGURATION_FILE", "ID_PREFIX", "INCLUDE_RE",
           "SCENES_FILE", "SCENE_INCLUDE_RE", "TARGETS",
           "INDEX", "JOURNAL_DIR", "SNAP_DIR", "TOOL", "apply", "apply_edit", "entry_for",
           "is_protected", "locate", "protected_patterns", "remove",
           "remove_entry",
           "replace_entry", "revert", "slugify", "snapshot"]
