"""The house's health after it installs a release: the canary.

With no person in the loop (the owner's decision, plan section 0), what
replaces the human who would have noticed a bad release is the house that
installed it. For a window after every install (`canary_window_hours`,
24) the `canary` stream reports, once an hour, in ONE rolling issue per
release titled ``[canary] brain <version>``:

* ``new_faults`` — fault fingerprints first seen on this release (seen on
  at least two passes, so one blip while the add-on came back is not a
  fault the release made);
* ``came_back`` — fixed reports seen again after the install
  (`upstream._follow_up`'s and `_held_check`'s ``came_back_at``);
* ``scorecard_drops`` — a rule whose right-share fell by
  `DROP_POINTS` or more against the previous release, read off the settled
  ledger's ``release`` field (absent on a ledger from before that field:
  then there is nothing to compare, and nothing is claimed);
* ``start_crash`` — the panel started `CRASH_STARTS` times on this
  release, or `UNREADY_STARTS` starts never reached a running checks loop.

Any one of them is ``regressed``, said at once; none by the window's end
is ``healthy``; until then ``pending``. The cloud reverts the release's
PR on a regression. The verdict is final once said: the stream files
nothing more for that release, and `upstream._post_canary_final` posts it
once as a comment. A release replaced before its window ended is judged on
what its window saw.

The other BRUH add-ons get the same, cheaply, from what the siblings stream
already reads: a new release of one (its version moving in the queue's
``products``) opens its own canary, judged on that add-on's new faults, its
fixes that came back and its "not running although set to start" row.
There is no scorecard for them.

Pure where it can be (`judge`, `rows_for`); the state is `canary.json`
beside the queue. Never raises out of `pass_rows`: it runs on the tick.
"""
from __future__ import annotations

import json
import logging
import time

import atomic_write

from . import data_dir, enabled, load_settings
from .siblings import PRODUCTS, spec_by_name

log = logging.getLogger("brain.devloop")

DROP_POINTS = 20.0
# A rule needs this many endings on BOTH releases before its share is
# compared: two Wrongs out of two is not a release getting worse.
MIN_ENDINGS = 3
CRASH_STARTS = 4
UNREADY_STARTS = 2
MAX_STARTS = 60
MAX_RELEASES = 12
RECENT = 5
NEW_FAULT_MIN_SEEN = 2
BRAIN = "brAIn"


def state_file():
    return data_dir() / "canary.json"


def load() -> dict:
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("products"), dict):
        data["products"] = {}
    if not isinstance(data.get("starts"), list):
        data["starts"] = []
    return data


def save(data: dict) -> None:
    data["starts"] = [s for s in data.get("starts") or [] if isinstance(s, dict)][-MAX_STARTS:]
    for prod in (data.get("products") or {}).values():
        rel = prod.get("releases") or {}
        if len(rel) > MAX_RELEASES:
            for ver in sorted(rel, key=lambda k: float(rel[k].get("installed_at") or 0)
                              )[:len(rel) - MAX_RELEASES]:
                rel.pop(ver, None)
    atomic_write.write_json(state_file(), data, mode=0o600)


def slug(product: str) -> str:
    spec = spec_by_name(product)
    return str(spec["key"]) if spec else "brain"


# ---------------------------------------------------------------------------
# The heartbeat: every start, and whether it reached a running loop
# ---------------------------------------------------------------------------

def note_start(version: str, now: float | None = None) -> None:
    """The panel started on ``version``. Called from `on_startup`; recorded
    only while the loop is on, and never raises."""
    try:
        if not enabled():
            return
        data = load()
        data["starts"].append({"at": float(now or time.time()),
                               "version": str(version or "")[:40], "ready": False})
        save(data)
    except Exception as exc:  # noqa: BLE001 — a start must not fail on this
        log.info("devloop canary: could not note the start: %s", exc)


def note_ready(now: float | None = None) -> None:
    """The newest start reached the checks loop: it came up."""
    data = load()
    starts = data["starts"]
    if starts and not starts[-1].get("ready"):
        starts[-1]["ready"] = True
        starts[-1]["ready_at"] = float(now or time.time())
        save(data)


def start_crash(starts: list[dict], version: str, since: float, until: float) -> bool:
    """Whether the panel struggled to start on ``version`` in the window:
    too many starts, or starts that never reached the checks loop (the
    newest is not counted, since it may simply not have got there yet)."""
    mine = [s for s in starts or [] if isinstance(s, dict)
            and str(s.get("version") or "") == version
            and since <= float(s.get("at") or 0) < until]
    unready = [s for s in mine[:-1] if not s.get("ready")]
    return len(mine) >= CRASH_STARTS or len(unready) >= UNREADY_STARTS


# ---------------------------------------------------------------------------
# Installs: a version that moved is a release installed
# ---------------------------------------------------------------------------

