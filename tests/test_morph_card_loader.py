"""A card file defined twice on one page is not a broken card.

A house reported four cards (scenes, a room, two cameras) each showing
"the name … has already been used" as its own fault. A custom element is
defined once per page, and a card file runs again whenever its version
changes or Morph's own modules are served from a new URL after an update —
which starts a module-level record of what was loaded empty, so the old
loader read a second run as the first and filed it, once per card.

What is driven here: the page record lives on the window, a define of a
name the page already has is skipped (the element already drawing goes on
drawing), an import in flight is shared, a newer file whose elements exist
is a reload to offer rather than a fault, and a real failure is one fault
with its cause rather than one per card.
"""
import json
import subprocess
import textwrap
import unittest

from morph_env import FRONTEND


def run_node(body: str):
    script = textwrap.dedent(body)
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=30, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


UTIL = json.dumps((FRONTEND / "util.js").as_uri())

# A registry that behaves as the browser's does: a second define throws.
REGISTRY = """
const defined = new Map();
const registry = {
  get: (n) => defined.get(n),
  define(n, c) {
    if (defined.has(n)) throw new DOMException(`Failed to execute 'define' on 'CustomElementRegistry': the name "${n}" has already been used with this registry`);
    defined.set(n, c);
  },
};
"""


class TestADefinedCardIsNotAFault(unittest.TestCase):

    def test_a_card_file_run_again_does_not_throw_and_keeps_drawing(self):
        got = run_node(f"""
            const U = await import({UTIL});
            {REGISTRY}
            const page = {{ versions: new Map(), inflight: new Map(), redefined: new Set(), reported: new Set(), guarded: false }};
            U.guardDefine(registry, page);
            class A {{}}; class B {{}};
            // A file that defines two elements: run once, then again.
            const file = (cls) => () => {{ registry.define('morph-camera', cls); registry.define('morph-camera-wall', cls); }};
            const first = await U.loadCard('cams.js', 1, '/morph_cards/cams.js?v=1', file(A), page);
            const again = await U.loadCard('cams.js', 2, '/morph_cards/cams.js?v=2', file(B), page);
            console.log(JSON.stringify({{ first, again,
              camera: registry.get('morph-camera') === A, wall: registry.get('morph-camera-wall') === A,
              redefined: [...page.redefined].sort() }}));
        """)
        self.assertEqual("loaded", got["first"])
        self.assertEqual("changed", got["again"], "a newer file whose elements exist is a reload to offer")
        self.assertTrue(got["camera"] and got["wall"], "the element already registered goes on drawing")
        self.assertEqual(["morph-camera", "morph-camera-wall"], got["redefined"])

    def test_the_page_record_survives_morphs_own_modules_running_again(self):
        # Two evaluations of util.js (an update serves it from a new URL)
        # share one record, because it is kept on the window.
        got = run_node(f"""
            const one = await import({UTIL} + '?a');
            const two = await import({UTIL} + '?b');
            one.cardPage().versions.set('scenes.js', 7);
            console.log(JSON.stringify({{ same: one.cardPage() === two.cardPage(),
              seen: two.cardPage().versions.get('scenes.js') }}));
        """)
        self.assertTrue(got["same"])
        self.assertEqual(7, got["seen"])

    def test_a_card_already_loaded_at_this_version_is_not_imported_again(self):
        got = run_node(f"""
            const U = await import({UTIL});
            const page = {{ versions: new Map(), inflight: new Map(), redefined: new Set(), reported: new Set(), guarded: false }};
            let runs = 0;
            const start = () => {{ runs += 1; return new Promise((r) => setTimeout(r, 5)); }};
            const url = '/morph_cards/room.js?v=3';
            const [a, b] = await Promise.all([U.loadCard('room.js', 3, url, start, page), U.loadCard('room.js', 3, url, start, page)]);
            const c = await U.loadCard('room.js', 3, url, start, page);
            console.log(JSON.stringify({{ runs, a, b, c }}));
        """)
        self.assertEqual(1, got["runs"], "an import in flight is shared, and a loaded version is not run again")
        self.assertEqual("same", got["c"])

    def test_a_browser_throwing_redefined_is_not_a_failure_either(self):
        # Without the guard (another registry, an older page), the browser's
        # own refusal is read the same way and never thrown on.
        got = run_node(f"""
            const U = await import({UTIL});
            const page = {{ versions: new Map([['x.js', 1]]), inflight: new Map(), redefined: new Set(), reported: new Set(), guarded: false }};
            const start = () => Promise.reject(new DOMException('the name "morph-scenes" has already been used with this registry'));
            let out;
            try {{ out = await U.loadCard('x.js', 2, '/morph_cards/x.js?v=2', start, page); }} catch (e) {{ out = 'threw'; }}
            console.log(JSON.stringify({{ out }}));
        """)
        self.assertEqual("changed", got["out"])


class TestOneCauseIsOneFault(unittest.TestCase):

    def test_a_fetch_failure_names_no_card(self):
        got = run_node(f"""
            const U = await import({UTIL});
            const a = U.cardFailure(new TypeError('Failed to fetch dynamically imported module: https://h/morph_cards/cam.js?v=1'));
            const b = U.cardFailure(new TypeError('Failed to fetch dynamically imported module: https://h/morph_cards/septic.js?v=9'));
            const c = U.cardFailure(new ReferenceError('x is not defined'));
            console.log(JSON.stringify({{ a, b, c }}));
        """)
        self.assertEqual(got["a"], got["b"], "two cards failing for one cause are one fault")
        self.assertNotIn("cam.js", got["a"])
        self.assertIn("x is not defined", got["c"])

    def test_the_panel_loads_reports_and_dedupes_through_the_page_record(self):
        src = (FRONTEND / "morph-panel.js").read_text()
        start = src.index("  loadModules(mods) {")
        body = src[start:src.index("\n  }\n", start)]
        self.assertIn("guardDefine()", body)
        self.assertIn("loadCard(", body)
        self.assertIn("cardFailure(e)", body)
        rep = src[src.index("  report(kind, message, detail, cardType) {"):]
        self.assertIn("cardPage().reported", rep[:600])


if __name__ == "__main__":
    unittest.main()
