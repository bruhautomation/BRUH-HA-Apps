#!/usr/bin/env python3
"""Tests for the brAIn add-on: the merged Terminal + Insights add-on.

Covers what is genuinely new in brAIn rather than re-testing the code it
inherited:

- the merged manifest (one ingress port, both faces switchable, no
  leftover git-backup options)
- the `brain` / `ha` CLI dispatchers and the split between them
- the edit journal hook that replaced git auto-backup
- `brain undo`
- the ttyd reverse proxy that makes the terminal a tab
"""

import json
import os
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
SCRIPTS = ADDON_DIR / "scripts"
PANEL = ADDON_DIR / "panel"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

class TestBrainManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())

    def test_identity(self):
        self.assertEqual(self.config["name"], "brAIn")
        self.assertEqual(self.config["slug"], "brain")

    def test_ingress_is_the_panel_not_ttyd(self):
        """One ingress port, owned by the panel — the terminal is proxied."""
        self.assertTrue(self.config["ingress"])
        self.assertEqual(self.config["ingress_port"], 8099)

    def test_ttyd_still_published_for_direct_access(self):
        self.assertIn("7681/tcp", self.config["ports"])

    def test_both_faces_are_switchable(self):
        for opt in ("enable_terminal", "enable_insights"):
            self.assertIn(opt, self.config["options"])
            self.assertIn(opt, self.config["schema"])

    def test_git_backup_options_are_gone(self):
        """Auto-backup was removed in favour of the edit journal."""
        for opt in ("auto_backup", "backup_interval_minutes"):
            self.assertNotIn(opt, self.config["options"])
            self.assertNotIn(opt, self.config["schema"])

    def test_edit_journal_option_present(self):
        self.assertIn("edit_journal_days", self.config["options"])

    def test_learning_option_is_not_assist_scoped(self):
        """Learning spans voice, insights and study — not just Assist."""
        self.assertIn("learning", self.config["options"])
        self.assertNotIn("assist_learning", self.config["options"])

    def test_every_option_has_a_schema_entry(self):
        for key in self.config["options"]:
            self.assertIn(key, self.config["schema"], f"{key} has no schema")

    def test_discovery_announces_the_brain_domain(self):
        self.assertEqual(self.config["discovery"], ["brain"])

    def test_version_matches_integration_manifest(self):
        manifest = json.loads(
            (ADDON_DIR / "custom_components" / "brain" / "manifest.json").read_text())
        self.assertEqual(manifest["version"], self.config["version"])
        self.assertEqual(manifest["domain"], "brain")


class TestNoStaleReferences(unittest.TestCase):
    """The rename has to be complete or half the add-on talks to itself."""

    def _all_text_files(self):
        skip_suffix = {".png", ".jpg", ".svg", ".ico"}
        # The changelog documents the rename, so the old names belong there.
        skip_names = {"CHANGELOG.md"}
        for path in ADDON_DIR.rglob("*"):
            if not path.is_file() or path.suffix in skip_suffix:
                continue
            if path.name in skip_names:
                continue
            try:
                yield path, path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

    def test_no_legacy_identifiers_remain(self):
        legacy = "bruh" + "_claude"  # split so this test never matches itself
        offenders = [str(p.relative_to(BASE_DIR))
                     for p, t in self._all_text_files() if legacy in t]
        self.assertEqual(offenders, [], f"stale {legacy} refs: {offenders}")

    def test_no_bruh_env_prefix_remains(self):
        offenders = [str(p.relative_to(BASE_DIR))
                     for p, t in self._all_text_files() if "BRUH_" in t]
        self.assertEqual(offenders, [], f"stale BRUH_ env refs: {offenders}")

    def test_worker_pool_moved_off_the_panel_port(self):
        """8099 is the panel's; the pool's internal API must not collide."""
        pool = (ADDON_DIR / "integrations" / "assist-worker-pool.py").read_text()
        self.assertIn('"BRAIN_API_PORT", "8098"', pool)


