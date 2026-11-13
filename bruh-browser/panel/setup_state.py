"""The four setup steps, each read from the real state on disk.

Nothing here is a flag the panel set when somebody pressed a button: a step
is done when the thing it asks for is there.

1. The Claude extension is in Chrome's profile
   (`Default/Extensions/<id>/<version>/manifest.json`), at a version the docs
   accept (1.0.36 or later), and not switched off in the profile's
   preferences when they say so.
2. The extension is signed in to claude.ai. That lives inside the
   extension's own storage, which nothing outside it can read, so this step
   is proved by the Test (step 4) and said to be unknown until then — never
   claimed.
3. Claude Code is signed in with a Claude account: `~/.claude/.credentials.json`
   carries a `claudeAiOauth` token. An API key (in `~/.claude.json` or the
   environment) is called out, because it keeps the Chrome integration off.
4. The last Test errand, as it ended.

`HOME` is read at call time so a test can point it anywhere.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

EXTENSION_ID = "fcoeoabgfenejglbffodgkkbkcdhcgfn"
MIN_EXTENSION = (1, 0, 36)
NATIVE_HOST = "com.anthropic.claude_code_browser_extension.json"


def _home() -> Path:
    return Path(os.environ.get("HOME", "/data/home"))


def _version_tuple(text: str) -> tuple[int, ...]:
    out = []
    for part in str(text).split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def extension() -> dict:
    profile = _home() / ".config" / "google-chrome"
    root = profile / "Default" / "Extensions" / EXTENSION_ID
    versions = []
    try:
        for child in root.iterdir():
            manifest = _read_json(child / "manifest.json")
            if isinstance(manifest, dict) and manifest.get("version"):
                versions.append(str(manifest["version"]))
    except OSError:
        pass
    version = max(versions, key=_version_tuple) if versions else ""
    enabled = None
    for prefs_name in ("Secure Preferences", "Preferences"):
        prefs = _read_json(profile / "Default" / prefs_name)
        row = (((prefs or {}).get("extensions") or {}).get("settings") or {}).get(EXTENSION_ID)
        if isinstance(row, dict) and "state" in row:
            enabled = row.get("state") == 1
            break
        if isinstance(row, dict) and "disable_reasons" in row:
            enabled = not row.get("disable_reasons")
            break
    host = (profile / "NativeMessagingHosts" / NATIVE_HOST).is_file()
    if not version:
        status, detail = "not_yet", (
            "The Claude extension is not in this Chrome yet. It is normally "
            "installed by itself within a minute of Chrome starting; if it is "
            "not, open the Web Store page and press Add to Chrome.")
    elif _version_tuple(version) < MIN_EXTENSION:
        status, detail = "not_yet", (
            f"The Claude extension is version {version}; Claude Code needs "
            "1.0.36 or later. Chrome updates it by itself; open the extensions "
            "page and press Update to hurry it.")
    elif enabled is False:
        status, detail = "not_yet", ("The Claude extension is installed but switched "
                                     "off. Open the extensions page and switch it on.")
    else:
        status, detail = "done", f"Claude extension {version} is installed."
    return {"status": status, "detail": detail, "version": version,
            "enabled": enabled, "native_host": host}


def claude_code() -> dict:
    home = _home()
    creds = _read_json(home / ".claude" / ".credentials.json")
    oauth = (creds or {}).get("claudeAiOauth") if isinstance(creds, dict) else None
    config = _read_json(home / ".claude.json")
    api_key = bool(os.environ.get("ANTHROPIC_API_KEY")) or bool(
        isinstance(config, dict) and config.get("primaryApiKey"))
    if isinstance(oauth, dict) and oauth.get("accessToken"):
        plan = str(oauth.get("subscriptionType") or "").strip()
        detail = "Claude Code is signed in with a Claude account" + (
            f" ({plan} plan)." if plan else ".")
        if api_key:
            detail += (" An API key is also set, and an API key keeps the Chrome "
                       "integration off: sign in again with /login and choose your "
                       "Claude account.")
        return {"status": "done" if not api_key else "not_yet", "detail": detail,
                "plan": plan}
    if api_key:
        return {"status": "not_yet", "plan": "", "detail": (
            "Claude Code has an API key, which keeps the Chrome integration off. "
            "Open the sign-in window, type /login and choose your Claude account "
            "(a paid plan).")}
    return {"status": "not_yet", "plan": "", "detail": "Claude Code is not signed in."}


def steps(last_test: dict | None) -> list[dict]:
    """The four steps, in order, for the page."""
    ext = extension()
    code = claude_code()
    test = last_test or {}
    state = test.get("state")
    test_step = test.get("setup_step")
    if state == "done":
        signed = {"status": "done", "detail": "Proved by the last Test: the extension "
                                              "answered Claude Code."}
        tested = {"status": "done", "detail": test.get("answer") or "The Test passed."}
    elif state in ("failed", "needs_you", "stopped"):
        tested = {"status": "not_yet",
                  "detail": test.get("error") or test.get("needs_you")
                  or "The last Test did not finish."}
        signed = ({"status": "not_yet", "detail": tested["detail"]} if test_step == 2
                  else {"status": "unknown", "detail": (
                      "Cannot be read from outside the extension; the Test "
                      "proves it.")})
    elif state in ("queued", "running"):
        tested = {"status": "running", "detail": test.get("progress") or "Testing…"}
        signed = {"status": "unknown", "detail": "The Test running now will prove it."}
    else:
        tested = {"status": "not_yet", "detail": "Not tested yet."}
        signed = {"status": "unknown", "detail": (
            "Cannot be read from outside the extension; the Test proves it.")}
    return [
        {"n": 1, "title": "Install the Claude extension", **ext},
        {"n": 2, "title": "Sign the extension in to claude.ai", **signed},
        {"n": 3, "title": "Sign Claude Code in", **code},
        {"n": 4, "title": "Test", **tested},
    ]
