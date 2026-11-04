"""The after picture: a fix to a screen, photographed once it is installed.

The owner's "is this fixed?" (`verify.py`) was the only judge of a fix to
how brAIn LOOKS, and with no person in the loop (plan section 0) nothing
may wait on it. So when a `look` or `unmet` report about a screen is fixed
in a release this house now runs, the house photographs the same screen
again — through the Screens stream's own capture, redacted on the page
before the picture and guarded the same way — puts the picture in the
reports repository beside the Screens pictures, and posts ONE comment on
the issue with a ``brain-after`` block:

    {"v":1,"fp","release","before":path|"","after":path,"digest"}

``before`` is the newest picture of that screen the Screens stream
uploaded on a release older than the fix, or "" when it never sent one;
``after`` the new one. The cloud's evaluator compares them against the issue's
``Done when:``. The owner's question is still asked and still posted; it is
an extra signal, never waited on.

Which screen a report is about is read off its own words, deterministically:
the longest screen label (or its last part, "Notifications" for "Settings ›
Notifications") that appears as whole words in the report's place and
title. A report naming no screen gets no picture, and is not guessed at.

State is `after.json` beside the queue: one record per report and fix
release, so a report is photographed once per fix. Never raises.
"""
from __future__ import annotations

import json
import logging
import re
import time

import atomic_write

from . import blocks, data_dir
from .upstream import product_of, running_at_least, running_for

log = logging.getLogger("brain.devloop")

STREAMS = frozenset({"look", "unmet"})
MAX_PER_PASS = 2
MAX_STATE = 300
VIEW = (390, 844, True, "light")


def state_file():
    return data_dir() / "after.json"


def load() -> dict:
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    if len(data) > MAX_STATE:
        keep = sorted(data.items(), key=lambda kv: float((kv[1] or {}).get("at") or 0))
        data = dict(keep[-MAX_STATE:])
    atomic_write.write_json(state_file(), data, mode=0o600)


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower())) + " "


def target_product(entry: dict) -> str:
    """Whose screens a report is about: Morph's when it names Morph (brAIn
    files Morph's reports, `streams.parse_reply`), else its own product."""
    product = product_of(entry)
    if product == "brAIn" and str(entry.get("where") or "").startswith("Morph"):
        return "Morph"
    return product


def match_screen(entry: dict, screens: list[dict]) -> dict | None:
    """The screen a report names, or None. ``screens`` are a capture
    target's ``{"slug", "label", ...}``. The longest name that appears as
    whole words wins, so "Settings › Notifications" beats "Settings"."""
    text = _words(f"{entry.get('where') or ''} {entry.get('what') or ''}")
    best, best_len = None, 0
    for scr in screens or []:
        label = str(scr.get("label") or "")
        names = {label, label.split("›")[-1].strip()}
        for name in names:
            w = _words(name).strip()
            if len(w) >= 3 and f" {w} " in text and len(w) > best_len:
                best, best_len = scr, len(w)
    return best


def due(items: dict, version: str, products: dict | None, state: dict) -> list[dict]:
    """Fixed screen reports whose fix this house runs and that have not
    been photographed for that fix."""
    out = []
    for entry in sorted((e for e in (items or {}).values() if isinstance(e, dict)),
                        key=lambda e: float(e.get("closed_at") or 0)):
        fixed_in = str(entry.get("fixed_in") or "")
        if (entry.get("stream") not in STREAMS or entry.get("verdict") != "fixed"
                or not fixed_in or not int(entry.get("issue") or 0)
                or running_at_least(running_for(entry, version, products), fixed_in) is not True):
            continue
        if (state.get(entry["fp"]) or {}).get("fixed_in") == fixed_in:
            continue
        out.append(entry)
    return out


def before_path(items: dict, product: str, screen: dict, fixed_in: str) -> str | None:
    """The newest uploaded Screens picture of ``screen`` at the phone view,
    taken on a release older than the fix; None when the house never sent
    one."""
    from . import screens as screens_mod  # noqa: PLC0415 — screens imports upstream
    from .upstream import _rolling_owner, version_tuple  # noqa: PLC0415
    best, best_v = None, None
    need = version_tuple(fixed_in)
    for entry in (items or {}).values():
        if (not isinstance(entry, dict) or entry.get("stream") != "screens"
                or _rolling_owner(entry) != product):
            continue
        ver = str(entry.get("version") or "")
        have = version_tuple(ver)
        if have is None or (need is not None and have >= need):
            continue
        uploaded = entry.get("uploaded") or {}
        for g in entry.get("gallery") or []:
            if (g.get("screen") == screen.get("label") and int(g.get("width") or 0) == VIEW[0]
                    and g.get("scheme") == VIEW[3]
                    and (uploaded.get(g.get("name")) or {}).get("sha") == g.get("sha")
                    and (best_v is None or have > best_v)):
                best = screens_mod.repo_path(ver, g["name"], product_of(entry))
                best_v = have
    return best


def comment_text(entry: dict, release: str, before: str | None, after: str,
                 after_url: str) -> str:
    # "" for no before picture: the block's fields are strings (the cloud
    # half types them), never null.
    obj = {"v": 1, "fp": str(entry.get("fp") or ""), "release": release,
           "before": before or "", "after": after}
    lines = [f"After the fix: this screen on {target_product(entry)} {release}, "
             "photographed on this house (redacted on the page before the picture)."]
    if after_url:
        lines += ["", f"![after]({after_url})"]
    return "\n".join(lines) + "\n\n" + blocks.make_block("after", obj)


async def run_pass(*, token: str, repo: str, items: dict, version: str,
                   products: dict | None, catalog: list[dict], capture,
                   now: float | None = None) -> int:
    """Photograph and post for the reports due. ``catalog`` is every capture
    target (`screens.own_target` and `server._screen_catalog`'s);
    ``capture(target, screen) -> (bytes, name)`` takes one redacted picture
    or raises. Answers how many comments were posted; never raises."""
    from . import github, screens as screens_mod  # noqa: PLC0415
    now = now or time.time()
    posted = 0
    try:
        state = load()
        for entry in due(items, version, products, state)[:MAX_PER_PASS]:
            fixed_in = str(entry["fixed_in"])
            product = target_product(entry)
            target = next((t for t in catalog or [] if t.get("product") == product), None)
            screen = match_screen(entry, (target or {}).get("screens") or [])
            rec = {"fixed_in": fixed_in, "at": now}
            if target is None or screen is None:
                state[entry["fp"]] = {**rec, "skipped": "no screen named"}
                continue
            try:
                data, name = await capture(target, screen)
            except Exception as exc:  # noqa: BLE001 — try again next pass
                log.info("devloop: could not photograph %s after the fix: %s",
                         screen.get("label"), exc)
                continue
            running = running_for(entry, version, products) or fixed_in
            path = screens_mod.repo_path(running, name, product_of(entry))
            url, err = github.put_file(token, repo, path, data,
                                       f"brAIn after: {screen.get('label')} on {running}")
            if err:
                log.info("devloop: could not upload the after picture: %s", err)
                continue
            before = before_path(items, product, screen, fixed_in)
            ok, err = github.comment(token, repo, int(entry["issue"]),
                                     comment_text(entry, running, before, path, url))
            if not ok:
                log.info("devloop: could not post the after picture: %s", err)
                continue
            state[entry["fp"]] = {**rec, "before": before, "after": path,
                                  "screen": screen.get("label"), "posted": True}
            posted += 1
        save(state)
    except Exception as exc:  # noqa: BLE001 — one pass, never the loop
        log.warning("devloop: the after pictures failed: %s", exc)
    return posted
