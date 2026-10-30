"""What brAIn brings to each kind of run, and what it looks up — measured.

The owner's question: "It's not clear to me what is imported on each new
conversation vs what's in knowledge." Nothing on screen answered it. The
memory document sat under ⚙, the facts under Knowledge, and what a run was
actually handed was spread over a dozen builders — the chat's appended
prompt (`server._chat_system_prompt`), the generated /config/CLAUDE.md
(`ha-context-gen.sh`, which splices in an excerpt of the document), the
per-message hook (`server._chat_context`), the card bundle
(`ha_data._memory_for` / `_read_context`), the Resident's `_memory_block`
and the voice worker's own system prompt (`brain_voice_context`).

This module is the one place that says it in words. It holds no prompt
text and never builds one of its own: the server hands it the texts the
real builders produce right now (`server._context_sources`), and this
module measures them, names them and says what each run may look up. A
part that depends on the request (the facts about the message somebody is
typing) is reported by the cap its builder enforces, marked `upto`.

What is reported is names, sizes and where a thing is changed. Never the
text: the page opens the document itself, through its own route, only
when somebody asks for it.

Stdlib only; never raises into a caller for a file that is not there.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# The same estimate the server prints beside a prompt (`server.CHARS_PER_TOKEN`).
CHARS_PER_TOKEN = 4

# The shell's own budget for the memory excerpt in /config/CLAUDE.md
# (`ha-context-gen.sh` `memory_excerpt`, `BRAIN_CONTEXT_MEMORY_BYTES`,
# default 8 KB). Read from the same variable the shell reads; the default is
# pinned against the script by `tests/test_context_map.py`.
def claude_md_memory_budget() -> int:
    raw = os.environ.get("BRAIN_CONTEXT_MEMORY_BYTES", "")
    return int(raw) if raw.isdigit() else 8192


# The voice worker's caps (`integrations/assist-worker-pool.py`
# MEMORY_MAX_BYTES and AREA_MAP_MAX_BYTES). The pool is a separate process
# and its module starts threads on import, so the numbers are named here and
# pinned against its source by the test rather than imported.
VOICE_MEMORY_BYTES = 2048
VOICE_MAP_BYTES = 16000

# The headings `ha-context-gen.sh` writes around the memory excerpt.
MEMORY_HEADING = "## Learned Home Knowledge"
AFTER_MEMORY = "\n## Available Directories"
NOTES_START = "<!-- bruh:user-notes:start -->"
NOTES_END = "<!-- bruh:user-notes:end -->"

MCP_PREFIX = re.compile(r"^mcp__[a-z0-9_-]+?__")


def bare(name) -> str:
    """A tool's own name, without the `mcp__<server>__` the CLI adds."""
    return MCP_PREFIX.sub("", str(name or ""))


def size(text) -> int:
    """Bytes, which is what every budget here is kept in."""
    return len(str(text or "").encode("utf-8"))


def part(key: str, label: str, about: str, nbytes: int, *, upto: bool = False,
         change: str = "", sec: str = "") -> dict:
    """One thing a run is handed. `upto` marks a cap rather than a reading;
    `change` says where a person changes it, `sec` the ⚙ section that is."""
    nbytes = max(0, int(nbytes or 0))
    return {"key": key, "label": label, "about": about, "bytes": nbytes,
            "tokens": round(nbytes / CHARS_PER_TOKEN), "upto": bool(upto),
            "change": change, "sec": sec}


def claude_md_split(text: str) -> dict:
    """How much of /config/CLAUDE.md is the memory excerpt and your notes."""
    text = str(text or "")
    memory = 0
    start = text.find(MEMORY_HEADING)
    if start >= 0:
        end = text.find(AFTER_MEMORY, start)
        memory = size(text[start:end if end >= 0 else len(text)].strip())
    notes = 0
    a, b = text.find(NOTES_START), text.find(NOTES_END)
    if a >= 0 and b > a:
        body = text[a + len(NOTES_START):b].strip()
        # The placeholder the generator writes when nobody has added notes.
        if body and not (body.startswith("<!--") and body.endswith("-->")):
            notes = size(body)
    return {"memory": memory, "notes": notes}


# ------------------------------------------------------------------ tools

