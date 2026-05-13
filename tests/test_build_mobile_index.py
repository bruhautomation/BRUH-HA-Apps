"""Tests for `scripts/build-mobile-index.py`'s splice logic.

We can't easily test the full `build()` flow without a real `ttyd`
binary on PATH, but the splice — the part that has historically failed
in production (1.17.0's mis-extracted inline tags, 1.17.1's `</head>`
matching issues) — is a pure string operation. We import it and
exercise it directly.

The script is `build-mobile-index.py` (with a hyphen, not a valid
Python module name), so we load it via `importlib.util.spec_from_file
_location`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = (
    REPO_ROOT
    / "bruh-claude-terminal"
    / "scripts"
    / "build-mobile-index.py"
)


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    """Load `build-mobile-index.py` as a module despite the hyphen."""
    assert SCRIPT_PATH.exists(), f"missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "build_mobile_index", str(SCRIPT_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------
# splice_inject_into_html: positive path
# ---------------------------------------------------------------------


def test_splice_inserts_before_head_close(builder: ModuleType):
    html = "<html><head><title>x</title></head><body>hello</body></html>"
    snippet = "<style>.bruh{}</style>"
    out = builder.splice_inject_into_html(html, snippet)
    head_close_idx = out.find("</head>")
    snippet_idx = out.find(snippet)
    assert snippet_idx != -1, "snippet not present in merged output"
    assert snippet_idx < head_close_idx, (
        "snippet must come BEFORE </head> so our <script> runs in front "
        "of ttyd's inline bundle"
    )


def test_splice_preserves_full_input(builder: ModuleType):
    html = "<html><head><meta a=b></head><body>z</body></html>"
    snippet = "<!-- inject -->"
    out = builder.splice_inject_into_html(html, snippet)
    # All of the original head + body content survives.
    assert "<meta a=b>" in out
    assert "<body>z</body>" in out
    assert out.endswith("</html>")
    # Output length is input + snippet length.
    assert len(out) == len(html) + len(snippet)


def test_splice_uses_last_head_close(builder: ModuleType):
    """`rfind("</head>")` defends against a stray `</head>` inside an
    inline string literal in ttyd's bundle. The splice must land at
    the LAST occurrence, which is the structural one."""
    html = (
        "<html><head>"
        "<script>var x = '</head>';</script>"   # stray inside inline JS
        "</head><body>real</body></html>"
    )
    snippet = "<!--BRUH-->"
    out = builder.splice_inject_into_html(html, snippet)
    # The snippet must end up between the closing </script> and the
    # real </head> — i.e. AFTER the stray inside the JS string.
    stray_idx = out.find("var x = '</head>'")
    snippet_idx = out.find(snippet)
    real_head_close_idx = out.rfind("</head>")
    assert stray_idx < snippet_idx < real_head_close_idx


def test_splice_handles_uppercase_head(builder: ModuleType):
    """Some hand-written HTML uses `</HEAD>`. ttyd lowercases by
    convention but we match case-insensitively to be defensive."""
    html = "<HTML><HEAD>x</HEAD><BODY>y</BODY></HTML>"
    out = builder.splice_inject_into_html(html, "<!--Q-->")
    # The snippet lands before the uppercase tag.
    assert out.index("<!--Q-->") < out.index("</HEAD>")


def test_splice_case_preserving(builder: ModuleType):
    """We use `.lower()` to locate `</head>` but slice the ORIGINAL
    string, so the input's casing must survive unchanged in the
    output. If `splice_inject_into_html` ever switched to returning
    the lower-cased version, ttyd's case-sensitive attributes (e.g.
    `viewBox`) would break the React mount."""
    html = "<HTML><HEAD><DIV ViewBox='0 0 1 1'/></HEAD></HTML>"
    out = builder.splice_inject_into_html(html, "")
    assert "<HTML>" in out and "<HEAD>" in out
    assert "ViewBox='0 0 1 1'" in out
    assert "viewbox" not in out  # no accidental lower-casing


# ---------------------------------------------------------------------
# splice_inject_into_html: error path
# ---------------------------------------------------------------------


def test_splice_raises_when_no_head_close(builder: ModuleType):
    """No `</head>` means ttyd's HTML is malformed (or the probe came
    back with garbage). Should raise `SpliceError`, not silently
    no-op and write a corrupted index.html that ttyd then fails to
    serve."""
    html = "<html>no head here</html>"
    with pytest.raises(builder.SpliceError):
        builder.splice_inject_into_html(html, "<!--x-->")


def test_splice_error_preview_is_truncated(builder: ModuleType):
    """The error message includes a preview of the bad HTML so the
    add-on log shows something actionable. Make sure that preview is
    short — a megabyte of binary data dumped into the log isn't
    useful."""
    big_garbage = "X" * 10_000
    with pytest.raises(builder.SpliceError) as excinfo:
        builder.splice_inject_into_html(big_garbage, "")
    # The repr in the error message must NOT contain the full payload.
    assert len(str(excinfo.value)) < 500


# ---------------------------------------------------------------------
# End-to-end: splice the real inject.html into a fake ttyd HTML
# ---------------------------------------------------------------------


REAL_INJECT = (
    REPO_ROOT
    / "bruh-claude-terminal"
    / "ttyd-assets"
    / "inject.html"
)


def test_splice_real_inject_into_fake_ttyd_html(builder: ModuleType):
    """Smoke test: real inject.html + a plausible ttyd HTML shape
    produces a well-formed merged document with our <style> and our
    <script> running BEFORE ttyd's inlined bundle in document order.

    ttyd 1.7.x bakes its bundle into a single inline `<script>` tag at
    the end of `<body>` (via `inlineSource()`). Splicing our snippet
    just before `</head>` puts our `<script>` at the END of `<head>`,
    which runs first per the HTML spec's "inline scripts run in
    document order".
    """
    snippet = REAL_INJECT.read_text(encoding="utf-8")
    fake_ttyd = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "  <meta charset='utf-8'>\n"
        "  <title>ttyd</title>\n"
        "  <style>/* ttyd's inline styles */</style>\n"
        "</head>\n"
        "<body>\n"
        "  <div id='terminal-container'></div>\n"
        "  <script>console.log('ttyd inline bundle');</script>\n"
        "</body>\n"
        "</html>\n"
    )
    out = builder.splice_inject_into_html(fake_ttyd, snippet)

    # Our snippet is in the document.
    assert "bruh-bar" in out

    # Our <script> appears BEFORE ttyd's inline bundle in document
    # order (which is the whole point — we need to wrap WebSocket
    # before ttyd's bundle calls `new WebSocket(...)`).
    our_script_marker = "ttydSocket"      # variable from our snippet
    ttyd_script_marker = "ttyd inline bundle"
    assert our_script_marker in out, "our wrap script is missing from merged output"
    assert ttyd_script_marker in out, "ttyd bundle dropped from merged output"
    assert out.index(our_script_marker) < out.index(ttyd_script_marker), (
        "our WebSocket wrap must execute before ttyd's bundle "
        "(if ttyd's `new WebSocket(...)` runs first, we can't capture it)"
    )

    # The <body> + terminal-container survive intact.
    assert "<div id='terminal-container'></div>" in out
