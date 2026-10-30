"""The other BRUH add-ons, watched from outside and filed through this loop.

brAIn's own faults reach the development loop because brAIn measures
itself. GardenRX, BRUH Bambu Studio, BRUH Print, BRight, BRUH Minecraft and
Morph do not, and until this the only route from one of them breaking to a
fix was the owner noticing, opening a cloud session and describing it. Yet
brAIn already holds what a description would carry: it is the Supervisor's
admin, so it can read each add-on's state and its log, and Home Assistant's
own error log says what each add-on's integration raised.

So this stream needs nothing from the add-ons it watches. Every pass it
reads, per BRUH add-on that is installed:

- its Supervisor state, and files "stopped although set to start at boot";
- its log, and files each distinct error it finds (a traceback's last line,
  a line logged at ERROR), with the lines around it as evidence;
- Home Assistant's error log filtered to that add-on's integration;
- an optional outbox the add-on writes itself, in the row shape Morph
  already publishes (``/config/.bruh/devloop/<key>.json``), for faults only
  the add-on can see (a card that failed to draw).

Every row's ``where`` begins with the add-on's own name, carries the add-on
and its version, and is labelled ``devloop:<key>`` when filed: that is how
the cloud routine knows which directory of the repository the fix belongs
in, and how the house knows which release a "Fixed in GardenRX 0.1.1" is
waiting for.

The module is in two halves: `collect` reads (the Supervisor, the outboxes)
and never raises, and `rows` is pure over what it is handed, so a test hands
it a house. Nothing here redacts: `upstream.compose` does, over the whole
issue, the way it does for every stream.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from textclip import clip

log = logging.getLogger("brain.devloop.siblings")

# The BRUH add-ons this repository ships beside brAIn. ``key`` is the slug
# in the add-on's own config.yaml (the Supervisor puts the repository's
# hash in front of it); ``dir`` is where its code is in the repository,
# which the cloud routine reads off the label; ``domain`` is its
# integration's.
CATALOG: tuple[dict, ...] = (
    {"key": "gardenrx", "name": "GardenRX", "dir": "gardenrx/",
     "domain": "gardenrx"},
    {"key": "bruh-bambu-studio", "name": "BRUH Bambu Studio",
     "dir": "bruh-bambu-studio/", "domain": "bruh_bambu"},
    {"key": "bruh-print", "name": "BRUH Print", "dir": "bruh-print/",
     "domain": "bruh_print"},
    {"key": "bright", "name": "BRight", "dir": "bright/", "domain": "bright"},
    {"key": "bruh_minecraft_server", "name": "BRUH Minecraft",
     "dir": "bruh-minecraft-server/", "domain": "bruh_minecraft"},
    {"key": "bruh-cooking", "name": "BRUH Cooking", "dir": "bruh-cooking/",
     "domain": "bruh_cooking"},
)
PRODUCTS = tuple(s["name"] for s in CATALOG)

SUPERVISOR_URL = os.environ.get("BRAIN_SUPERVISOR_URL", "http://supervisor")
OUTBOX_DIR = Path(os.environ.get("BRAIN_SIBLING_OUTBOX", "/config/.bruh/devloop"))
FETCH_TIMEOUT_S = 15
# How much of a log is read, and how many distinct errors one add-on may
# file per pass: a log full of one repeating traceback is one issue, and a
# log full of twenty different ones is a release to read, not twenty
# issues.
LOG_BYTES = 400_000
MAX_LOG_ROWS = 3
MAX_INTEGRATION_ROWS = 3
MAX_OUTBOX_ROWS = 20
CONTEXT_BEFORE = 12
CONTEXT_AFTER = 3
SIGNATURE_CHARS = 150

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# A line's own clock and level, which make every occurrence look new.
_STAMP = re.compile(
    r"^\s*\[?(?:\d{4}-\d\d-\d\d[T ][\d:.,]+(?:Z|[+-]\d\d:?\d\d)?"
    r"|\d\d:\d\d:\d\d(?:[.,]\d+)?)\]?\s*")
# Upper case only: "Error fetching data" is the message, "ERROR" is the level.
_LEVEL = re.compile(r"^\s*\[?(?:ERROR|CRITICAL|FATAL|ERR)\]?\s*[:\-]?\s*")
_HEX = re.compile(r"\b(?:0x)?[0-9a-f]{8,}\b", re.I)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
# What counts as an error, in Python's logging, Node's and the s6 runner's
# words. WARNING is left out on purpose: warnings are what a healthy
# add-on says about a slow network, and a loop that filed them would be
# closed as noise until it was switched off.
_ERROR_LINE = re.compile(
    r"(?:^|\s|\[)(?:ERROR|CRITICAL|FATAL)(?:\]|:|\s)"
    r"|^\s*(?:Uncaught|Unhandled)\b"
    r"|^\s*\w+(?:\.\w+)*(?:Error|Exception)(?::|$)"
    r"|\bexited with code [1-9]"
    r"|\bsegmentation fault\b", re.I)
_TRACEBACK = re.compile(r"^\s*Traceback \(most recent call last\)")
_EXC_LINE = re.compile(r"^\s*[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)\b")


def spec_for(slug: str, name: str = "") -> dict | None:
    """The catalog row an installed add-on is, by its slug (with the
    repository's hash in front, or ``local_``) and its name; None for an
    add-on that is not one of ours."""
    slug = str(slug or "")
    for spec in CATALOG:
        if slug == spec["key"] or slug.endswith("_" + spec["key"]):
            if not name or name.strip().lower() == spec["name"].lower():
                return spec
    return None


def spec_by_name(product: str) -> dict | None:
    product = str(product or "").strip().lower()
    return next((s for s in CATALOG if s["name"].lower() == product), None)


# ---------------------------------------------------------------- reading

def _get(path: str, *, text: bool = False):
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise OSError("no Supervisor token in this process")
    headers = {"Authorization": f"Bearer {token}"}
    if text:
        headers["Accept"] = "text/plain"
    req = urllib.request.Request(f"{SUPERVISOR_URL}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:  # noqa: S310 — fixed host
        raw = resp.read(LOG_BYTES * 3 if text else 2_000_000)
    if text:
        return raw.decode("utf-8", "replace")[-LOG_BYTES:]
    body = json.loads(raw.decode("utf-8", "replace"))
    return body.get("data", body) if isinstance(body, dict) else body


def read_outbox(spec: dict, root: Path | None = None) -> list[dict] | None:
    """The rows an add-on published about itself, or None for no outbox.
    Only rows whose ``where`` names the add-on are kept: the cloud routes
    a fix by that name."""
    path = Path(root or OUTBOX_DIR) / f"{spec['key']}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return None
    out = []
    for row in data["rows"]:
        if not isinstance(row, dict):
            continue
        where, what = str(row.get("where") or ""), str(row.get("what") or "")
        if not where.lower().startswith(spec["name"].lower()) or not what:
            continue
        item = {"where": where[:80], "what": clip(what, 200),
                "detail": clip(str(row.get("detail") or ""), 600),
                "body": str(row.get("body") or "")[:6000]}
        if row.get("seen_at") is not None:
            item["seen_at"] = row.get("seen_at")
        out.append(item)
        if len(out) >= MAX_OUTBOX_ROWS:
            break
    return out


def collect(system_log: list | None = None, outbox_root: Path | None = None,
            get=None) -> dict:
    """What every installed BRUH add-on looks like right now.

    ``{"addons": [observation…], "unread": [add-on name…], "error": str}``.
    An observation is ``{spec, slug, info, log, log_error, system_log,
    outbox}``. ``unread`` names every catalog add-on this pass could not
    look at — not installed, or its info could not be read — because
    "could not look" must never let one of its issues be told it has not
    been seen since. ``system_log`` is the caller's (it is a WebSocket
    read). Never raises."""
    get = get or _get
    try:
        listing = get("/addons")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"addons": [], "unread": list(PRODUCTS),
                "error": f"could not list the add-ons: {exc}"}
    addons = (listing or {}).get("addons") if isinstance(listing, dict) else listing
    seen: dict[str, dict] = {}
    for row in addons or []:
        if not isinstance(row, dict):
            continue
        spec = spec_for(row.get("slug"), row.get("name"))
        if spec and spec["name"] not in seen:
            seen[spec["name"]] = {"spec": spec, "slug": str(row["slug"]), "row": row}
    out, unread = [], [s["name"] for s in CATALOG if s["name"] not in seen]
    for name, found in seen.items():
        slug = found["slug"]
        try:
            info = get(f"/addons/{slug}/info")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.info("devloop: could not read %s's info: %s", name, exc)
            unread.append(name)
            continue
        if not isinstance(info, dict):
            unread.append(name)
            continue
        text, log_error = "", ""
        try:
            text = get(f"/addons/{slug}/logs", text=True)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log_error = f"could not read the log: {exc}"
        out.append({"spec": found["spec"], "slug": slug, "info": info,
                    "log": text if isinstance(text, str) else "",
                    "log_error": log_error,
                    "system_log": system_log,
                    "outbox": read_outbox(found["spec"], outbox_root)})
    return {"addons": out, "unread": unread, "error": ""}


# ---------------------------------------------------------------- the rows

def signature(line: str) -> str:
    """One error line without what changes between occurrences: its clock,
    its level marker, long hex runs and uuids. Digits are left for the
    fingerprint, which folds them."""
    line = _ANSI.sub("", str(line or ""))
    line = _STAMP.sub("", line)
    for _ in range(2):
        line = _LEVEL.sub("", line)
    line = _UUID.sub("<id>", line)
    line = _HEX.sub("<hex>", line)
    return " ".join(line.split())[:SIGNATURE_CHARS]


def log_errors(text: str) -> list[dict]:
    """The distinct errors in a log, most frequent first:
    ``[{signature, count, context, last}]``. A traceback counts once, as
    its exception line; the context is the lines around its LAST
    occurrence, which is the one worth reading."""
    lines = [_ANSI.sub("", ln).rstrip() for ln in str(text or "").splitlines()]
    found: dict[str, dict] = {}
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        hit, at = "", i
        if _TRACEBACK.search(line):
            # The exception line closes the block: the first unindented
            # line after the frames that names an exception.
            j = i + 1
            while j < n and j - i < 200:
                if _EXC_LINE.match(lines[j]) and not lines[j].startswith((" ", "\t")):
                    hit, at = lines[j], j
                    break
                j += 1
            i = (at if hit else i) + 1
            if not hit:
                continue
        elif _ERROR_LINE.search(line):
            hit = line
            i += 1
        else:
            i += 1
            continue
        sig = signature(hit)
        if not sig:
            continue
        rec = found.setdefault(sig, {"signature": sig, "count": 0, "last": 0})
        rec["count"] += 1
        rec["last"] = at
        lo = max(0, at - CONTEXT_BEFORE)
        rec["context"] = "\n".join(lines[lo:at + 1 + CONTEXT_AFTER])
    return sorted(found.values(), key=lambda r: (-r["count"], -r["last"]))


def _integration_errors(entries, domain: str) -> list[dict]:
    """Home Assistant's own error log, for one integration: ERROR and
    above only, the way the add-on log is read."""
    out = []
    needles = (f"custom_components.{domain}", f"homeassistant.components.{domain}")
    path = f"custom_components/{domain}/"
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("level") or "").upper() not in ("ERROR", "CRITICAL"):
            continue
        name = str(entry.get("name") or "")
        source = " ".join(str(s) for s in entry.get("source") or [])
        if not (name.startswith(needles) or path in source):
            continue
        message = entry.get("message")
        first = message[0] if isinstance(message, list) and message else message
        sig = signature(str(first or ""))
        if not sig:
            continue
        out.append({"signature": sig, "count": int(entry.get("count") or 1),
                    "name": name, "source": source[:200],
                    "exception": str(entry.get("exception") or "")[:4000]})
    out.sort(key=lambda r: -r["count"])
    return out


def _fence(text: str) -> str:
    return "```\n" + str(text).replace("```", "'''") + "\n```"


def rows(collected: dict) -> list[dict]:
    """Every observation as issue rows. Pure."""
    out: list[dict] = []
    for obs in (collected or {}).get("addons") or []:
        spec, info = obs.get("spec") or {}, obs.get("info") or {}
        name = spec.get("name") or "?"
        version = str(info.get("version") or "")
        base = {"product": name, "product_version": version,
                "addon": spec.get("key", "")}
        head = (f"{name} {version or '(version unknown)'}, add-on slug "
                f"`{obs.get('slug')}`; its code is under `{spec.get('dir')}` "
                "in the BRUH-HA-Apps repository.")
        state, boot = str(info.get("state") or ""), str(info.get("boot") or "")
        errors = log_errors(obs.get("log") or "")
        if state and state != "started" and boot == "auto":
            tail = "\n".join((obs.get("log") or "").splitlines()[-30:])
            out.append({**base, "where": f"{name} · Add-on",
                        "what": "The add-on is not running although it is set to start at boot",
                        "detail": f"Supervisor state: {state}.",
                        "body": head + ("\n\nThe last lines of its log:\n\n" + _fence(tail)
                                        if tail.strip() else
                                        "\n\n" + (obs.get("log_error") or "Its log is empty."))})
        for err in errors[:MAX_LOG_ROWS]:
            out.append({**base, "where": f"{name} · Log",
                        "what": f"Logged: {err['signature']}",
                        "detail": (f"{err['count']} time{'s' if err['count'] != 1 else ''} "
                                   "in the add-on's current log."),
                        "body": head + "\n\nThe lines around the last time:\n\n"
                                + _fence(err.get("context") or err["signature"])})
        for err in _integration_errors(obs.get("system_log"), spec.get("domain", ""))[
                :MAX_INTEGRATION_ROWS]:
            body = head + (f"\n\nHome Assistant's log, logger `{err['name']}`"
                           + (f", at {err['source']}" if err["source"] else "") + ".")
            if err["exception"]:
                body += "\n\n" + _fence(err["exception"])
            out.append({**base, "where": f"{name} · Integration",
                        "what": f"Home Assistant logged: {err['signature']}",
                        "detail": f"{err['count']} times since Home Assistant started.",
                        "body": body})
        for row in obs.get("outbox") or []:
            out.append({**base, **row,
                        "body": head + ("\n\n" + row["body"] if row.get("body") else "")})
    return out


def products(collected: dict) -> dict:
    """``{product name: installed version}`` for every add-on looked at."""
    return {o["spec"]["name"]: str((o.get("info") or {}).get("version") or "")
            for o in (collected or {}).get("addons") or []
            if isinstance(o.get("spec"), dict)}


def status(collected: dict) -> list[dict]:
    """One line per BRUH add-on for the chat's read tool: what is
    installed, its state, and how many distinct errors each source holds."""
    out = []
    for obs in (collected or {}).get("addons") or []:
        spec, info = obs["spec"], obs.get("info") or {}
        errors = log_errors(obs.get("log") or "")
        integ = _integration_errors(obs.get("system_log"), spec["domain"])
        out.append({
            "addon": spec["name"], "slug": obs.get("slug"),
            "version": info.get("version"), "state": info.get("state"),
            "boot": info.get("boot"),
            "update_available": info.get("update_available"),
            "version_latest": info.get("version_latest"),
            "log_errors": [{"error": e["signature"], "count": e["count"],
                            "context": e.get("context", "")[-2500:]}
                           for e in errors[:5]],
            "log_error": obs.get("log_error") or "",
            "integration_errors": [{"error": e["signature"], "count": e["count"],
                                    "exception": e["exception"][-2500:]}
                                   for e in integ[:5]],
            "self_reported": len(obs.get("outbox") or []),
        })
    return out
