"""The access steward — who and what can reach this house.

Every other check reads whether the house WORKS. These read who can make
it do something: a lock a cloud speaker can open, a brAIn terminal
session still acting without asking after the switch was turned off, an
add-on running with the Supervisor's protection mode turned off, and an
address Home Assistant has banned after failed logins. None of them shows up as
anything looking wrong — the lock locks, the terminal works, the add-on
runs — which is exactly why nobody notices them.

The bar is the catalog's own: a check that fires on a healthy house is
the one people learn to ignore first, and a security check that cries
wolf is worse than most, because the one row that matters is read past
with the rest. So each rule fires only on a state somebody has to have
chosen and is worth a second look at, never on an ordinary house:

  * a partner with an admin account is ordinary — not a check; the users
    list is gathered for the weekly review instead, where a sentence can
    say "three people can administer this house" without filing it as a
    fault. The other half of the brief — a non-admin whose long-lived
    token reaches admin endpoints — is **not visible**: Core lists
    refresh tokens only for the user asking, so a rule about everybody
    else's would be a rule about nothing, and it is not written;
  * a lock exposed to Alexa or Google is a choice somebody made (Core
    never exposes a lock by default), so it is a finding;
  * protection mode off is a choice, so it is a finding;
  * a ban is something that HAPPENED, within a window.

Three new snapshot keys, each "I could not look" when its fetch failed —
`exposure` (Core's expose list), `posture` (this add-on's own options),
`ip_bans` (`/config/ip_bans.yaml`) — and `users`. No check reads `users`;
the weekly review does. `posture` carries the live permission switch and
any terminal session still acting under an old setting, and only the
second files a row. `collect` is the one function that fills them, and
`checks.snapshot.collect` calls it at one point inside its session.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

from ._util import House, domain_of, join_names, load_yaml_file, parse_ts

CONFIG_DIR = os.environ.get("BRAIN_HA_CONFIG_DIR", "/config")
IP_BANS_FILE = os.environ.get(
    "BRAIN_IP_BANS_FILE", os.path.join(CONFIG_DIR, "ip_bans.yaml"))
# The add-on's own options as the Supervisor wrote them for this container.
# Read rather than asked for: it is the file run.sh's `bashio::config` reads,
# so it is the posture the terminal is actually running under.
OPTIONS_FILE = os.environ.get("BRAIN_ADDON_OPTIONS_FILE", "/data/options.json")

# The keys `collect` fills. A snapshot built before them has none of them,
# and a check that needs one is skipped there — the honest answer on a
# frozen corpus entry.
SNAPSHOT_KEYS = ("users", "exposure", "posture", "ip_bans")

# The voice assistants that run somewhere other than this house. Core's
# own `conversation` is local and brAIn's voice refuses unlock anyway; a
# cloud assistant's reach is the internet's.
CLOUD_ASSISTANTS = {"cloud.alexa": "Alexa", "cloud.google_assistant":
                    "Google Assistant"}
# The domains a voice command can open the house with. A garage door is
# deliberately not here: "close the garage" is the commonest thing anybody
# exposes, and a rule that fired on it would fire on most houses that use
# a cloud speaker at all.
OPENING_DOMAINS = frozenset({"lock", "alarm_control_panel"})
# A ban older than this is history rather than something to look at.
BAN_WINDOW_DAYS = 14
# The options whose being ON is part of this add-on's posture. They ride in
# the weekly access digest: "Let brAIn act without asking" used to file a
# card every time it was on, which is a warning about the one setting a
# person turned on deliberately, with a label that already says what it
# does and what stays guarded. The weekly sentence can still say it is on.
POSTURE_FLAGS = ("dangerously_skip_permissions",)
# What IS worth a row: the switch is OFF, but a terminal session started
# while it was on is still running. Turning it off reaches a session only
# when one STARTS (ttyd re-attaches to the same tmux session), so that
# session goes on acting without asking after the person said ask. That is
# not a choice anybody made — it is the setting and the house disagreeing.
# Its own text, deliberately: the old "switched off" row was the one people
# answered Wrong to when they had turned the switch on on purpose, and that
# answer must not suppress this one.
STILL_ACTING_TEXT = ("A terminal session is still acting without asking "
                     "after the switch was turned off")
STILL_RUNNING = (
    "\"Let brAIn act without asking\" is off, but {n} started while it was "
    + "on {verb} still running, and {pronoun} still {act} without asking "
    + "first. The switch reaches a terminal session only when it starts.",
    "End it with /exit in the Terminal tab (a background task ends when it "
    + "finishes). The next session asks.")


# ---------------------------------------------------------------------------
# Gathering — inside the checks pass's one session
# ---------------------------------------------------------------------------

def read_options(path: str | None = None) -> dict | None:
    """This add-on's options, or None when the file cannot be read."""
    path = OPTIONS_FILE if path is None else path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_ip_bans(path: str | None = None) -> list[dict] | None:
    """`[{ip, banned_at}]` — an absent file is an EMPTY list, an unreadable
    one None.

    Core writes the file only once it has banned something, so a house
    with ip_ban on and nothing banned has no file at all: that is an
    answer ("nothing banned"), where a file that will not parse is not.
    """
    path = IP_BANS_FILE if path is None else path
    if not os.path.exists(path):
        return []
    data = load_yaml_file(path)
    if data is None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                empty = not fh.read().strip()
        except OSError:
            return None
        return [] if empty else None
    if not isinstance(data, dict):
        return None
    out = []
    for ip, row in data.items():
        when = row.get("banned_at") if isinstance(row, dict) else None
        out.append({"ip": str(ip)[:64], "banned_at": str(when or "")[:40]})
    return out