def observe(data: dict, versions: dict[str, str], now: float) -> list[tuple[str, str]]:
    """Record every product whose running version changed. A first
    reading is only the baseline, brAIn's included: the loop may have been
    switched on a year after the install, and every fault already there
    would read as one the release made. Answers ``[(product, version)]``
    newly installed."""
    out = []
    for product, version in versions.items():
        version = str(version or "")
        if not version or version in ("?", "dev"):
            continue
        prod = data["products"].setdefault(product, {"current": "", "releases": {}})
        prod.setdefault("releases", {})
        current = str(prod.get("current") or "")
        if current == version:
            continue
        if current:
            old = prod["releases"].get(current)
            if isinstance(old, dict) and not old.get("superseded_at"):
                old["superseded_at"] = now
            prod["releases"][version] = {"installed_at": now, "previous": current,
                                         "verdict": "pending", "final": False}
            out.append((product, version))
        prod["current"] = version
    return out


# ---------------------------------------------------------------------------
# The judgement
# ---------------------------------------------------------------------------

def _mine(entry: dict, product: str) -> bool:
    named = str(entry.get("product") or "")
    named = named if named in PRODUCTS else BRAIN
    return named == product


def new_faults(items: dict, product: str, since: float, until: float) -> list[dict]:
    streams = ("faults", "morph") if product == BRAIN else ("siblings",)
    out = []
    for entry in (items or {}).values():
        if (not isinstance(entry, dict) or entry.get("stream") not in streams
                or not _mine(entry, product) or entry.get("state") == "discarded"
                or entry.get("verdict") in ("not_brain", "duplicate", "declined")
                or int(entry.get("seen") or 0) < NEW_FAULT_MIN_SEEN):
            continue
        if since <= float(entry.get("first_seen") or 0) < until:
            out.append({"fp": str(entry.get("fp") or ""),
                        "what": str(entry.get("what") or "")[:200]})
    out.sort(key=lambda r: r["fp"])
    return out[:20]


def came_back(items: dict, product: str, since: float, until: float) -> list[str]:
    out = []
    for entry in (items or {}).values():
        if not isinstance(entry, dict) or not _mine(entry, product):
            continue
        at = float(entry.get("came_back_at") or 0)
        if not at and entry.get("verdict") == "fixed" and entry.get("returned"):
            at = float(entry.get("returned_at") or 0)
        if since <= at < until:
            out.append(str(entry.get("fp") or ""))
    return sorted(set(out))[:20]


def _shares(settled: list[dict], release: str) -> dict[str, tuple[int, int]]:
    """Per producer on one release: (confirmed, total), from the settled
    ledger rows that carry ``release`` — the scorecard's own counting
    (`findings_store.scorecard`): fixed/accepted right, ignored wrong."""
    out: dict[str, list[int]] = {}
    for e in settled or []:
        if not isinstance(e, dict) or str(e.get("release") or "") != release:
            continue
        src = str(e.get("source") or "")
        kind = e.get("kind")
        if not src or kind == "not_applicable":
            continue
        row = out.setdefault(src, [0, 0])
        if kind in ("fixed", "accepted"):
            row[0] += 1
            row[1] += 1
        elif kind == "ignored":
            row[1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def scorecard_drops(settled: list[dict], release: str, previous: str) -> list[dict]:
    """Producers whose right-share fell `DROP_POINTS` or more against the
    previous release. Nothing without a ``release`` on the ledger rows:
    "could not compare" is never "it dropped"."""
    if not release or not previous:
        return []
    now_s, was_s = _shares(settled, release), _shares(settled, previous)
    out = []
    for src, (right, total) in now_s.items():
        was = was_s.get(src)
        if not was or total < MIN_ENDINGS or was[1] < MIN_ENDINGS:
            continue
        before = round(100.0 * was[0] / was[1], 1)
        after = round(100.0 * right / total, 1)
        if before - after >= DROP_POINTS:
            out.append({"producer": src, "before": before, "after": after})
    out.sort(key=lambda r: (r["after"] - r["before"], r["producer"]))
    return out[:20]


def _sibling_crash(items: dict, product: str, since: float, until: float) -> bool:
    for entry in (items or {}).values():
        if (isinstance(entry, dict) and entry.get("stream") == "siblings"
                and _mine(entry, product)
                and str(entry.get("where") or "").endswith("· Add-on")
                and since <= float(entry.get("last_seen") or 0) < until):
            return True
    return False


def judge(rel: dict, *, product: str, version: str, items: dict, settled: list,
          starts: list, window_s: float, now: float) -> dict:
    """The block's object (without its digest) for one release, now."""
    since = float(rel.get("installed_at") or now)
    end = since + window_s
    until = min(end, float(rel.get("superseded_at") or end), now + 1)
    obj = {
        "v": 1,
        "product": slug(product),
        "release": version,
        "installed_at": _iso(since),
        "checked_at": _iso(now),
        "window_hours": int(round(window_s / 3600)),
        "new_faults": new_faults(items, product, since, until),
        "came_back": came_back(items, product, since, until),
        "scorecard_drops": (scorecard_drops(settled, version, str(rel.get("previous") or ""))
                            if product == BRAIN else []),
        "start_crash": (start_crash(starts, version, since, until) if product == BRAIN
                        else _sibling_crash(items, product, since, until)),
    }
    signal = bool(obj["new_faults"] or obj["came_back"] or obj["scorecard_drops"]
                  or obj["start_crash"])
    over = now >= end or bool(rel.get("superseded_at"))
    obj["verdict"] = "regressed" if signal else ("healthy" if over else "pending")
    return obj


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(epoch or 0)))


