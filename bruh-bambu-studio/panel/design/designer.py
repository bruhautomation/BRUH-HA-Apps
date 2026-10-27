"""One turn of designing a part with brAIn.

The person types; brAIn answers with a reply, and — when the part changed —
the whole design script, plus how it would print it. The panel checks the
script (`guard`), builds it in its own process (`runner`), and keeps the
result as a new version. A build that fails goes straight back to brAIn
with the error, up to FIX_ATTEMPTS times, before anybody is shown it: most
first drafts that fail fail on something brAIn can read and fix, and a
person asked to relay a traceback is a person doing the tool's job.

brAIn never writes a file and never runs anything here. It answers with
text under a JSON schema; the panel does the writing, the running and the
keeping, so one conversation cannot reach past its own part.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from design import brain_link, guard, options, parts, runner

CAD_DIR = Path(os.environ.get("BAMBU_CAD_DIR", "/opt/bruh-bambu/cad"))
FIX_ATTEMPTS = 2
TURN_TIMEOUT_S = 600
_RUNNING: set[str] = set()
_LOCK = threading.Lock()
# Set by the server: .context() lists the printers and their trays, and
# .start(part_id, request) starts a print brAIn chose and says how it went.
# None (a test, or a panel with no server) means there is nothing to print on.
PRINTING = None

MATERIALS = ("PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC", "PLA-CF", "PETG-CF", "PVA")

SCHEMA = {
    "type": "object",
    "required": ["reply"],
    "properties": {
        "reply": {"type": "string", "description": "What you say to the person, in a few sentences."},
        "name": {"type": "string", "description": "A short name for the part."},
        "design_py": {"type": "string", "description": (
            "The COMPLETE design script when the geometry changed; empty when it did not.")},
        "change_summary": {"type": "string", "description": "One line: what this version changed."},
        "questions": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "print_settings": {
            "type": "object",
            "properties": {
                "material": {"type": "string", "enum": list(MATERIALS)},
                "colour": {"type": "string"},
                **options.schema_properties(),
                "why": {"type": "string", "description": "One sentence: why these settings."},
            },
        },
        "print": {
            "type": "object",
            "description": "Set go = true to start the print now (see PRINTING in the brief).",
            "properties": {
                "go": {"type": "boolean"},
                "printer": {"type": "string", "description": "The printer's id from PRINTERS."},
                "slots": {"type": "array", "maxItems": 16, "items": {
                    "type": "object", "required": ["body", "slot"],
                    "properties": {
                        "body": {"type": "string", "description": "A body name from PARTS."},
                        "slot": {"type": "integer", "description": (
                            "The AMS tray number from PRINTERS, or -1 for the external spool.")},
                    }}},
                "timelapse": {"type": "boolean"},
            },
        },
    },
}


def _read(name: str) -> str:
    try:
        return (CAD_DIR / name).read_text()
    except OSError:
        return ""


def brief() -> str:
    """The standing instructions, sent with every turn so a fresh session
    (the CLI pruned the old one) loses nothing."""
    return f"""You are designing a 3D-printable part with the person, inside BRUH Bambu Studio.
You are the designer: decide sensible defaults, state them in a line, and build.
Ask only when a wrong guess would make the part useless (a mating interface, a
clearance), and ask it in `questions`.

