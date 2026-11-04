"""brAIn's four switches (⚙ › Features), and the one file that says them.

    /config/.brain/features.json
    {"morph": true, "personality": true, "learning_loop": true,
     "development_loop": false, "name": "Aria", "updated_at": 1700000000}

* **morph** — the Morph dashboard: the Home tab, and Morph's service in this
  container (`brain/morph/service`), which does nothing while it is off.
* **personality** — brAIn takes the name and personality the household gave
  it, everywhere a person reads it. Off, the stored personality is kept and
  nothing reads it (`personality.enabled`): not the name, not the persona or
  its growth, and not the voice (`personality.identity` answers "brAIn" and
  no voice), on brAIn's side and Morph's.
* **learning_loop** — everything that learns, in this house: the memory
  extractor after a conversation, voice's `remember_fact` auto-writes, the
  nightly reflect, the presence loop, Morph's learning and memory clean-up
  applied on its own. Nothing leaves the house. It is THE switch: the
  add-on option `learning` used to be a second gate over half of these and
  is now only this switch's default — migrated once (`learning_on`,
  `migrate_learning`), so a house that had `learning: false` starts with
  the switch off, and from then on only the switch decides. Every reader
  asks the file at call time (`learning_on` here, the same rule copied
  into the scripts that cannot import the panel), so flipping it needs no
  restart.
* **development_loop** — brAIn reports its own faults, redacted, to the
  private GitHub repository its code is fixed from. The one switch that
  sends anything out. It IS the devloop's `enabled` (devloop/__init__.py):
  stored there, shown here, so there is one switch and not two that can
  disagree.

This module is the file's one writer. Morph's service, the integration (the
sidebar entry, its title, the Home tab) and the CLI read it; each reads it
when it needs it, so a switch needs no restart. `name` is resolved here so a
reader outside the panel never has to know how a name is chosen.

A house that has never opened Features gets switches that keep what it had:
the dashboard on when `/config/morph/dashboard.yaml` exists (it had the
retired Morph app), the personality on when one is set. Those are decided once,
at the first `ensure`, and written down, so a later absence of either does
not quietly turn a switch the person set.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

import atomic_write
import personality

log = logging.getLogger("brain.features")

FILE = os.environ.get("BRAIN_FEATURES_FILE", "/config/.brain/features.json")
MORPH_DASHBOARD = os.environ.get("BRAIN_MORPH_DASHBOARD", "/config/morph/dashboard.yaml")

KEYS = ("morph", "personality", "learning_loop", "development_loop")
# Written beside the switches once the add-on option `learning` has been
# folded into `learning_loop`; from then on the option is never read again.
LEARNING_MIGRATED = "learning_from_option"
# What run.sh exports the add-on option `learning` as, for the migration.
# BRAIN_ASSIST_LEARNING is the switch as it stood at boot (the fallback of
# every reader that cannot read this file), never the option.
LEARNING_OPTION_VAR = "BRAIN_LEARNING_OPTION"
# The switches stored in this file; development_loop is the devloop's.
OWN = ("morph", "personality", "learning_loop")

_LOCK = threading.Lock()


def _devloop():
    import devloop  # noqa: PLC0415 — heavy, and only the development switch needs it
    return devloop


def _read(path: str | None = None) -> dict:
    try:
        with open(path or FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def option_learning() -> bool:
    """The add-on option `learning`, as run.sh exported it: the switch's
    default and nothing more. Unset (a dev checkout, a test) is on."""
    raw = os.environ.get(LEARNING_OPTION_VAR)
    if raw is None:
        raw = os.environ.get("BRAIN_ASSIST_LEARNING", "true")
    return str(raw).strip().lower() not in ("false", "0", "no", "off")


def _learning_value(stored: dict) -> bool:
    """`learning_loop` from a stored body. Before the migration a stored
    True (every house that ever opened Features has one, written as a
    default) still answers to an option somebody set to false: the person
    who switched learning off keeps it off."""
    value = stored.get("learning_loop")
    if not isinstance(value, bool):
        return option_learning()
    if stored.get(LEARNING_MIGRATED) is not True:
        return value and option_learning()
    return value


def learning_on(path: str | None = None) -> bool:
    """May anything in brAIn learn right now? Read at call time; never
    raises. The one answer the extractor, voice, reflect, presence, Morph
    and memory clean-up all follow."""
    try:
        return _learning_value(_read(path))
    except Exception:  # noqa: BLE001 — unreadable is the default
        return option_learning()


def migrate_learning(path: str | None = None) -> bool:
    """Fold the add-on option into the switch, once, and say the switch.

    run.sh calls this at boot (before anything that learns starts) and
    `ensure` at the panel's start. Only the learning key and the marker are
    written here: the other switches' defaults are `ensure`'s to decide."""
    target = path or FILE
    with _LOCK:
        stored = _read(target)
        value = _learning_value(stored)
        if stored.get(LEARNING_MIGRATED) is True \
                and stored.get("learning_loop") is value:
            return value
        if not os.path.isdir(os.path.dirname(target) or "."):
            return value
        try:
            atomic_write.write_json(target, {**stored, "learning_loop": value,
                                             LEARNING_MIGRATED: True})
        except OSError:
            log.exception("could not write %s", target)
    return value


def defaults() -> dict:
    """What a house that never chose gets: what it already had."""
    return {
        "morph": os.path.isfile(MORPH_DASHBOARD),
        "personality": personality.is_set(personality.load()),
        "learning_loop": option_learning(),
    }


def _development() -> bool:
    try:
        return _devloop().enabled()
    except Exception:  # noqa: BLE001 — an unreadable devloop store sends nothing
        return False


def load(path: str | None = None) -> dict:
    """Every switch as it is in force now. Never raises."""
    stored = _read(path)
    base = None
    out = {}
    for key in OWN:
        value = stored.get(key)
        if key == "learning_loop":
            value = _learning_value(stored)
        elif not isinstance(value, bool):
            base = base if base is not None else defaults()
            value = base[key]
        out[key] = value
    out["development_loop"] = _development()
    return out


def resolved(path: str | None = None) -> dict:
    """The file's whole body: the switches and the name they give."""
    out = load(path)
    name = personality.DEFAULT_NAME
    if out["personality"]:
        name = " ".join(str(personality.load().get("name") or "").split()) or personality.DEFAULT_NAME
    out["name"] = name
    return out


