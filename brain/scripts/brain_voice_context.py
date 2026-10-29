#!/usr/bin/env python3
"""Where a voice request came from and who asked, as words in the turn.

Home Assistant hands every conversation agent the device and satellite a
request came from, the user who spoke, an `extra_system_prompt` an
automation may have set, and a chat log holding whatever was said before
brAIn was asked — and brAIn's conversation entity threw all of it away. So
"turn off the lights" said to the kitchen satellite had no "here" to
resolve against, a preference stated by voice had no owner, and a
`assist_satellite.start_conversation` flow lost both its question and its
instructions, leaving the person's "yes" to land in a session with no idea
what it was a yes to. The entity resolves those to plain facts (an area, a
floor, a person) and sends them on the request as `context`; this module is
the one place they are turned into words.

**It goes in the TURN, never the system prompt.** The pool pre-warms a
spare worker with a system prompt baked in and hands it to the next new
conversation only when the prompts match — a prompt that named the room
would match no spare, and every satellite command would pay the cold
start the pool exists to avoid. The turn is also where the facts belong:
the speaker and the room are true of this request, not of the agent.

Two readers and one writer of the words: the worker pool imports this
module (a sibling directory in the image and in the repo, the way it
imports `brain_exposed`), and the classic listener runs it as
``brain_voice_context.py preamble < context.json``. One implementation,
because two copies of what a voice turn is told about where it is would be
two answers the day one of them is edited.

Every field is data from another process — a satellite's name, an
automation's prompt, another agent's words — so each is capped and each
is a single line, and the block says in as many words that it is context
rather than something the person said. Never raises: a request whose
context cannot be read is a request with no context, which is every
request before this existed.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys

# Caps, in characters. A name is a name; a prompt from an automation may
# carry a paragraph and is worth a little more; a prior turn is one line.
NAME_MAX = 80
PROMPT_MAX = 1000
PRIOR_MAX = 300
PRIOR_TURNS = 6

_SPACE = re.compile(r"\s+")


def _line(value, cap: int) -> str:
    """One line of somebody else's text, capped, or "" for anything else."""
    if not isinstance(value, str):
        return ""
    text = _SPACE.sub(" ", value).strip()
    if len(text) > cap:
        text = text[: cap - 1].rstrip() + "…"
    return text


def person_id(context) -> str:
    """The speaker's person, as the id a fact's subject takes (`ben` for
    `person.ben`), or "". What the pool files a voice preference under."""
    if not isinstance(context, dict):
        return ""
    value = _line(context.get("person"), NAME_MAX)
    if value.startswith("person."):
        value = value[len("person."):]
    return value if re.fullmatch(r"[a-z0-9_]+", value or "") else ""


