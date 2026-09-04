#!/usr/bin/env python3
"""The Lovelace card's Home Assistant half: is /local even a route?

Home Assistant registers the `/local` static path once, while it is
starting, and only if `/config/www` is already a directory — core's own
frontend setup, verbatim:

    local = hass.config.path("www")
    if await hass.async_add_executor_job(os.path.isdir, local):
        static_paths_configs.append(StaticPathConfig("/local", local, ...))

BRUH Print's run.sh creates `/config/www/bruh_print` when the ADD-ON starts,
which on an ordinary install is after Home Assistant started. On a house that
had no `/config/www` at all — you only have one if you have already installed
a custom card or HACS — `/local` is not a route on that run: every request
for the card 404s and the dashboard shows Home Assistant's own "Custom
element doesn't exist: bruh-print-card". Restarting the add-on cannot fix it;
only restarting Home Assistant can. `_register_card` checked that the FILE
was there, which passes happily, so the failure was invisible from every
surface the add-on has.

The browser half of the card is driven by
`tests/manual/measure-print-card.mjs`, which loads the real file into a real
browser: nothing here can say whether a card renders.

`homeassistant` is not installed in CI, so the integration is imported behind
permissive stubs (the pattern `tests/test_power_tools_device_cycles.py` uses,
and `sys.modules` is put back the same way) and the two helpers are then
DRIVEN. Everything that cannot be driven — the shape of the source, the
strings files — is asserted separately and says so in its own docstring.
"""
import ast
import importlib
import importlib.util
import json
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION = BASE_DIR / "bruh-print" / "custom_components" / "bruh_print"


class _AutoModule(types.ModuleType):
    """A module whose every attribute exists, so the import gets through."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


class _Coordinator:
    """Stands in for `DataUpdateCoordinator`, which is SUBCLASSED.

    A MagicMock cannot be a base class, so the one Home Assistant name the
    integration inherits from has to be a real one.
    """

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, *args, **kwargs):
        pass


def _import_integration():
    """Import `bruh_print/__init__.py` behind stubs, restoring sys.modules.

    Several test modules in this repository install their own partial
    `homeassistant` stubs and whichever runs first wins a shared table — the
    reason the brain equivalent passed alone and failed under `unittest
    discover`. So the stubs go in, the module comes out, and the table is put
    back exactly as it was found.
    """
    saved = dict(sys.modules)
    try:
        for name in (
            "voluptuous",
            "homeassistant",
            "homeassistant.config_entries",
            "homeassistant.const",
            "homeassistant.core",
            "homeassistant.exceptions",
            "homeassistant.helpers",
            "homeassistant.helpers.config_validation",
            "homeassistant.helpers.event",
            "homeassistant.helpers.issue_registry",
            "homeassistant.helpers.update_coordinator",
        ):
            sys.modules[name] = _AutoModule(name)
        # `@callback` is Home Assistant's marker decorator and hands back the
        # function it was given; a MagicMock in its place would replace every
        # decorated function in the module with a mock.
        sys.modules["homeassistant.core"].callback = lambda func: func
        sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = (
            _Coordinator)
        # Loaded from its file under a stand-in package name, rather than
        # put in sys.modules as a bare module: `import_module` on a name
        # already in that table hands the entry back WITHOUT running the
        # file, which is an integration whose every attribute is missing.
        # `submodule_search_locations` is what makes `.const`, `.bridge` and
        # `.coordinator` resolve.
        for stale in [m for m in sys.modules if m.startswith("bruh_print_cc")]:
            del sys.modules[stale]
        spec = importlib.util.spec_from_file_location(
            "bruh_print_cc", INTEGRATION / "__init__.py",
            submodule_search_locations=[str(INTEGRATION)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["bruh_print_cc"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


bruh_print = _import_integration()


class _Resource:
    """One row of aiohttp's router. `canonical` is what the check reads."""

    def __init__(self, canonical):
        self.canonical = canonical


class _Nameless:
    """A router entry with no `canonical` at all — aiohttp has several
    resource types and nothing promises every one carries it."""


class _Router:
    def __init__(self, rows):
        self._rows = rows

    def resources(self):
        return list(self._rows)


