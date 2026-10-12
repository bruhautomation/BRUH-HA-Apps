"""Where everything lives, and the two file helpers every module shares.

Three folders, three owners:

* ``/config/morph`` — the dashboard. Somebody's files, a git repository,
  edited by the person in Edit, by brAIn, and by a suggestion somebody
  approved. Handed to UID 1000 (the ``claude`` user in brAIn's container) so
  brAIn can edit it in place; only this service runs ``git`` in it.
* ``/config/.morph`` — the shared folder. The integration and this service
  talk through it, and the integration reads the mirrors in it directly so a
  dashboard load never waits on a round trip.
* ``/data`` — this add-on's own state: settings, the learning store.

Every path reads an environment variable first so a test can point it at a
temporary directory.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _p(var: str, default: str) -> Path:
    return Path(os.environ.get(var, default))


MORPH_DIR = _p("MORPH_DIR", "/config/morph")
SHARED = _p("MORPH_SHARED", "/config/.morph")
DATA = _p("MORPH_DATA", "/data")
BRAIN_SHARED = _p("MORPH_BRAIN_SHARED", "/config/.brain")
# What a brAIn task is doing while it does it: one line per tool call,
# written by brAIn's brain-task-progress.sh hook (spelled the same there).
BRAIN_PROGRESS = BRAIN_SHARED / "task_progress"
DEFAULTS = _p("MORPH_DEFAULTS", str(Path(__file__).resolve().parent.parent / "defaults"))

DASHBOARD = MORPH_DIR / "dashboard.yaml"
AGENTS = MORPH_DIR / "AGENTS.md"
LEARNED = MORPH_DIR / "LEARNED.md"
CARDS_DIR = MORPH_DIR / "cards"

REQUESTS = SHARED / "requests"
RESPONSES = SHARED / "responses"
MIRROR = SHARED / "dashboard.json"
STATE = SHARED / "state.json"
TELLS = SHARED / "tells"
# Pictures the panel took of what somebody held, written by the integration
# (`morph/shot`) and read by brAIn's Read tool — so readable by UID 1000.
SHOTS = SHARED / "shots"
USAGE = SHARED / "usage.jsonl"
ERRORS = SHARED / "errors.jsonl"
DEVLOOP_OUTBOX = SHARED / "devloop" / "outbox.json"
DEVLOOP_ACK = SHARED / "devloop" / "ack.json"

SETTINGS = DATA / "settings.json"
SUGGESTIONS = DATA / "suggestions.json"
OUTCOMES = DATA / "outcomes.jsonl"
LEARN_STATE = DATA / "learning.json"

# brAIn's own uid, so the files brAIn edits are files brAIn can write.
BRAIN_UID = int(os.environ.get("MORPH_BRAIN_UID", "1000"))


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data, *, indent: int | None = None) -> None:
    write_text(path, json.dumps(data, indent=indent, ensure_ascii=False,
                                sort_keys=indent is not None))


def _default_mode() -> int:
    """The mode an ordinary ``open(..., "w")`` would create, read per call."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def write_text(path: Path, text: str) -> None:
    """Atomic against a reader AND a second writer: a unique scratch name in
    the target's own folder, then a rename. A name derived from the target
    is the same name for two writers, and one of them loses its write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            st = os.stat(path)
            # codeql[py/overly-permissive-file] — this puts back the mode the file already had; tightening it would change who can read an existing file.
            os.chmod(tmp, st.st_mode & 0o7777)
            if os.geteuid() == 0:
                os.chown(tmp, st.st_uid, st.st_gid)
        except FileNotFoundError:
            # A new file gets what an ordinary open(..., "w") would have made
            # (mkstemp's 0600 would hide it from brAIn's claude user).
            os.chmod(tmp, _default_mode())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path, limit: int = 20000) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        return []
    return out[-limit:]


def hand_to_brain(path: Path) -> None:
    """Give a file under /config/morph to brAIn's uid, so a Claude run can
    edit it in place. Never raises: ownership is a convenience, and brAIn's
    own edit hook hands an unwritable file back anyway."""
    if os.geteuid() != 0:
        return
    try:
        os.chown(path, BRAIN_UID, BRAIN_UID)
    except OSError:
        pass  # ownership is a convenience; brAIn's edit hook hands a file back anyway
