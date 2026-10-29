"""One look by brAIn: is this print going wrong?

brAIn is handed up to three pictures — the camera now, Bambu Studio's own
picture of the finished plate (what it should become), and the frame from
the previous look (how it was) — with what the code knows: which layer of
how many, how tall the part is so far, which moment of the print this is
and why it was chosen for a look. The answer is a schema the CLI checks
before it is sent, and the code checks it again: a verdict outside the
vocabulary, a confidence that is not a number, is no verdict.

What a verdict MEANS is decided here, not by the model: a failure becomes a
pause only above the sensitivity's confidence, anything less becomes a
warning, and a kind of problem somebody already told it to ignore on this
print is recorded and not raised. The model says what it sees; the code
says what that costs.

brAIn's run is read-only and is handed the pictures as pictures: it cannot
open a file, and nothing in a frame can make it act.
"""
from __future__ import annotations

PROBLEMS = ("none", "spaghetti", "detached", "not_sticking", "blob", "no_extrusion",
            "layer_shift", "warping", "knocked_over", "stringing", "other")
PROBLEM_WORDS = {
    "none": "nothing wrong", "spaghetti": "spaghetti", "detached": "a part come loose",
    "not_sticking": "the first layer not sticking", "blob": "a blob on the nozzle",
    "no_extrusion": "nothing coming out of the nozzle", "layer_shift": "a layer shift",
    "warping": "warping", "knocked_over": "a part knocked over", "stringing": "stringing",
    "other": "a problem",
}
VERDICTS = ("ok", "warning", "failure", "cannot_see")
PLATE = ("empty", "has_print", "unknown")

# How sure a failure must be before the printer is paused, and how sure
# anything must be before somebody is told, by the sensitivity chosen.
PAUSE_AT = {"low": 0.85, "medium": 0.75, "high": 0.65}
WARN_AT = {"low": 0.7, "medium": 0.55, "high": 0.4}
# Problems that are worth a word but never worth stopping a print for.
NEVER_PAUSE = {"stringing", "warping", "other"}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "confidence", "problem", "summary", "plate"],
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "problem": {"type": "string", "enum": list(PROBLEMS)},
        "summary": {"type": "string", "maxLength": 240},
        "plate": {"type": "string", "enum": list(PLATE)},
        "where": {"type": "string", "maxLength": 120},
    },
}

TIMEOUT_S = 240


def prompt(ctx: dict) -> str:
    """The question, with everything the code knows about this moment."""
    pics = ["Picture 1 is the printer's camera right now."]
    n = 2
    if ctx.get("expected"):
        pics.append(f"Picture {n} is Bambu Studio's render of the FINISHED plate — what this " +
                    "print becomes — drawn from a different angle than the camera, in the " +
                    "slicer's colours, without the brim, the purge line or the prime tower.")
        n += 1
    if ctx.get("earlier"):
        pics.append(f"Picture {n} is the camera at the previous look"
                    + (f", {ctx['earlier_ago']} ago" if ctx.get("earlier_ago") else "")
                    + (f" (layer {ctx['earlier_layer']})" if ctx.get("earlier_layer") else "")
                    + ", which was judged fine unless said otherwise below.")
    facts = []
    if ctx.get("printer"):
        facts.append(f"Printer: {ctx['printer']}" + (f" ({ctx['model']})" if ctx.get("model") else ""))
    if ctx.get("file"):
        facts.append(f"Printing: {ctx['file']}")
    if ctx.get("layer") is not None and ctx.get("total_layers"):
        facts.append(f"Layer {ctx['layer']} of {ctx['total_layers']}"
                     + (f", {ctx['progress']}% done" if ctx.get("progress") is not None else ""))
    if ctx.get("z_mm"):
        facts.append(f"The part should be about {ctx['z_mm']:g} mm tall so far"
                     + (f" of {ctx['height_mm']:g} mm" if ctx.get("height_mm") else ""))
    if ctx.get("filaments"):
        facts.append(f"Filament: {ctx['filaments']}")
    if ctx.get("stage"):
        facts.append(f"The printer says it is: {ctx['stage']}")
    if ctx.get("why"):
        facts.append(f"Why this look: {ctx['why']}")
    if ctx.get("history"):
        facts.append(f"Earlier looks this print: {ctx['history']}")
    if ctx.get("ignored"):
        facts.append(f"The owner said to ignore: {ctx['ignored']}")
    return "\n".join([
        "You are watching a Bambu Lab 3D printer for a failed print. Look at the pictures " +
        "and say whether the print is going wrong.",
        "",
        *pics,
        "",
        *facts,
        "",
        "Judge the print, not the picture. Expect and ignore: the toolhead and its cables " +
        "(often in front of the part), the purge line and the prime tower, a brim or skirt, " +
        "support material, the camera's wide-angle bend, reflections on the plate, and only " +
        "the bottom part of the object existing so far.",
        "The bed and the toolhead move while a printer prints (an A1's bed slides front to " +
        "back, every bed drops a little at each layer), so the plate may sit in a different " +
        "place than in an earlier picture and parts of the frame may be smeared: neither is " +
        "a problem with the print. Judge what is sharp enough to see.",
        "Look for: spaghetti (loose tangled strands); a part come loose, moved or knocked over; " +
        "a first layer not sticking or dragged; a blob of plastic on the nozzle; nothing being " +
        "laid down where the part should be growing (compare with the earlier picture); a layer " +
        "shift; corners lifting (warping); heavy stringing.",
        "",
        "If no picture came with this message, answer `cannot_see` and say so: never judge " +
        "a print you were not shown. " +
        "verdict: `failure` only when the print is ruined, or will be if it carries on " +
        "(spaghetti, a part come loose, a big blob, nothing coming out). `warning` when " +
        "something looks wrong but the print may still be fine, or you are unsure. `ok` " +
        "when it looks like a print going to plan. `cannot_see` when the picture does not " +
        "show the plate well enough to judge (covered, black, blurred, pointing elsewhere).",
        "confidence: how sure you are of that verdict, 0 to 1.",
        "problem: the main problem, or `none`.",
        "summary: one plain sentence for the owner's phone, under 30 words, saying what you " +
        "see (\"Spaghetti is building up behind the left part.\"). No advice, no hedging words.",
        "plate: `empty` if nothing at all is on the build plate, `has_print` if a print is on " +
        "it, `unknown` if you cannot tell.",
        "where: optional, where in picture 1 the problem is (\"left front corner\").",
    ])


