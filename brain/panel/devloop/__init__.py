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
Issues read/write, plus Contents read/write if the Screens stream is on
(the pictures are files in that repository). It reaches no other
repository, so a compromised box can do no more with it than post issues
and pictures in one repository nobody else can read. `github.check_repo` refuses a public
repository outright, because a report is evidence about a home.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import atomic_write

from .siblings import CATALOG

DATA_DIR =Path(os.environ.get("BRAIN_DEVLOOP_DIR", "/data/devloop"))
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
    # The Resident's own judgement, graded by what the household answered
    # (`outcomes.candidates`): a look that keeps raising what gets marked
    # wrong, or passing over what turns out to matter. The scorecard grades
    # the rules; this grades the model's calls, which is the half the loop
    # never carried. Off by default because the body quotes the reasons a
    # person typed when answering.
    "outcomes": {
        "label": "Judgement: where brAIn's own looks were wrong here, from what you answered",
        "cost": "free", "clears": True, "rolling": False,
        "default_on": False, "default_hours": 24},
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
    # brAIn photographing its own panel, redacted, at a phone's width and a
    # laptop's, with the layout faults a script can measure. The pictures
    # go to the private repository with the issue; `devloop/screens.py`
    # says what is blanked and covered before anything is captured.
    "screens": {
        "label": "Screens: pictures of every BRUH panel and card, redacted, with the layout faults measured, once for each new release",
        "cost": "free", "clears": False, "rolling": True,
        "default_on": False, "default_hours": 168},
    # The one stream that reports what went RIGHT. Every other stream
    # carries a fault, a Wrong or a gap, so a cloud that reads only them
    # can only make brAIn quieter; this is what the household agreed with,
    # thanked and kept, as counts (`streams.liked`). Off by default with the
    # other streams drawn from what people did; nothing a person typed.
    "liked": {
        "label": "Liked: what this household agreed with, thanked and kept, as counts, so a fix does not remove it",
        "cost": "free", "clears": False, "rolling": True,
        "default_on": False, "default_hours": 24},
    # Morph — brAIn's dashboard (part of brAIn since 4.0) — keeps a ledger of its own
    # faults (a card that failed to draw, sections that overlapped, a request
    # it could not carry out) and publishes them for this stream to file. It
    # carries no second token, queue or cap: Morph's reports ride this loop's.
    "morph": {
        "label": "Morph: problems the Morph dashboard found in its own code",
        "cost": "free", "clears": True, "rolling": False,
        "default_on": True, "default_hours": 1},
    # The other BRUH add-ons — GardenRX, BRUH Bambu Studio, BRUH Print,
    # BRight, BRUH Minecraft, BRUH Cooking, BRUH Task Manager, BRUH Browser — watched from outside: each one's
    # Supervisor state, the errors in its log, what Home Assistant logged
    # about its integration, and anything it published about itself
    # (`devloop/siblings.py`). Needs nothing from the add-on it watches.
    "siblings": {
        "label": "Other BRUH add-ons: errors in GardenRX, Bambu Studio, Print, BRight, Minecraft, Cooking, Task Manager and Browser",
        "cost": "free", "clears": True, "rolling": False,
        "default_on": True, "default_hours": 1},
    # brAIn using what it can reach the way a person does: its own panels,
    # Morph, and each other BRUH app switched on in `WALK_APPS`, one run
    # per app. Every screen is opened through the read-only capture at a
    # phone's width and a laptop's, and what a person living here would
    # trip on is filed. Nothing it presses can reach the house.
    "walkthrough": {
        "label": "Walkthrough: brAIn uses its own screens, Morph and the apps switched on below like a person, and files what it finds (one Claude run per app)",
        "cost": "claude", "clears": False, "rolling": False,
        "default_on": False, "default_hours": 24},
    "look": {
        "label": "What do you want to fix?: your words, turned into an issue (one Claude run each)",
        "cost": "claude", "clears": False, "rolling": False,
        "default_on": True, "default_hours": 0},
    # The house's health after it installs a release, for the cloud's
    # automatic revert (`devloop/canary.py`): one rolling issue per release,
    # rewritten hourly through its window, its verdict posted at the end —
    # or at once on a regression. Measured, never a model; no review hold.
    "canary": {
        "label": "Canary: how this house runs on each new release, so a bad fix is reverted",
        "cost": "free", "clears": False, "rolling": True,
        "default_on": True, "default_hours": 1},
    # First looks that ended Wrong or missed, as candidate regression cases
    # for the corpus (`devloop/corpus.py`). Off by default, and only while
    # capture is on: it sends what a look was shown, redacted and aliased.
    "corpus": {
        "label": "Corpus: first looks that were wrong or missed here, as test cases (needs capture)",
        "cost": "free", "clears": False, "rolling": False,
        "default_on": False, "default_hours": 24},
}
# What the Walkthrough may look at, one switch each (`walks` in the
# settings): brAIn's own panels, Morph, and every other BRUH add-on the
# loop knows. A look is one Claude run, so an app nobody uses is not worth
# one a day: brAIn and Morph are on, every other app is off until the
# owner switches it on, and AUTOPILOT DOES NOT — it is the one thing
# autopilot leaves alone, because it spends tokens on an app the owner may
# not use. "Look now" (⚙ › Developer) is one look whatever the switch says.
WALK_APPS: dict[str, dict] = {
    "brain": {"name": "brAIn", "default_on": True},
    "morph": {"name": "Morph", "default_on": True},
    **{s["key"]: {"name": s["name"], "default_on": False} for s in CATALOG},
}
# The schedule choices, in hours. 0 is "only when asked" — Run now, the
# What do you want to fix? box and `brain devloop` still work.
HOURS_CHOICES = (0, 1, 3, 6, 12, 24, 168)
# The two daily caps, as (lowest, highest); None is no ceiling. Claude runs
# cost money, so they keep a cap. New issues do not (#797, the owner: "If
# there is an issue to send, just send it"): 0, the default, is NO limit,
# and every ready report goes on the next pass. A number the owner sets is
# kept, and past it a report waits for tomorrow rather than being dropped.
CAP_LIMITS = {"max_issues_per_day": (0, None), "max_runs_per_day": (0, 24)}
# Before #797 the issue cap defaulted to 10, and autopilot read it as at
# least 20 — which the panel then saved back. A stored 10 or 20 written
# before the marker below existed is one of those, not a number anybody
# chose, so it reads as no limit; a save writes the marker, and from then
# on every stored number is the owner's own.
OLD_ISSUE_CAPS = (10, 20)
ISSUE_CAP_MARK = "issue_cap_chosen"


