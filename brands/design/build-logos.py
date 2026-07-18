#!/usr/bin/env python3
"""Generate the unified BRUH Automation add-on logo set.

One design system, three add-ons. Every icon shares the same rounded
dark-navy tile, a hairline dodger-blue inner ring, and the BRUH chip —
a brand-blue rounded badge with a bold white B broadcasting signal
waves (the bruhautomation.com lettermark) — in the top-left corner.
Each add-on then gets its own centerpiece glyph and accent colour:

  * Claude Terminal — blue prompt chevron + underscore, coral AI spark
  * Insights       — blue→violet→pink rising bars + white sparkle
  * Minecraft      — pixel grass block in harmonised greens/browns

Outputs (rendered with cairosvg):
  <addon>/icon.png                 512×512 square store icon
  <addon>/logo.png                 1024×320 landscape store banner
  <addon>/panel/favicon.svg        simplified 64×64 panel favicon
  brands/custom_integrations/bruh_claude/icon.png (+@2x)
  bruh-claude-terminal/custom_components/bruh_claude/icon.png

SVG masters are also written next to this script so they can be edited
and re-rendered:  python3 brands/design/build-logos.py
Requires: pip install cairosvg
"""

from __future__ import annotations

import os

import cairosvg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BLUE = "#1e90ff"          # BRUH Automation brand blue (dodger blue)
BLUE_SOFT = "#4aa3ff"
BG_TOP = "#182432"        # tile gradient top
BG_BOTTOM = "#0b111a"     # tile gradient bottom
TEXT_LIGHT = "#edf3fa"
TEXT_MUTED = "#8fa8c4"
CORAL = "#d97757"         # Claude Terminal accent
VIOLET = "#8f7ae8"        # Insights mid-bar
PINK = "#d55181"          # Insights accent
GREEN = "#6fbf43"         # Minecraft accent


def defs(accent: str) -> str:
    """Shared gradient / glow definitions, glow tinted per add-on."""
    return f"""
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_TOP}"/>
      <stop offset="1" stop-color="{BG_BOTTOM}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.5" cy="0.58" r="0.62">
      <stop offset="0" stop-color="{accent}" stop-opacity="0.26"/>
      <stop offset="1" stop-color="{accent}" stop-opacity="0"/>
    </radialGradient>
  </defs>"""


def tile(size: int = 512, rx: int = 116) -> str:
    """Rounded tile background + glow + hairline brand ring."""
    return f"""
  <rect width="{size}" height="{size}" rx="{rx}" fill="url(#bg)"/>
  <rect width="{size}" height="{size}" rx="{rx}" fill="url(#glow)"/>
  <rect x="8" y="8" width="{size - 16}" height="{size - 16}" rx="{rx - 8}"
        fill="none" stroke="{BLUE_SOFT}" stroke-opacity="0.16" stroke-width="3"/>"""


def bruh_chip(x: int = 56, y: int = 56, size: int = 128) -> str:
    """The shared BRUH badge — identical on every icon.

    The B-lettermark with antenna + signal waves, exactly as on
    bruhautomation.com's favicon, on a brand-blue rounded chip.
    """
    s = size / 128
    return f"""
  <g transform="translate({x},{y}) scale({s})">
    <rect width="128" height="128" rx="28" fill="{BLUE}"/>
    <circle cx="64" cy="34" r="5.5" fill="white"/>
    <path d="M 51 32 A 13 13 0 0 1 77 32" fill="none" stroke="white"
          stroke-width="6" stroke-linecap="round"/>
    <path d="M 42 30 A 22 22 0 0 1 86 30" fill="none" stroke="white"
          stroke-width="6" stroke-linecap="round"/>
    <path fill="white" fill-rule="evenodd" d="
      M 46 57 L 69 57 Q 85 57 85 71.5 Q 85 81 76 85
      Q 88 88.5 88 99 Q 88 112 70 112 L 46 112 Z
      M 58 68 L 67 68 Q 73.5 68 73.5 73.5 Q 73.5 79 67 79 L 58 79 Z
      M 58 89 L 69 89 Q 76.5 89 76.5 95 Q 76.5 101 69 101 L 58 101 Z"/>
  </g>"""


# ---------------------------------------------------------------------------
# Per-add-on glyphs (drawn on the 512×512 grid)
# ---------------------------------------------------------------------------

def spark(cx: float, cy: float, r: float, fill: str, opacity: float = 1.0) -> str:
    """Four-point AI spark with concave sides."""
    k = r * 0.17
    return (
        f'<path fill="{fill}" fill-opacity="{opacity}" d="'
        f"M {cx} {cy - r} "
        f"C {cx + k} {cy - k * 2.2} {cx + k * 2.2} {cy - k} {cx + r} {cy} "
        f"C {cx + k * 2.2} {cy + k} {cx + k} {cy + k * 2.2} {cx} {cy + r} "
        f"C {cx - k} {cy + k * 2.2} {cx - k * 2.2} {cy + k} {cx - r} {cy} "
        f"C {cx - k * 2.2} {cy - k} {cx - k} {cy - k * 2.2} {cx} {cy - r} Z"
        f'"/>'
    )


