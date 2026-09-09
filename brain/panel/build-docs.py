#!/usr/bin/env python3
"""Generate `panel/docs.js` from `brain/DOCS.md`.

The panel's Docs tab and the add-on's DOCS.md said the same things twice, by
hand, and drifted the way two copies always do: the guide in the panel went on
teaching a tab layout, a button set and a CLI that the file beside it had
already corrected. So there is one source now — DOCS.md, which is what Home
Assistant shows on the add-on's Documentation tab — and this writes the other.

**It generates for the renderer that exists, not for CommonMark.**
`renderMarkdown()` in `app.js` understands headings, fenced code, pipe tables,
blockquotes, one level of list nesting, paragraphs, and inline `code`, **bold**
and `[text](http…)` links. Everything else is rendered as the literal text it
was written as, so three shapes are normalised on the way through rather than
left to render as prose:

* a **horizontal rule** (`---`) has no branch at all and comes out as a
  paragraph containing three hyphens;
* an **in-page anchor link** (`[Ports](#ports)`) is not an `http` URL, so the
  inline rule skips it and the reader sees the brackets and the anchor. The
  text survives and the link does not, which is the honest trade: there is
  nothing on the page to jump to, because each section is its own entry;
* a **heading inside a blockquote** (`> ### Back up first`) is swallowed by the
  blockquote branch, which joins its lines and renders them inline — so the
  hashes would be printed. It becomes bold;
* **single-asterisk emphasis** (`*here*`) has no inline rule — only `**bold**`
  does — so the asterisks are printed. They become bold, which is the nearest
  thing the renderer can draw. This one was true of the hand-written docs.js
  too, in forty places, and stopping at "it was already like that" is how a
  wart survives a rewrite whose whole point was to make one source right.

The table of contents at the top of DOCS.md is dropped for the same reason it
exists: it is a list of anchors into one long file, and this produces a nav out
of the sections themselves.

**One entry per `##`, except `## What it can do`, which is split per `###`.**
That section is about 1,100 lines — three quarters of the guide — so a single
entry would be a nav with one unusable item in it. Nothing else is split: the
remaining sections are one screen or two each.

Usage:

    python3 panel/build-docs.py            # write panel/docs.js
    python3 panel/build-docs.py --check    # exit 1 if it would change

`--check` is what CI runs: an edit to DOCS.md that nobody regenerated is a Docs
tab one release behind the file it was generated from, which is the failure
this replaced.

Standard library only, and no dependency on the panel's own modules: this runs
in CI and in a checkout, neither of which has the add-on runtime.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS_MD = HERE.parent / "DOCS.md"
DOCS_JS = HERE / "docs.js"

# The one section that is split into an entry per `###`. Named rather than
# derived from a length, because "long enough to split" is a threshold that
# would silently re-shape the nav the day a section grew past it.
SPLIT_SECTIONS = {"What it can do"}

HEADER = """\
// GENERATED from brain/DOCS.md by panel/build-docs.py — do not edit.
//
// Run `python3 panel/build-docs.py` after editing DOCS.md; CI runs it with
// `--check` and fails if this file is out of date.
//
// Kept as data rather than markup so the same source drives the sidebar, the
// search index, and the rendered page — a docs page whose nav can drift out of
// sync with its own body is worse than no nav.
//
// `body` is a small markdown subset (headings, lists, tables, fenced code,
// inline code, bold, links) rendered by renderDocs() in app.js.