def in_limits(value, limits: tuple) -> bool:
    """A whole number (never a bool) within (lowest, highest)."""
    lo, hi = limits
    return (isinstance(value, int) and not isinstance(value, bool)
            and value >= lo and (hi is None or value <= hi))


def limits_text(limits: tuple) -> str:
    lo, hi = limits
    return f"from {lo} to {hi}" if hi is not None else f"of {lo} or more"

# "Autopilot": the owner has handed brAIn's development to the loop. Every
# stream on, on these schedules, nothing waiting for a press, and caps no
# lower than these. Somebody who chose that should not tune eight switches
# to get it, nor find their reports sitting in a review queue they never
# open.
AUTOPILOT_HOURS = {"faults": 1, "scorecard": 24, "wrongs": 24, "outcomes": 24, "unmet": 24,
                   "snapshot": 168, "gaps": 24, "ideas": 168, "design": 24,
                   "screens": 168, "liked": 24, "morph": 1, "siblings": 1,
                   "walkthrough": 24, "look": 0, "canary": 1, "corpus": 24}
# Only runs: the issue cap is no limit unless the owner sets one (#797),
# and autopilot leaves a number they set alone.
AUTOPILOT_CAPS = {"max_runs_per_day": 8}

DEFAULTS = {
    "enabled": False,
    "autopilot": False,
    "streams": {k: v["default_on"] for k, v in STREAMS.items()},
    "schedule": {k: v["default_hours"] for k, v in STREAMS.items()},
    "walks": {k: v["default_on"] for k, v in WALK_APPS.items()},
    "repo": "",
    # Every new report waits for a press until this is turned off. On by
    # default because the first few reports are how somebody learns what
    # "aliased" means on their own house.
    "review": True,
    # 0 is no limit (#797): every ready report goes on the next pass.
    "max_issues_per_day": 0,
    "max_runs_per_day": 4,
    # How long a declined, not-brAIn or duplicate verdict silences a report
    # (`upstream.STAND_DOWN_STREAMS`): it used to be for ever, and a wrong
    # decline silenced the house for good (plan 0.5). The same numbers as
    # `.claude/devloop.json`, which the house never reads: it is the cloud's.
    "stand_down_days": 90,
    # How long after an install the canary watches (`devloop/canary.py`).
    "canary_window_hours": 24,
    # The GitHub account the house's token files as, when the owner says.
    # Informational on the house; the cloud half checks authors by it.
    "house_login": "",
}
# The ranges the two numbers above may take.
NUMBER_LIMITS = {"stand_down_days": (1, 3650), "canary_window_hours": (1, 336)}
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?$")


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
    # Every stream, and NOT every app the Walkthrough may look at: `walks`
    # stays the owner's (see `WALK_APPS`).
    out["streams"] = {k: True for k in STREAMS}
    out["schedule"] = {k: AUTOPILOT_HOURS.get(k, v["default_hours"])
                       for k, v in STREAMS.items()}
    out["review"] = False
    out["max_runs_per_day"] = max(int(out.get("max_runs_per_day") or 0),
                                  AUTOPILOT_CAPS["max_runs_per_day"])
    return out


