"""The development loop: an opt-in route from this house's faults to a
private GitHub repository, so brAIn can be fixed by the evidence its own
users run into.

**Off for everyone, and nothing here runs until somebody switches it on.**
It ships in every image so turning it on needs no install, and the panel
asks `enabled()` at call time — the way `insights_enabled()` is read — so
switching it off stops the next pass rather than the next restart. It is
deliberately not an add-on option: an option is documented to every user
on the Configuration tab, and this is a developer feature most people
should never have to read about. ⚙ › Diagnostics › Developer is where it
lives, and `brain/DEVLOOP.md` is the page that says it exists.

The four modules:

* `aliases` — stable stand-ins for entity ids, names and rooms, kept on
  this box only, so a report can say ``light.light_07`` rather than
  where somebody's bedroom is;
* `github` — the five REST calls the loop makes, against a base URL a
  test can point at a real local server;
* `upstream` — the queue: fingerprint each fault, compose the issue,
  hold it for review, send it, and note when it stops happening;
* this file — the settings and the token.

**The token lives in /data/secrets**, which `backup_exclude` already
leaves out of every Home Assistant backup, and is never handed back to
the browser: the panel answers whether one is set, never what it is.
It should be a fine-grained token scoped to ONE private repository with
Issues read/write and nothing else. The house can file reports; it can
never write code, so a compromised box can do no more with it than post
issues nobody else can read. `github.check_repo` refuses a public
repository outright, because a report is evidence about a home.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import atomic_write

DATA_DIR = Path(os.environ.get("BRAIN_DEVLOOP_DIR", "/data/devloop"))
TOKEN_FILE = Path(os.environ.get(
    "BRAIN_SECRETS", "/data/secrets")) / "devloop_github_token"

# owner/repo, GitHub's own rules: a user or org name, then a repository
# name of letters, digits, `.`, `_` and `-`. Checked before it becomes a
# URL path, because it arrives off the wire.
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
# A token is never shown, but it is checked for shape before it is kept, so
# a paste with a trailing newline or the word "token:" in front fails here
# rather than as a 401 an hour later.
TOKEN_RE = re.compile(r"^(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})$")

# What the loop may report, one switch and one schedule each. The master
# switch (`enabled`) gates all of them; a stream is a kind of evidence with
# its own privacy cost and its own spend, so each is chosen on its own.
#
#   free    — built from what brAIn already measured; costs no Claude run
#   claude  — one read-only analyst run per pass, counted against the cap
#   clears  — a fingerprint that stops appearing is told "not seen since"
#   rolling — ONE issue whose body is rewritten each pass (a scorecard per
#             release, the house's shape), never a new issue per pass
#
# `default_on` is what a house gets when it switches the loop on and has
# chosen nothing: the streams that carry nothing a person typed. The chat
# mining and the model streams are a further choice each.
STREAMS: dict[str, dict] = {
    "faults": {
        "label": "Faults: what is broken, from the fault list in ⚙ › Diagnostics",
        "cost": "free", "clears": True, "rolling": False,
        "default_on": True, "default_hours": 1},
    "scorecard": {
        "label": "Scorecard: how right each rule was, for this release",
        "cost": "free", "clears": False, "rolling": True,
        "default_on": True, "default_hours": 24},
    "wrongs": {
        "label": "Wrongs: rules you keep marking Wrong, with your reasons",
        "cost": "free", "clears": True, "rolling": False,
        "default_on": True, "default_hours": 24},
    "unmet": {
        "label": "Unmet requests: things you asked the chat for that brAIn could not do",
        "cost": "free", "clears": False, "rolling": False,
        "default_on": False, "default_hours": 24},
    "snapshot": {
        "label": "House shape: an aliased outline of this house, for UI audits",
        "cost": "free", "clears": False, "rolling": True,
        "default_on": False, "default_hours": 168},
    "gaps": {
        "label": "Gaps: where brAIn falls short on this house (one Claude run)",
        "cost": "claude", "clears": False, "rolling": False,
        "default_on": False, "default_hours": 168},
    "ideas": {
        "label": "Ideas: features this house would use (one Claude run)",
        "cost": "claude", "clears": False, "rolling": False,
        "default_on": False, "default_hours": 168},
    # brAIn reading what it actually SAID on this house — the cards, the
    # findings, what a look concluded — as somebody who has to live with it.
    # Faults and wrongs report what broke; nothing else reported a card that
    # is accurate and not worth reading, which is most of what makes a
    # product feel chaotic.
    "design": {
        "label": "Design review: what brAIn showed you, judged as a product (one Claude run)",
        "cost": "claude", "clears": False, "rolling": False,
        "default_on": False, "default_hours": 24},
    "look": {
        "label": "What do you want to fix?: your words, turned into an issue (one Claude run each)",
        "cost": "claude", "clears": False, "rolling": False,
        "default_on": True, "default_hours": 0},
}
# The schedule choices, in hours. 0 is "only when asked" — Run now, the
# What do you want to fix? box and `brain devloop` still work.
HOURS_CHOICES = (0, 1, 3, 6, 12, 24, 168)
# The two caps that keep an unattended loop from being an unattended bill
# or an unattended flood. A cap REFUSES rather than queueing: the next day
# is a fresh allowance, and a backlog filed all at once is the flood.
CAP_LIMITS = {"max_issues_per_day": (0, 50), "max_runs_per_day": (0, 24)}

# "Autopilot": the owner has handed brAIn's development to the loop. Every
# stream on, on these schedules, nothing waiting for a press, and caps no
# lower than these. Somebody who chose that should not tune eight switches
# to get it, nor find their reports sitting in a review queue they never
# open.
AUTOPILOT_HOURS = {"faults": 1, "scorecard": 24, "wrongs": 24, "unmet": 24,
                   "snapshot": 168, "gaps": 24, "ideas": 168, "design": 24,
                   "look": 0}
AUTOPILOT_CAPS = {"max_issues_per_day": 20, "max_runs_per_day": 8}

DEFAULTS = {
    "enabled": False,
    "autopilot": False,
    "streams": {k: v["default_on"] for k, v in STREAMS.items()},
    "schedule": {k: v["default_hours"] for k, v in STREAMS.items()},
    "repo": "",
    # Every new report waits for a press until this is turned off. On by
    # default because the first few reports are how somebody learns what
    # "aliased" means on their own house.
    "review": True,
    "max_issues_per_day": 10,
    "max_runs_per_day": 4,
}


def data_dir() -> Path:
    """Read at call time, so a test (or anything else) that moves
    `DATA_DIR` moves every file in the package with it."""
    return DATA_DIR


def settings_file() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    """The settings in force: what is stored, as autopilot reads it."""
    return _apply_autopilot(_raw_settings())


def _apply_autopilot(settings: dict) -> dict:
    """Autopilot is a READING of the stored settings, never a rewrite of
    them: switch it off and the streams, schedule and review you had are
    back exactly as they were."""
    if not settings.get("autopilot"):
        return settings
    out = dict(settings)
    out["streams"] = {k: True for k in STREAMS}
    out["schedule"] = {k: AUTOPILOT_HOURS.get(k, v["default_hours"])
                       for k, v in STREAMS.items()}
    out["review"] = False
    out["max_issues_per_day"] = max(int(out.get("max_issues_per_day") or 0),
                                    AUTOPILOT_CAPS["max_issues_per_day"])
    out["max_runs_per_day"] = max(int(out.get("max_runs_per_day") or 0),
                                  AUTOPILOT_CAPS["max_runs_per_day"])
    return out


def _raw_settings() -> dict:
    out = dict(DEFAULTS)
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    if isinstance(data.get("enabled"), bool):
        out["enabled"] = data["enabled"]
    if isinstance(data.get("review"), bool):
        out["review"] = data["review"]
    if isinstance(data.get("autopilot"), bool):
        out["autopilot"] = data["autopilot"]
    repo = data.get("repo")
    if isinstance(repo, str) and REPO_RE.match(repo):
        out["repo"] = repo
    out["streams"] = dict(DEFAULTS["streams"])
    for name, on in (data.get("streams") or {}).items() \
            if isinstance(data.get("streams"), dict) else []:
        if name in STREAMS and isinstance(on, bool):
            out["streams"][name] = on
    out["schedule"] = dict(DEFAULTS["schedule"])
    for name, hours in (data.get("schedule") or {}).items() \
            if isinstance(data.get("schedule"), dict) else []:
        if name in STREAMS and hours in HOURS_CHOICES:
            out["schedule"][name] = hours
    for key, (lo, hi) in CAP_LIMITS.items():
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) \
                and lo <= value <= hi:
            out[key] = value
    return out


def save_settings(changes: dict) -> dict:
    """Merge ``changes`` into the stored settings. Raises ValueError naming
    the field for anything that is not what it should be."""
    current = _raw_settings()
    for key, value in (changes or {}).items():
        if key in ("enabled", "review", "autopilot"):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
            current[key] = value
        elif key == "streams":
            if not isinstance(value, dict):
                raise ValueError("streams must be an object")
            for name, on in value.items():
                if name not in STREAMS:
                    raise ValueError(f"unknown stream: {name}")
                if not isinstance(on, bool):
                    raise ValueError(f"streams.{name} must be true or false")
                current["streams"][name] = on
        elif key == "schedule":
            if not isinstance(value, dict):
                raise ValueError("schedule must be an object")
            for name, hours in value.items():
                if name not in STREAMS:
                    raise ValueError(f"unknown stream: {name}")
                if hours not in HOURS_CHOICES or isinstance(hours, bool):
                    raise ValueError(f"schedule.{name} must be one of "
                                     f"{', '.join(map(str, HOURS_CHOICES))} hours")
                current["schedule"][name] = hours
        elif key in CAP_LIMITS:
            lo, hi = CAP_LIMITS[key]
            if not isinstance(value, int) or isinstance(value, bool) \
                    or not lo <= value <= hi:
                raise ValueError(f"{key} must be a whole number from {lo} to {hi}")
            current[key] = value
        elif key == "repo":
            value = str(value or "").strip()
            if value and not REPO_RE.match(value):
                raise ValueError("repo must look like owner/name")
            current[key] = value
        else:
            raise ValueError(f"unknown setting: {key}")
    atomic_write.write_json(settings_file(), current)
    return _apply_autopilot(current)


def enabled() -> bool:
    """Read at call time, so switching it off stops the next pass."""
    return bool(load_settings().get("enabled"))


def catalog() -> list[dict]:
    """The streams as the panel lists them, in order."""
    return [{"name": k, **v} for k, v in STREAMS.items()]


def stream_on(name: str) -> bool:
    """The master switch AND this stream's own."""
    s = load_settings()
    return bool(s.get("enabled")) and bool((s.get("streams") or {}).get(name))


def read_token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def token_set() -> bool:
    return bool(read_token())


def save_token(token: str) -> None:
    token = str(token or "").strip()
    if not TOKEN_RE.match(token):
        raise ValueError("that does not look like a GitHub token "
                         "(github_pat_… or ghp_…)")
    atomic_write.write_text(TOKEN_FILE, token, mode=0o600)


def forget_token() -> None:
    try:
        TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass  # already gone is what removing it asked for
