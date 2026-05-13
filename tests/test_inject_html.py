"""
Structural tests for `bruh-claude-terminal/ttyd-assets/inject.html`.

This file is the mobile-UI splice that `scripts/build-mobile-index.py`
injects into ttyd's `<head>` at addon startup. It is small (one inline
`<style>`, one inline `<script>`) but historically every release between
1.18.0 and 1.18.8 broke it in subtle ways that only manifested on an
actual iOS HA Companion app device — by which point the bug was already
shipped. These tests catch the structural / regression-prone parts at
PR time so CI fails before a broken release goes out.

What we *can* check from Python:

  * The HTML has exactly one `<style>` and one `<script>` block, both
    at the file's top level (no nesting inside HTML comments).
  * The CSS section is well-formed (balanced braces) and contains the
    selectors the mobile UX depends on.
  * The JS section parses cleanly under `node --check`.
  * The script captures ttyd's WebSocket constructor, ships the iOS
    dictation diff-fix, and builds a toolbar with the canonical button
    set — no more, no less.
  * Specific layout decisions that have bitten us before:
    - body shrinks via `height: calc(100% - var(...))` (NOT
      `padding-bottom`, because ttyd's terminal-container is sized
      to body's BOX, not its content area — see 1.18.6).
    - body has `touch-action: none` (1.18.3) so swipes don't leak
      to the HA frontend.
    - tmux mouse mode is NOT presumed on (xterm.js disables native
      drag-selection when mouse mode is on — 1.18.8 trade-off).

What we *can't* check without a real browser: layout under a soft
keyboard, dictation event handling, native selection. Those are
manually verified per release.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INJECT_HTML = (
    REPO_ROOT
    / "bruh-claude-terminal"
    / "ttyd-assets"
    / "inject.html"
)


@pytest.fixture(scope="module")
def inject_text() -> str:
    return INJECT_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def style_block(inject_text: str) -> str:
    """The contents (no tags) of the inline `<style>` block."""
    style_open = inject_text.find("<style>")
    style_close = inject_text.find("</style>")
    assert style_open != -1 and style_close != -1, (
        "inject.html must contain exactly one <style> block"
    )
    return inject_text[style_open + len("<style>") : style_close]


@pytest.fixture(scope="module")
def script_block(inject_text: str) -> str:
    """The contents (no tags) of the inline `<script>` block.

    We find the *real* `<script>` tag, not the one inside the leading
    HTML comment ('<!-- ... <script> blocks ...-->'), by anchoring the
    search past `</style>`.
    """
    style_close = inject_text.find("</style>")
    assert style_close != -1, "inject.html is missing its </style>"
    script_open = inject_text.find("<script>", style_close)
    script_close = inject_text.find("</script>", script_open)
    assert script_open != -1 and script_close != -1, (
        "inject.html must contain exactly one <script> block after </style>"
    )
    return inject_text[script_open + len("<script>") : script_close]


# ---------------------------------------------------------------------
# File-level structure
# ---------------------------------------------------------------------


def test_inject_html_exists():
    assert INJECT_HTML.exists(), (
        f"{INJECT_HTML} not found — build-mobile-index.py needs this file"
    )
    assert INJECT_HTML.stat().st_size > 0, "inject.html is empty"


def test_inject_html_has_single_real_style_and_script(inject_text: str):
    """Exactly one top-level <style> and one top-level <script>.

    Mismatched counts mean build-mobile-index.py's `find('<head>')` would
    happily splice into a comment-embedded tag — and shipping a broken
    build is the failure mode we're trying to catch.
    """
    assert inject_text.count("<style>") == 1
    assert inject_text.count("</style>") == 1
    # The introductory HTML comment refers to `<script>` as plain text,
    # so the raw count is 2 — the second must be the real opening tag.
    # `</script>` only appears as the real closing tag (1).
    assert inject_text.count("<script>") == 2
    assert inject_text.count("</script>") == 1

    # And the real tag must follow </style>.
    style_close = inject_text.find("</style>")
    second_script_open = inject_text.find("<script>", style_close)
    assert second_script_open != -1


# ---------------------------------------------------------------------
# CSS section
# ---------------------------------------------------------------------


def test_css_braces_balanced(style_block: str):
    opens = style_block.count("{")
    closes = style_block.count("}")
    assert opens == closes, (
        f"CSS has unbalanced braces: {opens} '{{' vs {closes} '}}'"
    )


@pytest.mark.parametrize(
    "selector",
    [
        "#bruh-bar",
        ".bruh-key",
        "body.bruh-is-touch",
        "html.bruh-is-touch",
        # `body.bruh-is-touch .xterm-viewport` keeps touch scroll alive
        # in xterm's own viewport for normal-screen scrollback if it
        # ever materialises.
        "body.bruh-is-touch .xterm-viewport",
    ],
)
def test_css_contains_required_selector(style_block: str, selector: str):
    assert selector in style_block, (
        f"Required CSS selector missing: {selector!r}"
    )


def test_body_shrinks_via_height_not_padding(style_block: str):
    """Regression test for 1.18.6.

    Pre-1.18.6 we widened body's padding-bottom when the keyboard came
    up. ttyd's `#terminal-container { height: 100% }` measures against
    body's BOX (not its content box), so padding-bottom never made
    xterm.fit() see a smaller area — the input row stayed buried under
    the keyboard. 1.18.6 switched to shrinking body's BOX itself via
    `height: calc(100% - var(--bruh-bar-h, 56px))`. If anyone reverts
    that to padding-bottom in the future, the keyboard-overlap bug
    comes back; catch it here.
    """
    # The whole-line match is robust against insignificant whitespace.
    height_pat = re.compile(
        r"height:\s*calc\(\s*100%\s*-\s*var\(\s*--bruh-bar-h",
        re.IGNORECASE,
    )
    assert height_pat.search(style_block), (
        "body.bruh-is-touch must shrink via `height: calc(100% - "
        "var(--bruh-bar-h, ...))`; padding-bottom alone does not "
        "resize ttyd's #terminal-container (see 1.18.6 CHANGELOG)."
    )
    # And the padding-bottom variant must NOT be present on
    # body.bruh-is-touch — otherwise we'd silently regress.
    padding_pat = re.compile(
        r"body\.bruh-is-touch\s*\{[^}]*padding-bottom:\s*var\(\s*--bruh-bar-h",
        re.IGNORECASE | re.DOTALL,
    )
    assert not padding_pat.search(style_block), (
        "body.bruh-is-touch must NOT use padding-bottom for the bar/"
        "keyboard reserve — switch to height: calc(...) (1.18.6)."
    )


def test_body_blocks_native_panning(style_block: str):
    """Regression test for 1.18.3.

    `body { touch-action: none }` is what stops iOS from delegating
    swipes in the iframe up to the parent HA frontend (which would
    scroll the HA panel header off the top of the screen). Removing
    this regresses the original parent-scroll bug.
    """
    # The rule is inside body.bruh-is-touch's block somewhere; assert
    # the literal property text appears in the block.
    assert re.search(
        r"body\.bruh-is-touch\s*\{[^}]*touch-action:\s*none",
        style_block,
        re.DOTALL,
    ), "body.bruh-is-touch must set `touch-action: none`"


def test_toolbar_keys_disable_double_tap_zoom(style_block: str):
    """Regression test for 1.18.2 — `.bruh-key { touch-action:
    manipulation }` opts out of iOS's 300 ms double-tap-zoom delay and
    keeps the keyboard from blinking shut on slow taps."""
    assert re.search(
        r"\.bruh-key\s*\{[^}]*touch-action:\s*manipulation",
        style_block,
        re.DOTALL,
    ), ".bruh-key must set `touch-action: manipulation`"


def test_html_uses_overflow_hidden_not_position_fixed(style_block: str):
    """Regression test for 1.18.2.

    `position: fixed` on the root <html> is treated inconsistently by
    WebViews (Mobile Safari honours it, some Android WebViews ignore
    it, and it breaks Android adjustResize inside HA Companion). The
    correct lock is `overflow: hidden` + `height: 100%` on <html>.
    """
    html_rule = re.search(
        r"html\.bruh-is-touch\s*\{([^}]*)\}",
        style_block,
        re.DOTALL,
    )
    assert html_rule is not None, "html.bruh-is-touch rule missing"
    body = html_rule.group(1)
    assert "overflow: hidden" in body or "overflow:hidden" in body, (
        "html.bruh-is-touch must set overflow: hidden"
    )
    # The `position: fixed on <html>` antipattern must NOT be present.
    assert "position: fixed" not in body and "position:fixed" not in body, (
        "html.bruh-is-touch must NOT use `position: fixed` (1.18.2)"
    )


# ---------------------------------------------------------------------
# JS section: syntax + required behaviour
# ---------------------------------------------------------------------


def _have_node() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _have_node(), reason="node not available")
def test_js_passes_node_check(script_block: str, tmp_path: Path):
    """The inline script must parse without syntax errors."""
    js_file = tmp_path / "extracted.js"
    js_file.write_text(script_block, encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(js_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node --check failed:\n{result.stderr}"
    )


def test_js_wraps_websocket(script_block: str):
    """The toolbar can only push raw stdin to the PTY if we've captured
    ttyd's WebSocket. The wrap has to be installed before ttyd's inline
    bundle runs, which is why the splice is in <head>."""
    assert "WrappedWS" in script_block or "ttydSocket" in script_block
    assert "window.WebSocket" in script_block


def test_js_keeps_ios_dictation_diff_fix(script_block: str):
    """WebKit bug 261764: iOS voice dictation never fires
    `compositionstart`/`compositionend`; each interim transcript
    arrives as a plain `input` event whose textarea value contains the
    whole cumulative transcript so far. Without the diff-and-send
    handler, saying "testing" gets typed as "ttesttesting". Don't
    silently drop this fix."""
    assert "diffAndSend" in script_block
    assert "xterm-helper-textarea" in script_block
    assert "stopImmediatePropagation" in script_block


def test_js_defines_keys_map(script_block: str):
    """The `KEYS` map translates symbolic toolbar keys to the raw bytes
    that get sent over the WebSocket. At minimum the canonical Claude
    Code combos have to be there."""
    assert re.search(r"\bvar\s+KEYS\s*=\s*\{", script_block), (
        "expected a `KEYS = {` map"
    )
    # `\x1b` shows up as a literal backslash-x-1-b in the source.
    required_codes = [
        r"'esc':\s*'\\x1b'",
        r"'tab':\s*'\\x09'",
        r"'shtab':\s*'\\x1b\[Z'",
        r"'up':\s*'\\x1b\[A'",
        r"'down':\s*'\\x1b\[B'",
        r"'right':\s*'\\x1b\[C'",
        r"'left':\s*'\\x1b\[D'",
        r"'ctrlc':\s*'\\x03'",
        r"'ctrld':\s*'\\x04'",
        r"'ctrll':\s*'\\x0c'",
        r"'ctrlu':\s*'\\x15'",
        # Claude Code prefix chars
        r"'slash':\s*'/'",
        r"'at':\s*'@'",
        r"'hash':\s*'#'",
        r"'bang':\s*'!'",
        r"'pipe':\s*'\|'",
    ]
    for pattern in required_codes:
        assert re.search(pattern, script_block), (
            f"missing KEYS entry: {pattern}"
        )


# ---------------------------------------------------------------------
# Toolbar spec: positive and negative regressions
# ---------------------------------------------------------------------


# The toolbar `spec` is a JS array of `{ k, l, ... }` objects. We pull
# out every `k:` value with a regex on the relevant lines. Not a full
# JS parser, but the file format is tightly controlled.
_SPEC_KEY_PAT = re.compile(r"\{\s*k:\s*'([a-z]+)'", re.IGNORECASE)


def _toolbar_keys(script_block: str) -> list[str]:
    """Return the ordered list of toolbar button `k` identifiers."""
    spec_match = re.search(
        r"var\s+spec\s*=\s*\[(.*?)\];",
        script_block,
        re.DOTALL,
    )
    assert spec_match, "toolbar `spec` array not found"
    return _SPEC_KEY_PAT.findall(spec_match.group(1))


def test_toolbar_canonical_buttons(script_block: str):
    """The exact, ordered button set we ship in 1.18.9.

    Hard-coded so an accidental reorder / addition / deletion fails CI.
    If the toolbar genuinely should change, update this expectation in
    the same PR — that's the point.
    """
    expected = [
        "esc",
        "kbdown",
        "tab",
        "shtab",
        "up",
        "down",
        "left",
        "right",
        "ctrlc",
        "ctrld",
        "ctrll",
        "ctrlu",
        "slash",
        "at",
        "hash",
        "bang",
        "pipe",
        "paste",
        "hide",
    ]
    assert _toolbar_keys(script_block) == expected


def test_toolbar_has_close_keyboard_button(script_block: str):
    """`▾ Kbd` closes the on-screen keyboard by blurring xterm-helper-
    textarea. Without it the user has no way to dismiss the keyboard
    (taps outside the textarea are eaten by `body { touch-action: none }`).
    """
    keys = _toolbar_keys(script_block)
    assert "kbdown" in keys, "▾ Kbd button missing from toolbar"
    # And the handler does the right thing.
    assert re.search(
        r"keyName\s*===\s*'kbdown'.*?ta\.blur\(\)",
        script_block,
        re.DOTALL,
    ), "'kbdown' handler must call .blur() on the xterm helper-textarea"


def test_toolbar_no_history_scroll_button(script_block: str):
    """Regression test for the 1.18.8 `📜 Hist` button.

    That button sent `Ctrl+B [` to enter tmux copy mode, but tmux's
    copy mode in alt-screen mode shows the *normal-screen* history
    (i.e. pre-Claude-Code bash output), not Claude Code's chat — so
    tapping it produced confusing behaviour: a visible mode change,
    no useful scroll, and toolbar arrows that the user (correctly)
    perceived as "moving the cursor but not scrolling". Removed in
    1.18.9; the constraint is documented in the CHANGELOG.

    If a future release puts it back without re-thinking the alt-
    screen / scrollback model, fail loudly here.
    """
    keys = _toolbar_keys(script_block)
    assert "hist" not in keys, (
        "'hist' button is back — but tmux's copy mode in alt-screen "
        "doesn't show Claude Code's chat. See 1.18.9 CHANGELOG."
    )


def test_no_setup_scroll_forwarder(script_block: str):
    """Regression test for 1.18.3 – 1.18.8's `setupScrollForwarder`.

    The function dispatched synthetic WheelEvents from touchmove. In
    Claude Code's alt-screen the wheel translated to ↑/↓ key escape
    sequences, which the user saw as "every swipe moves the cursor".
    Removed in 1.18.9. Catch any future attempt to bring it back so
    we don't re-ship the symptom.
    """
    # Match a real function declaration / call only, not a passing
    # reference inside a comment.
    fn_decl = re.compile(r"function\s+setupScrollForwarder\s*\(")
    fn_call = re.compile(r"\bsetupScrollForwarder\s*\(\s*\)")
    assert not fn_decl.search(script_block), (
        "setupScrollForwarder is back — but it caused the 'every "
        "swipe moves the cursor' symptom in Claude Code TUI. See "
        "1.18.9 CHANGELOG."
    )
    assert not fn_call.search(script_block), (
        "setupScrollForwarder() is being called somewhere. The "
        "function was removed in 1.18.9; calling it now would be a "
        "ReferenceError."
    )
    # Also assert no document-level touchmove handler at all — that's
    # the underlying mechanism setupScrollForwarder used, and a
    # functionally-equivalent rename would still regress us.
    assert "addEventListener('touchmove'" not in script_block, (
        "document-level touchmove listener is back. body { touch-"
        "action: none } is the supported way to block iOS panning "
        "delegation; we shouldn't also be intercepting touchmove "
        "from JS (1.18.9)."
    )


# ---------------------------------------------------------------------
# handleKey() handler completeness
# ---------------------------------------------------------------------


def test_handle_key_handles_every_button(script_block: str):
    """Every `k` in the toolbar spec must have either:
      * a matching entry in KEYS (sent as literal bytes), or
      * a dedicated branch in handleKey() (special action).

    A typo'd `k` would silently no-op when tapped, which is the kind
    of bug that's hard to spot in code review but trivial to test.
    """
    keys = _toolbar_keys(script_block)
    special_handlers = re.findall(
        r"keyName\s*===\s*'([a-z]+)'",
        script_block,
    )
    keys_map = re.findall(r"'([a-z]+)':\s*'", script_block)
    keys_in_keys_map = set(keys_map)
    keys_in_handlers = set(special_handlers)

    for k in keys:
        assert k in keys_in_keys_map or k in keys_in_handlers, (
            f"toolbar key {k!r} has no KEYS entry and no handleKey() "
            f"branch — tapping it would do nothing"
        )