class _AngryRouter:
    def resources(self):
        raise RuntimeError("the app is not up yet")


class _Hass:
    """The slice of `hass` these two helpers touch."""

    def __init__(self, router=None, http=True):
        self.data = {}
        if http:
            self.http = types.SimpleNamespace(
                app=types.SimpleNamespace(router=router))

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _routes(*canonicals):
    """A router shaped like a real one: a pile of Home Assistant's own
    routes, with whatever is asked for mixed in."""
    rows = [_Resource("/api/"), _Resource("/auth/token"), _Nameless(),
            _Resource("/static")]
    rows.extend(_Resource(name) for name in canonicals)
    return _Router(rows)


class TestIsLocalServed(unittest.TestCase):
    """Drives the real `_local_is_served`."""

    def test_it_finds_local_when_core_is_serving_it(self):
        self.assertTrue(bruh_print._local_is_served(_Hass(_routes("/local"))))

    def test_it_says_no_when_core_is_not_serving_it(self):
        """The reported failure: /config/www did not exist at startup, so
        Home Assistant never registered the route and every request for the
        card is a 404."""
        self.assertFalse(bruh_print._local_is_served(_Hass(_routes())))

    def test_a_router_that_raises_reads_as_served(self):
        """Fails open, always. This is a diagnosis and never a gate: being
        wrong this way costs nothing, and being wrong the other way tells a
        house whose card works to go and restart Home Assistant."""
        self.assertTrue(bruh_print._local_is_served(_Hass(_AngryRouter())))

    def test_a_hass_with_no_http_reads_as_served(self):
        self.assertTrue(bruh_print._local_is_served(_Hass(http=False)))

    def test_an_empty_router_reads_as_served(self):
        """A router with nothing on it is not a Home Assistant serving
        nothing; it is the question asked where it cannot be answered."""
        self.assertTrue(bruh_print._local_is_served(_Hass(_Router([]))))

    def test_a_resource_without_a_canonical_is_not_an_explosion(self):
        """`_Nameless` rides in every fixture above, so a router carrying one
        must not be able to take the answer down — but assert it directly
        too, since the other cases would still pass if the loop stopped at
        the first row."""
        router = _Router([_Nameless(), _Resource("/local")])
        self.assertTrue(bruh_print._local_is_served(_Hass(router)))


class _IssueRegistry:
    """Records what the integration asks the repair machinery to do."""

    IssueSeverity = types.SimpleNamespace(WARNING="warning", ERROR="error")

    def __init__(self):
        self.created = []
        self.deleted = []

    def async_create_issue(self, hass, domain, issue_id, **kwargs):
        self.created.append((domain, issue_id, kwargs))

    def async_delete_issue(self, hass, domain, issue_id):
        self.deleted.append((domain, issue_id))


class TestTheRepair(unittest.TestCase):
    """Drives the real `_sync_local_issue` with a recording issue registry."""

    def setUp(self):
        self.registry = _IssueRegistry()
        self._real = bruh_print.ir
        bruh_print.ir = self.registry
        self.addCleanup(setattr, bruh_print, "ir", self._real)

    def test_it_raises_the_repair_when_local_is_not_served(self):
        served = bruh_print._sync_local_issue(_Hass(_routes()))
        self.assertFalse(served)
        self.assertEqual(len(self.registry.created), 1)
        domain, issue_id, kwargs = self.registry.created[0]
        self.assertEqual(domain, bruh_print.DOMAIN)
        self.assertEqual(issue_id, bruh_print.ISSUE_LOCAL_NOT_SERVED)
        self.assertFalse(kwargs["is_fixable"],
                         "nothing the integration can do fixes this — only a "
                         "restart of Home Assistant does")
        self.assertEqual(kwargs["severity"], self.registry.IssueSeverity.WARNING)
        self.assertEqual(kwargs["translation_key"],
                         bruh_print.ISSUE_LOCAL_NOT_SERVED)
        self.assertEqual(kwargs["learn_more_url"], bruh_print.DOCS_URL)
        self.assertFalse(self.registry.deleted)

    def test_it_takes_the_repair_away_once_the_restart_has_happened(self):
        """A house that has restarted must stop being told to restart."""
        served = bruh_print._sync_local_issue(_Hass(_routes("/local")))
        self.assertTrue(served)
        self.assertFalse(self.registry.created)
        self.assertEqual(self.registry.deleted,
                         [(bruh_print.DOMAIN, bruh_print.ISSUE_LOCAL_NOT_SERVED)])

    def test_a_check_that_could_not_look_raises_nothing(self):
        bruh_print._sync_local_issue(_Hass(_AngryRouter()))
        self.assertFalse(self.registry.created)


