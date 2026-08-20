"""What a whole show will look like, before a single packet goes out.

The Effects tab previews ONE effect on the bench. This is the same idea at
the scale of a show, and it exists so the editor can be visual: a floor
plan that shows the room at whatever instant the scrub bar is holding, and
a strip that shows the whole song at a glance.

Everything here goes through `compiler.script_actions` and
`effects.simulate` — the same two calls `compile_show` makes. There is no
second opinion about what a show does, which matters more here than
anywhere else in the add-on: a preview drawn from its own idea of the
script is a preview of that idea, and it would look right while the room
did something else.

Two shapes, for two questions:

* `window` — "what is happening at 2:14?" Frames at a real frame rate over
  a few seconds, enough to animate and to scrub inside without asking
  again.
* `overview` — "what does this show look like?" The whole song at about a
  column a second, one row per fixture, for the strip under the timeline.

Both cost the same walk. `window` is the one that runs on every scrub, so
it is the one that skips the frames it does not need (see `simulate`'s
`start_s`) rather than rendering four minutes to show two seconds.
"""
from __future__ import annotations

from . import compiler
from . import effects as fx

# A scrub window. Long enough that dragging inside it is free and the
# animation has somewhere to run; short enough that a Pi answers quickly
# and an idle tab is not holding a megabyte of frames.
WINDOW_S = 12.0
WINDOW_FPS = 15

# The overview strip. Columns are what the UI draws, not seconds: a
# 90-second track and a 6-minute one both get a strip the width of the
# panel, so the resolution is per-column and the seconds-per-column falls
# out of the duration.
OVERVIEW_COLUMNS = 240
OVERVIEW_FPS = 4


def _walk(script: dict, fixtures: list[dict], analysis: dict) -> dict:
    """The show as actions. Raises CompileError, same as compiling does."""
    return compiler.script_actions(script, fixtures, analysis)


def window(script: dict, fixtures: list[dict], analysis: dict, *,
           start_s: float = 0.0, span_s: float = WINDOW_S,
           fps: int = WINDOW_FPS) -> dict:
    """Frames covering [start_s, start_s + span_s].

    The window is clamped to the show — asking past the end returns the
    last moment rather than an error, because a scrub bar dragged to its
    right-hand end is a person looking at the end of the show, not a bug.
    """
    walked = _walk(script, fixtures, analysis)
    duration = walked["duration_s"]
    start = max(0.0, min(float(start_s), duration))
    span = max(0.5, min(float(span_s), WINDOW_S * 4))
    span = min(span, max(0.5, duration - start))

    frames = fx.simulate(walked["actions"], fixtures, duration_s=span,
                         fps=fps, start_s=start)
    return {
        "track_duration_s": round(duration, 3),
        "start_s": frames["start_s"],
        "span_s": round(span, 3),
        "fps": frames["fps"],
        "fixtures": frames["fixtures"],
        "frames": frames["frames"],
    }


def overview(script: dict, fixtures: list[dict], analysis: dict, *,
             columns: int = OVERVIEW_COLUMNS) -> dict:
    """The whole show as a low-resolution strip, one row per fixture.

    Simulated at a low frame rate and then thinned to `columns`, rather
    than simulated at `columns / duration` frames a second: `simulate`
    clamps its fps to a sane range (it is a preview, not a sampler), and a
    six-minute show would ask for less than one frame a second. Thinning
    afterwards keeps one simulator and one answer.
    """
    walked = _walk(script, fixtures, analysis)
    duration = max(0.5, walked["duration_s"])
    columns = max(24, min(1200, int(columns)))

    frames = fx.simulate(walked["actions"], fixtures, duration_s=duration,
                         fps=OVERVIEW_FPS)
    raw = frames["frames"]
    if not raw:
        return {"columns": [], "fixtures": frames["fixtures"],
                "duration_s": round(duration, 3), "seconds_per_column": 0.0}

    # Thin by index rather than by averaging: these are colours, and the
    # mean of red and green is a muddy yellow that is in the show nowhere.
    # A sampled column is a moment that really happened, across the whole
    # room at once, which is what makes it readable beside the scrub
    # preview rather than a different kind of picture.
    #
    # Per-fixture peaks were tried instead, on the theory that a strobe was
    # too short to survive point sampling. Measured, they showed LESS: a
    # strobe alternates bright and dark, and taking each light's brightest
    # sample in the span throws the dark half away. The case that prompted
    # it was not a sampling failure at all — the effect was landing on the
    # same instant as the drop's stab, which owns those lights there, so
    # the show really did look identical. Effects layer, and the last one
    # to name a light at a moment wins.
    step = len(raw) / float(columns)
    picked = [raw[min(len(raw) - 1, int(i * step))] for i in range(columns)]
    return {
        "columns": picked,
        "fixtures": frames["fixtures"],
        "duration_s": round(duration, 3),
        "seconds_per_column": round(duration / columns, 4),
    }


def timeline(script: dict, analysis: dict) -> dict:
    """The furniture the editor draws behind the strip.

    Scene boundaries come from the script (they are what an edit moves);
    sections, downbeats and bpm come from the analysis (they are what the
    song is, and no edit changes them). Downbeats are what a scene edge
    should snap to — the bar line is the musical edge a person means when
    they drag a scene, and there are few enough of them to send.
    """
    scenes = []
    for index, scene in enumerate(script.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        try:
            scenes.append({
                "index": index,
                "start": round(float(scene["start"]), 3),
                "end": round(float(scene["end"]), 3),
                "label": scene.get("mood") or scene.get("kind")
                or f"scene {index}",
                "kind": scene.get("kind"),
                "palette": scene.get("palette") or [],
                "brightness": float(scene.get("brightness", 0.5)),
                "effects": len(compiler.scene_effects(scene)),
            })
        except (KeyError, TypeError, ValueError):
            # A scene the compiler will refuse anyway. The editor's job is
            # to show what IS there, and a half-typed scene should not take
            # the timeline down with it — the save is where it gets named.
            continue

    sections = []
    for section in (analysis.get("sections") or []):
        if not isinstance(section, dict):
            continue
        try:
            sections.append({"start": round(float(section["start"]), 3),
                             "end": round(float(section["end"]), 3),
                             "kind": section.get("kind") or ""})
        except (KeyError, TypeError, ValueError):
            continue

    moments = []
    for moment in (script.get("moments") or []):
        if not isinstance(moment, dict):
            continue
        effect = moment.get("effect") if isinstance(moment.get("effect"), dict) \
            else moment
        try:
            moments.append({"t": round(float(moment.get(
                "t", effect.get("start", 0.0))), 3),
                "type": effect.get("type") or "",
                "name": effect.get("name") or effect.get("type") or "moment"})
        except (TypeError, ValueError):
            continue

    return {
        "scenes": scenes,
        "sections": sections,
        "moments": moments,
        "downbeats": [round(float(b), 3)
                      for b in (analysis.get("downbeats") or [])
                      if isinstance(b, (int, float))],
        "bpm": analysis.get("bpm"),
    }
