"""Pure helpers for insight jobs — no Home Assistant imports, so the
formatting/truncation logic is unit-testable outside an HA install."""

from __future__ import annotations

import re
import textwrap

# Recorder drops attribute payloads over ~16KB; stay comfortably under and
# keep dashboards snappy.
MARKDOWN_MAX_CHARS = 12000


def truncate_markdown(text: str, limit: int = MARKDOWN_MAX_CHARS) -> str:
    """Cap insight markdown on a line boundary with a visible marker."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    nl = cut.rfind("\n")
    if nl > 0:
        cut = cut[:nl]
    return cut + "\n\n*…truncated*"


# Models sometimes ignore "write markdown" and emit a whole Lovelace card
# (``type: markdown`` / ``content: >-``) or fence the answer in a code block.
# That scaffolding then renders as literal text inside the real card, so peel
# it back down to the report body before storing.
_FENCE_RE = re.compile(r"^```[^\n]*\n(.*)\n```\s*$", re.DOTALL)
_CARD_TYPE_RE = re.compile(r"^type:\s*markdown\s*$", re.IGNORECASE)
_CARD_CONTENT_RE = re.compile(r"^content:\s*(?:[|>][+-]?)?\s*(.*)$", re.IGNORECASE)


def strip_card_wrapper(text: str) -> str:
    """Return only the markdown body when the model wraps its answer.

    Unwraps a surrounding code fence and/or a Lovelace markdown-card header
    (``type: markdown`` … ``content: >-``). Anything that isn't a recognised
    wrapper is returned unchanged, so a plain markdown report is never altered.
    """
    if not text or not text.strip():
        return text

    s = text.strip()
    fenced = _FENCE_RE.match(s)
    if fenced:
        s = fenced.group(1).strip()

    lines = s.split("\n")
    if lines and _CARD_TYPE_RE.match(lines[0].strip()):
        for i, line in enumerate(lines):
            content = _CARD_CONTENT_RE.match(line)
            if content:
                inline = (content.group(1) or "").strip()
                body = textwrap.dedent("\n".join(lines[i + 1:])).strip()
                unwrapped = "\n".join(p for p in (inline, body) if p).strip()
                return unwrapped or text

    return s if fenced else text


def make_preview(markdown: str | None, limit: int = 180) -> str | None:
    """First line(s) of the report, flattened — readable in the attributes
    pane without expanding the full markdown blob."""
    if not markdown:
        return None
    flat = " ".join(markdown.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def build_card_yaml(entity_id: str, title: str) -> str:
    """Ready-to-paste Lovelace markdown card for an insight sensor."""
    return (
        "type: markdown\n"
        f"title: {title}\n"
        "content: >-\n"
        f"  {{{{ state_attr('{entity_id}', 'markdown') or 'No insight yet — run the bruh_claude.run_insight service.' }}}}"
    )


# Shipped prompt templates. Each leans on the MCP tools the agent already
# has (states, history, statistics, cameras) rather than assuming injected
# data — users can still embed HA Jinja in custom prompts, which the
# integration renders before sending.
INSIGHT_TEMPLATES: dict[str, str] = {
    "daily_briefing": """You are the situational-awareness layer for this household. Write a short markdown briefing for the dashboard that surfaces what the residents would actually want to know right now — not a system status report.

Use your MCP tools to look around: get_all_states for anything that looks off (filter by domain), get_history/get_statistics to judge whether something is unusual, get_areas for context.

PRIORITIES, in order:
1. Anomalies and connections — things that are weird TOGETHER ("garage open AND nobody home" matters; "garage open with someone in the driveway" doesn't).
2. Quiet things they'd miss — a device on for hours that shouldn't be, a critical battery, an unavailable entity that matters, maintenance wearing due.
3. Today's context — weather or calendar ONLY if it changes a decision.

STRICT RULES:
- Do NOT enumerate every system. If something is fine, omit it. Silence means fine.
- No "all-OK" sections, no fixed structure, variable length (a quiet day is 2-3 lines).
- Start with one short natural weather sentence unless an urgent problem should lead.
- Use emojis sparingly: warning sign for real problems, wrench for maintenance, clock for time-sensitive.
- Output ONLY the markdown body — no code fences, no YAML, no `type:`/`title:`/`content:` card wrapper (the dashboard supplies that).

Write the briefing now.""",
    "anomaly_watch": """Scan this Home Assistant instance for anomalies RIGHT NOW using your MCP tools (get_all_states by domain, get_history to compare against recent behavior).

Report ONLY genuine anomalies: doors/covers open that are normally closed, devices unavailable that matter (cameras, locks, climate), devices on far longer than usual, sensors flatlined or reporting impossible values, anything unsafe.

Output: a short markdown list, one line per finding, most important first — the markdown body only, no code fence or `type:`/`content:` card wrapper. If nothing is anomalous, output exactly: "All quiet." """,
    "battery_maintenance": """Audit batteries and maintenance using your MCP tools.

1. get_all_states with domain sensor and name_filter battery — list everything at or below 20%, lowest first, with its device.
2. Look for maintenance-style sensors (filters, brushes, consumables) below 15%.
3. Flag battery-powered devices that have gone unavailable (they often die silently).

Output a compact markdown checklist grouped by urgency (replace now / soon / watch) — the markdown body only, no code fence or `type:`/`content:` card wrapper. Omit healthy items entirely. If everything is healthy, output exactly: "All batteries and consumables healthy." """,
    "camera_check": """Use get_camera_snapshot to look at each camera in this home (find them with get_all_states domain camera, skip unavailable ones).

For each: one line describing anything NOTABLE — people, vehicles, packages, open doors/gates, weather damage, anything out of place. Skip cameras showing nothing notable.

Output a short markdown list — the markdown body only, no code fence or `type:`/`content:` card wrapper. If nothing is notable anywhere, output exactly: "Nothing notable on any camera." """,
}