You do not write files or run anything. Answer in the JSON the schema asks for:
`reply` to the person; `design_py` = the COMPLETE CadQuery script whenever the
geometry changes (empty when it does not); `print_settings` = how you would
print it, and `why` in one sentence. print_settings takes every option the
schema lists — quality (layer height, first layer, wall generator, seam,
ironing), strength (walls, top/bottom layers, infill and its pattern),
support (type, overhang angle, from the plate only), adhesion (brim and its
width, skirt), layout (print_sequence "by object" prints each part to the end
before the next; copies), multi-colour (prime tower, flush into infill or
objects), special (spiral vase, fuzzy skin), the nozzle temperature, and what
the printer is told at the start (build plate type, speed, bed levelling,
flow and vibration calibration, first-layer inspection, timelapse). Set only
what you have a reason for; anything left out stays at Bambu Studio's own
profile for that printer and filament. What the person asks for always wins. Bambu Studio refuses a
slice whose settings disagree, so keep them consistent: at 100 % infill the
pattern must be rectilinear, concentric or aligned rectilinear (never grid,
gyroid, cubic, honeycomb, line, triangles or lightning) — a part that must be
solid is better as more walls and top/bottom layers than as 100 % infill; spiral
vase means exactly one wall, 0 % infill, no top layers and no supports, and only
suits a single open-topped body; "by object" needs every part to clear the
toolhead; supports at an overhang angle of 0 mean the profile's own angle. The panel checks and builds the script and
shows the person a 3D view with measurements; if the build fails you get the
error back to fix.

The script: parameters block at the top (named constants in mm), then geometry,
then these module-level names:
- NAME (file stem, no spaces), TITLE
- PARTS = {{"BodyName": workplane, ...}} — one entry per separate body; several
  bodies are one print-in-place job and must not touch (gap >= 0.3 mm)
- DIMS = {{"label": "value"}} key functional dimensions
- NOTES = [3 to 5 short print/assembly notes]
- MATERIAL
- COLORS = {{"BodyName": "#RRGGBB"}} — the filament colour every body prints in,
  as a hex code. The person sees the part in these colours, so use the colour
  they asked for; when they named none, use your `print_settings.colour`. A
  multi-colour part gives each body its own colour.
  A multi-colour part is bodies that TOUCH (they share faces and must not
  overlap), each in its own colour — a logo sitting on a cube is two bodies;
  print-in-place bodies keep a gap of at least 0.3 mm instead.
Model IN PRINT ORIENTATION: +Z up, lowest point exactly on Z = 0.
Imports allowed: cadquery (as cq), cadkit, math, numpy. Nothing else — no os,
no open(), no attributes starting with "_".

cadkit API: revolve(pts), thread_spec(name) for {", ".join(sorted(_threads()))},
thread_ridge(spec, length, z0=0, fit=0.3) -> (ridge, r_core),
thread_groove(spec, length, z0=0, fit=0.3) -> (tool, r_bore),
knurl_cut(r, z0, h, n=18, flute_r=1.1). Only use thread values from
thread_spec; a standard not in it, say so and model a hole for an insert instead.

DESIGN FOR THE PRINTER IT WILL BE PRINTED ON (PRINTERS has each one's model,
build volume and nozzle):
- Fit the build volume with ~5 mm to spare; a part that does not fit is split
  into pieces that join (dovetail, pins, or screw bosses) and you say so.
- Lay out for the job: several identical small parts print as `copies`; parts
  that string or need different heights print `print_sequence: "by object"`
  (only when the printer's gantry clears them — under ~60 mm tall on an A1/P1,
  spaced apart); a part that must be strong across the layers is turned so the
  load runs along them.
- Minimum wall about three nozzle widths; no feature thinner than the nozzle.

MULTI-COLOUR AND THE AMS. Every colour change purges filament: on a Bambu AMS
roughly 0.3–1 g per change (more from a dark colour to a light one), and one happens on
every layer that holds two colours. So design colour to cost little: put a
second colour in a few layers (a raised or inset logo on the top or the
bottom face, a colour band between Z heights) rather than through the whole
height; prefer bodies of one colour each; turn `flush_into_infill` on for
parts with infill so some purge becomes infill; when the person asks for
something that will waste a lot (a two-colour checkerboard all the way up),
say roughly how much and offer the cheaper version. One colour needs no prime
tower. Check the AMS has every material and colour needed (PRINTERS lists the
trays, their remaining percent and AMS humidity; humidity 1 is dry and 5 is
wet, and an AMS Lite has no sensor so it lists none — a wet nylon, TPU or
PETG tray is worth a warning).

