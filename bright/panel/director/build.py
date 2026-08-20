"""Build one track's show: pick the script tier, compile, persist.

The tier ladder lives here and nowhere else. `algorithmic` always works;
`claude` (arriving with the next phase) is tried when asked for and its
output is schema-validated — any failure lands on the algorithmic floor
per-track, logged, never fatal. `director_mode=claude` (strict) is the
one mode allowed to fail instead of downgrade, because the user asked it
to.
"""
from __future__ import annotations

import json
import logging
import time

import atomic_write
from analyzer import library
from stores import effect_presets, light_map

from . import choreographer, compiler

log = logging.getLogger("bright.director")


def fixtures_for_show(devices: dict[str, dict]) -> list[dict]:
    """The cast: mapped LIFX fixtures that are reachable right now, plus
    every mapped aux switch."""
    return light_map.lifx_fixtures(devices) + light_map.ha_fixtures()


def report_path(hash_hex: str):
    return library.SHOWS_DIR / hash_hex / "director.json"


def save_report(hash_hex: str, report: dict) -> None:
    """Persist how this show came to be, beside the show itself.

    Separate from show.json because it answers a different question — not
    "what does this show do" but "who wrote it and did the one you asked
    for actually run" — and because it has to survive being read back by a
    panel that is looking at a show it did not just compile.
    """
    try:
        atomic_write.write_json(report_path(hash_hex), report)
    except (OSError, ValueError):
        # The show is already saved; losing the note about how costs an
        # explanation and never the thing itself.
        pass


def load_report(hash_hex: str) -> dict | None:
    try:
        return json.loads(report_path(hash_hex).read_text())
    except (OSError, ValueError):
        return None


def build_show(hash_hex: str, devices: dict[str, dict], source: int,
               director_mode: str = "algorithmic",
               script_writer=None, vibe: str | None = None) -> dict:
    """Compile and persist. Returns the show. Raises ValueError/CompileError
    with a person-readable message when it cannot.

    `script_writer` is the pluggable Claude tier: a callable
    (analysis, fixtures) -> script dict, or None for algorithmic only.
    """
    analysis = library.load_analysis(hash_hex)
    if analysis is None:
        raise ValueError("track not analyzed — run the Library tab first")
    fixtures = fixtures_for_show(devices)
    if not fixtures:
        raise ValueError("no reachable fixtures — run Lab discovery, then "
                         "place your lights on the Light Map")

    # What happened while writing this show, kept rather than logged.
    #
    # A fallback used to be a WARNING line and nothing else: the show came
    # back tagged `algorithmic`, the panel showed no reason, and the only
    # record was in a log nobody reads until something is obviously wrong.
    # Every Claude-written show on a real install fell back for a week
    # without anyone noticing, because from the outside a fallback and a
    # success look the same — you get a show either way.
    report: dict = {"asked": director_mode, "used": "algorithmic",
                    "available": script_writer is not None,
                    "fell_back": False, "reason": None, "seconds": None,
                    "vibe": vibe}

    script = None
    if script_writer is not None and director_mode in ("auto", "claude"):
        started = time.monotonic()
        try:
            candidate = script_writer(analysis, fixtures, vibe=vibe) \
                if vibe else script_writer(analysis, fixtures)
            problems = choreographer.validate_script(candidate)
            if problems:
                # Named separately from a crash because they are a
                # different failure: Claude answered, and the answer was
                # not usable. That distinction is the first thing you want
                # when deciding whether to press the button again.
                raise ValueError("the script did not validate: "
                                 + "; ".join(problems[:5]))
            script = candidate
            report["used"] = "claude"
        except Exception as exc:  # noqa: BLE001 — the floor exists for exactly this
            report["fell_back"] = True
            report["reason"] = str(exc)
            if director_mode == "claude":
                raise ValueError(
                    f"the Claude director failed ({exc}) and director_mode "
                    "is 'claude' (strict) — fix the login or switch to "
                    "'auto'") from exc
            log.warning("Claude director failed (%s); using the "
                        "algorithmic choreographer for this track", exc)
        finally:
            report["seconds"] = round(time.monotonic() - started, 1)
    elif director_mode in ("auto", "claude"):
        report["reason"] = ("brAIn is not installed — the Claude director "
                            "runs through brAIn's task surface")

    if script is None:
        script = choreographer.write_script(analysis, fixtures)

    show = compile_and_save(hash_hex, script, analysis, fixtures, source)
    show["director"] = report
    save_report(hash_hex, report)
    return show


def compile_and_save(hash_hex: str, script: dict, analysis: dict,
                     fixtures: list[dict], source: int) -> dict:
    """Compile a script that already exists and persist both halves.

    The tier ladder above chooses a script; this is what happens to one
    afterwards — and it is also the whole of "save my edits", which is
    why it is a function rather than three lines inside build_show. A
    hand-edited script goes through the same compiler, the same rate
    budget and the same mirror as one the director wrote, because a
    script is a script whoever typed it.
    """
    # Saved effects are resolved HERE, once, before the script is compiled
    # or written — so what lands on disk is the effect in full.
    #
    # A show that stored the NAME would be a show that changes when
    # somebody edits the library: silently, and usually the night after
    # they edited it. The library is a place to copy from, not a layer a
    # saved show hangs off. This is also the one choke point every script
    # passes through — the director's, Claude's, and a hand-edited one —
    # so `use` works the same in all three without any of them knowing
    # the library exists.
    script = effect_presets.expand_script(script)
    show = compiler.compile_show(script, fixtures, analysis, source)
    title = (analysis.get("tags") or {}).get("title") or ""
    library.save_show(hash_hex, script, show, title)
    return show
