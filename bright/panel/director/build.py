"""Build one track's show: pick the script tier, compile, persist.

The tier ladder lives here and nowhere else. `algorithmic` always works;
`claude` (arriving with the next phase) is tried when asked for and its
output is schema-validated — any failure lands on the algorithmic floor
per-track, logged, never fatal. `director_mode=claude` (strict) is the
one mode allowed to fail instead of downgrade, because the user asked it
to.
"""
from __future__ import annotations

import logging

from analyzer import library
from stores import light_map

from . import choreographer, compiler

log = logging.getLogger("bright.director")


def fixtures_for_show(devices: dict[str, dict]) -> list[dict]:
    """The cast: mapped LIFX fixtures that are reachable right now, plus
    every mapped aux switch."""
    return light_map.lifx_fixtures(devices) + light_map.ha_fixtures()


def build_show(hash_hex: str, devices: dict[str, dict], source: int,
               director_mode: str = "algorithmic",
               script_writer=None) -> dict:
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

    script = None
    if script_writer is not None and director_mode in ("auto", "claude"):
        try:
            candidate = script_writer(analysis, fixtures)
            problems = choreographer.validate_script(candidate)
            if problems:
                raise ValueError("; ".join(problems[:5]))
            script = candidate
        except Exception as exc:  # noqa: BLE001 — the floor exists for exactly this
            if director_mode == "claude":
                raise ValueError(
                    f"the Claude director failed ({exc}) and director_mode "
                    "is 'claude' (strict) — fix the login or switch to "
                    "'auto'") from exc
            log.warning("Claude director failed (%s); using the "
                        "algorithmic choreographer for this track", exc)

    if script is None:
        script = choreographer.write_script(analysis, fixtures)

    show = compiler.compile_show(script, fixtures, analysis, source)
    library.save_show(hash_hex, script, show)
    return show
