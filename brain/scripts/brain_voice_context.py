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
    if speaker and pid:
        lines.append(
            f"The speaker is {speaker} (person.{pid}). A preference they "
            f"state is theirs: remember it with remember_fact person=\"{pid}\".")
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


def _cli(argv: list[str]) -> int:
    """`preamble`: read a context object (or a whole request) on stdin and
    print the block. Prints nothing for anything it cannot read."""
    if not argv or argv[0] != "preamble":
        print("usage: brain_voice_context.py preamble < context.json",
              file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if isinstance(data, dict) and isinstance(data.get("context"), dict):
        data = data["context"]
    sys.stdout.write(preamble(data))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