def preamble(context) -> str:
    """The block that goes in front of the person's words, or "".

    Empty for a request with no context, so a turn from a caller that sent
    none — `brain.send_prompt`, an older integration — is byte-for-byte the
    turn it always was.
    """
    if not isinstance(context, dict):
        return ""
    lines: list[str] = []

    area = _line(context.get("area"), NAME_MAX)
    floor = _line(context.get("floor"), NAME_MAX)
    device = _line(context.get("device"), NAME_MAX)
    if area:
        where = f"It came from {device} in the {area} area" if device \
            else f"It came from the {area} area"
        if floor:
            where += f" ({floor})"
        lines.append(
            f"{where}. \"Here\", \"this room\" and a room-less request like "
            f"\"turn off the lights\" mean the {area} area.")
    elif device:
        lines.append(f"It came from {device}, which has no area set in "
                     "Home Assistant, so ask which room if it matters.")

    speaker = _line(context.get("speaker"), NAME_MAX)
    pid = person_id(context)
    if speaker and pid and learning_on():
        lines.append(
            f"The speaker is {speaker} (person.{pid}). A preference they "
            f"state is theirs: remember it with remember_fact person=\"{pid}\".")
    elif speaker and pid:
        lines.append(f"The speaker is {speaker} (person.{pid}).")
    elif speaker:
        lines.append(f"The speaker is {speaker}.")

    narrowed = _line(context.get("narrowed_from"), 16)
    if narrowed:
        lines.append(
            "The speaker is not a Home Assistant administrator, so this turn "
            "runs at the voice-assistant level — only what is exposed to "
            "Assist — whatever this agent is set to. If they ask for more, "
            "say so plainly.")

    extra = _line(context.get("extra_system_prompt"), PROMPT_MAX)
    if extra:
        lines.append(
            "The automation that started this conversation gave these "
            f"instructions: \"{extra}\"")

    prior = context.get("prior")
    said = []
    if isinstance(prior, list):
        for item in prior[-PRIOR_TURNS:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            text = _line(item.get("text"), PRIOR_MAX)
            if role in ("user", "assistant") and text:
                who = "The person" if role == "user" else "Home Assistant"
                said.append(f"{who} said: \"{text}\"")
    if said:
        lines.append("Before this request, without you: " + " / ".join(said))

    if not lines:
        return ""
    return ("(Context for this request, from Home Assistant — not words the "
            "person said:\n- " + "\n- ".join(lines) + ")\n")


# ---------------------------------------------------------------------------
# The voice system prompt — one copy, for both voice paths
# ---------------------------------------------------------------------------
#
# The worker pool and the classic listener each carried a hand copy of this
# text and the two had drifted (one had the remember_fact line, one did
# not; the memory block was cut on a line in one and mid-character in the
# other). Both build it here now: the pool imports `system_prompt`, the
# classic listener runs `brain_voice_context.py system-prompt < spec.json`.
#
# Identity, tone and verbosity come from exactly ONE source — the agent's
# personality when one is set (with explicit precedence), the default style
# otherwise; the operational block is identity-free either way. Two "You
# are X" statements is what waters a personality down.

PERSONALITY_FRAME = (
    "PERSONALITY — this defines who you are, how you speak, and how verbose "
    "you are. It takes precedence over any tone or style implied by the "
    "instructions below:\n{custom}")

DEFAULT_STYLE = (
    "You are a helpful, efficient Home Assistant voice assistant. Answer in "
    "1-2 short sentences unless the user explicitly asks for detail.")

# What a voice turn is for, in the order a turn needs it. It used to open
# "FULL authorization to control all devices — never ask for permission or
# confirmation", directly above a capability block saying what this agent
# may NOT reach and a protected list that refuses; a refusal then read as a
# failure to work around rather than the household's answer. It also listed
# sixteen tool names the tools already describe, and left out the ones a
# voice turn most often has to go and find.
OPERATIONAL = """You run this home's Home Assistant by voice. Your replies are spoken aloud: say the result in a short sentence a person can hear — no lists, no markdown, no entity ids.
Act on ordinary requests straight away and confirm in a few words; you do not need to ask before turning things on or off, setting a level or running a scene. For anything that deletes, disables or removes something, say what you are doing as you do it.
When a tool refuses, that is the household's own setting (something they protected, or have not exposed to voice): say so in one sentence and do not try another way.
The past ("how cold did it get last night", "when did the garage open"): get_history for the last few days, get_statistics for longer. The future ("weather tomorrow"): get_weather_forecast — a weather entity's state is only the weather now.
{remember}Labels, the Minecraft server, the light show and the 3D printers have their own tools: print_label, minecraft_*, bright_show, bambu_design (make a part; to print it as well, say so in the description and it prints once built — say it is being made, never wait) and bambu_print. The garden's record is GardenRX: garden_log_harvest ("log 2 pounds of tomatoes"), garden_log_spray, garden_log_note, and garden_harvests for what was picked. The sous vide and the oven are BRUH Cooking: cooking_status ("is the water ready?", "how long is left?") and cooking_control (start, stop, continue — say the oven waits for Start on its panel). A camera answers only if the household has allowed brAIn to look at it; if it refuses, say so and do not try another camera."""

# The one line that depends on the add-on's `learning` switch: with it off,
# nothing a voice turn hears is filed, and a prompt asking for it would be
# asking the model for a call the household switched off.
REMEMBER_LINE = (
    'When the person states a lasting preference, a correction or a nickname '
    '("actually…", "we call X…", "always/never…"), call remember_fact in the '
    'same turn so it sticks.\n')


def learning_on() -> bool:
    """The add-on's `learning` switch, as run.sh exports it."""
    return os.environ.get("BRAIN_ASSIST_LEARNING", "true").lower() != "false"


TIMEZONE_LINE = (
    "The user's timezone is {tz}. Every user message starts with the "
    "current local time — answer times in that local timezone, never UTC.")

# The flag file both area-map writers leave beside the cache when the map
# was cut to fit (`AREA_MAP_CUT_FILE`). A map that said "current and
# complete" over a list missing rooms told the model not to search for the
# room it could not see. A file and not a marker line, because the
# exposure filter drops every line that is not `Area: ids`.
AREA_MAP_CUT_NAME = "area_map.cut"

MAP_BLOCK = """

Known areas and their controllable entity_ids ({completeness}):
{area_map}

Act on these entity_ids DIRECTLY with your control_* tools in your FIRST response — never call get_areas or get_all_states to verify an entity that is already listed.
For weather questions, call get_entity_state on a Weather entity above.
For anything not listed above, search with get_all_states (domain and name_filter arguments)."""

NO_MAP_BLOCK = """
For room/area requests (e.g. 'turn off the bedroom lights') call get_areas to resolve the room to entity_ids first.
If unsure of an entity_id, call get_all_states with a domain filter first."""

MEMORY_BLOCK = "\n\nKnown about this household (learned):\n{memory}"


def cut_on_line(text: str, limit: int) -> str:
    """At most `limit` bytes of `text`, ending on a whole line.

    A byte cut ends on half a fact — or half a UTF-8 character — and reads
    as a fact it is not.
    """
    data = (text or "").encode("utf-8")
    if len(data) <= limit:
        return text or ""
    cut = data[:limit].decode("utf-8", errors="ignore")
    return cut.rsplit("\n", 1)[0] if "\n" in cut else ""


# The household's own personality for brAIn (⚙ › Personality, the panel's
# `personality.py`), which stands in for DEFAULT_STYLE when an agent has no
# personality of its own. An agent's own still wins: it is the more specific
# choice, made on that agent. Kept short for a spoken reply either way.
HOUSEHOLD_FRAME = (
    "PERSONALITY — the household chose this for brAIn. Keep replies to 1-2 "
    "short spoken sentences unless asked for detail:\n{household}")


def _panel_dir() -> str:
    """Where the panel's modules are: the image's /opt/panel, or the repo's."""
    configured = os.environ.get("BRAIN_PANEL_DIR", "")
    if configured:
        return configured
    here = os.path.dirname(os.path.abspath(__file__))
    sibling = os.path.normpath(os.path.join(here, "..", "panel"))
    return sibling if os.path.isdir(sibling) else "/opt/panel"


def household_personality() -> str:
    """The household's personality as prompt lines, or "" (none set, or the
    panel's reader could not be found). Never raises.

    The panel's `personality` module is the one reader of that file, so it
    is borrowed rather than written down a second time; appended to the END
    of sys.path so it can never shadow a standard-library module.
    """
    path = _panel_dir()
    if path not in sys.path:
        sys.path.append(path)
    try:
        import personality  # noqa: PLC0415 — the panel's, found at call time
        return personality.prompt_block(personality.load(
            os.environ.get("BRAIN_PERSONALITY_FILE") or None))
    except Exception:  # noqa: BLE001 — no reader is no personality
        return ""


def system_prompt(custom: str = "", tz: str = "", area_map: str = "",
                  memory: str = "", capabilities: str = "",
                  partial: bool = False, learning: bool | None = None,
                  household: str | None = None) -> str:
    """The whole voice system prompt, from its parts. Pure but for the
    `learning` default, which reads the add-on's switch, and the `household`
    default, which reads the household's personality file."""
    custom = (custom or "").strip()
    learning = learning_on() if learning is None else learning
    operational = OPERATIONAL.replace("{remember}", REMEMBER_LINE if learning else "")
    if custom:
        prompt = PERSONALITY_FRAME.format(custom=custom) + "\n\n" + operational
    else:
        household = (household_personality() if household is None
                     else household).strip()
        prompt = (HOUSEHOLD_FRAME.format(household=household) + "\n\n" + operational
                  if household else DEFAULT_STYLE + "\n" + operational)
    if tz:
        prompt += "\n" + TIMEZONE_LINE.format(tz=tz)
    area_map = (area_map or "").rstrip()
    if area_map:
        prompt += MAP_BLOCK.format(
            area_map=area_map,
            completeness=("cut to fit — some rooms are not listed, so search "
                          "for one you cannot see" if partial else "complete"))
    else:
        prompt += NO_MAP_BLOCK
    if (memory or "").strip():
        prompt += MEMORY_BLOCK.format(memory=memory.rstrip())
    return prompt + (capabilities or "")


def _cli(argv: list[str]) -> int:
    """`preamble`: read a context object (or a whole request) on stdin and
    print the block. Prints nothing for anything it cannot read.

    `system-prompt`: read {custom, tz, area_map, memory, capabilities,
    partial} on
    stdin and print the voice system prompt — the classic listener's door
    to the text the pool imports.
    """
    verb = argv[0] if argv else ""
    if verb not in ("preamble", "system-prompt"):
        print("usage: brain_voice_context.py preamble|system-prompt < input.json",
              file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0 if verb == "preamble" else 1
    if verb == "system-prompt":
        if not isinstance(data, dict):
            return 1
        fields = {k: str(data.get(k) or "") for k in (
            "custom", "tz", "area_map", "memory", "capabilities")}
        cap = data.get("memory_max")
        if isinstance(cap, int) and cap > 0:
            fields["memory"] = cut_on_line(fields["memory"], cap)
        sys.stdout.write(system_prompt(partial=data.get("partial") is True,
                                       **fields))
        return 0
    if isinstance(data, dict) and isinstance(data.get("context"), dict):
        data = data["context"]
    sys.stdout.write(preamble(data))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