class TestPanelBranding(unittest.TestCase):
    """The panel is the only thing most users ever see, and a bulk rename
    can't reach text that is split across HTML tags."""

    @classmethod
    def setUpClass(cls):
        cls.html = (PANEL / "index.html").read_text()
        cls.js = (PANEL / "app.js").read_text()

    def test_wordmark_reads_brain(self):
        """The bar carries the real wordmark, not a mark plus a word. The
        gable IS the "A", so the lockup can't be assembled from an icon and
        live text — and it can't be checked by reading the text either, so
        this pins the pieces the lockup is made of."""
        self.assertIn('class="wordmark"', self.html)
        self.assertIn('aria-label="brAIn"', self.html)
        # BR ligature, gable-A, and the N's diagonal: if any goes, the mark
        # silently degrades into something that isn't the logo.
        for part in ("M159.55,176c0-23.95",          # BR ligature
                     "M186,333 L239,198",            # A
                     "M362,198 L377,198 L486,333"):  # N diagonal
            self.assertIn(part, self.html, "the wordmark lost a glyph")

    # brAIn's roof is the parent's own path, unmodified. Minecraft's is the
    # same roof redrawn on the block grid — same apex, same 45° slopes, same
    # knockout window, stepped instead of smooth — so that the roof and the MC
    # caps are built to one rule rather than two.
    SMOOTH_GABLE = "M293.5,21.6V70.83S189.86,174.05,188.83,175.5H450.09Z"
    BLOCKY_GABLE = "M188.83,175.5V158.4H200.46"

    def test_the_mark_is_the_gable(self):
        """Each app's roof is one path, used everywhere that app appears —
        inline in the bar, in the favicon, in every rendered PNG. A second
        hand-drawn copy is how a mark drifts.

        The two apps do not share the *same* roof any more, and that is the
        point: an app whose caps are blocky and whose roof is smooth is two
        drawings in one lockup."""
        self.assertIn(self.SMOOTH_GABLE, self.html, "the top bar isn't drawing the gable")
        self.assertIn(self.SMOOTH_GABLE, (PANEL / "favicon.svg").read_text())

        for app, gable in (("brain", self.SMOOTH_GABLE), ("minecraft", self.BLOCKY_GABLE)):
            for svg in sorted((BASE_DIR / "branding" / app).glob("*.svg")):
                self.assertIn(gable, svg.read_text(),
                              f"{svg.name} does not carry {app}'s gable path")

    def test_each_app_draws_only_its_own_roof(self):
        """The blocky roof belongs to Minecraft and the smooth one to brAIn.
        Mixing them is the failure this catches: a Minecraft square built from
        a brAIn tile would pass every other check here."""
        for app, mine, theirs in (("brain", self.SMOOTH_GABLE, self.BLOCKY_GABLE),
                                  ("minecraft", self.BLOCKY_GABLE, self.SMOOTH_GABLE)):
            for svg in sorted((BASE_DIR / "branding" / app).glob("*.svg")):
                body = svg.read_text()
                self.assertIn(mine, body, f"{svg.name} lost its own roof")
                self.assertNotIn(theirs, body, f"{svg.name} is wearing the other app's roof")

        mc_favicon = (BASE_DIR / "bruh-minecraft-server" / "panel" / "favicon.svg").read_text()
        self.assertIn(self.BLOCKY_GABLE, mc_favicon,
                      "the Minecraft favicon is not the blocky roof")
        self.assertNotIn(self.SMOOTH_GABLE, mc_favicon,
                         "the Minecraft favicon is wearing brAIn's roof")

    def test_no_asset_is_the_gable_alone(self):
        """The gable is the *family* mark: it says BRUH and says nothing about
        which add-on you are looking at. Two add-ons putting the same roof in
        the same Home Assistant sidebar are two add-ons nobody can tell apart,
        so every shipped asset carries the BR ligature too — including the
        squares and the favicons, which is exactly where the temptation to drop
        back to a bare roof lives."""
        ligature = "M159.55,176c0-23.95"
        for svg in sorted((BASE_DIR / "branding").glob("*/*.svg")):
            self.assertIn(ligature, svg.read_text(),
                          f"{svg.name} is the gable without the BR ligature")
        for panel in ("brain", "bruh-minecraft-server"):
            favicon = BASE_DIR / panel / "panel" / "favicon.svg"
            self.assertIn(ligature, favicon.read_text(),
                          f"{panel}'s favicon is the gable without the BR ligature")

    def test_both_apps_have_a_full_brand_set(self):
        """Twelve files each, same names, so render.mjs and anything else that
        reaches for a variant can do it by pattern rather than by special case."""
        for app, stem in (("brain", "brain"), ("minecraft", "bruh-minecraft")):
            for shape in ("logo-onlight", "logo-ondark", "logo-onazure",
                          "logo-mono-black", "logo-mono-white",
                          "square-onlight", "square-ondark",
                          "square-mono-black", "square-mono-white",
                          "tile-dark", "tile-azure", "tile-light"):
                path = BASE_DIR / "branding" / app / f"{stem}-{shape}.svg"
                self.assertTrue(path.exists(), f"missing {path.relative_to(BASE_DIR)}")

    def test_the_two_apps_are_told_apart_by_their_caps(self):
        """What distinguishes the marks is the drawing of the small caps and
        the roof together. brAIn sets AIN smooth over the parent's smooth gable
        and keeps its signal rules; Minecraft sets MC on a 16u block grid under
        a stepped roof, and drops the signal so the blocks carry it alone.
        Swapping either is how the two apps stop being distinguishable."""
        brain = (BASE_DIR / "branding" / "brain" / "brain-logo-ondark.svg").read_text()
        mc = (BASE_DIR / "branding" / "minecraft" / "bruh-minecraft-logo-ondark.svg").read_text()
        self.assertIn("M186,333 L239,198", brain, "brAIn lost its A")
        self.assertIn("M362,198 L377,198 L486,333", brain, "brAIn lost its N diagonal")
        self.assertNotIn("M186,333 L239,198", mc,
                         "the Minecraft mark is carrying brAIn's smooth caps")
        # The blocky MC is built from 16-unit rects, which brAIn never uses.
        self.assertIn('width="16" height="16"', mc, "the Minecraft caps aren't blocky")

    def test_the_inline_mark_follows_the_theme(self):
        """One SVG serves a light and a dark bar, so its three brand roles
        have to be separable: the B/R/N follow the theme's ink, the roof is
        azure and stays azure, and the "AI" plus the signal motif are always
        the same colour as each other. And the window in the roof is a
        knockout — a filled shape would blot it out."""
        css = (PANEL / "style.css").read_text()
        for role in ("wm-ink", "wm-roof", "wm-ai", "wm-signal"):
            self.assertIn(f'class="{role}"', self.html,
                          f"the wordmark has no {role} shapes")
            self.assertIn(f".{role} {{", css, f"{role} is unstyled")
        self.assertIn("--wm-ink: var(--ink)", css, "the ink doesn't follow the theme")
        self.assertIn("--wm-roof: #1e9fe0", css, "the roof was recoloured")
        self.assertIn('fill-rule="evenodd"', self.html)

    def test_retired_marks_are_gone(self):
        """The neural mesh and the solid-brain variant were two directions
        kept while the choice was open. It is closed."""
        icons = BASE_DIR / "branding" / "icons"
        for stale in ("brain.svg", "brain-alt-solid.svg", "brain-logo.svg",
                      "brain-logo-alt-solid.svg", "bruh-terminal.svg",
                      "bruh-insights.svg",
                      # Gable-only art, retired when the squares arrived: an
                      # icon that doesn't say which app it is isn't an icon.
                      "brain-icon.svg", "brain-icon-mono-black.svg",
                      "brain-icon-mono-white.svg", "brain-app-tile-dark.svg",
                      "brain-app-tile-azure.svg", "bruh-mark.svg",
                      # The old Minecraft cube: a gradient plate and an
                      # isometric block, sharing nothing with the family.
                      "bruh-minecraft.svg"):
            self.assertFalse((icons / stale).exists(),
                             f"branding/icons/{stale} belongs to a retired mark")

    def test_no_old_product_names_are_rendered(self):
        """Catches the split-tag case: `BRUH <span>Insights</span>` reads as
        "BRUH Insights" on screen but never matches a naive replace."""
        import re
        text = re.sub(r"<[^>]+>", "", self.html)
        text = re.sub(r"\s+", " ", text)
        for stale in ("BRUH Insights", "BRUH Terminal", "BRUH Claude"):
            self.assertNotIn(stale, text, f"panel still shows {stale!r}")

    def test_panel_does_not_send_users_to_itself(self):
        """Hints inherited from the standalone add-ons told you to go run a
        command in the *other* add-on. Now that there is only one, that
        advice points at the thing you are already looking at."""
        for stale in ("brAIn add-on? Run", "if <b>brAIn</b> is installed"):
            self.assertNotIn(stale, self.html)

    def test_no_retired_cli_names_in_the_ui(self):
        for stale in ("ha-share-login", "ha-memory", "ha-backup"):
            self.assertNotIn(stale, self.html, f"panel references {stale}")

    def test_every_view_tab_has_a_pane(self):
        for view in ("insights", "findings", "terminal", "memory", "docs"):
            self.assertIn(f'data-view="{view}"', self.html)
            self.assertIn(f'id="view{view.capitalize()}"', self.html)

    def test_terminal_frame_is_lazy_and_points_at_the_proxy(self):
        self.assertIn('id="termFrame"', self.html)
        self.assertIn('src="about:blank"', self.html)
        self.assertIn('frame.src = "terminal/"', self.js)

    def test_memory_pane_is_adopted_rather_than_duplicated(self):
        """Duplicating the markup would duplicate every id with it."""
        self.assertIn("adoptMemoryPane", self.js)
        self.assertEqual(self.html.count('id="kAddForm"'), 1)