def _raw_settings() -> dict:
    # The two nested dicts copied too: with no settings file the early
    # return handed back DEFAULTS' own `streams`, and the first save then
    # switched a stream on for every later reader in the process.
    out = {**DEFAULTS, "streams": dict(DEFAULTS["streams"]),
           "schedule": dict(DEFAULTS["schedule"]),
           "walks": dict(DEFAULTS["walks"])}
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
    for name, on in (data.get("walks") or {}).items() \
            if isinstance(data.get("walks"), dict) else []:
        if name in WALK_APPS and isinstance(on, bool):
            out["walks"][name] = on
    for key, limits in {**CAP_LIMITS, **NUMBER_LIMITS}.items():
        value = data.get(key)
        if in_limits(value, limits):
            out[key] = value
    if data.get(ISSUE_CAP_MARK) is not True \
            and out["max_issues_per_day"] in OLD_ISSUE_CAPS:
        out["max_issues_per_day"] = 0
    login = data.get("house_login")
    if isinstance(login, str) and LOGIN_RE.match(login):
        out["house_login"] = login
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
        elif key == "walks":
            if not isinstance(value, dict):
                raise ValueError("walks must be an object")
            for name, on in value.items():
                if name not in WALK_APPS:
                    raise ValueError(f"unknown app: {name}")
                if not isinstance(on, bool):
                    raise ValueError(f"walks.{name} must be true or false")
                current["walks"][name] = on
        elif key in CAP_LIMITS or key in NUMBER_LIMITS:
            limits = {**CAP_LIMITS, **NUMBER_LIMITS}[key]
            if not in_limits(value, limits):
                raise ValueError(f"{key} must be a whole number "
                                 f"{limits_text(limits)}")
            current[key] = value
        elif key == "house_login":
            value = str(value or "").strip()
            if value and not LOGIN_RE.match(value):
                raise ValueError("house_login must be a GitHub account name")
            current[key] = value
        elif key == "repo":
            value = str(value or "").strip()
            if value and not REPO_RE.match(value):
                raise ValueError("repo must look like owner/name")
            current[key] = value
        else:
            raise ValueError(f"unknown setting: {key}")
    # Every stored issue cap from here on is the owner's own (or the
    # no-limit default), never the old default read as a choice.
    atomic_write.write_json(settings_file(), {**current, ISSUE_CAP_MARK: True})
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
