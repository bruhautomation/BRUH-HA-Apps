"""
Structural tests for `brain/ttyd-assets/inject.html`.

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
    / "brain"
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
    """The exact, ordered button set we ship today.

    Hard-coded so an accidental reorder / addition / deletion fails CI.
    If the toolbar genuinely should change, update this expectation in
    the same PR — that's the point.

    1.18.10 added `pgup` / `pgdn` between the arrow keys and the
    `^C/^D/^L/^U` group so mobile users can scroll Claude Code chat
    history (the desktop wheel→PgUp/PgDn handler in section 3 covers
    desktop).
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
        "pgup",
        "pgdn",
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


def test_toolbar_has_pgup_pgdn_buttons(script_block: str):
    """Regression test for 1.18.10.

    Mobile users can't produce a wheel event with their finger, so
    the only way they can scroll through Claude Code chat history
    is via these toolbar buttons. If anyone removes them, scrolling
    on touch silently breaks again."""
    keys = _toolbar_keys(script_block)
    assert "pgup" in keys, "PgUp toolbar button missing — mobile loses chat scroll-up"
    assert "pgdn" in keys, "PgDn toolbar button missing — mobile loses chat scroll-down"


def test_keys_map_has_pgup_pgdn(script_block: str):
    r"""The PgUp / PgDn buttons need real escape sequence entries in
    the KEYS map; the toolbar otherwise silently no-ops. Pin the
    canonical CSI ~5/~6 sequences so a typo doesn't ship."""
    assert re.search(r"'pgup':\s*'\\x1b\[5~'", script_block), (
        "'pgup' KEYS entry must be '\\x1b[5~'"
    )
    assert re.search(r"'pgdn':\s*'\\x1b\[6~'", script_block), (
        "'pgdn' KEYS entry must be '\\x1b[6~'"
    )


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


def test_no_synthetic_wheel_scroll_forwarder(script_block: str):
    """Regression test for 1.18.3 – 1.18.8's `setupScrollForwarder`.

    That code dispatched *synthetic WheelEvents* from touchmove. In
    Claude Code's alt-screen, xterm translated those to ↑/↓ key escape
    sequences, which the user saw as "every swipe moves the cursor".

    2.1.0 re-adds touch scrolling, but with a fundamentally different
    mechanism: the swipe handler reads the finger delta and calls
    `sendInput(PgUp/PgDn)` straight to the PTY — it never lets xterm
    interpret the gesture. So what we guard here is the BROKEN
    mechanism (the old name + synthetic WheelEvent dispatch), not
    touch handling in general. See `test_touch_scroll_sends_pgup_pgdn`
    for the positive side.
    """
    # The old function name must not come back.
    assert not re.search(r"function\s+setupScrollForwarder\s*\(", script_block), (
        "setupScrollForwarder is back — it caused the 'every swipe "
        "moves the cursor' symptom. The 2.1.0 approach is "
        "setupTouchScroll() + sendInput(PgUp/PgDn). See CHANGELOG."
    )
    assert not re.search(r"\bsetupScrollForwarder\s*\(\s*\)", script_block)
    # And nothing may synthesise WheelEvents — that's the root cause of
    # the arrow-key regression, regardless of what the handler is named.
    assert "new WheelEvent" not in script_block, (
        "touch/scroll code must not dispatch synthetic WheelEvents — "
        "xterm translates them to ↑/↓ arrow keys in alt-screen "
        "(1.18.9 regression). Send PgUp/PgDn via sendInput instead."
    )


def test_touch_scroll_sends_pgup_pgdn(script_block: str):
    r"""Positive test for 2.1.0 mobile swipe-to-scroll.

    Mobile users can't produce a wheel event with a finger, so without
    this the only chat-scroll affordance on touch is tapping the PgUp/
    PgDn toolbar buttons one page at a time. The swipe handler restores
    natural scrolling by translating a vertical drag into the same
    PgUp/PgDn sequences the wheel handler uses.
    """
    assert re.search(r"function\s+setupTouchScroll\s*\(", script_block), (
        "setupTouchScroll() missing — mobile swipe-to-scroll gone (2.1.0)"
    )
    assert re.search(r"\bsetupTouchScroll\s*\(\s*\)", script_block), (
        "setupTouchScroll() is never called — register it on touch devices"
    )
    # It has to listen to touchmove and page via the shared helper.
    assert "addEventListener('touchmove'" in script_block, (
        "no touchmove listener — swipe can't be detected"
    )
    assert "pageScroll(" in script_block, (
        "swipe handler must drive the shared pageScroll() accumulator"
    )
    # The canonical PgUp/PgDn sequences must be what gets sent.
    assert "\\x1b[5~" in script_block and "\\x1b[6~" in script_block