class _Frontend(types.ModuleType):
    """`homeassistant.components.frontend`, to the extent the card uses it."""

    def __init__(self):
        super().__init__("homeassistant.components.frontend")
        self.urls = []
        self.add_extra_js_url = lambda hass, url: self.urls.append(url)


class TestTheCardIsRegisteredEitherWay(unittest.TestCase):
    """Drives the real `_register_card`, which is the half that matters:
    the URL it registers works the moment Home Assistant restarts, so
    refusing to register on a failed check would leave a repair that nothing
    could ever clear."""

    def setUp(self):
        import asyncio

        self.asyncio = asyncio
        self.frontend = _Frontend()
        saved = dict(sys.modules)
        sys.modules.setdefault("homeassistant", _AutoModule("homeassistant"))
        sys.modules.setdefault("homeassistant.components",
                               _AutoModule("homeassistant.components"))
        sys.modules["homeassistant.components.frontend"] = self.frontend

        def _restore():
            sys.modules.clear()
            sys.modules.update(saved)

        self.addCleanup(_restore)

        self.registry = _IssueRegistry()
        real = bruh_print.ir
        bruh_print.ir = self.registry
        self.addCleanup(setattr, bruh_print, "ir", real)

        # A card that is really on disk, so `card_url` hashes real bytes.
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        card = Path(tmp.name) / "bruh-print-card.js"
        card.write_text("const CARD_VERSION = '9.9.9';\n")
        real_file = bruh_print.CARD_FILE
        bruh_print.CARD_FILE = card
        self.addCleanup(setattr, bruh_print, "CARD_FILE", real_file)

    def test_it_registers_the_card_and_raises_the_repair(self):
        hass = _Hass(_routes())
        self.asyncio.run(bruh_print._register_card(hass))
        self.assertEqual(len(self.frontend.urls), 1,
                         "the card was not registered, so the repair would "
                         "ask for a restart that changes nothing")
        # The hashed URL, not the bare one: what is registered has to be
        # what `card_url` makes of the bytes on disk.
        self.assertEqual(self.frontend.urls[0],
                         bruh_print.card_url(bruh_print.CARD_FILE))
        self.assertEqual(len(self.registry.created), 1)

    def test_a_working_house_gets_the_card_and_no_repair(self):
        hass = _Hass(_routes("/local"))
        self.asyncio.run(bruh_print._register_card(hass))
        self.assertEqual(len(self.frontend.urls), 1)
        self.assertFalse(self.registry.created)
        self.assertEqual(len(self.registry.deleted), 1)