def glyph_terminal() -> str:
    """Prompt chevron + underscore in blue, coral spark as the cursor."""
    return f"""
  <path d="M 136 224 L 244 318 L 136 412" fill="none" stroke="{BLUE}"
        stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="298" y="390" width="112" height="30" rx="15" fill="{BLUE}"/>
  {spark(354, 288, 84, CORAL)}
  {spark(432, 196, 26, CORAL, 0.85)}"""


def glyph_insights() -> str:
    """Rising bars in the Insights gradient, sparkle over the peak."""
    return f"""
  <rect x="104" y="290" width="64" height="130" rx="20" fill="{BLUE}"/>
  <rect x="204" y="220" width="64" height="200" rx="20" fill="{VIOLET}"/>
  <rect x="304" y="150" width="64" height="270" rx="20" fill="{PINK}"/>
  {spark(424, 130, 46, "#ffffff")}
  {spark(400, 210, 17, "#ffffff", 0.85)}"""


# Minecraft pixel block: 8×8 grid, rows 0-2 grass / 3-7 dirt.
# Hand-placed specks keep the pattern deterministic and tileable.
_GRASS_LIGHT = [(1, 0), (4, 0), (6, 1), (2, 1), (0, 2), (5, 2), (7, 0), (3, 2)]
_GRASS_DARK = [(2, 0), (5, 1), (7, 2), (0, 1), (3, 1), (6, 2)]
_DIRT_DARK = [(1, 3), (4, 4), (6, 3), (0, 5), (3, 6), (7, 5), (2, 7), (5, 7), (0, 3)]
_DIRT_LIGHT = [(2, 4), (5, 5), (7, 7), (0, 6), (6, 6), (3, 4), (1, 6)]
_DIRT_GREEN = [(3, 3), (6, 4), (0, 4)]