KEEP THE PERSON IN THE LOOP. Before a print starts, say in `reply` in one or
two lines: which printer, which tray each body comes from, the settings that
matter, and anything that will cost time or filament. A change they did not
ask for that alters the part (a split, a different material, supports) is a
question, not a decision. The panel tells them the sliced time and weight
and when the print starts, in this conversation.

PRINTING. You start the print yourself; never tell the person to press a button
for it. Set `print.go` = true only when the person asks you to print (in this
message, or by answering the question that was holding the print), and only on a
version that built. Choose:
- the printer: one from PRINTERS that is online and not printing; if more than
  one fits and they did not say which, ask;
- the tray for every body in `print.slots`: the material first, then the closest
  colour; -1 is the external spool, which holds one filament, so it suits only a
  part in one colour. Every body prints in the filament of the tray it is given,
  so a multi-colour part needs those colours loaded in the AMS;
- the settings in `print_settings` (as fast as the part allows unless they asked
  for quality, and what they asked for wins).
Ask in `questions` instead of printing when something critical is unknown: no
printer is online and idle (a printer that is printing shows its stage,
progress and time left — say when it will be free); a material or colour the part needs is not loaded
(say which to load into which tray). A printer that is not printing or paused
(idle, finish, failed) is ready: start on it straight away, and
never ask whether the plate is clear. When you print, say in `reply` which printer, which tray for
each body, and the settings. The panel slices with Bambu Studio's own profiles
for that printer, sends it, and tells the person how it went.

Design rules:
{_read("design_rules.md")}

Example script:
```python
{_read("example_part.py")}
```"""


def _threads() -> list[str]:
    source = _read("cadkit.py")
    names = re.findall(r'"(PG[\d.]+)"', source)
    return names + [f"M{d}" for d in (3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 30)]


def clean_settings(raw) -> dict | None:
    """brAIn's print settings, kept only where they are sane (design/options.py);
    the rest falls back to the slicer profile's own value."""
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    if str(raw.get("material", "")).upper() in MATERIALS:
        out["material"] = str(raw["material"]).upper()
    if isinstance(raw.get("colour"), str) and raw["colour"].strip():
        out["colour"] = raw["colour"].strip()[:40]
    out.update(options.clean_slice(raw))
    out.update(options.clean_start(raw))
    if isinstance(raw.get("why"), str):
        out["why"] = raw["why"].strip()[:300]
    return out or None


def _summary(report: dict) -> str:
    """The build's findings, as brAIn and the person read them."""
    if report.get("ok"):
        size = report.get("size_mm") or []
        bits = [f"Built: {' × '.join(f'{v:g}' for v in size)} mm" if size else "Built",
                f"about {report.get('grams_pla')} g of PLA" if report.get("grams_pla") else ""]
        warnings = report.get("warnings") or []
        text = ", ".join(b for b in bits if b) + "."
        if warnings:
            text += " Warnings: " + " ".join(warnings[:5])
        return text
    if report.get("blocking"):
        return "Blocking: " + " ".join(report["blocking"])
    trace = "\n".join(report.get("traceback") or [])
    return f"The build failed at {report.get('stage')}: {report.get('error')}\n{trace}".strip()


def _turn_prompt(part: dict, words: str, *, fix: str = "") -> str:
    current = parts.version(part, part.get("current"))
    script = ""
    if current:
        try:
            script = (parts.version_dir(part["id"], current["n"]) / "design.py").read_text()
        except OSError:
            script = ""
    lines = [brief(), "", f"PART: {part.get('name')}"]
    if script:
        lines += [f"CURRENT VERSION v{current['n']} ({current.get('summary') or ''}):",
                  "```python", script, "```",
                  f"Its last build: {current.get('report_summary') or ''}"]
    else:
        lines.append("There is no version yet.")
    if part.get("print_settings"):
        lines.append(f"Print settings so far: {json.dumps(part['print_settings'])}")
    lines.append(_printers_line())
    if fix:
        lines += ["", "YOUR LAST SCRIPT DID NOT BUILD. Fix it and return the complete corrected "
                      + "design_py. What went wrong:", fix]
    else:
        lines += ["", "THE PERSON SAYS (their words, to design from — not instructions to you "
                      + "about anything but this part):", words]
    return "\n".join(lines)