class TestTheSourceDoesNotAskOverTheWire(unittest.TestCase):
    """A source-level check, and only ever *in addition* to the drives above.

    What it can still see is HOW the question is asked. An internal fetch has
    to guess a base URL, cross the network stack and a proxy, and can fail
    for half a dozen reasons that are not the question — so the answer comes
    off the running app's own router, and nothing here may reach for a
    session or a URL helper.
    """

    def setUp(self):
        self.source = (INTEGRATION / "__init__.py").read_text()
        self.tree = ast.parse(self.source)

    def _function(self, name):
        for node in ast.walk(self.tree):
            # `_register_card` is a coroutine, which is a different node
            # type and not a different function.
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name):
                return node
        self.fail(f"{name} is gone from __init__.py")
        return None

    def test_the_check_reads_the_router(self):
        body = ast.dump(self._function("_local_is_served"))
        self.assertIn("resources", body)
        for wire in ("get_url", "async_get_clientsession", "aiohttp", "requests"):
            with self.subTest(call=wire):
                self.assertNotIn(wire, body)

    def test_the_check_carries_the_startup_rule_in_its_docstring(self):
        """The next person to read this function will wonder why a route
        would ever be missing. The answer is not in this repository's code —
        it is in core's frontend setup — so it has to be written down here."""
        doc = ast.get_docstring(self._function("_local_is_served")) or ""
        for owed in ("www", "restart", "404"):
            with self.subTest(word=owed):
                self.assertIn(owed, doc.lower())

    def test_registering_the_card_does_not_depend_on_the_check(self):
        """`_register_card` must call `add_extra_js_url` before it ever asks
        about /local, and must not branch on the answer."""
        register = self._function("_register_card")
        calls = [node for node in ast.walk(register) if isinstance(node, ast.Call)]
        names = [node.func.id for node in calls if isinstance(node.func, ast.Name)]
        self.assertIn("add_extra_js_url", names)
        self.assertIn("_sync_local_issue", names)
        self.assertLess(names.index("add_extra_js_url"),
                        names.index("_sync_local_issue"))


class TestTheIssueStrings(unittest.TestCase):
    """The repair's own words. An issue with no `issues` entry renders its
    raw translation key, which is the same failure as an add-on option with
    no line in translations/en.yaml."""

    def setUp(self):
        self.strings = json.loads((INTEGRATION / "strings.json").read_text())
        self.translations = json.loads(
            (INTEGRATION / "translations" / "en.json").read_text())

    def test_both_files_carry_the_issue(self):
        for name, blob in (("strings.json", self.strings),
                           ("translations/en.json", self.translations)):
            with self.subTest(file=name):
                issue = blob["issues"][bruh_print.ISSUE_LOCAL_NOT_SERVED]
                self.assertTrue(issue["title"].strip())
                self.assertTrue(issue["description"].strip())

    def test_they_are_the_same_file(self):
        """`test_bruh_print_addon.test_the_translations_are_the_strings`
        compares the whole of both; this says which half drifted."""
        self.assertEqual(self.strings["issues"], self.translations["issues"])

    def test_it_says_what_to_do_and_that_it_is_once(self):
        """Somebody reads this in the Repairs list with a broken dashboard
        behind them. It has to name the folder, the restart, and the fact
        that this does not come back — an instruction with no end reads as a
        thing that will keep happening."""
        issue = self.strings["issues"][bruh_print.ISSUE_LOCAL_NOT_SERVED]
        text = f"{issue['title']} {issue['description']}".lower()
        for owed in ("/config/www", "restart", "once", "custom element"):
            with self.subTest(phrase=owed):
                self.assertIn(owed, text)

    def test_the_learn_more_url_is_the_documented_one(self):
        """The manifest's documentation URL, not a second copy of it that
        can rot on its own."""
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(bruh_print.DOCS_URL, manifest["documentation"])


CARD_FILE = BASE_DIR / "bruh-print" / "lovelace" / "bruh-print-card.js"


class TestTheCardSaysWhatIsMissing(unittest.TestCase):
    """Source-level, and only in addition to
    `tests/manual/measure-print-card.mjs`, which loads this file into a real
    browser and drives it. What a grep can still hold is that the sentence
    the block renders has not been quietly reduced to a word.
    """

    def setUp(self):
        self.card = CARD_FILE.read_text()

    def test_the_block_names_both_halves_of_the_setup(self):
        for owed in ("add-on", "Devices & services"):
            with self.subTest(phrase=owed):
                self.assertIn(owed, self.card)

    def test_the_block_carries_the_card_version(self):
        """A screenshot of a broken dashboard should answer "which card is
        this" without anybody having to ask — a browser holding a month-old
        cached copy is one of the answers."""
        self.assertIn("BRUH Print card ${CARD_VERSION}", self.card)

    def test_the_old_line_inside_the_rolls_block_is_gone(self):
        """It was the only thing the card could say about a missing
        integration, and `show_rolls: false` deleted it."""
        self.assertNotIn("No BRUH Print sensors found", self.card)

    def test_the_block_names_the_entity_options(self):
        """The half 0.4.0's block could not say.

        Entities are matched by suffix, so a renamed device, a renamed
        entity or a second config entry leaves a working printer with a card
        that cannot describe it — and `<suffix>_entity` is the way out. The
        card has accepted those keys since it was written and nothing had
        ever told anybody they exist. `_find` builds the key from a template
        literal, so these strings appear here only because the block names
        them.
        """
        for suffix in _find_suffixes(self.card):
            with self.subTest(option=f"{suffix}_entity"):
                self.assertIn(f"{suffix}_entity", self.card)

    def test_a_print_is_not_announced_from_the_request(self):
        """A grep, and only as a guard against the shape coming back — the
        measure is what proves the card reports what it was told.

        `Printed ${answer.printed || data.copies || 1}` announced a label
        off the request whenever the response carried nothing, so a call
        that resolved with no response data at all reported a print the card
        had never been told about. That is indistinguishable, from the other
        side, from a card that does not print.
        """
        self.assertNotIn("data.copies || 1", self.card)