def plate_prompt(ctx: dict) -> str:
    return "\n".join([
        "Picture 1 is the camera of a Bambu Lab 3D printer whose print finished"
        + (f" ({ctx['file']})" if ctx.get("file") else "") + ".",
        "Has the finished print been taken off? Say whether the build plate is empty.",
        "Ignore the purge line's leftover and the toolhead. A plate with any part, brim or " +
        "large piece left on it is not empty.",
        "Answer verdict `ok`, problem `none`, and plate `empty`, `has_print` or `unknown`; " +
        "summary one sentence; confidence how sure you are about the plate.",
    ])


def parse(data) -> dict | None:
    """brAIn's structured answer, checked; None when it is not one."""
    if not isinstance(data, dict):
        return None
    verdict = data.get("verdict")
    problem = data.get("problem") or "none"
    plate = data.get("plate") or "unknown"
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        return None
    if verdict not in VERDICTS or problem not in PROBLEMS or plate not in PLATE:
        return None
    if not 0 <= confidence <= 1:
        return None
    summary = " ".join(str(data.get("summary") or "").split())[:240]
    if not summary:
        summary = {"ok": "The print looks fine.", "cannot_see": "The camera does not show the print."
                   }.get(verdict, f"Looks like {PROBLEM_WORDS[problem]}.")
    if verdict == "ok" and problem != "none":
        problem = "none"
    return {"verdict": verdict, "confidence": round(confidence, 2), "problem": problem,
            "summary": summary, "plate": plate,
            "where": " ".join(str(data.get("where") or "").split())[:120]}


def decide(answer: dict, *, sensitivity: str = "medium", mode: str = "pause",
           ignored=(), no_pause=()) -> str:
    """What a checked verdict means: ok, watch, warning, failure (pause), ignored or blind.

    `ignored` are problems somebody said to ignore on this print: they are
    recorded and raise nothing. `no_pause` are problems somebody already
    called a false alarm after a pause: they warn, and do not pause again.
    """
    verdict, confidence, problem = answer["verdict"], answer["confidence"], answer["problem"]
    if verdict == "cannot_see":
        return "blind"
    if verdict == "ok":
        return "ok"
    pause_at = PAUSE_AT.get(sensitivity, PAUSE_AT["medium"])
    warn_at = WARN_AT.get(sensitivity, WARN_AT["medium"])
    if problem in ignored:
        return "ignored"
    if verdict == "failure" and confidence >= pause_at:
        if mode == "pause" and problem not in no_pause and problem not in NEVER_PAUSE:
            return "failure"
        return "warning"
    if confidence >= warn_at:
        return "warning"
    # Something that may be wrong, too unsure to tell anybody about: look
    # again soon rather than raise it or forget it.
    return "watch"