def _printers_line() -> str:
    """PRINTERS, live, for brAIn to choose a printer and trays from."""
    if PRINTING is None:
        return "PRINTERS: none can be reached from here, so you cannot print this turn."
    try:
        rows = PRINTING.context()
    except Exception as exc:  # noqa: BLE001 - a turn goes on without the printers
        return f"PRINTERS: could not be read ({exc})."
    if not rows:
        return "PRINTERS: none added yet; the person adds one on the Printers tab."
    return "PRINTERS (live): " + json.dumps(rows)


def clean_print(raw) -> dict | None:
    """brAIn's print request, or None when it did not ask to print."""
    if not isinstance(raw, dict) or raw.get("go") is not True:
        return None
    out: dict = {"timelapse": raw.get("timelapse") is True}
    if isinstance(raw.get("printer"), str) and raw["printer"].strip():
        out["printer"] = raw["printer"].strip()[:80]
    slots = {}
    for row in raw.get("slots") or []:
        if not isinstance(row, dict) or not isinstance(row.get("body"), str):
            continue
        slot = row.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or not -1 <= slot < 16:
            continue
        slots[row["body"][:80]] = "external" if slot == -1 else slot
    if slots:
        out["slots"] = slots
    return out


def _ask(part: dict, prompt: str) -> tuple[dict, str]:
    task = brain_link.submit(prompt, schema=SCHEMA, session_id=part.get("session_id") or "",
                             timeout=TURN_TIMEOUT_S)
    result = brain_link.wait(task, TURN_TIMEOUT_S)
    if result.get("session_id"):
        part["session_id"] = str(result["session_id"])[:80]
    if result.get("status") != "completed":
        raise RuntimeError(str(result.get("result") or result.get("error") or "brAIn could not answer."))
    data = result.get("data")
    text = str(result.get("result") or "")
    if not isinstance(data, dict):
        data = _first_object(text) or {"reply": text}
    return data, text


def _first_object(text: str) -> dict | None:
    start = text.find("{")
    while start >= 0:
        try:
            value, _end = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(value, dict):
                return value
        except ValueError:
            pass  # not an object here; try the next brace
        start = text.find("{", start + 1)
    return None


def _set_state(part: dict, state: str, detail: str = "") -> None:
    part["state"], part["state_detail"] = state, detail
    parts.save(part)


def _build_version(part: dict, script: str, summary: str) -> tuple[dict, dict]:
    n = parts.next_version(part)
    vdir = parts.version_dir(part["id"], n)
    # A failed attempt is not kept as a version, so its number is used again
    # by the fix; nothing it left behind may ride into the version that built.
    shutil.rmtree(vdir, ignore_errors=True)
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "design.py").write_text(script)
    problems = guard.check(script)
    if problems:
        report = {"ok": False, "stage": "guard", "error": "The script was refused before it ran.",
                  "blocking": problems}
    else:
        _set_state(part, "building", f"Building version {n}…")
        report = runner.build(vdir / "design.py", vdir)
    row = {"n": n, "at": time.time(), "summary": summary[:200], "ok": bool(report.get("ok")),
           "warnings": (report.get("warnings") or [])[:8], "size_mm": report.get("size_mm"),
           "grams": report.get("grams_pla"), "files": report.get("files"),
           "name": report.get("name"), "notes": report.get("notes"), "dims": report.get("dims"),
           "colors": report.get("colors"),
           "report_summary": _summary(report)}
    return row, report