window.BRAIN_DOCS = [
"""

FOOTER = "];\n"

# slug -> emoji. A section with no entry takes DEFAULT_ICON, which is a
# perfectly good nav row: a missing icon must not be a missing section.
DEFAULT_ICON = "📄"
ICONS = {
    "brain": "🏠",
    # ## What it can do, split per ###
    "it-runs-home-assistant": "🏡",
    "it-finds-whats-broken-and-fixes-it": "🔧",
    "it-checks-the-house-without-spending-a-token": "✅",
    "it-explains-your-house-to-you": "📊",
    "it-remembers": "🧠",
    "it-answers-when-you-talk-to-it": "🗣️",
    "it-has-a-full-terminal-in-two-shapes": "💻",
    "it-works-while-youre-asleep": "🌙",
    "it-knows-what-unusual-means-here": "📈",
    "it-knows-what-is-normally-open": "🚪",
    "it-knows-when-your-house-gets-up": "⏰",
    "a-morning-brief-when-there-is-something-to-say": "☕",
    "one-report-a-week": "📰",
    "what-the-house-used": "⚡",
    "it-knows-when-the-washing-finished": "🧺",
    "it-knows-how-your-house-holds-its-heat": "🌡️",
    "what-the-thermal-model-is-for": "♨️",
    "where-a-proposal-comes-from": "💡",
    "it-suggests-things-and-proves-them-first": "🧪",
    "saying-yes-and-taking-it-back": "↩️",
    "what-a-replay-can-and-cannot-answer": "⏪",
    "the-house-acts": "🛠️",
    "the-condition-it-is-missing": "🧩",
    "something-that-happens-once": "🎯",
    "four-scenes-for-a-room": "🎨",
    "answering-without-opening-anything": "📱",
    "it-knows-what-changed-and-what-changed-it": "🕵️",
    "it-says-when-it-is-not-working": "❤️",
    "everything-it-does-can-be-undone": "🔙",
    # the remaining ## sections
    "setup": "🚀",
    "what-to-expect": "🗓️",
    "the-panel": "🖥️",
    "what-brain-is-measuring": "📐",
    "checking-brain-itself": "🩺",
    "capture-corpus-and-replay": "🔬",
    "the-cli": "⌨️",
    "configuration-options": "⚙️",
    "what-it-costs": "💰",
    "what-it-will-not-do": "🚫",
    "ports": "🔌",
    "security": "🔒",
    "where-things-live": "📁",
    "credits": "🙏",
    "license": "📜",
}

_SLUG_DROP = re.compile(r"['’]")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_ANCHOR_LINK = re.compile(r"\[([^\]]+)\]\(#[^)]*\)")
_TOC_ITEM = re.compile(r"^\s*[-*]\s+\[[^\]]+\]\(#[^)]*\)\s*$")
_QUOTE_HEADING = re.compile(r"^>\s*#{1,6}\s+(.*?)\s*$")
_RULE = re.compile(r"^\s*-{3,}\s*$")
# `*here*` but never `**bold**` and never across an asterisk or a backtick:
# the span has to be bounded by non-asterisks on both sides, which is what
# keeps a `**` pair from being read as an empty emphasis plus a stray.
_EMPHASIS = re.compile(r"(?<!\*)\*([^*`\n]+)\*(?!\*)")


def emphasis(line: str) -> str:
    """`*x*` → `**x**`, outside inline code.

    Split on backticks and rewrite only the even segments: an asterisk inside
    `` `light.*` `` is a glob somebody meant literally, and bolding half of it
    would be a docs page teaching a pattern that does not exist. An unbalanced
    backtick leaves an odd number of segments, and the tail is then treated as
    code — the conservative half, since the cost is one un-bolded phrase.
    """
    parts = line.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = _EMPHASIS.sub(r"**\1**", parts[i])
    return "`".join(parts)


def slug(title: str) -> str:
    """A stable id from a heading, matching GitHub's anchors closely enough
    that the two never have to be reconciled by hand.

    An apostrophe is DROPPED rather than turned into a separator, which is what
    GitHub does and what keeps `it-works-while-youre-asleep` from becoming
    `...you-re-asleep` — a difference nobody would notice until an icon looked
    up by slug quietly stopped matching.
    """
    plain = _SLUG_DROP.sub("", title.strip().lower())
    return _SLUG_STRIP.sub("-", plain).strip("-") or "section"


def normalise(lines: list[str]) -> list[str]:
    """The three shapes `renderMarkdown` would print as literal text.

    Fenced code is passed through untouched: a `---` inside a code block is
    somebody's YAML document marker, and rewriting it would corrupt an example.
    """
    out: list[str] = []
    fenced = False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        if _TOC_ITEM.match(line) or _RULE.match(line):
            continue
        quoted = _QUOTE_HEADING.match(line)
        if quoted:
            out.append(f"> **{emphasis(quoted.group(1))}**")
            continue
        out.append(emphasis(_ANCHOR_LINK.sub(r"\1", line)))
    return out


def _trim(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def promote(lines: list[str], levels: int) -> list[str]:
    """Lift every heading `levels` closer to `#`, so a section's own heading
    becomes the page's `#` and its children follow it down.

    A heading already at `#` cannot be promoted and is left alone; `renderDocs`
    renders whatever level it is given, so this is about the page reading like a
    page rather than about correctness.
    """
    out = []
    fenced = False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line) if not fenced else None
        if m:
            level = max(1, len(m.group(1)) - levels)
            out.append("#" * level + " " + m.group(2))
        else:
            out.append(line)
    return out


def parse(markdown: str) -> list[dict]:
    """DOCS.md as the list of `{id, icon, title, body}` the panel reads."""
    lines = normalise(markdown.replace("\r\n", "\n").split("\n"))

    title = "brAIn"
    for line in lines:
        m = re.match(r"^#\s+(.*)$", line)
        if m:
            title = m.group(1).strip()
            break

    # Split at top-level `##`, keeping whatever came before the first one as
    # the overview: it is the pitch, and a guide that opens on "Setup" has
    # thrown away the paragraph that says what the thing is.
    blocks: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current: list[str] = []
    preamble: list[str] = []
    fenced = False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = re.match(r"^##\s+(?!#)(.*)$", line) if not fenced else None
        if m:
            if current_title is None:
                preamble = current
            else:
                blocks.append((current_title, current))
            current_title, current = m.group(1).strip(), []
            continue
        current.append(line)
    if current_title is None:
        preamble = current
    else:
        blocks.append((current_title, current))

    sections: list[dict] = []

    def add(name: str, body_lines: list[str], levels: int) -> None:
        body = _trim(promote(_trim(list(body_lines)), levels))
        sections.append({"id": slug(name), "title": name,
                         "icon": ICONS.get(slug(name), DEFAULT_ICON),
                         "body": "\n".join([f"# {name}", ""] + body)})

    # The preamble keeps DOCS.md's own H1 as its title, and its body drops that
    # H1 because `add` writes the heading itself.
    add(title, [ln for ln in preamble if not re.match(r"^#\s+", ln)], 1)

    for name, body_lines in blocks:
        if name not in SPLIT_SECTIONS:
            add(name, body_lines, 1)
            continue
        subs: list[tuple[str, list[str]]] = []
        sub_title: str | None = None
        sub: list[str] = []
        lead: list[str] = []
        fenced = False
        for line in body_lines:
            if line.lstrip().startswith("```"):
                fenced = not fenced
            m = re.match(r"^###\s+(?!#)(.*)$", line) if not fenced else None
            if m:
                if sub_title is None:
                    lead = sub
                else:
                    subs.append((sub_title, sub))
                sub_title, sub = m.group(1).strip(), []
                continue
            sub.append(line)
        if sub_title is None:
            add(name, sub, 1)
            continue
        subs.append((sub_title, sub))
        # Anything before the first `###` belongs to the FIRST sub-entry: a
        # section's own opening paragraph is about what follows it, and there
        # is no longer a page for it to sit at the top of.
        opening = _trim(list(lead))
        if opening:
            subs[0] = (subs[0][0], opening + [""] + subs[0][1])
        for sub_name, sub_body in subs:
            add(sub_name, sub_body, 2)

    seen: dict[str, int] = {}
    for section in sections:
        base = section["id"]
        if base in seen:
            seen[base] += 1
            section["id"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
    return sections


def js_literal(text: str) -> str:
    """A template literal's body. Backslash first, or the escapes escape each
    other; `${` last, because it is only special after the backslash pass."""
    return (text.replace("\\", "\\\\").replace("`", "\\`")
                .replace("${", "\\${"))


def js_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(sections: list[dict]) -> str:
    parts = [HEADER]
    for section in sections:
        parts.append("  {\n")
        parts.append(f"    id: {js_string(section['id'])},\n")
        parts.append(f"    icon: {js_string(section['icon'])},\n")
        parts.append(f"    title: {js_string(section['title'])},\n")
        parts.append("    body: `\n")
        parts.append(js_literal(section["body"]))
        parts.append("\n`,\n")
        parts.append("  },\n")
    parts.append(FOOTER)
    return "".join(parts)


def build(src: Path = DOCS_MD) -> str:
    return render(parse(src.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if docs.js is not what this would write")
    ap.add_argument("--source", type=Path, default=DOCS_MD)
    ap.add_argument("--out", type=Path, default=DOCS_JS)
    args = ap.parse_args(argv)

    wanted = build(args.source)
    if args.check:
        try:
            have = args.out.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"{args.out} could not be read: {exc}", file=sys.stderr)
            return 1
        if have != wanted:
            print(f"{args.out} is out of date — run "
                  f"`python3 {Path(__file__).name}` and commit the result.",
                  file=sys.stderr)
            return 1
        print(f"{args.out.name} is up to date "
              f"({len(parse(args.source.read_text(encoding='utf-8')))} sections).")
        return 0

    args.out.write_text(wanted, encoding="utf-8")
    print(f"wrote {args.out} "
          f"({len(parse(args.source.read_text(encoding='utf-8')))} sections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
