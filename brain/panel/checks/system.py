"""Checks on the machine Home Assistant is running on.

These are the four failures that take a house down without anything in it
looking wrong: nothing has been backed up, an add-on that is meant to run
is not running, the disk is nearly full, and the recorder database has
grown past what the disk can hold a copy of. Every one of them is quiet
right up until it is not recoverable.

They read the Supervisor's own answers (``/backups``, ``/addons``,
``/host/info``) and one ``stat`` of the recorder database — nothing here
asks Core anything. A Supervisor that did not answer leaves the key
unavailable, so these checks do not run, and so cannot clear a row they
could not look at.
"""
from __future__ import annotations

from ._util import age_days, join_names, num, when

GB = 1024.0 ** 3
BACKUP_STALE_DAYS = 7
# Free space below either of these is worth saying out loud: a percentage
# alone is meaningless on a 32GB SD card and an absolute alone is
# meaningless on a 2TB NVMe.
DISK_FREE_MIN_GB = 2.0
DISK_FREE_MIN_PCT = 8.0
# A recorder database this big is worth a look whatever the disk says.
DB_LARGE_GB = 1.0
# Home Assistant's own default when `recorder:` does not set one.
DEFAULT_PURGE_DAYS = 10


def _sup(snap: dict) -> dict:
    return snap.get("supervisor") or {}


# ---------------------------------------------------------------------------
# sys.backup_stale — nothing has been backed up
# ---------------------------------------------------------------------------

def backup_stale(snap: dict, now: float) -> list[dict]:
    backups = _sup(snap).get("backups") or []
    ages = []
    for b in backups:
        if not isinstance(b, dict):
            continue
        age = age_days(b.get("date"), now)
        if age is not None:
            ages.append((age, b))
    if not ages:
        return [{
            "text": "Home Assistant has never been backed up",
            "detail": "The Supervisor is holding no backups at all. A "
                      "corrupt SD card or a bad update takes the whole "
                      "house with it.",
            "fix": "Settings > System > Backups > Create backup, then set "
                   "an automatic backup so it keeps happening.",
            "severity": "serious",
            "fixable": False,
            "entity_id": "",
        }]
    ages.sort(key=lambda r: r[0])
    newest_age, newest = ages[0]
    if newest_age < BACKUP_STALE_DAYS:
        return []
    return [{
        "text": "The newest backup is more than a week old",
        "detail": f"'{newest.get('name') or newest.get('slug') or 'a backup'}' "
                  f"from {when(newest.get('date'))}, "
                  f"{int(newest_age)} days ago. "
                  f"{len(ages)} backup{'' if len(ages) == 1 else 's'} stored.",
        "fix": "Settings > System > Backups — take one now, and set an "
               "automatic backup so this does not drift again.",
        "severity": "warning",
        "fixable": False,
        "entity_id": "",
    }]


# ---------------------------------------------------------------------------
# sys.addon_down — set to start, and not running
# ---------------------------------------------------------------------------

def addon_down(snap: dict, now: float) -> list[dict]:
    addons = _sup(snap).get("addons") or []
    stopped: list[str] = []
    errored: list[str] = []
    for a in addons:
        if not isinstance(a, dict) or not a.get("installed", True):
            continue
        name = str(a.get("name") or a.get("slug") or "an add-on")
        state = str(a.get("state") or "")
        if state == "error":
            errored.append(name)
        elif state != "started" and str(a.get("boot") or "") == "auto":
            # `boot: manual` is somebody's decision, not a fault. An add-on
            # with no boot recorded is one whose info we could not read,
            # and "I could not look" is not "it is down".
            stopped.append(name)
    out = []
    if errored:
        errored.sort()
        out.append({
            "text": "An add-on is in an error state",
            "detail": join_names(errored)
                      + ". The Supervisor could not start it, or it exited "
                        "and kept exiting.",
            "fix": "Open the add-on's Log tab — the reason is in the last "
                   "few lines. A crash loop shows the same lines repeating.",
            "severity": "serious",
            "fixable": False,
            "entity_id": "",
        })
    if stopped:
        stopped.sort()
        out.append({
            "text": "An add-on set to start on boot is not running",
            "detail": ("These have boot set to automatic and are "
                       "stopped: " + join_names(stopped)
                       + f" ({len(stopped)})."),
            "fix": "Start it from Settings > Add-ons, or set its boot to "
                   "manual if you stopped it on purpose.",
            "severity": "warning",
            "fixable": False,
            "entity_id": "",
        })
    return out