async def collect(session, snap: dict, mark) -> None:
    """Fill the four keys. Never raises; each fetch is its own attempt."""
    import ha_data

    try:
        users, exposure = await ha_data._ws_calls(session, [
            {"type": "config/auth/list"},
            {"type": "homeassistant/expose_entity/list"},
        ])
    except Exception as exc:  # noqa: BLE001 — every fetch is best effort
        users = exposure = {"ok": False, "error": str(exc)}

    rows = users.get("result") if users.get("ok") else None
    if isinstance(rows, list):
        snap["users"] = [_user_row(r) for r in rows if isinstance(r, dict)]
        mark("users", True)
    else:
        # `config/auth/list` is an admin command: a token that cannot run
        # it has not answered, which is not a house with no users.
        snap["users"] = []
        mark("users", False, str(users.get("error") or
                                 "Home Assistant did not list its users"))

    listed = exposure.get("result") if exposure.get("ok") else None
    table = listed.get("exposed_entities") if isinstance(listed, dict) else None
    if isinstance(table, dict):
        snap["exposure"] = {
            str(eid): {str(k): bool(v) for k, v in (settings or {}).items()}
            for eid, settings in table.items() if isinstance(settings, dict)}
        mark("exposure", True)
    else:
        snap["exposure"] = {}
        mark("exposure", False, str(exposure.get("error") or
                                    "Home Assistant did not list what it exposes"))

    options = read_options()
    posture = ({k: options.get(k) for k in POSTURE_FLAGS}
               if options is not None else None)
    # The permission switch as a terminal session starting NOW reads it —
    # the panel rewrites that file the moment the switch moves, where
    # options.json is what the Supervisor wrote when the add-on started —
    # plus anything still running that began with it on.
    import permission_mode

    live = permission_mode.published()
    if live is not None:
        posture = {**(posture or {}), "dangerously_skip_permissions": live}
    sessions = permission_mode.terminal_sessions()
    if posture is not None and sessions and sessions.get("acting"):
        posture["terminal_acting"] = sessions["acting"]
    snap["posture"] = posture if posture is not None else {}
    mark("posture", posture is not None,
         "" if posture is not None else "this add-on's options could not be read")

    bans = read_ip_bans()
    snap["ip_bans"] = bans or []
    mark("ip_bans", bans is not None,
         "" if bans is not None else "ip_bans.yaml could not be read")


def _user_row(row: dict) -> dict:
    """The fields the review reads, and nothing else — never credentials."""
    groups = [str(g) for g in (row.get("group_ids") or []) if g]
    return {
        "id": str(row.get("id") or "")[:64],
        "name": str(row.get("name") or row.get("username") or "")[:80],
        "admin": "system-admin" in groups,
        "owner": bool(row.get("is_owner")),
        "active": bool(row.get("is_active", True)),
        "system": bool(row.get("system_generated")),
        "local_only": bool(row.get("local_only")),
    }


# ---------------------------------------------------------------------------
# sec.lock_cloud_voice — a lock a cloud speaker can open
# ---------------------------------------------------------------------------

def cloud_exposed(snap: dict) -> list[tuple[str, list[str]]]:
    """`[(entity_id, [assistant names])]` for every opening-domain entity
    a cloud assistant is explicitly allowed to control. Shared with the
    review, so the sentence and the row cannot disagree."""
    out = []
    for eid, settings in sorted((snap.get("exposure") or {}).items()):
        if domain_of(eid) not in OPENING_DOMAINS:
            continue
        who = [label for key, label in CLOUD_ASSISTANTS.items()
               if settings.get(key) is True]
        if who:
            out.append((eid, who))
    return out