def _find_suffixes(card):
    """Every entity this card looks for, read off its own `_find` calls."""
    found = set(re.findall(r"_find\('([a-z_]+)'\)", card))
    assert found, "no _find calls in the card — has it been renamed?"
    return sorted(found)


class TestTheCardAndTheIntegrationAgreeOnTheServices(unittest.TestCase):
    """Cross-file, which is the one thing the browser drive cannot see.

    `measure-print-card.mjs` drives the card against a `hass` whose service
    map the measure writes itself, so it can only ever agree with the card.
    What services actually get registered is in the integration, and the two
    drift silently in the worst possible direction: a renamed service leaves
    a card that both disables Print on every house — because the service it
    asks about is not there — and calls a service that is not there either.
    """

    def setUp(self):
        self.card = CARD_FILE.read_text()

    def test_every_service_the_card_calls_is_one_the_integration_registers(self):
        called = set(re.findall(r"_call\('([a-z_]+)'", self.card))
        self.assertTrue(called, "the card calls no service at all")
        self.assertLessEqual(called, set(bruh_print.SERVICES))

    def test_the_service_the_card_gates_print_on_is_one_it_calls(self):
        """Print is disabled on exactly one question — is the service there —
        so the name asked about has to be the name called. Asking about a
        service the card never calls is a gate on something else."""
        gated = set(re.findall(r"'(print_[a-z_]+)'", self.card))
        called = set(re.findall(r"_call\('([a-z_]+)'", self.card))
        self.assertTrue(gated)
        self.assertLessEqual(gated, called | set(bruh_print.SERVICES))

    def test_the_card_uses_the_integrations_domain(self):
        self.assertIn(f"const DOMAIN = '{bruh_print.DOMAIN}'", self.card)


class TestTheEntityOptionsAreDocumented(unittest.TestCase):
    """A card option nothing documents is a card option nobody can use.

    This is the answer the card's own block now points at, and the docs are
    where somebody looks after reading it — so a suffix `_find` learns about
    has to reach both, or the block names a key the reference does not.
    """

    def setUp(self):
        self.suffixes = _find_suffixes(CARD_FILE.read_text())
        self.docs = (BASE_DIR / "bruh-print" / "DOCS.md").read_text()
        self.readme = (BASE_DIR / "bruh-print" / "README.md").read_text()

    def test_the_reference_names_every_one_of_them(self):
        for suffix in self.suffixes:
            with self.subTest(option=f"{suffix}_entity"):
                self.assertIn(f"{suffix}_entity", self.docs)

    def test_the_readme_says_they_exist(self):
        """Not all four — the README is the overview — but somebody whose
        card says "no status" has to find out from it that there is
        something to set."""
        self.assertIn("printer_entity", self.readme)

    def test_the_docs_say_the_sensors_do_not_gate_printing(self):
        """The regression in as many words, because the next person to add a
        readout to this card will reach for the same gate."""
        self.assertIn("printer_entity", self.docs)
        window = self.docs[self.docs.index("printer_entity") - 2000:]
        self.assertRegex(window, r"(?s)print.{0,400}service")


if __name__ == "__main__":
    unittest.main()