# What a tool is FOR, in the words a person would use, decided by its name.
# Read in order; the first that matches wins. The MCP server's own list is
# what is grouped (`mcp_tool_names`, `engine.ANALYST_TOOLS`), so a tool added
# there is counted the day it lands — under "Other" until it is named here,
# which the test refuses for any tool a card or an investigation may call.
_GROUPS: tuple[tuple[str, re.Pattern], ...] = (
    ("What brAIn remembers", re.compile(r"^(recall|remember_fact)$")),
    ("Changing the house", re.compile(
        r"^(control_\w+|call_service|activate_scene|run_script|fire_event|"
        r"timed_action|reload_config|send_notification|set_\w+|show_switch_as|"
        r"stop_showing_switch_as|create_\w+|update_\w+|delete_\w+|rename_\w+|"
        r"assign_\w+|enable_\w+|disable_\w+|restore_\w+|apply_\w+|undo_\w+)$")),
    ("Other add-ons and devices", re.compile(
        r"^(esphome_\w+|music_assistant_\w+|minecraft_\w+|label_printer_\w+|"
        r"print_label|bright_\w+|bambu_\w+|garden_\w+|cooking_\w+|"
        r"bruh_addon_status)$")),
    ("What brAIn has measured", re.compile(
        r"^(get_baseline|get_house_model|what_is_normal|room_physics|"
        r"appliance_status|house_rhythm|door_habits|habits|"
        r"simulate_automation|replay_automation)$")),
    ("brAIn's own findings and health", re.compile(
        r"^(get_findings|get_health|explain_decision|notification_history|"
        r"offer_resolutions|report_bug|note_personality_change|"
        r"screenshot_panel)$")),
    ("Device states and history", re.compile(
        r"^(get_all_states|get_entity_state|get_history|get_statistics|"
        r"get_logbook|get_activity|explain_change|get_camera_snapshot|"
        r"render_template|get_weather_forecast|get_states)$")),
    ("Automations, rooms and setup", re.compile(
        r"^(get_automation\w*|get_areas|get_registry|list_\w+|get_dashboard\w*|"
        r"get_ha_config|get_services|get_service_details|get_entity_counts|"
        r"search_related|get_error_log|get_supervisor_info|"
        r"assistant_exposure|get_\w+)$")),
)
OTHER = "Other"


def tool_group(name: str) -> str:
    own = bare(name)
    for label, pattern in _GROUPS:
        if pattern.match(own):
            return label
    return OTHER


def group_tools(names) -> list[dict]:
    """Tool names as groups a person can read, in a fixed order."""
    buckets: dict[str, list[str]] = {}
    for name in names or ():
        own = bare(name)
        if own:
            buckets.setdefault(tool_group(own), []).append(own)
    order = [g for g, _ in _GROUPS] + [OTHER]
    return [{"label": g, "count": len(buckets[g]), "tools": sorted(set(buckets[g]))}
            for g in order if g in buckets]


_TOOL_FILES = ("/opt/ha-mcp-server/ha_mcp_server.py",
               str(Path(__file__).resolve().parent.parent / "ha-mcp-server"
                   / "ha_mcp_server.py"))
_TOOL_NAMES: list[str] | None = None


def mcp_tool_names() -> list[str]:
    """Every tool the Home Assistant MCP server lists, read off its source
    (`house_words.tool_names`' arrangement, one-word names included)."""
    global _TOOL_NAMES
    if _TOOL_NAMES is None:
        names: list[str] = []
        for path in _TOOL_FILES:
            try:
                source = Path(path).read_text(encoding="utf-8")
            except OSError:
                continue
            names = sorted(set(re.findall(
                r'^\s+"name":\s*"([a-z][a-z0-9_]*)"', source, re.M)))
            if names:
                break
        _TOOL_NAMES = names
    return list(_TOOL_NAMES)


# ------------------------------------------------------------------ voice

def voice_module():
    """`scripts/brain_voice_context.py`, the voice worker's own prompt
    builder: the image's /opt/scripts, or the repo's. None when absent."""
    here = Path(__file__).resolve().parent
    for path in (here.parent / "scripts", Path("/opt/scripts")):
        if (path / "brain_voice_context.py").is_file():
            if str(path) not in sys.path:
                sys.path.append(str(path))
            try:
                import brain_voice_context  # noqa: PLC0415
                return brain_voice_context
            except Exception:  # noqa: BLE001 — no builder is no voice row
                return None
    return None


def read_size(path, cap: int | None = None) -> int:
    try:
        n = Path(path).stat().st_size
    except OSError:
        return 0
    return min(n, cap) if cap else n


# ------------------------------------------------------------------ report