def _sentence(obj: dict, product: str) -> str:
    """The human half: what was measured, in one paragraph."""
    parts = [f"{product} {obj['release']} was installed {obj['installed_at']}; "
             f"checked {obj['checked_at']}, in a {obj['window_hours']}-hour window."]
    if obj["verdict"] == "pending":
        parts.append("Nothing has gone wrong yet; the verdict is posted when the window ends.")
    elif obj["verdict"] == "healthy":
        parts.append("Healthy: no new faults, no fix came back, no rule got less "
                     "right and it started cleanly.")
    else:
        parts.append("Regressed:")
    lines = [" ".join(parts)]
    if obj["start_crash"]:
        lines.append(f"- {product} restarted repeatedly or did not finish starting.")
    for f in obj["new_faults"]:
        lines.append(f"- New fault: {f['what']}")
    for fp in obj["came_back"]:
        lines.append(f"- A fixed report came back: `{fp}`")
    for d in obj["scorecard_drops"]:
        lines.append(f"- `{d['producer']}` was right {d['after']}% of the time, "
                     f"down from {d['before']}% on the release before.")
    return "\n".join(lines)


def rows_for(data: dict, *, items: dict, settled: list, window_s: float,
             now: float) -> list[dict]:
    """One row per release still being watched, its final verdict included
    on the pass it is reached — after which the release files nothing
    more. Marks what it finalised in ``data``."""
    out = []
    for product, prod in (data.get("products") or {}).items():
        for version, rel in (prod.get("releases") or {}).items():
            if not isinstance(rel, dict) or rel.get("final"):
                continue
            obj = judge(rel, product=product, version=version, items=items,
                        settled=settled, starts=data.get("starts") or [],
                        window_s=window_s, now=now)
            final = obj["verdict"] != "pending"
            rel["verdict"] = obj["verdict"]
            rel["checked_at"] = now
            if final:
                rel["final"] = True
                rel["final_at"] = now
            row = {"key": f"canary:{slug(product)}:{version}", "where": "canary",
                   "what": f"{slug(product)} {version}", "detail": "",
                   "body": _sentence(obj, product), "canary": obj, "final": final}
            if product in PRODUCTS:
                row.update(product=product, product_version=version)
            out.append(row)
    return out


def pass_rows(version: str, settled: list | None = None,
              now: float | None = None) -> list[dict]:
    """The canary stream's pass: note that the loop is running (the start
    came up), read the installs off the queue's versions, and answer the
    rows. Never raises."""
    from . import upstream  # noqa: PLC0415 — upstream reads this module back
    now = now or time.time()
    try:
        note_ready(now)
        queue = upstream._load()
        data = load()
        versions = {BRAIN: str(version or queue.get("version") or "")}
        for name, ver in (queue.get("products") or {}).items():
            if name in PRODUCTS:
                versions[name] = str(ver or "")
        observe(data, versions, now)
        settings = load_settings()
        try:
            hours = int(settings.get("canary_window_hours") or 24)
        except (TypeError, ValueError):
            hours = 24
        rows = rows_for(data, items=queue.get("items") or {}, settled=settled or [],
                        window_s=max(1, hours) * 3600.0, now=now)
        save(data)
        return rows
    except Exception as exc:  # noqa: BLE001 — the tick must go on
        log.warning("devloop canary pass failed: %s", exc)
        return []


def recent(limit: int = RECENT) -> list[dict]:
    """The newest releases' verdicts, newest first: what ⚙ shows."""
    data = load()
    out = []
    for product, prod in (data.get("products") or {}).items():
        for version, rel in (prod.get("releases") or {}).items():
            if isinstance(rel, dict):
                out.append({"product": product, "release": version,
                            "verdict": str(rel.get("verdict") or "pending"),
                            "final": bool(rel.get("final")),
                            "installed_at": float(rel.get("installed_at") or 0)})
    out.sort(key=lambda r: -r["installed_at"])
    return out[:limit]