# ---------------------------------------------------------------------------
# sys.disk_space — the host is nearly full
# ---------------------------------------------------------------------------

def _floats(host: dict) -> tuple[float | None, float | None]:
    return num(host.get("disk_free")), num(host.get("disk_total"))


def disk_space(snap: dict, now: float) -> list[dict]:
    host = _sup(snap).get("host") or {}
    free, total = _floats(host)
    if free is None or total is None or total <= 0:
        return []
    pct = free / total * 100.0
    if free > DISK_FREE_MIN_GB and pct > DISK_FREE_MIN_PCT:
        return []
    return [{
        "text": "The disk Home Assistant runs on is nearly full",
        "detail": f"{free:.1f} GB free of {total:.1f} GB ({pct:.0f}%). "
                  "A full disk stops the recorder, stops backups, and can "
                  "corrupt the database it stops in the middle of.",
        "fix": "Delete old backups first — they are the biggest thing on "
               "most systems. Then shorten recorder purge_keep_days, or "
               "exclude the entities that write most often.",
        "severity": "serious",
        "fixable": False,
        "entity_id": "",
    }]


# ---------------------------------------------------------------------------
# sys.recorder_size — the database has outgrown its headroom
# ---------------------------------------------------------------------------

def recorder_size(snap: dict, now: float) -> list[dict]:
    rec = snap.get("recorder") or {}
    db_bytes = num(rec.get("db_bytes"))
    if not db_bytes:
        return []
    db_gb = db_bytes / GB
    keep = rec.get("purge_keep_days")
    keep_text = (f"purge_keep_days is {keep}" if isinstance(keep, int)
                 else f"purge_keep_days is not set, so it is Home "
                      f"Assistant's default of {DEFAULT_PURGE_DAYS} days")
    # The disk is opportunistic: this check needs the recorder key and
    # nothing else, so that a Supervisor outage cannot take it out. When
    # the host did answer, "no room for a copy" is the sharper sentence.
    free, _total = _floats(_sup(snap).get("host") or {})
    tight = free is not None and free < db_gb
    if db_gb < DB_LARGE_GB and not tight:
        return []
    detail = f"{db_gb:.1f} GB at {rec.get('db_path')}. {keep_text}."
    if tight:
        detail += (f" There is {free:.1f} GB free — less than the database "
                   "itself, so a backup of it cannot be written.")
    return [{
        "text": "The recorder database has grown large",
        "detail": detail,
        "fix": "Lower recorder purge_keep_days, or exclude the entities "
               "that write most often (a power meter at one row a second "
               "is most of a database like this). The file only shrinks "
               "after a repack: Developer tools > Actions > "
               "recorder.purge with repack on.",
        "severity": "warning" if tight else "info",
        "fixable": False,
        "entity_id": "",
    }]


CHECKS = [
    {"id": "sys.backup_stale", "title": "Backups missing or stale",
     "needs": ("supervisor",), "run": backup_stale},
    {"id": "sys.addon_down", "title": "Add-ons stopped or erroring",
     "needs": ("supervisor",), "run": addon_down},
    {"id": "sys.disk_space", "title": "Disk nearly full",
     "needs": ("supervisor",), "run": disk_space},
    {"id": "sys.recorder_size", "title": "Recorder database size",
     "needs": ("recorder",), "run": recorder_size},
]