def report(src: dict) -> dict:
    """Every kind of run, what it is given and what it may look up.

    ``src`` is what `server._context_sources` read from the real builders:
    texts (measured here, never sent) and the numbers the builders cap at.
    """
    s = src
    doc = int(s.get("document_bytes") or 0)
    facts = int(s.get("facts") or 0)
    claude_md = s.get("claude_md") or ""
    split = claude_md_split(claude_md)
    all_tools = group_tools(s.get("mcp_tools") or mcp_tool_names())
    read_only = group_tools(s.get("analyst_tools") or ())
    # One hook for both faces of Ask (`chat_session.conversation_settings`):
    # the chat's own settings and the terminal's carry the same one, so
    # what a conversation is handed does not depend on the face.
    hook = bool(s.get("context_hook"))

    def facts_or_doc(key: str, cap: int, head: int, label: str) -> dict:
        # `_memory_block` and `ha_data._memory_for`: the facts about this
        # run's subjects over the document's head — or, on a house with no
        # facts yet, the document itself, capped.
        if facts:
            return part(key, label,
                        "The facts brAIn holds about what this run is about, "
                        "with the first lines of your memory document.",
                        cap + min(head, doc), upto=True)
        return part(key, "Your memory document",
                    "No facts are stored yet, so the run gets the document "
                    "itself, cut to fit.", min(doc, cap), upto=doc > cap)

    conversation = {
        "key": "conversation",
        "title": "A conversation in Ask",
        "when": "Each new chat or terminal window — also Discuss on a card and "
                "anything you press and hold to ask about.",
        "given": [
            part("identity", "Who brAIn is and how it works here",
                 "The rules every conversation starts with.",
                 size(s.get("identity")), change="⚙ › Instructions",
                 sec="instructions"),
            part("personality", "The personality you gave it",
                 "Its name and how it speaks." if s.get("personality")
                 else "None is set, so nothing is sent.",
                 size(s.get("personality")), change="⚙ › Personality",
                 sec="personality"),
            part("house_now", "How the house stands as it starts",
                 "How many things are waiting on you, brAIn's own health and "
                 "when the house wakes and settles — as of the start.",
                 size(s.get("house_now"))),
            part("claude_md", "The house summary file",
                 "/config/CLAUDE.md: your rooms, devices, automations, add-ons, "
                 "dashboards and how to work here. Rewritten when brAIn starts "
                 "and after each filing.", size(claude_md)),
            part("memory_excerpt", "Your memory document (inside that file)",
                 "As much of the document as fits in "
                 f"{claude_md_memory_budget() // 1024} KB — every section keeps "
                 "its heading and first line. Counted in the file above.",
                 split["memory"], sec="knowledge"),
            part("notes", "Your notes (inside that file)",
                 "The block of CLAUDE.md that is yours. Counted in the file "
                 "above.", split["notes"], change="⚙ › Instructions",
                 sec="instructions"),
        ],
        "each_time": [
            part("facts_for_message", "Facts about what you just typed",
                 "brAIn looks up the facts that match your message and hands "
                 "them over with it, each fact once per conversation."
                 + ("" if hook else " Not wired on this install."),
                 int(s.get("chat_context_chars") or 0), upto=True),
        ],
        "looks_up": {
            "summary": "Every Home Assistant tool brAIn has — reading and "
                       "changing — plus the files and the shell in /config. "
                       "It asks what brAIn remembers with recall.",
            "groups": all_tools,
            "count": sum(g["count"] for g in all_tools),
        },
    }

    card_rules = s.get("card_rules") or ""
    search = s.get("gather_mode", "search") == "search"
    card = {
        "key": "card",
        "title": "An insight card",
        "when": "Each time a card is written or refreshed, starting from its "
                "own question and a map of what the house contains.",
        "given": [
            part("card_rules", "How to write a card",
                 "The card contract, " + ("for a card that looks the house up "
                                          "itself." if search else
                                          "for a card handed the whole house."),
                 size(card_rules), change="⚙ › Instructions",
                 sec="instructions"),
            facts_or_doc("memory_facts", int(s.get("card_memory_cap") or 0),
                         int(s.get("card_memory_head") or 0),
                         "Facts about what the card covers"),
            part("claude_md_head", "The start of the house summary file",
                 "/config/CLAUDE.md, cut to fit.",
                 min(size(claude_md), int(s.get("card_context_chars") or 0))),
            part("measured", "What brAIn has measured",
                 "What is normal here, how rooms hold heat, machines, habits.",
                 int(s.get("house_chars") or 0), upto=True),
            part("learned", "What its earlier cards learned",
                 "Notes earlier runs kept, and brAIn's own name.",
                 size(s.get("learned"))),
            part("findings", "What is already open",
                 "The problems and questions on Needs you, so a card does not "
                 "report them twice.", size(s.get("findings"))),
            part("guesses", "Guesses waiting for an answer",
                 "Questions brAIn has asked and you have not answered.",
                 size(s.get("guesses"))),
        ],
        "each_time": [],
        "looks_up": {
            "summary": ("Home Assistant's reading tools only — it can change "
                        "nothing. It asks what brAIn remembers with recall."
                        if search else
                        "Nothing: it is handed the whole house instead."),
            "groups": read_only if search else [],
            "count": sum(g["count"] for g in read_only) if search else 0,
        },
    }

    voice_given = [
        part("voice_rules", "How to answer out loud",
             "Short spoken replies, the time zone, and what this agent may "
             "reach.", int(s.get("voice_rules") or 0)),
        part("personality", "The personality you gave it",
             "Unless the voice agent has one of its own." if s.get("personality")
             else "None is set, so it speaks in brAIn's own short style.",
             size(s.get("voice_personality")), change="⚙ › Personality",
             sec="personality"),
        part("room_map", "Every room and what is in it",
             "Refreshed every few minutes. Only devices exposed to voice, "
             "unless the agent may reach the whole house.",
             int(s.get("voice_map") or 0)),
        part("voice_memory", "A short summary of your memory document",
             ("The voice summary the filing pass writes."
              if s.get("voice_summary") else
              f"The first {VOICE_MEMORY_BYTES // 1024} KB of the document.")
             + " Not the whole document, and not the house summary file.",
             int(s.get("voice_memory") or 0), sec="knowledge"),
    ]
    voice = {
        "key": "voice",
        "title": "A voice request",
        "when": "Each request to a brAIn voice agent in Home Assistant Assist. "
                "It does not read the house summary file.",
        "given": voice_given,
        "each_time": [
            part("where_who", "Where it was said and who said it",
                 "The room, the person, and what was said just before.",
                 int(s.get("voice_request_cap") or 0), upto=True),
        ],
        "looks_up": {
            "summary": "The Home Assistant tools its access level allows — by "
                       "default only devices exposed to voice. It can ask what "
                       "brAIn remembers (recall), limited the same way.",
            "groups": [], "count": 0,
        },
    }

    first_look = {
        "key": "first_look",
        "title": "A first look at something new",
        "when": "Every few minutes, when sensors report something that might "
                "matter.",
        "given": [
            part("look_rules", "How to judge what matters",
                 "The first look's rules.", size(s.get("first_look_rules")),
                 change="⚙ › Instructions", sec="instructions"),
            facts_or_doc("memory_facts", int(s.get("retrieval_chars") or 0),
                         int(s.get("memory_head_chars") or 0),
                         "Facts about those devices"),
        ],
        "each_time": [],
        "looks_up": {"summary": "Nothing. It has no tools: it decides from "
                                "what it was handed.", "groups": [], "count": 0},
    }

    investigation = {
        "key": "investigation",
        "title": "An investigation",
        "when": "When a first look decides something deserves a closer look.",
        "given": [
            part("investigate_rules", "How to investigate",
                 "The investigation's rules.", size(s.get("investigate_rules")),
                 change="⚙ › Instructions", sec="instructions"),
            facts_or_doc("memory_facts", int(s.get("retrieval_chars") or 0),
                         int(s.get("memory_head_chars") or 0),
                         "Facts about the device"),
            part("measured", "What brAIn has measured",
                 "What is normal here, how rooms hold heat, machines, habits.",
                 int(s.get("house_chars") or 0), upto=True),
        ],
        "each_time": [],
        "looks_up": {
            "summary": "The same reading tools a card has — it can change "
                       "nothing — including recall.",
            "groups": read_only, "count": sum(g["count"] for g in read_only),
        },
    }

    overnight = {
        "key": "overnight",
        "title": "The overnight check",
        "when": "Once a night, over brAIn's own logs. The house checks "
                "themselves are rules in brAIn's code and send nothing to "
                "Claude.",
        "given": [
            part("overnight_rules", "How to read the night's logs",
                 "The overnight check's rules.", size(s.get("overnight_rules")),
                 change="⚙ › Instructions", sec="instructions"),
        ],
        "each_time": [],
        "looks_up": {"summary": "Nothing, and not your memory either: it reads "
                                "only the logs it is handed.",
                     "groups": [], "count": 0},
    }

    return {
        "runs": [conversation, card, voice, first_look, investigation, overnight],
        "memory": {
            "document_bytes": doc,
            "document_tokens": round(doc / CHARS_PER_TOKEN),
            "waiting": int(s.get("waiting") or 0),
            "filed_at": int(s.get("filed_at") or 0),
            "facts": facts,
            "context_hook": hook,
        },
    }


__all__ = ["CHARS_PER_TOKEN", "VOICE_MAP_BYTES", "bare", "VOICE_MEMORY_BYTES",
           "claude_md_memory_budget", "claude_md_split", "group_tools",
           "mcp_tool_names", "part", "read_size", "report", "size",
           "tool_group", "voice_module"]