class TestTopbarLayout(unittest.TestCase):
    """The bar has two shapes: one 56px row on a pointer-sized screen, and a
    two-row phone bar with the tabs on a strip of their own.

    It used to have one shape and five breakpoints, holding a 48px row at
    every width by deleting text until it fit — tab labels first, then the
    words inside the status chips. On a phone that left five unlabelled
    glyphs and a bare amber dot, with the only copy in a title attribute, on
    the one device that cannot hover to read it.

    Pixel fitting is verified by rendering the bar in a browser
    (tests/manual/measure-topbar.mjs, which also fails any target under
    44px); this pins the structure that the fitting depends on."""

    @classmethod
    def setUpClass(cls):
        cls.html = (PANEL / "index.html").read_text()
        cls.css = (PANEL / "style.css").read_text()
        cls.js = (PANEL / "app.js").read_text()

    def test_nothing_in_the_bar_may_shrink(self):
        """A shrinking chip compresses its own nowrap text and reads as a
        rendering glitch rather than as 'too narrow' — it fails invisibly.
        Refusing to shrink is what makes an overflow visible to the browser
        test instead of silently ugly."""
        self.assertIn(".topbar > * { flex: none; }", self.css)

    def test_touch_targets_are_at_least_44px(self):
        """32px tabs and 26px chips were mouse sizes on a bar that spends
        half its life on a phone. 44px is the floor for a tab or a button;
        chips are text pills and sit at 40."""
        import re
        tab = re.search(r"\n\.viewtab \{(.*?)\n\}", self.css, re.S)
        self.assertIsNotNone(tab, "no .viewtab rule")
        self.assertIn("height: 44px", tab.group(1))
        self.assertIn("min-width: 44px", tab.group(1))
        self.assertIn(".topbar .btn.icon { width: 44px; height: 44px; }", self.css)
        self.assertRegex(self.css, r"\.topbar \.chip \{ height: 40px")

    def test_chips_never_collapse_to_a_bare_dot(self):
        """An amber dot with no word beside it says something is going on
        without saying what — and it appeared at exactly the widths where
        hovering for the title text isn't possible. Nothing may hide a chip's
        words; what gives way instead is the row."""
        self.assertNotIn(".chipwords", self.css)
        self.assertNotIn("chipwords", self.html)
        for chip_text in ("authChipText", "pausedChipText"):
            self.assertIn(f'id="{chip_text}"', self.html)

    def test_usage_numbers_are_labelled_in_the_bar(self):
        """'19% · 100%' is two readings with nothing saying which window
        either belongs to. The label sits next to the number, in the bar —
        not in a tooltip."""
        self.assertIn('<span class="ulab">Session</span>', self.html)
        self.assertIn('<span class="ulab">Week</span>', self.html)
        self.assertIn('id="usageChipPct"', self.html)
        self.assertIn('id="usageChipWeekPct"', self.html)
        import re
        for span in ("usageChipPct", "usageChipWeekPct"):
            m = re.search(r'\$\("#%s"\)\.textContent = (.+);' % span, self.js)
            self.assertIsNotNone(m, f"{span} is never set")
            self.assertNotIn("reset", m.group(1),
                             "reset times belong in the hover, not the bar")

    def test_the_reset_times_are_behind_a_press_not_a_hover(self):
        """When each usage window rolls over is the one fact the pill has no
        room for — and it lived in a `title`, which on a phone is a fact that
        exists and cannot be read. Pressing the pill opens it in place."""
        body = self.js[self.js.index("function renderUsageChip()"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("chip.removeAttribute(\"title\")", body)
        self.assertNotIn("chip.title =", body)
        fill = self.js[self.js.index("function fillUsagePop()"):]
        fill = fill[:fill.index("\n}\n")]
        self.assertIn("resets_at", fill)
        self.assertIn("week_resets_at", fill)
        self.assertIn('id="chipPop"', self.html)

    def test_every_control_in_the_bar_does_its_own_job(self):
        """Three controls all opened Settings, so a bar that reported three
        different things answered all of them with the same dialog. The pill
        opens its own reset times, the paused chip switches automatic
        insights back on, and ⚙ is the one route to Settings."""
        import re
        handlers = dict(re.findall(
            r'\$\("#(\w+)"\)\.addEventListener\("click", (.{0,90})', self.js,
            re.S))
        self.assertIn("openSettings", handlers.get("settingsBtn", ""))
        self.assertNotIn("openSettings", handlers.get("usageChip", ""))
        self.assertNotIn("openSettings", handlers.get("pausedChip", ""))
        self.assertIn("toggleChipPop", handlers.get("usageChip", ""))
        # The paused chip's press is the switch itself, not a trip to a
        # dialog that holds the switch.
        press = self.js[self.js.index('$("#pausedChip").addEventListener'):]
        press = press[:press.index("\n});")]
        self.assertIn("auto_enabled: true", press)

    def test_collapsed_chips_keep_their_meaning(self):
        """Sighted users read the words; a screen reader reads the label."""
        self.assertIn('chip.setAttribute("aria-label"', self.js)

    def test_the_healthy_auth_chip_does_not_exist_at_any_width(self):
        """"Claude · subscription" was a permanent green label for a state
        that never changes, and it cost 165px of the widest band. The chip is
        now only rendered when there is trouble — checking, failed, or not
        connected — so nothing has to make room for the settled case."""
        self.assertIn('id="authChip" class="chip hidden"', self.html)
        self.assertIn('chip.classList.toggle("hidden", settled)', self.js)

    # The staged bands, widest first. Sliced out of the CSS rather than
    # listed here: the widths move whenever anything joins the bar, and a
    # test that hardcodes them only ever says "someone changed the numbers".
    def _bands(self):
        import re
        tail = self.css[self.css.index("The bar never wraps text away to fit"):]
        parts = re.split(r"@media \(max-width: (\d+)px\) \{", tail)
        return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]

    def test_the_bar_changes_layout_in_stages(self):
        """One breakpoint could not work: the labelled row needs ~1200px and
        the phone bar fits 320. The exact widths are measured by
        tests/manual/measure-topbar.mjs, which renders all three bar states
        and fails on any overflow. This pins that the staging exists at all
        and reads downward."""
        widths = [w for w, _ in self._bands()]
        self.assertGreaterEqual(len(widths), 2, "the bar needs staged bands")
        self.assertEqual(widths, sorted(widths, reverse=True),
                         "bands must narrow monotonically")

    def test_no_width_gets_a_row_of_bare_glyphs(self):
        """There used to be a middle band — one row, tab labels deleted,
        tabs shrunk to icons — and it covered 960 to 1239px, which is what a
        laptop with the HA sidebar open actually renders. So the compromise
        shape was the one most people saw, and widening the window made the
        tabs grow, which reads as a bug. Labels now leave only when the
        single row does, and the two-row bar keeps them."""
        self.assertNotIn(".viewtab span:not(.badge) { display: none; }", self.css)
        phone = next((css for _, css in self._bands()
                      if "flex-wrap: wrap" in css), None)
        self.assertIsNotNone(phone, "no band turns the bar into the two-row shape")
        self.assertIn("flex-direction: column", phone)
        self.assertIn(".viewtab span:not(.badge) {", phone)
        self.assertIn("width: 100%", phone, "the tabs need a strip of their own")
        for view in ("insights", "findings", "terminal", "memory", "docs"):
            self.assertIn(f'data-view="{view}"', self.html)

    def test_the_two_row_tabs_stop_growing_with_the_window(self):
        """Five equal shares of a phone is a thumb-sized tab; five equal
        shares of 1200px is a 240px target with a 20px glyph adrift in it.
        The tabs cap and centre instead."""
        phone = next((css for _, css in self._bands()
                      if "flex-wrap: wrap" in css), None)
        self.assertIn("justify-content: center", phone)
        self.assertRegex(phone, r"max-width: \d+px;")

    def test_badges_survive_the_phone_layout_as_a_corner_count(self):
        """A badge you can't see is a decision nobody makes. Stacked tabs
        can't hold it in the row, so it pins to the icon's corner rather
        than disappearing or collapsing to an unreadable dot."""
        phone = next((css for _, css in self._bands()
                      if "flex-wrap: wrap" in css), None)
        badge = phone.split(".viewtab .badge {")[1][:300]
        self.assertIn("position: absolute", badge)
        self.assertNotIn("display: none", badge)
        self.assertNotIn("font-size: 0;", badge, "a badge with no text is a dot")

    def test_the_terminal_is_sized_from_a_measured_bar(self):
        """The phone bar is two rows and goes to three when a trouble chip
        joins the usage pill, so 'viewport minus 48px' is wrong at three
        different heights. --bar-h is a per-layout fallback that the panel
        overwrites with what the bar actually measures."""
        self.assertIn("--bar-h", self.css)
        self.assertIn("height: calc(100dvh - var(--bar-h))", self.css)
        self.assertIn("trackBarHeight", self.js)
        self.assertIn("bar.getBoundingClientRect()", self.js)

    def test_measuring_the_bar_does_not_feed_on_its_own_last_answer(self):
        """`.topbar { height: var(--bar-h) }` and the panel writes --bar-h
        from the measured bar, so measuring while our inline override is in
        place measures the previous measurement.

        Stable at rest, and wrong exactly once: immersive sets 0, and on the
        way back out the bar is visible again but pinned to 0 by our own
        inline value, so it renders clipped — and the next measurement
        latches the clipped height. That is the half-height header after a
        round trip through the full-screen terminal.

        Two rules keep it honest: clear the override before measuring, and
        never write a zero (the CSS class already says 0, and an inline 0
        would outlive the class that justified it)."""
        self.assertIn("height: var(--bar-h)", self.css)
        body = self.js.split("function syncBarHeight(")[1].split("\n}")[0]
        self.assertIn('removeProperty("--bar-h")', body)
        self.assertLess(body.index('removeProperty("--bar-h")'),
                        body.index("getBoundingClientRect()"),
                        "clear the override BEFORE measuring, or it measures itself")
        self.assertIn("if (h > 0)", body)

    def test_the_terminal_can_fold_the_bar_away(self):
        """A phone with the keyboard up gave the terminal about a third of
        the screen: HA's header, our two rows, the tab strip, the keyboard.
        The bar folds — on ⤢, and by itself while the keyboard is up, which
        only the ttyd frame can see and so is where it is reported from."""
        self.assertIn("body.term-immersive .topbar { display: none; }", self.css)
        self.assertIn("body.term-immersive { --bar-h: 0px; }", self.css)
        self.assertIn('id="termExpand"', self.html)
        self.assertIn("brain-keyboard", self.js)
        inject = (ADDON_DIR / "ttyd-assets" / "inject.html").read_text()
        self.assertIn("brain-keyboard", inject)
        self.assertIn("function reportKeyboard(", inject)
        # A press of ⤢ outlives a reload; the keyboard's fold does not. And
        # it goes through prefSet, because a browser may refuse an iframe its
        # storage — a throw there would take out every handler bound below.
        self.assertIn('prefSet("brain.termFull"', self.js)
        self.assertIn("try { return localStorage.getItem(key); }", self.js)


class TestHypothesisIdentity(unittest.TestCase):
    """ts doubles as the id the panel settles by."""

    def setUp(self):
        import tempfile
        sys.path.insert(0, str(PANEL))
        import hypotheses
        self.mod = hypotheses
        self.tmp = tempfile.TemporaryDirectory()
        self._old = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "h.jsonl"

    def tearDown(self):
        self.mod.HYPOTHESES_FILE = self._old
        self.tmp.cleanup()

    def test_claims_proposed_in_the_same_second_get_distinct_ids(self):
        """A study session proposes several at once. Colliding ids made the
        panel settle the FIRST match — so clicking ✓ on the second row
        confirmed the first one instead."""
        made = [self.mod.propose(f"claim {i}") for i in range(3)]
        self.assertEqual(len({m["ts"] for m in made}), 3)

    def test_settling_acts_on_the_row_you_picked(self):
        a, b, c = (self.mod.propose(f"claim {i}") for i in range(3))
        self.mod.confirm(b["ts"])
        by_text = {e["text"]: e["status"] for e in self.mod.list_all()}
        self.assertEqual(by_text["claim 1"], "confirmed")
        self.assertEqual(by_text["claim 0"], "open")
        self.assertEqual(by_text["claim 2"], "open")

    def test_rejecting_acts_on_the_row_you_picked(self):
        a, b, c = (self.mod.propose(f"claim {i}") for i in range(3))
        self.mod.reject(c["ts"])
        by_text = {e["text"]: e["status"] for e in self.mod.list_all()}
        self.assertEqual(by_text["claim 2"], "rejected")
        self.assertEqual(by_text["claim 0"], "open")


class TestChatTerminalPanel(unittest.TestCase):
    """The chat terminal's half of the Terminal tab. The session itself is
    covered by tests/test_chat_terminal.py; this is the markup and the
    handlers, which is where "the tab is blank" comes from."""

    @classmethod
    def setUpClass(cls):
        cls.html = (PANEL / "index.html").read_text()
        cls.js = (PANEL / "app.js").read_text()
        cls.css = (PANEL / "style.css").read_text()

    def test_both_faces_live_in_the_terminal_tab(self):
        """One tab, two renderings of the same session — not a sixth tab."""
        self.assertIn('id="termChat"', self.html)
        self.assertIn('id="termFrame"', self.html)
        self.assertIn("body:not(.term-classic) #viewTerminal.active .chat", self.css)
        self.assertIn("body:not(.term-classic) #viewTerminal.active #termFrame",
                      self.css)

    def test_the_composer_is_a_real_textarea(self):
        """The whole point: dictation, autocorrect, selection and the system
        keyboard all behave, because there is no hidden xterm helper element
        for them to fight with. And 16px, because anything smaller makes iOS
        zoom the page on focus."""
        self.assertIn('<textarea id="chatInput"', self.html)
        self.assertRegex(self.css, r"\.chatbar textarea \{[^}]*font-size: 16px")

    def test_code_blocks_scroll_inside_themselves(self):
        """The one thing that genuinely wants a character grid keeps one —
        without making the page scroll sideways to give it."""
        import re
        block = re.search(r"\.msg\.bot pre, \.chat pre \{(.*?)\}", self.css, re.S)
        self.assertIsNotNone(block, "no code-block rule")
        self.assertIn("overflow-x: auto", block.group(1))

    def test_model_output_is_escaped_before_it_is_rendered(self):
        """Chat content is the one thing in this panel that is neither
        authored by us nor typed by the user, so it is exactly where a lazy
        innerHTML becomes an injection vector."""
        self.assertIn("node.innerHTML = renderMarkdown(", self.js)
        self.assertIn("function esc(s)", self.js)
        # renderMarkdown escapes first — pinned by the docs tests too, but
        # this is the caller that makes it load-bearing.
        self.assertIn("inlineMd(s)", self.js)

    def test_tool_calls_collapse_to_one_line(self):
        """Twenty lines of JSON per call is what made the grid terminal
        unreadable; the name and what it was aimed at is what a reader
        scanning back actually wants."""
        self.assertIn("function chatToolNode(", self.js)
        self.assertIn('el("span", "tsum"', self.js)
        self.assertIn(".toolcall > summary", self.css)
        # A failure opens itself: it is the reason the next thing Claude
        # says will look strange.
        self.assertIn("if (!ev.ok) box.open = true;", self.js)

    def test_the_stream_is_dropped_when_the_tab_is_not_in_front(self):
        """An open SSE for a tab nobody is looking at holds a connection and
        a subscriber for nothing."""
        self.assertIn("function chatDisconnect()", self.js)
        self.assertIn("chatDisconnect();", self.js)

    def test_the_mode_is_a_setting_not_a_browser_preference(self):
        """It is a property of this brAIn, not of the device that happened
        to open it — and ⚙ Settings is where someone goes looking for it
        after switching by accident."""
        self.assertIn('id="setTerminalUi"', self.html)
        self.assertIn("terminal_ui", self.js)
        store = (PANEL / "settings_store.py").read_text()
        self.assertIn('TERMINAL_UIS = ("chat", "classic")', store)
        self.assertIn('"terminal_ui": "chat"', store)

    def test_the_switch_is_also_where_the_terminal_is(self):
        """Nobody goes to Settings to change what they are looking at."""
        self.assertIn('id="termMode"', self.html)
        self.assertIn('$("#termMode").addEventListener("click"', self.js)

    def test_both_faces_stand_in_the_same_project_directory(self):
        """Claude Code files conversations under
        ~/.claude/projects/<escaped-cwd>/ and `--resume` only lists the ones
        belonging to the directory you are in. If the tmux session inherits
        some other cwd from the add-on's init, the two faces of this tab keep
        their conversations where the other cannot see them — and
        /config/CLAUDE.md and /config/.claude/settings.local.json stop
        applying to the terminal at the same time."""
        import re
        run = (ADDON_DIR / "run.sh").read_text()
        menu = (SCRIPTS / "brain-menu.sh").read_text()
        self.assertIn('CLAUDE_PROJECT_DIR="/config"', run)
        for launch in re.findall(r"tmux new-session[^\n]*", run):
            self.assertIn("-c '${CLAUDE_PROJECT_DIR}'", launch, launch)
        for launch in re.findall(r"^\s*(?:exec )?tmux new-(?:session|window)[^\n]*",
                                 menu, re.M):
            self.assertIn('-c "$CLAUDE_PROJECT_DIR"', launch, launch)
        chat = (PANEL / "chat_session.py").read_text()
        self.assertIn('BRAIN_CHAT_WORKDIR", "/config"', chat)

    def test_a_subscription_is_not_shown_a_price_per_message(self):
        """total_cost_usd is what those tokens would have cost had you bought
        them, which on a Pro or Max plan is not a charge. The CLI's own
        apiKeySource says which case this is."""
        self.assertIn("function chatBilledPerToken()", self.js)
        self.assertIn("chatBilledPerToken()", self.js)
        self.assertIn('src !== "none"', self.js)
        chat = (PANEL / "chat_session.py").read_text()
        self.assertIn('"api_key_source": event.get("apiKeySource")', chat)

    def test_the_two_faces_can_hand_a_conversation_to_each_other(self):
        """Interchangeable means both directions. Chat → terminal writes a
        handoff the terminal's launcher reads; terminal → chat is the
        conversation picker, which lists Claude Code's own store and replays
        the one you choose."""
        self.assertIn('id="chatOpen"', self.html)
        self.assertIn('id="convModal"', self.html)
        self.assertIn("api/chat/resume", self.js)
        self.assertIn("api/chat/conversations", self.js)
        chat = (PANEL / "chat_session.py").read_text()
        self.assertIn("async def resume(", chat)
        self.assertIn("def _open_in_terminal(", chat)
        # The launcher is what makes a terminal that has never been opened
        # still come up inside the conversation.
        start = (SCRIPTS / "brain-terminal-start.sh").read_text()
        self.assertIn("--resume", start)
        run = (ADDON_DIR / "run.sh").read_text()
        self.assertIn("brain-terminal-start", run)

    def test_the_handoff_expires(self):
        """A stale id would silently reopen last week's conversation the
        next time the add-on restarted."""
        start = (SCRIPTS / "brain-terminal-start.sh").read_text()
        self.assertIn("HANDOFF_MAX_AGE", start)
        # Consumed before it is acted on, so a handoff that fails to launch
        # is not retried forever.
        self.assertLess(start.index('rm -f "$HANDOFF_FILE"'),
                        start.index('resume_id="$candidate"'))

    def test_only_two_things_float_over_the_terminal(self):
        """These sit on top of somebody's output. Five translucent squares
        stacked over the text is exactly the clutter this view exists to get
        away from — ⤢ earns its place because it is also the way back from a
        folded bar, and the rest are a menu."""
        import re
        fabs = re.search(r'<div class="termfabs">(.*?)</div>', self.html, re.S)
        self.assertIsNotNone(fabs, "no floating button group")
        self.assertEqual(len(re.findall(r"<button ", fabs.group(1))), 2,
                         "more than two buttons float over the terminal")
        self.assertIn('id="termMenu"', fabs.group(1))
        self.assertIn('id="termExpand"', fabs.group(1))
        # The menu is static markup, not rebuilt on open: a menu that
        # recreates its own controls loses every listener bound to them.
        for item in ("chatNew", "chatOpen", "chatInfo", "termMode"):
            self.assertIn(f'id="{item}"', self.html)
        self.assertIn('id="termMenuPop"', self.html)

    def test_the_bar_does_not_report_usage_twice(self):
        """"Usage budget reached" was a chip sitting next to a usage pill
        already showing the number it was about — the same fact twice, and
        on a phone it wrapped the bar onto a third row to say it. The pill
        carries that state itself now."""
        self.assertNotIn("Usage budget reached", self.js)
        paused = self.js[self.js.index("function renderPausedChip()"):]
        paused = paused[:paused.index("\n}\n")]
        self.assertIn("auto_enabled === false", paused)
        self.assertNotIn("blocked", paused,
                         "the paused chip is reporting usage again")
        # ...and the pill says it, in the one place that now can.
        fill = self.js[self.js.index("function fillUsagePop()"):]
        fill = fill[:fill.index("\n}\n")]
        self.assertIn("Automatic insights are paused", fill)

    def test_a_popover_is_not_closed_by_the_press_that_opened_it(self):
        """The dismiss-on-outside-click listener runs after the handler that
        opens a popover, so it has to know what "outside" means. It used to
        name `.chip.clickable` specifically, which meant any other control
        that opened one — a finding's "Remind me later" — could never show
        it at all."""
        self.assertIn("chipPopFor.contains(ev.target)", self.js)
        self.assertNotIn('ev.target.closest(".chip.clickable")', self.js)

    def test_a_finding_can_be_discussed_and_deferred(self):
        """Two things a work list needs and did not have: asking about an
        item, and saying "not now" without saying "never"."""
        self.assertIn('id="chatFinding"', self.html)
        self.assertIn("function discussFinding(", self.js)
        self.assertIn("function openSnoozePop(", self.js)
        # The decisions travel with the discussion — agreeing to a fix at the
        # end of a conversation about it should not mean going to find the
        # card again.
        for act in ("chatFindingFix", "chatFindingDone",
                    "chatFindingLater", "chatFindingIgnore"):
            self.assertIn(f'id="{act}"', self.html)
        # And the discussion itself changes nothing.
        server = (PANEL / "server.py").read_text()
        self.assertIn("Do not change anything yet", server)

    def test_remind_me_later_is_not_a_decision(self):
        """Dismissing is permanent and is fed back into every future
        analysis. Using that for "not right now" would quietly throw away a
        real problem — so snooze must not touch the status."""
        store = (PANEL / "findings_store.py").read_text()
        self.assertIn("def snooze(", store)
        self.assertIn("snoozed_until", store)
        snooze = store[store.index("def snooze("):]
        snooze = snooze[:snooze.index("\ndef ")]
        self.assertNotIn('entry["status"]', snooze,
                         "snoozing changed the finding's status")
        # It comes back, and it is findable while it waits.
        self.assertIn('if status == "snoozed"', store)
        self.assertIn('{ id: "snoozed", label: "Later"', self.js)

    def test_the_palette_offers_the_brain_and_ha_commands_too(self):
        """They are not slash commands, so nothing announced them — and
        they are half of what anyone types into that box."""
        self.assertIn("CLI_PREFIX", self.js)
        self.assertIn("chatState.cli", self.js)
        cli = (PANEL / "cli_commands.py").read_text()
        # Parsed from the dispatchers' own help, never hardcoded.
        self.assertIn('[path, "help"]', cli)
        self.assertNotIn('"brain memory add"', cli)

    def test_the_command_palette_uses_the_clis_own_list(self):
        """A hardcoded list is wrong the first time somebody adds a command
        to /config/.claude/commands."""
        self.assertIn('id="chatCmds"', self.html)
        self.assertIn("function chatCmdMatches()", self.js)
        self.assertIn("chatState.commands", self.js)
        chat = (PANEL / "chat_session.py").read_text()
        self.assertIn('"commands_changed"', chat)
        self.assertIn("slash_commands", chat)
        # The palette owns Enter while it is open, or half-typing /model
        # sends "/mod" as a message.
        self.assertIn("const pick = matches[Math.min(chatState.cmdIndex", self.js)
        # ...and the index is clamped where it is USED, not only where the
        # list is drawn: the list shrinks as you type, so reading past its
        # end threw and killed the handler.
        self.assertIn("if (pick) chatPickCmd(", self.js)


class TestDocsTab(unittest.TestCase):
    """The guide's nav, search index and body all come from one source, so
    the thing worth testing is that the source is well-formed and that the
    renderer turns every section into balanced HTML."""

    @classmethod
    def setUpClass(cls):
        cls.docs = (PANEL / "docs.js").read_text()
        cls.html = (PANEL / "index.html").read_text()
        cls.app = (PANEL / "app.js").read_text()
        cls.server = (PANEL / "server.py").read_text()

    def test_tab_is_registered(self):
        self.assertIn('data-view="docs"', self.html)
        self.assertIn('id="viewDocs"', self.html)
        self.assertIn('if (name === "docs") renderDocs();', self.app)

    def test_docs_script_parses(self):
        """docs.js is a template-literal minefield — an unescaped backtick in
        prose is a syntax error, and a broken docs.js is a blank tab."""
        res = subprocess.run(["node", "--check", str(PANEL / "docs.js")],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_app_script_parses(self):
        res = subprocess.run(["node", "--check", str(PANEL / "app.js")],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_docs_script_is_loaded_and_served(self):
        """A script tag with no route behind it is a blank tab."""
        self.assertIn('src="docs.js', self.html)
        self.assertIn('add_get("/docs.js"', self.server)

    def test_search_box_exists(self):
        self.assertIn('id="docsSearch"', self.html)
        self.assertIn('id="docsNav"', self.html)

    def test_every_section_has_the_fields_the_nav_needs(self):
        import re
        ids = re.findall(r'^\s*id: "([^"]+)"', self.docs, re.M)
        icons = re.findall(r'^\s*icon: "([^"]+)"', self.docs, re.M)
        titles = re.findall(r'^\s*title: "([^"]+)"', self.docs, re.M)
        self.assertGreaterEqual(len(ids), 6, "guide is suspiciously short")
        self.assertEqual(len(ids), len(icons), "a section is missing an icon")
        self.assertEqual(len(ids), len(titles), "a section is missing a title")
        self.assertEqual(len(ids), len(set(ids)), "duplicate section id")

    def test_guide_documents_the_current_cli_not_the_retired_one(self):
        for retired in ("ha-memory", "ha-backup", "ha-share-login", "ha-reload",
                        "ha-yaml-check", "ha-selftest"):
            self.assertNotIn(retired, self.docs, f"guide teaches retired {retired}")
        for current in ("brain memory", "brain learn", "brain undo",
                        "brain doctor", "ha reload", "ha check"):
            self.assertIn(current, self.docs, f"guide never mentions {current}")

    def test_the_guide_teaches_the_buttons_that_are_actually_there(self):
        """The guide named six icon buttons on a card. Five of them moved
        behind ⋯ and the sixth (Refresh all, in the top bar) is gone, so the
        guide was teaching a UI nobody had."""
        self.assertNotIn("refreshAll", self.app)
        self.assertNotIn("refreshAll", self.html)
        self.assertIn("⋯ → Regenerate", self.docs)
        self.assertIn("⋯ → Delete", self.docs)
        self.assertIn("⋯ → Give feedback", self.docs)
        self.assertIn("⋯ → Add to dashboard", self.docs)

    def test_no_form_control_can_trigger_the_ios_zoom_trap(self):
        """iOS Safari zooms the page in when a text control's font is under
        16px, and does NOT zoom back out on blur — in an ingress iframe that
        strands the panel at an arbitrary scale. The docs search box was the
        one people found, but every dialog input had it too, so the floor is
        set once for touch rather than per control."""
        css = (PANEL / "style.css").read_text()
        self.assertIn("@media (pointer: coarse)", css)
        coarse = css.split("@media (pointer: coarse)", 1)[1]
        # the block has to actually name the control types and set 16px
        block = coarse[:coarse.index("}\n}") + 3]
        for control in ('input[type="text"]', "textarea", "select"):
            self.assertIn(control, block, f"{control} can still zoom")
        self.assertIn("font-size: 16px", block)

    def test_core_panel_functions_all_survive(self):
        """A blunt edit to app.js can silently delete whole subsystems — the
        file still parses, and nothing fails until you open the tab. Pin the
        entry points so a truncation is a test failure, not a discovery."""
        required = [
            "function esc(", "function inlineMd(", "function renderMarkdown(",
            "function docsSearch(", "function renderDocsNav(", "function selectDocs(",
            "function renderDocs(", "function renderMemory(", "function mdInline(",
            "function mdToHtml(", "function setMemEditing(", "function makeQuestions(",
            "function switchView(", "async function refreshMemoryBadge(",
        ]
        missing = [fn for fn in required if fn not in self.app]
        self.assertEqual(missing, [], f"app.js lost: {missing}")

    def test_cards_settle_guesses_with_two_taps(self):
        """The card renderer kept a free-text answer box after hypotheses
        replaced questions — so it asked for an essay where the answer is
        yes or no, and never settled the queue."""
        self.assertNotIn("Answer to help future insights", self.app)
        self.assertIn('"api/questions/answer", { answer: q }', self.app)

    def test_renderer_escapes_before_formatting(self):
        """The content is ours, but a docs renderer is exactly where a lazy
        innerHTML becomes an injection vector later."""
        esc_at = self.app.index("function esc(s)")
        inline_at = self.app.index("function inlineMd(s)")
        self.assertLess(esc_at, inline_at)
        self.assertIn("return esc(s)", self.app)


# ---------------------------------------------------------------------------
# CLI dispatchers
# ---------------------------------------------------------------------------

def run_cli(script: str, *args, env=None):
    full_env = {**os.environ, "BRAIN_SCRIPTS_DIR": str(SCRIPTS), **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        capture_output=True, text=True, env=full_env, timeout=30)


class TestCliDispatchers(unittest.TestCase):
    def test_brain_help_lists_its_faculties(self):
        out = run_cli("brain.sh", "help").stdout
        for word in ("memory", "learn", "ask", "undo", "doctor"):
            self.assertIn(word, out)

    def test_ha_help_lists_ha_operations(self):
        out = run_cli("ha.sh", "help").stdout
        for word in ("log", "reload", "entity", "service", "context"):
            self.assertIn(word, out)

    def test_bare_invocation_shows_usage(self):
        for script in ("brain.sh", "ha.sh"):
            self.assertIn("Usage:", run_cli(script).stdout)

    def test_ha_redirects_brain_faculties(self):
        """`ha memory` should point at `brain memory`, not just fail."""
        res = run_cli("ha.sh", "memory")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("brain memory", res.stderr)

    def test_brain_suggests_ha_for_unknown_subcommands(self):
        res = run_cli("brain.sh", "reload")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ha reload", res.stderr)

    def test_every_delegated_script_exists(self):
        """A dispatcher entry pointing at a missing script is a dead command."""
        missing = []
        for script in (SCRIPTS / "brain.sh", SCRIPTS / "ha.sh"):
            for line in script.read_text().splitlines():
                line = line.strip()
                if line.startswith(")") or "delegate " not in line:
                    continue
                target = line.split("delegate ", 1)[1].split()[0]
                if not target.endswith(".sh"):
                    continue
                if not (SCRIPTS / target).exists():
                    missing.append(f"{script.name} -> {target}")
        self.assertEqual(missing, [], f"dispatcher points at missing scripts: {missing}")


class TestSharedLogin(unittest.TestCase):
    """Signing in once must be enough.

    Sharing used to run one way — the terminal's `ha login` published a
    credential the Insights panel read. Merged into one add-on the panel
    became the primary sign-in surface, so a panel login has to reach the
    CLI too or the terminal prompts for a second, pointless login.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "secrets").mkdir()
        (self.root / "shared").mkdir()
        (self.root / "home" / ".claude").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _resolve(self):
        """Source the resolver and report what it exported."""
        script = SCRIPTS / "brain-auth-env.sh"
        cmd = (f". {script}; "
               'echo "OAUTH=${CLAUDE_CODE_OAUTH_TOKEN:-}"; '
               'echo "APIKEY=${ANTHROPIC_API_KEY:-}"')
        res = subprocess.run(
            ["bash", "-c", cmd], capture_output=True, text=True, timeout=30,
            env={**os.environ,
                 "BRAIN_HOME": str(self.root / "home"),
                 "BRAIN_SECRETS": str(self.root / "secrets"),
                 "BRAIN_SHARED_AUTH": str(self.root / "shared" / "claude_auth.json")})
        out = dict(line.split("=", 1) for line in res.stdout.splitlines() if "=" in line)
        return out.get("OAUTH", ""), out.get("APIKEY", "")

    def _panel_login(self, cred_type, value):
        (self.root / "secrets" / "claude_auth.json").write_text(
            json.dumps({"type": cred_type, "value": value}))

    def _terminal_login(self, cred_type, value):
        (self.root / "shared" / "claude_auth.json").write_text(
            json.dumps({"type": cred_type, "value": value}))

    def test_panel_oauth_login_reaches_the_cli(self):
        self._panel_login("oauth_token", "sk-ant-oat01-PANEL")
        oauth, apikey = self._resolve()
        self.assertEqual(oauth, "sk-ant-oat01-PANEL")
        self.assertEqual(apikey, "")

    def test_panel_api_key_uses_the_api_key_variable(self):
        self._panel_login("api_key", "sk-ant-api-PANEL")
        oauth, apikey = self._resolve()
        self.assertEqual(apikey, "sk-ant-api-PANEL")
        self.assertEqual(oauth, "")

    def test_terminal_shared_login_is_still_honoured(self):
        self._terminal_login("oauth_token", "sk-ant-oat01-SHARED")
        oauth, _ = self._resolve()
        self.assertEqual(oauth, "sk-ant-oat01-SHARED")

    def test_panel_login_wins_over_the_shared_file(self):
        self._panel_login("oauth_token", "sk-ant-oat01-PANEL")
        self._terminal_login("oauth_token", "sk-ant-oat01-SHARED")
        oauth, _ = self._resolve()
        self.assertEqual(oauth, "sk-ant-oat01-PANEL")

    def test_cli_own_login_is_left_alone(self):
        """The CLI refreshes its own OAuth credential; injecting a token over
        the top would break that refresh."""
        (self.root / "home" / ".claude" / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-CLIOWN"}}))
        self._panel_login("oauth_token", "sk-ant-oat01-PANEL")
        oauth, apikey = self._resolve()
        self.assertEqual((oauth, apikey), ("", ""))

    def test_nothing_stored_exports_nothing(self):
        """An empty variable makes the CLI fail with an auth error instead of
        prompting to log in — unset is the correct 'signed out' state."""
        self.assertEqual(self._resolve(), ("", ""))

    def test_malformed_credential_is_ignored(self):
        (self.root / "secrets" / "claude_auth.json").write_text("not json{")
        self.assertEqual(self._resolve(), ("", ""))


class TestSharedLoginWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_sh = (ADDON_DIR / "run.sh").read_text()

    def test_claude_run_wrapper_sources_the_resolver(self):
        wrapper = self.run_sh.split("claude-run << 'WRAPPER'")[1]
        self.assertIn("brain-auth-env.sh", wrapper)

    def test_wrapper_forwards_the_credential_across_su_exec(self):
        """su-exec does not preserve the environment by itself."""
        wrapper = self.run_sh.split("claude-run << 'WRAPPER'")[1]
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", wrapper)
        self.assertIn("ANTHROPIC_API_KEY", wrapper)

    def test_interactive_shell_picks_up_the_credential(self):
        profile = self.run_sh.split("<< 'PROFILE'")[1]
        self.assertIn("brain-auth-env.sh", profile)


class TestRunSourceLedgerOwnership(unittest.TestCase):
    """Both halves of the run-source ledger have to be able to write it.

    The panel creates it as root; the consolidator and the study watcher
    are started with `su-exec claude` and append to the same file. Whoever
    got there first owned it, root won, and every daemon pass failed its
    claim with "Permission denied" and ran unlabelled — which is exactly
    what the ledger exists to prevent: an unlabelled consolidation shows up
    in the Chats rail as a conversation somebody typed, and `adopt` picks
    it up. Root can write a claude-owned file, so only this direction
    needs arranging, and it has to happen before the daemons start.
    """

    @classmethod
    def setUpClass(cls):
        cls.run_sh = (ADDON_DIR / "run.sh").read_text()

    def test_the_ledger_is_created_claude_owned(self):
        self.assertIn("chown claude:claude /data/run-sources.jsonl", self.run_sh)

    def test_the_daemons_that_claim_run_as_claude(self):
        for script in ("brain-memory-consolidate.sh", "brain-study-watcher.sh"):
            self.assertIn(f"su-exec claude bash /opt/scripts/{script}",
                          self.run_sh, script)

    def test_the_ledger_exists_before_anything_claims_it(self):
        setup = self.run_sh.index("chown claude:claude /data/run-sources.jsonl")
        for script in ("brain-memory-consolidate.sh", "brain-study-watcher.sh"):
            self.assertLess(setup, self.run_sh.index(f"su-exec claude bash "
                                                     f"/opt/scripts/{script}"),
                            script)


class TestTurnBudgets(unittest.TestCase):
    """A turn cap TRUNCATES — it doesn't degrade. A run that hits one stops
    mid-thought and produces nothing parseable, so the work is paid for and
    then thrown away. That makes a tight cap the most expensive setting in
    the add-on, and it must not be set by reflex."""

    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
        cls.learn = (SCRIPTS / "brain-learn.sh").read_text()
        cls.ask = (SCRIPTS / "brain-ask.sh").read_text()

    def test_study_can_run_uncapped(self):
        """Depth is the deliverable for a study session, so 0 must be legal."""
        self.assertIn("study_max_turns", self.config["options"])
        self.assertTrue(self.config["schema"]["study_max_turns"].startswith("int(0,"))

    def test_study_omits_the_flag_when_uncapped(self):
        """Passing --max-turns 0 would cap at zero, not remove the cap."""
        self.assertIn('if [ "${MAX_TURNS:-0}" -gt 0 ]', self.learn)
        self.assertIn('turn_args=(--max-turns "$MAX_TURNS")', self.learn)
        self.assertIn('-p "${turn_args[@]}"', self.learn)

    def test_ask_also_supports_uncapped(self):
        self.assertIn('if [ "${MAX_TURNS:-0}" -gt 0 ]', self.ask)
        self.assertIn('-p "${turn_args[@]}"', self.ask)

    def test_study_defaults_are_generous(self):
        self.assertGreaterEqual(self.config["options"]["study_max_turns"], 40)
        self.assertGreaterEqual(self.config["options"]["study_timeout_minutes"], 15)

    def test_voice_stays_tight_but_not_starved(self):
        """Voice is the one place a cap is genuinely right — latency is the
        product — but 5 was tight enough to truncate real commands."""
        turns = self.config["options"]["assist_max_turns"]
        self.assertGreaterEqual(turns, 8)
        self.assertLessEqual(turns, 15)

    def test_background_work_is_not_held_to_voice_limits(self):
        self.assertGreaterEqual(self.config["options"]["automation_max_turns"], 20)

    def test_truncation_is_reported_as_truncation(self):
        """Blaming the model for a limit we imposed sends people looking in
        entirely the wrong place."""
        self.assertIn("hit its ${MAX_TURNS}-turn limit", self.learn)
        self.assertIn("BRAIN_LEARN_MAX_TURNS", self.learn)

    def test_model_is_told_to_land_before_it_runs_out(self):
        """Converts a truncated run into a partial but useful one."""
        self.assertIn("running low on room", self.learn)


class TestStudyService(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.requests = self.root / "study_requests"
        self.requests.mkdir()
        self.learn_log = self.root / "learn.log"
        # Stand in for brain-learn.sh so the watcher can be exercised without
        # a Claude CLI.
        self.fake_learn = self.root / "fake-learn.sh"
        self.fake_learn.write_text(
            "#!/bin/bash\nprintf '%s\\n' \"$*\" >> " + str(self.learn_log) + "\n")
        self.fake_learn.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def _watch_once(self):
        return subprocess.run(
            ["bash", str(SCRIPTS / "brain-study-watcher.sh"), "--once"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ,
                 "BRAIN_SHARED_DIR": str(self.root),
                 "BRAIN_LEARN_SCRIPT": str(self.fake_learn)})

    def _request(self, topic):
        (self.requests / f"{int(time.time())}-{topic or 'auto'}.json").write_text(
            json.dumps({"ts": int(time.time()), "topic": topic}))

    def test_topic_request_runs_that_topic(self):
        self._request("energy")
        self._watch_once()
        self.assertEqual(self.learn_log.read_text().strip(), "energy")

    def test_empty_topic_studies_the_stalest(self):
        """A nightly 'study something' automation is the main use, so an
        empty topic must mean 'you choose', not 'study nothing'."""
        self._request("")
        self._watch_once()
        self.assertEqual(self.learn_log.read_text().strip(), "")

    def test_a_request_runs_exactly_once(self):
        """Study sessions are expensive — re-running one on every poll would
        quietly burn a usage window."""
        self._request("energy")
        self._watch_once()
        self._watch_once()
        self.assertEqual(len(self.learn_log.read_text().strip().splitlines()), 1)

    def test_processed_requests_are_archived_not_left_pending(self):
        self._request("energy")
        self._watch_once()
        self.assertEqual(list(self.requests.glob("*.json")), [])
        self.assertTrue(list((self.requests / "processed").iterdir()))

    def test_missing_learn_script_exits_quietly(self):
        res = subprocess.run(
            ["bash", str(SCRIPTS / "brain-study-watcher.sh"), "--once"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BRAIN_SHARED_DIR": str(self.root),
                 "BRAIN_LEARN_SCRIPT": "/nonexistent/learn.sh"})
        self.assertEqual(res.returncode, 0)


class TestSlashCommands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_sh = (ADDON_DIR / "run.sh").read_text()

    def test_learn_and_memory_commands_are_installed(self):
        self.assertIn('commands_dir="$claude_settings_dir/commands"', self.run_sh)
        self.assertIn("learn.md", self.run_sh)
        self.assertIn("memory.md", self.run_sh)

    def test_learn_command_files_through_the_cli(self):
        """A slash command that writes memory.md directly would bypass the
        single-writer rule the whole design rests on."""
        self.assertIn('brain memory add "<fact>"', self.run_sh)

    def test_study_watcher_starts_with_learning_enabled(self):
        self.assertIn("start_study_watcher", self.run_sh)
        self.assertIn("Study watcher disabled (learning: false)", self.run_sh)


# ---------------------------------------------------------------------------
# Edit journal (the git-auto-backup replacement)
# ---------------------------------------------------------------------------

class TestEditJournal(unittest.TestCase):
    """The PreToolUse hook must snapshot before an edit, and never block one."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.watched = self.root / "config"
        self.watched.mkdir()
        self.journal = self.root / "journal"

    def tearDown(self):
        self.tmp.cleanup()

    def _hook(self, payload: dict, extra_env=None):
        """Run the hook with WATCH_ROOTS repointed at the temp config dir."""
        src = (SCRIPTS / "brain-edit-snapshot.py").read_text().replace(
            'WATCH_ROOTS = ("/config",)', f'WATCH_ROOTS = ({str(self.watched)!r},)')
        runner = self.root / "hook.py"
        runner.write_text(src)
        env = {**os.environ, "BRAIN_EDIT_JOURNAL": str(self.journal),
               **(extra_env or {})}
        return subprocess.run(
            [sys.executable, str(runner)], input=json.dumps(payload),
            capture_output=True, text=True, env=env, timeout=30)

    def _index(self):
        path = self.journal / "index.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def test_snapshots_existing_file_before_edit(self):
        target = self.watched / "automations.yaml"
        target.write_text("before")
        res = self._hook({"tool_name": "Edit",
                          "tool_input": {"file_path": str(target)}})
        self.assertEqual(res.returncode, 0)

        entries = self._index()
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["existed"])
        snap = self.journal / "snapshots" / entries[0]["snapshot"]
        self.assertEqual(snap.read_text(), "before",
                         "snapshot must hold the PRIOR contents")

    def test_records_creation_with_no_snapshot(self):
        """A new file has nothing to restore — undo deletes it instead."""
        target = self.watched / "brand-new.yaml"
        self._hook({"tool_name": "Write",
                    "tool_input": {"file_path": str(target)}})
        entries = self._index()
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["existed"])
        self.assertEqual(entries[0]["snapshot"], "")

    def test_ignores_paths_outside_the_watched_root(self):
        outside = self.root / "elsewhere.yaml"
        outside.write_text("x")
        self._hook({"tool_name": "Write",
                    "tool_input": {"file_path": str(outside)}})
        self.assertEqual(self._index(), [])

    def test_never_snapshots_secrets(self):
        secrets = self.watched / "secrets.yaml"
        secrets.write_text("api_key: hunter2")
        self._hook({"tool_name": "Edit",
                    "tool_input": {"file_path": str(secrets)}})
        self.assertEqual(self._index(), [])

    def test_ignores_non_editing_tools(self):
        target = self.watched / "a.yaml"
        target.write_text("x")
        self._hook({"tool_name": "Bash", "tool_input": {"file_path": str(target)}})
        self.assertEqual(self._index(), [])

    def test_malformed_input_exits_clean(self):
        """A hook that errors would block the edit — it must always exit 0."""
        runner_src = (SCRIPTS / "brain-edit-snapshot.py").read_text()
        runner = self.root / "hook.py"
        runner.write_text(runner_src)
        res = subprocess.run(
            [sys.executable, str(runner)], input="not json at all",
            capture_output=True, text=True,
            env={**os.environ, "BRAIN_EDIT_JOURNAL": str(self.journal)},
            timeout=30)
        self.assertEqual(res.returncode, 0)

    def test_prunes_snapshots_past_the_retention_window(self):
        target = self.watched / "old.yaml"
        target.write_text("x")
        self._hook({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
        snap = next((self.journal / "snapshots").iterdir())
        stale = time.time() - 40 * 86400
        os.utime(snap, (stale, stale))

        other = self.watched / "new.yaml"
        other.write_text("y")
        self._hook({"tool_name": "Edit", "tool_input": {"file_path": str(other)}},
                   extra_env={"BRAIN_EDIT_JOURNAL_DAYS": "14"})
        self.assertFalse(snap.exists(), "snapshot older than the window survived")


class TestBrainUndo(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.journal = self.root / "journal"
        (self.journal / "snapshots").mkdir(parents=True)
        self.target = self.root / "automations.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def _journal_entry(self, existed=True, contents="original"):
        snapshot = ""
        if existed:
            snapshot = "1700000000-abc-automations.yaml"
            (self.journal / "snapshots" / snapshot).write_text(contents)
        entry = {"ts": 1700000000.0, "path": str(self.target), "tool": "Edit",
                 "snapshot": snapshot, "existed": existed}
        (self.journal / "index.jsonl").write_text(json.dumps(entry) + "\n")

    def _undo(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPTS / "brain-undo.sh"), *args],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BRAIN_EDIT_JOURNAL": str(self.journal)})

    def test_lists_recent_edits(self):
        self._journal_entry()
        out = self._undo().stdout
        self.assertIn("automations.yaml", out)
        self.assertIn("modified", out)

    def test_restores_prior_contents(self):
        self._journal_entry(contents="the original")
        self.target.write_text("claude's version")
        res = self._undo("1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.target.read_text(), "the original")

    def test_undoing_a_creation_removes_the_file(self):
        self._journal_entry(existed=False)
        self.target.write_text("created by claude")
        self._undo("1")
        self.assertFalse(self.target.exists())

    def test_empty_journal_is_not_an_error(self):
        res = self._undo()
        self.assertEqual(res.returncode, 0)

    def test_out_of_range_index_fails_clearly(self):
        self._journal_entry()
        res = self._undo("99")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("No edit #99", res.stderr)


# ---------------------------------------------------------------------------
# Memory: hypotheses replace the old open-ended question list
# ---------------------------------------------------------------------------

class TestMemoryHypotheses(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / "memory"
        self.mem.mkdir(parents=True)
        self.hyp = self.mem / "hypotheses.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_hypotheses(self, *entries):
        self.hyp.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def _mem(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPTS / "brain-memory.sh"), *args],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BRAIN_MEMORY_DIR": str(self.mem)})

    def _open_hypothesis(self, text="The garage fridge is meant to run 24/7"):
        self._write_hypotheses(
            {"ts": int(time.time()), "text": text, "topic": "devices",
             "status": "open"})
        return text

    def test_lists_open_hypotheses(self):
        text = self._open_hypothesis()
        out = self._mem("hypotheses").stdout
        self.assertIn(text, out)

    def test_confirming_settles_it_and_queues_a_fact(self):
        text = self._open_hypothesis()
        res = self._mem("confirm", text)
        self.assertEqual(res.returncode, 0, res.stderr)

        statuses = [json.loads(line)["status"]
                    for line in self.hyp.read_text().splitlines() if line]
        self.assertEqual(statuses, ["confirmed"])

        # The confirmed guess becomes a plain fact in the inbox — no
        # "Q: ... -> A: ..." string anywhere.
        queued = list((self.mem / "inbox").glob("*.jsonl"))
        self.assertEqual(len(queued), 1)
        fact = json.loads(queued[0].read_text().splitlines()[0])
        self.assertEqual(fact["fact"], text)
        self.assertNotIn("Q:", fact["fact"])

    def test_rejecting_settles_without_queueing_a_fact(self):
        text = self._open_hypothesis()
        self._mem("reject", text)
        statuses = [json.loads(line)["status"]
                    for line in self.hyp.read_text().splitlines() if line]
        self.assertEqual(statuses, ["rejected"])
        self.assertFalse(list((self.mem / "inbox").glob("*.jsonl")))

    def test_matches_on_a_distinctive_fragment(self):
        """Users shouldn't have to retype a whole sentence."""
        self._open_hypothesis()
        res = self._mem("confirm", "garage fridge")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_ambiguous_fragment_refuses_rather_than_guessing(self):
        self._write_hypotheses(
            {"ts": 1, "text": "The garage fridge runs 24/7", "status": "open"},
            {"ts": 2, "text": "The garage heater runs 24/7", "status": "open"})
        res = self._mem("confirm", "24/7")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("more than one", res.stderr)

    def test_settled_hypotheses_are_not_offered_again(self):
        self._write_hypotheses(
            {"ts": 1, "text": "Already answered", "status": "confirmed"},
            {"ts": 2, "text": "Wrong track", "status": "rejected"})
        out = self._mem("hypotheses").stdout
        self.assertNotIn("Already answered", out)
        self.assertNotIn("Wrong track", out)

    def test_forget_queues_a_removal(self):
        self._mem("add", "a fact")
        self._mem("forget", "the old thermostat")
        facts = []
        for f in (self.mem / "inbox").glob("*.jsonl"):
            facts += [json.loads(x)["fact"] for x in f.read_text().splitlines() if x]
        self.assertIn("FORGET: the old thermostat", facts)

    def test_empty_state_is_never_an_error(self):
        for args in (["hypotheses"], ["log"], ["inbox"], ["list"]):
            self.assertEqual(self._mem(*args).returncode, 0, args)


class TestMemoryChangeLog(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / "memory"
        (self.mem / "snapshots").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _mem(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPTS / "brain-memory.sh"), *args],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BRAIN_MEMORY_DIR": str(self.mem)})

    def _log_entry(self):
        (self.mem / "snapshots" / "100.md").write_text("# Home Memory\n\n- old line\n")
        (self.mem / "memory.log.jsonl").write_text(json.dumps({
            "ts": 1700000000, "snapshot": "snapshots/100.md",
            "source": "consolidation",
            "added": ["a new thing"], "removed": [],
        }) + "\n")

    def test_log_lists_changes(self):
        self._log_entry()
        out = self._mem("log").stdout
        self.assertIn("+1", out)
        self.assertIn("consolidation", out)

    def test_log_show_prints_the_lines(self):
        self._log_entry()
        out = self._mem("log", "--show", "1").stdout
        self.assertIn("a new thing", out)

    def test_undo_restores_the_snapshot(self):
        self._log_entry()
        (self.mem / "memory.md").write_text("# Home Memory\n\n- old line\n- a new thing\n")
        res = self._mem("undo", "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("a new thing", (self.mem / "memory.md").read_text())

    def test_undo_out_of_range_fails_clearly(self):
        self._log_entry()
        res = self._mem("undo", "99")
        self.assertNotEqual(res.returncode, 0)


# ---------------------------------------------------------------------------
# Terminal reverse proxy
# ---------------------------------------------------------------------------

class TestTerminalProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load by path under a unique name. brain/panel and brain/panel
        # both contain a `server.py`, so putting either on sys.path decides
        # which one every OTHER test file gets — import order should not
        # silently repoint another module's tests at a different add-on.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "brain_terminal_proxy", PANEL / "terminal_proxy.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.mod = module

    def test_registers_prefix_and_wildcard_routes(self):
        from aiohttp import web
        app = web.Application()
        self.mod.setup(app)
        canonical = {r.resource.canonical for r in app.router.routes()}
        self.assertIn("/terminal", canonical)
        self.assertIn("/terminal/{path}", canonical)

    def test_strips_hop_by_hop_headers(self):
        cleaned = self.mod._clean({
            "Connection": "upgrade", "Upgrade": "websocket",
            "Transfer-Encoding": "chunked", "Host": "x", "Content-Length": "3",
            "Cookie": "keep=me",
        })
        self.assertEqual(cleaned, {"Cookie": "keep=me"})

    def test_respects_the_enable_terminal_switch(self):
        original = os.environ.get("BRAIN_ENABLE_TERMINAL")
        try:
            os.environ["BRAIN_ENABLE_TERMINAL"] = "false"
            self.assertFalse(self.mod._enabled())
            os.environ["BRAIN_ENABLE_TERMINAL"] = "true"
            self.assertTrue(self.mod._enabled())
        finally:
            if original is None:
                os.environ.pop("BRAIN_ENABLE_TERMINAL", None)
            else:
                os.environ["BRAIN_ENABLE_TERMINAL"] = original

    def test_upstream_url_maps_onto_ttyd_root(self):
        """/terminal/ws must reach ttyd's /ws, or the session never opens."""
        class FakeRequest:
            match_info = {"path": "ws"}
            query_string = ""
        self.assertEqual(self.mod._upstream_url(FakeRequest()),
                         f"{self.mod.TTYD_BASE}/ws")

    def test_upstream_url_preserves_query_string(self):
        class FakeRequest:
            match_info = {"path": "token"}
            query_string = "arg=1&arg=2"
        self.assertEqual(self.mod._upstream_url(FakeRequest()),
                         f"{self.mod.TTYD_BASE}/token?arg=1&arg=2")


if __name__ == "__main__":
    unittest.main()