def glyph_minecraft() -> str:
    x0, y0, cell = 144, 196, 28
    px: list[str] = []
    px.append(
        f'<rect x="{x0}" y="{y0}" width="{cell * 8}" height="{cell * 3}" fill="#5da838"/>'
    )
    px.append(
        f'<rect x="{x0}" y="{y0 + cell * 3}" width="{cell * 8}" height="{cell * 5}" fill="#7a4f26"/>'
    )
    for coords, colour in (
        (_GRASS_LIGHT, GREEN),
        (_GRASS_DARK, "#4a9a28"),
        (_DIRT_DARK, "#6e4522"),
        (_DIRT_LIGHT, "#8a5a2b"),
        (_DIRT_GREEN, "#4a9a28"),
    ):
        for cx, cy in coords:
            px.append(
                f'<rect x="{x0 + cx * cell}" y="{y0 + cy * cell}" '
                f'width="{cell}" height="{cell}" fill="{colour}"/>'
            )
    body = "\n    ".join(px)
    return f"""
  <defs>
    <clipPath id="block">
      <rect x="{x0}" y="{y0}" width="{cell * 8}" height="{cell * 8}" rx="24"/>
    </clipPath>
  </defs>
  <g clip-path="url(#block)">
    {body}
  </g>"""


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def icon_svg(accent: str, glyph: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{defs(accent)}{tile()}{bruh_chip()}{glyph}
</svg>"""


def banner_svg(accent: str, glyph: str, name_line: str) -> str:
    """1024×320 landscape banner: mini tile + wordmark + faint beacon."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 320">{defs(accent)}
  <rect width="1024" height="320" rx="56" fill="url(#bg)"/>
  <rect x="7" y="7" width="1010" height="306" rx="49"
        fill="none" stroke="{BLUE_SOFT}" stroke-opacity="0.16" stroke-width="3"/>
  <defs>
    <clipPath id="banner"><rect width="1024" height="320" rx="56"/></clipPath>
  </defs>
  <g clip-path="url(#banner)">
    <g stroke="{BLUE}" fill="none">
      <circle cx="1004" cy="40" r="70" stroke-width="10" stroke-opacity="0.10"/>
      <circle cx="1004" cy="40" r="130" stroke-width="9" stroke-opacity="0.07"/>
      <circle cx="1004" cy="40" r="195" stroke-width="8" stroke-opacity="0.045"/>
    </g>
    <circle cx="1004" cy="40" r="18" fill="{BLUE}" fill-opacity="0.14"/>
  </g>
  <g transform="translate(56,54) scale(0.414)">
    <rect width="512" height="512" rx="116" fill="#141e2a"/>
    <rect width="512" height="512" rx="116" fill="url(#glow)"/>
    <rect x="8" y="8" width="496" height="496" rx="108"
          fill="none" stroke="{BLUE_SOFT}" stroke-opacity="0.2" stroke-width="4"/>{bruh_chip()}{glyph}
  </g>
  <text x="330" y="122" font-family="Liberation Sans" font-weight="bold"
        font-size="52" letter-spacing="16" fill="{BLUE}">BRUH</text>
  <text x="330" y="207" font-family="Liberation Sans" font-weight="bold"
        font-size="72" fill="{TEXT_LIGHT}">{name_line}</text>
  <text x="330" y="262" font-family="Liberation Sans" font-weight="bold"
        font-size="26" letter-spacing="7" fill="{TEXT_MUTED}">HOME ASSISTANT ADD-ON</text>
</svg>"""


FAVICON_INSIGHTS = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="{BG_BOTTOM}"/>
  <rect x="10" y="34" width="10" height="20" rx="3" fill="{BLUE}"/>
  <rect x="24" y="25" width="10" height="29" rx="3" fill="{VIOLET}"/>
  <rect x="38" y="16" width="10" height="38" rx="3" fill="{PINK}"/>
  <path fill="#ffffff" d="M53 8l1.7 5.3L60 15l-5.3 1.7L53 22l-1.7-5.3L46 15l5.3-1.7L53 8z"/>
</svg>
"""

FAVICON_MINECRAFT = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="{BG_BOTTOM}"/>
  <g>
    <rect x="12" y="12" width="40" height="16" fill="#5da838"/>
    <rect x="12" y="12" width="10" height="8" fill="{GREEN}"/>
    <rect x="32" y="20" width="10" height="8" fill="{GREEN}"/>
    <rect x="42" y="12" width="10" height="8" fill="#4a9a28"/>
    <rect x="22" y="20" width="10" height="8" fill="#4a9a28"/>
    <rect x="12" y="28" width="40" height="24" fill="#7a4f26"/>
    <rect x="22" y="28" width="10" height="8" fill="#6e4522"/>
    <rect x="42" y="36" width="10" height="8" fill="#6e4522"/>
    <rect x="12" y="44" width="10" height="8" fill="#6e4522"/>
    <rect x="32" y="36" width="10" height="8" fill="#8a5a2b"/>
    <rect x="12" y="28" width="10" height="8" fill="#4a9a28"/>
  </g>
</svg>
"""


ADDONS = {
    "claude-terminal": {
        "accent": CORAL,
        "glyph": glyph_terminal(),
        "name": "Claude Terminal",
        "dir": "bruh-claude-terminal",
    },
    "insights": {
        "accent": PINK,
        "glyph": glyph_insights(),
        "name": "Insights",
        "dir": "bruh-insights",
    },
    "minecraft": {
        "accent": GREEN,
        "glyph": glyph_minecraft(),
        "name": "Minecraft Server",
        "dir": "bruh-minecraft-server",
    },
}


def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  wrote {os.path.relpath(path, ROOT)}")


def render(svg: str, path: str, width: int, height: int) -> None:
    cairosvg.svg2png(
        bytestring=svg.encode(), write_to=path,
        output_width=width, output_height=height,
    )
    print(f"  rendered {os.path.relpath(path, ROOT)} ({width}x{height})")


def main() -> None:
    for key, spec in ADDONS.items():
        icon = icon_svg(spec["accent"], spec["glyph"])
        banner = banner_svg(spec["accent"], spec["glyph"], spec["name"])
        write(os.path.join(HERE, f"icon-{key}.svg"), icon)
        write(os.path.join(HERE, f"logo-{key}.svg"), banner)

        addon_dir = os.path.join(ROOT, spec["dir"])
        render(icon, os.path.join(addon_dir, "icon.png"), 512, 512)
        render(banner, os.path.join(addon_dir, "logo.png"), 1024, 320)

    # Panel favicons
    write(os.path.join(ROOT, "bruh-insights", "panel", "favicon.svg"), FAVICON_INSIGHTS)
    write(os.path.join(ROOT, "bruh-minecraft-server", "panel", "favicon.svg"), FAVICON_MINECRAFT)

    # bruh_claude integration branding (HA brands sizes: 256 + 512)
    terminal_icon = icon_svg(ADDONS["claude-terminal"]["accent"], ADDONS["claude-terminal"]["glyph"])
    brands_dir = os.path.join(ROOT, "brands", "custom_integrations", "bruh_claude")
    render(terminal_icon, os.path.join(brands_dir, "icon.png"), 256, 256)
    render(terminal_icon, os.path.join(brands_dir, "icon@2x.png"), 512, 512)
    render(
        terminal_icon,
        os.path.join(ROOT, "bruh-claude-terminal", "custom_components", "bruh_claude", "icon.png"),
        512, 512,
    )


if __name__ == "__main__":
    main()
