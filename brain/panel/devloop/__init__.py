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

# What the loop may report, one switch each. The master switch (`enabled`)
# gates all of them; a stream is a kind of evidence with its own privacy
# cost, so each is chosen on its own. Only streams that are BUILT are
# listed here — a switch that does nothing is a control asking to be
# understood. `docs/design/devloop.md` is the plan for the rest (real
# screenshots, a UX audit, code gaps, ideas for features).
STREAMS = {
    "faults": "What is broken: the fault list at the top of ⚙ › Diagnostics",
}

DEFAULTS = {
    "enabled": False,
    "streams": {"faults": True},
    "repo": "",
    # Every new report waits for a press until this is turned off. On by
    # default because the first few reports are how somebody learns what
    # "aliased" means on their own house.
    "review": True,
}


def data_dir() -> Path:
    """Read at call time, so a test (or anything else) that moves
    `DATA_DIR` moves every file in the package with it."""
    return DATA_DIR


def settings_file() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
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
    repo = data.get("repo")
    if isinstance(repo, str) and REPO_RE.match(repo):
        out["repo"] = repo
    streams = data.get("streams")
    out["streams"] = dict(DEFAULTS["streams"])
    if isinstance(streams, dict):
        for name, on in streams.items():
            if name in STREAMS and isinstance(on, bool):
                out["streams"][name] = on
    return out


def save_settings(changes: dict) -> dict:
    """Merge ``changes`` into the stored settings. Raises ValueError naming
    the field for anything that is not what it should be."""
    current = load_settings()
    for key, value in (changes or {}).items():
        if key in ("enabled", "review"):
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
        elif key == "repo":
            value = str(value or "").strip()
            if value and not REPO_RE.match(value):
                raise ValueError("repo must look like owner/name")
            current[key] = value
        else:
            raise ValueError(f"unknown setting: {key}")
    atomic_write.write_json(settings_file(), current)
    return current


def enabled() -> bool:
    """Read at call time, so switching it off stops the next pass."""
    return bool(load_settings().get("enabled"))


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