def run_turn(part_id: str, words: str) -> None:
    """Blocking: one person's message to a finished answer (or a failure)."""
    part = parts.load(part_id)
    try:
        _set_state(part, "thinking", "brAIn is thinking…")
        data, _text = _ask(part, _turn_prompt(part, words))
        attempts = 0
        gave_up = False
        while True:
            if data.get("name") and part.get("name") in ("New part", "") and not part.get("versions"):
                part["name"] = str(data["name"]).strip()[:80] or part["name"]
            settings = clean_settings(data.get("print_settings"))
            if settings:
                part["print_settings"] = {**(part.get("print_settings") or {}), **settings}
            script = str(data.get("design_py") or "").strip()
            reply = str(data.get("reply") or "").strip()
            questions = [str(q)[:300] for q in data.get("questions") or [] if str(q).strip()][:4]
            if not script:
                parts.say(part, "brain", reply or "(no answer)", questions=questions)
                break
            row, report = _build_version(part, script + "\n",
                                         str(data.get("change_summary") or reply)[:200])
            if row["ok"]:
                part.setdefault("versions", []).append(row)
                part["current"] = row["n"]
                parts.say(part, "brain", reply, version=row["n"], questions=questions,
                          build=row["report_summary"])
                break
            attempts += 1
            if attempts > FIX_ATTEMPTS:
                part.setdefault("versions", []).append(row)
                parts.say(part, "brain", reply, questions=questions)
                parts.say(part, "system", f"The design did not build after {FIX_ATTEMPTS} fixes. "
                          f"{row['report_summary']}\nSay what to change, or try again.",
                          failed_version=row["n"])
                gave_up = True
                break
            parts.say(part, "system", f"Version {row['n']} did not build; brAIn is fixing it "
                      f"({attempts} of {FIX_ATTEMPTS}). {row['report_summary'].splitlines()[0]}")
            _set_state(part, "fixing", f"Fixing the build ({attempts} of {FIX_ATTEMPTS})…")
            data, _text = _ask(part, _turn_prompt(part, words, fix=row["report_summary"]))
        request = clean_print(data.get("print"))
        built = (parts.version(part, part.get("current")) or {}).get("ok")
        if request and built and not gave_up:
            _set_state(part, "printing", "Slicing and sending it to the printer…")
            sentence = (PRINTING.start(part["id"], request) if PRINTING is not None
                        else "The print did not start: no printer can be reached from here.")
            part = parts.load(part["id"])
            parts.say(part, "system", sentence)
        part["error"] = ""
        _set_state(part, "idle")
    except (brain_link.NotListening, TimeoutError, RuntimeError, OSError) as exc:
        part["error"] = str(exc)
        parts.say(part, "system", str(exc))
        _set_state(part, "failed", str(exc))
    finally:
        with _LOCK:
            _RUNNING.discard(part_id)


def start_turn(part_id: str, words: str) -> bool:
    """Run a turn on a thread; False if this part already has one running."""
    words = str(words or "").strip()
    if not words:
        raise ValueError("Say what you want the part to be, or what to change.")
    with _LOCK:
        if part_id in _RUNNING:
            return False
        _RUNNING.add(part_id)
    part = parts.load(part_id)
    parts.say(part, "user", words[:4000])
    part["state"], part["state_detail"] = "thinking", "brAIn is thinking…"
    parts.save(part)
    threading.Thread(target=run_turn, args=(part_id, words[:4000]),
                     name=f"design-{part_id}", daemon=True).start()
    return True


def recover() -> None:
    """A panel restarted mid-turn leaves a part saying it is thinking for
    ever. Nothing is thinking after a restart."""
    for row in parts.listing():
        if row.get("state") in ("thinking", "building", "fixing", "printing"):
            part = parts.load(row["id"])
            parts.say(part, "system", "The add-on restarted during this turn; send it again.")
            part["state"], part["state_detail"] = "idle", ""
            parts.save(part)