def test_scroll_paging_is_throttled(script_block: str):
    """Regression test for the "very difficult to scroll on PC" report.

    The 1.18.10 wheel handler sent one full PgUp/PgDn per raw wheel
    event. On a trackpad / smooth-scroll mouse that's dozens of events
    per gesture, so the view rocketed to the top uncontrollably. 2.1.0
    routes both wheel and touch through a shared pixel accumulator that
    only emits a page once enough distance has built up. Pin the helper
    + threshold so the throttle can't be silently dropped.
    """
    assert "function pageScroll" in script_block, "shared pageScroll() helper missing"
    assert re.search(r"SCROLL_PAGE_PX\s*=\s*\d+", script_block), (
        "SCROLL_PAGE_PX threshold constant missing — paging is un-throttled again"
    )
    # The wheel handler must feed normalised pixels into the accumulator
    # rather than emitting a page per event.
    assert "wheelDeltaPx(" in script_block, (
        "wheel handler should normalise deltaMode → px via wheelDeltaPx()"
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


# ---------------------------------------------------------------------
# OSC 52 clipboard interceptor (added in 1.18.10)
# ---------------------------------------------------------------------


def test_websocket_message_listener_attached(script_block: str):
    """The OSC 52 interceptor needs an `addEventListener('message', ...)`
    on the captured ttyd socket. If anyone refactors the WebSocket wrap
    and forgets to re-attach the listener, OSC 52 silently drops on
    the floor again — exactly the failure mode this test guards against.
    """
    # Look for a message listener attached to a `ws.` reference inside
    # the WebSocket wrap. We don't pin the exact handler name to allow
    # safe renaming.
    assert re.search(
        r"ws\.addEventListener\(\s*['\"]message['\"]",
        script_block,
    ), (
        "the captured ttyd WebSocket must have a 'message' listener "
        "for OSC 52 interception (1.18.10)"
    )


def test_osc52_start_marker_present(script_block: str):
    r"""The OSC 52 detection looks for the literal `\x1b]52;` start
    marker. If anyone changes that to a different escape framing
    (e.g. trying to also match OSC 7, 8, etc. and accidentally
    losing 52), the parser silently stops working — this test pins
    the exact marker so the failure becomes a CI failure.
    """
    assert "'\\x1b]52;'" in script_block, (
        r"OSC 52 start marker '\x1b]52;' missing — Claude Code's "
        "press-c-to-copy will silently no-op (1.18.10)"
    )


def test_osc52_end_terminators_present(script_block: str):
    r"""OSC sequences end with BEL (`\x07`) or ST (`\x1b\\`). The
    parser has to handle both — Claude Code historically emits BEL
    but other clients use ST."""
    assert "'\\x07'" in script_block, "OSC BEL terminator missing"
    assert "'\\x1b\\\\'" in script_block, "OSC ST terminator missing"


def test_osc52_writes_to_clipboard(script_block: str):
    """The interceptor must actually call `navigator.clipboard
    .writeText` — otherwise it parses OSC 52 sequences and throws
    them away. Pin the call so a refactor can't accidentally drop
    it."""
    assert (
        "navigator.clipboard.writeText" in script_block
        or "navigator.clipboard\n" in script_block
    ), "navigator.clipboard.writeText call missing from OSC 52 path"


def test_osc52_decodes_base64(script_block: str):
    """`atob` is the canonical base64 decode in browsers. The
    OSC 52 payload is base64-encoded text and we have to decode
    before writing to the clipboard."""
    assert "atob(" in script_block, "atob() call missing from OSC 52 decoder"


def test_osc52_buffer_is_bounded(script_block: str):
    """Defence against a misbehaving PTY stream: the cross-frame OSC 52
    buffer has to have a hard cap so a malicious / broken stream can't
    grow our memory unbounded. Pin the constant name so its existence
    is checked even if the value gets re-tuned."""
    assert "OSC_BUFFER_MAX" in script_block, (
        "OSC_BUFFER_MAX cap missing — OSC 52 buffer could grow "
        "unbounded (1.18.10)"
    )


def test_osc52_handles_query_payload(script_block: str):
    """Per the OSC 52 spec, a payload of `?` is a clipboard *query*
    (the application asks the terminal what's on the clipboard).
    Browsers don't allow page → clipboard reads without explicit
    permission and a user gesture, so we can't satisfy queries —
    must skip them rather than treating `?` as a base64 payload."""
    assert "'?'" in script_block, (
        "OSC 52 query payload check missing — `?` would be passed "
        "to atob() and produce garbage (1.18.10)"
    )


def test_osc52_has_user_facing_failure_path(script_block: str):
    """clipboard.writeText() can reject (no transient user activation,
    permission denied, etc.). We must surface the failure to the user
    rather than silently dropping the copy — otherwise they think
    "press c" worked when it didn't."""
    # Look for a fallback that stashes the text and surfaces a UI.
    assert "pendingClipboardText" in script_block, (
        "no fallback for clipboard.writeText rejection — copy can "
        "fail silently (1.18.10)"
    )
    # And there must be SOME visible affordance — the toast.
    assert "bruh-toast" in script_block, (
        "OSC 52 toast UI element missing"
    )


# ---------------------------------------------------------------------
# Wheel → PgUp/PgDn translator (1.18.10)
# ---------------------------------------------------------------------


def test_wheel_handler_attached(script_block: str):
    """The desktop scroll-chat-history fix relies on intercepting
    `wheel` events at the document level *before* xterm.js's own
    wheel handler runs. If the listener disappears, Claude Code's
    "Scroll wheel is sending arrow keys" banner reappears."""
    assert re.search(
        r"document\.addEventListener\(\s*['\"]wheel['\"]",
        script_block,
    ), "document-level wheel listener missing (1.18.10)"


def test_wheel_handler_uses_capture_phase(script_block: str):
    """Capture phase is what makes our wheel listener fire BEFORE
    xterm's own `.terminal` wheel listener (which lives in bubble
    phase). Without capture, xterm sees the wheel first and translates
    to arrow keys before we get a chance to preventDefault."""
    # Find the wheel listener registration and check it uses capture.
    m = re.search(
        r"document\.addEventListener\(\s*['\"]wheel['\"],[^)]*?\{([^}]*)\}",
        script_block,
    )
    assert m, "wheel listener registration not found (or no options object)"
    assert "capture: true" in m.group(1) or "capture:true" in m.group(1), (
        "wheel listener must register with capture: true so it fires "
        "before xterm.js's bubble-phase wheel handler (1.18.10)"
    )


def test_wheel_handler_sends_pgup_pgdn(script_block: str):
    r"""Pin the exact PgUp / PgDn sequences. If a regression sends
    arrow keys here (the symptom we're fixing) or PageDown CSI 22~
    instead of 6~ (a common typo), tests fail."""
    # Find the wheel handler body and check it sends both sequences.
    # The handler decides based on deltaY sign.
    assert "\\x1b[5~" in script_block, "PgUp escape sequence missing"
    assert "\\x1b[6~" in script_block, "PgDn escape sequence missing"


def test_wheel_handler_steps_aside_when_xterm_has_scrollback(script_block: str):
    """In normal-screen mode (bash with real xterm scrollback), wheel
    events should NOT be intercepted — xterm's own scrollback path is
    correct there. The handler must early-return when scrollHeight >
    clientHeight."""
    # The condition lives inside the wheel handler. Look for the
    # scrollHeight vs clientHeight check.
    assert re.search(
        r"vp\.scrollHeight\s*>\s*vp\.clientHeight",
        script_block,
    ), (
        "wheel handler must skip intercepting when xterm has its "
        "own scrollback (bash normal-screen mode) (1.18.10)"
    )


# ---------------------------------------------------------------------
# Don't shrink the body before the keyboard is up (1.18.10)
# ---------------------------------------------------------------------


def test_compute_gap_gates_on_focus(script_block: str):
    """Regression test for the "white cutout at first load" bug.

    Pre-1.18.10, computeGap() used the visualViewport's reported gap
    even when the textarea wasn't focused. On iOS the parent's VV
    reports a small offset at page load (status bar / notch safe-
    area inset) that exceeded our 40 px threshold, so we shrank the
    terminal and left a gap-sized white space at the bottom of the
    panel *before* the user ever tapped to focus.

    1.18.10 gates ALL gap detection on `taFocused === true`: no
    focus → no keyboard → no shrink, regardless of what VV reports.
    """
    # Find computeGap() and assert there's an early `if (!taFocused)
    # return 0;` near the top.
    m = re.search(
        r"function\s+computeGap\s*\(\)\s*\{(.*?)\n\s{4}\}",
        script_block,
        re.DOTALL,
    )
    assert m, "computeGap function not found"
    body = m.group(1)
    # The first ~25 lines of computeGap should contain the gate.
    head = "\n".join(body.split("\n")[:25])
    assert re.search(r"if\s*\(\s*!\s*taFocused\s*\)\s*return\s+0", head), (
        "computeGap() must early-return 0 when !taFocused — "
        "otherwise the terminal shrinks at page load before the "
        "user has tapped into it (1.18.10 white-cutout regression)"
    )