def lock_cloud_voice(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    hits = [(eid, who) for eid, who in cloud_exposed(snap)
            if house.exists(eid) and house.enabled(eid)
            and not house.excepted(eid, "sec.lock_cloud_voice")]
    if not hits:
        return []
    names = [f"{house.name(eid)} ({' and '.join(who)})" for eid, who in hits]
    return [{
        "text": "A lock or alarm can be controlled by a cloud voice assistant",
        "detail": f"{len(hits)}: " + join_names(names)
                  + ". Home Assistant never exposes these by default, so "
                    "somebody chose to — and anybody who can speak to that "
                    "assistant, or reach its account, can ask.",
        "fix": "Settings > Voice assistants > Expose: take them off that "
               "assistant, or make sure it asks for a PIN before it unlocks "
               "or disarms anything.",
        "severity": "warning",
        "fixable": False,
        "entity_id": hits[0][0],
    }]


# ---------------------------------------------------------------------------
# sec.brain_posture — a terminal session the switch did not reach
# ---------------------------------------------------------------------------

def brain_posture(snap: dict, now: float) -> list[dict]:
    posture = snap.get("posture") or {}
    # On by choice is no card (POSTURE_FLAGS): only a session that kept
    # acting after the switch went off is.
    if posture.get("dangerously_skip_permissions") is True:
        return []
    acting = posture.get("terminal_acting")
    if not (isinstance(acting, int) and not isinstance(acting, bool)
            and acting > 0):
        return []
    many = acting > 1
    detail, fix = STILL_RUNNING
    return [{
        "text": STILL_ACTING_TEXT,
        "detail": detail.format(
            n=f"{acting} terminal sessions" if many else "a terminal session",
            verb="are" if many else "is",
            pronoun="they" if many else "it",
            act="act" if many else "acts"),
        "fix": fix, "severity": "warning", "fixable": False,
        "entity_id": ""}]


# ---------------------------------------------------------------------------
# sec.addon_unprotected — protection mode off
# ---------------------------------------------------------------------------

def addon_unprotected(snap: dict, now: float) -> list[dict]:
    """Installed add-ons the Supervisor says are running unprotected.

    `protected` comes off each add-on's own `/info` and is folded into its
    row by the collector. A row WITHOUT it — an `/info` that did not
    answer, or a snapshot from before the field was folded — is "I could
    not look", never "unprotected", so only an explicit False fires.
    """
    addons = ((snap.get("supervisor") or {}).get("addons") or [])
    hits = sorted(str(a.get("name") or a.get("slug") or "an add-on")
                  for a in addons
                  if isinstance(a, dict) and a.get("installed", True) is not False
                  and a.get("protected") is False)
    if not hits:
        return []
    return [{
        "text": "Some add-ons run with Protection mode switched off",
        "detail": f"{len(hits)}: " + join_names(hits)
                  + ". Protection mode is what stops an add-on that asks for "
                    "full access to the machine from getting it; with it off, "
                    "that add-on can reach the host and every other add-on.",
        "fix": "Settings > Add-ons > (the add-on) > Info: turn Protection mode "
               "back on unless you know that add-on needs it off.",
        "severity": "info",
        "fixable": False,
        "entity_id": "",
    }]


# ---------------------------------------------------------------------------
# sec.login_bans — failed logins Home Assistant acted on
# ---------------------------------------------------------------------------

def recent_bans(snap: dict, now: float) -> list[dict]:
    out = []
    for row in snap.get("ip_bans") or []:
        if not isinstance(row, dict):
            continue
        ts = parse_ts(row.get("banned_at"))
        # A ban with no date is one Core wrote before it stamped them —
        # old, by construction, and not this fortnight's news.
        if ts is None or now - ts > BAN_WINDOW_DAYS * 86400:
            continue
        out.append({"ip": row.get("ip", ""), "ts": ts})
    return sorted(out, key=lambda r: r["ts"])


def login_bans(snap: dict, now: float) -> list[dict]:
    bans = recent_bans(snap, now)
    if not bans:
        return []
    shown = [f"{b['ip']} ({dt.datetime.fromtimestamp(b['ts'], tz=dt.timezone.utc).strftime('%-d %b')})"
             for b in bans]
    return [{
        "text": "Home Assistant banned an address after failed logins",
        "detail": f"{len(bans)} in the last {BAN_WINDOW_DAYS} days: "
                  + join_names(shown)
                  + ". The ban is working — this is so you know somebody "
                    "tried.",
        "fix": "If you don't recognise the address, check Settings > People "
               "for accounts you don't expect and turn on multi-factor "
               "login for the ones that can sign in from outside.",
        "severity": "info",
        "fixable": False,
        "entity_id": "",
    }]


CHECKS = [
    {"id": "sec.lock_cloud_voice", "title": "Locks a cloud speaker can open",
     "needs": ("states", "registry", "exposure"), "run": lock_cloud_voice},
    {"id": "sec.brain_posture",
     "title": "A terminal session the permission switch did not reach",
     "needs": ("posture",), "run": brain_posture},
    {"id": "sec.addon_unprotected", "title": "Add-ons with protection off",
     "needs": ("supervisor",), "run": addon_unprotected},
    {"id": "sec.login_bans", "title": "Addresses banned after failed logins",
     "needs": ("ip_bans",), "run": login_bans},
]


# ---------------------------------------------------------------------------
# The weekly review's digest — read by the panel, never filed
# ---------------------------------------------------------------------------

def review_digest(snap: dict, now: float) -> dict:
    """What the weekly review sentence is written from, deterministically.

    Counts and names only — never a credential, never a state value. A key
    the snapshot could not fill is reported as unread rather than as zero,
    because "nobody is an admin" and "I could not list the users" must
    not read alike in the one sentence a person gets.
    """
    available = snap.get("available") or {}
    house = House(snap)
    people = [u for u in (snap.get("users") or [])
              if isinstance(u, dict) and not u.get("system") and u.get("active")]
    exposure = snap.get("exposure") or {}
    exposed_counts: dict[str, int] = {}
    for settings in exposure.values():
        for key, on in settings.items():
            if on:
                exposed_counts[key] = exposed_counts.get(key, 0) + 1
    addons = ((snap.get("supervisor") or {}).get("addons") or [])
    privileged = []
    for a in addons:
        if not isinstance(a, dict):
            continue
        flags = [f for f in ("full_access", "docker_api", "host_network")
                 if a.get(f) is True]
        if a.get("protected") is False:
            flags.append("protection off")
        if flags:
            privileged.append({"name": str(a.get("name") or a.get("slug")),
                               "flags": flags})
    any_assistant_locks = sorted(
        house.name(eid) for eid, settings in exposure.items()
        if domain_of(eid) in OPENING_DOMAINS and any(settings.values()))
    return {
        "users": ({"people": len(people),
                   "admins": sorted(u["name"] for u in people if u.get("admin")),
                   "remote_admins": sum(1 for u in people if u.get("admin")
                                        and not u.get("local_only"))}
                  if available.get("users") else "unread"),
        "exposed": exposed_counts if available.get("exposure") else "unread",
        "opening_devices_exposed": (any_assistant_locks
                                    if available.get("exposure") else "unread"),
        "cloud_opening": [{"entity": house.name(e), "assistants": w}
                          for e, w in cloud_exposed(snap)],
        "addon_privileges": (privileged if available.get("supervisor")
                             else "unread"),
        "posture": ({k: bool((snap.get("posture") or {}).get(k))
                     for k in POSTURE_FLAGS}
                    if available.get("posture") else "unread"),
        "recent_bans": (len(recent_bans(snap, now))
                        if available.get("ip_bans") else "unread"),
        "token_visibility": ("Home Assistant lists long-lived tokens only for "
                             "the account asking, so whose tokens reach admin "
                             "endpoints cannot be read here."),
    }


# ---------------------------------------------------------------------------
# The weekly review — one sentence over the digest, checked before it stands
# ---------------------------------------------------------------------------

REVIEW_SYSTEM = """You review who and what can reach one Home Assistant house.

You are given a digest: how many people can log in and which are
administrators, what is exposed to which voice assistant, which add-ons run
with extra privileges, this add-on's own posture, recent login bans, and the
open security findings. Anything marked "unread" could not be read: say so
rather than treating it as nothing.

Write ONE plain sentence (two at most, under 60 words) a homeowner reads
once a week: the thing most worth their attention, or that nothing changed
and nothing needs doing. No greeting, no markdown, no lists. Never invent a
user, an add-on or a number that is not in the digest.

Answer with JSON only: {"sentence": "..."}
"""

REVIEW_SCHEMA = {"type": "object",
                 "properties": {"sentence": {"type": "string"}},
                 "required": ["sentence"]}
REVIEW_MAX = 400
REVIEW_MIN = 20


def review_sentence(answer) -> str:
    """The sentence as it may be shown, or '' when it may not.

    One sentence, no markdown, capped — and too short is not an answer,
    the brief's rule: a four-word review is worse than the silence it
    replaced, and the page says the review did not finish instead.
    """
    if not isinstance(answer, dict):
        return ""
    text = str(answer.get("sentence") or "")
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < REVIEW_MIN:
        return ""
    return text[:REVIEW_MAX]


__all__ = ["CHECKS", "REVIEW_SCHEMA", "REVIEW_SYSTEM", "review_sentence", "SNAPSHOT_KEYS", "collect", "review_digest",
           "cloud_exposed", "recent_bans", "read_ip_bans", "read_options"]