def publish(path: str | None = None) -> dict:
    """Write the resolved switches when they changed. Returns them."""
    target = path or FILE
    with _LOCK:
        now = resolved(target)
        stored = _read(target)
        if {k: stored.get(k) for k in (*KEYS, "name")} == now \
                and stored.get(LEARNING_MIGRATED) is True:
            return now
        if not os.path.isdir(os.path.dirname(target) or "."):
            return now  # never creates its own directory (a dev checkout)
        try:
            atomic_write.write_json(target, {**now, LEARNING_MIGRATED: True,
                                             "updated_at": int(time.time())})
        except OSError:
            log.exception("could not write %s", target)
    return now


def ensure(path: str | None = None) -> dict:
    """At startup: decide the defaults once, then publish."""
    return publish(path)


def refusal(changes) -> str:
    """Why ``changes`` cannot be saved, in a sentence, or "" when it can.
    The route answers with this rather than with an exception's text."""
    if not isinstance(changes, dict) or not changes:
        return "send the switches to change, as {name: true|false}"
    for key, value in changes.items():
        if key not in KEYS:
            return f"unknown switch: {str(key)[:40]}"
        if not isinstance(value, bool):
            return f"{key} must be true or false"
    return ""


def save(changes: dict, path: str | None = None) -> dict:
    """Set some switches. Raises ValueError for anything `refusal` would
    refuse."""
    why = refusal(changes)
    if why:
        raise ValueError(why)
    if "development_loop" in changes:
        _devloop().save_settings({"enabled": changes["development_loop"]})
    target = path or FILE
    with _LOCK:
        current = load(target)
        current.update({k: v for k, v in changes.items() if k in OWN})
        body = {k: current[k] for k in OWN}
        if os.path.isdir(os.path.dirname(target) or "."):
            # The marker rides with every save: the person has chosen now,
            # so the option must never be read over what they chose.
            atomic_write.write_json(target, {**_read(target), **body,
                                             LEARNING_MIGRATED: True})
    return publish(target)


def on(key: str, path: str | None = None) -> bool:
    if key == "learning_loop":
        return learning_on(path)
    return bool(load(path).get(key))


if __name__ == "__main__":  # run.sh: `python3 /opt/panel/features.py learning`
    import sys
    if sys.argv[1:] == ["learning"]:
        print("true" if migrate_learning() else "false")
    else:
        sys.stderr.write("usage: features.py learning\n")
        sys.exit(2)
