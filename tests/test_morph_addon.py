"""Morph as part of brAIn (4.0): one version, the request vocabulary the
integration and the service share, the service brAIn's run.sh starts, the
retired add-on, and the wire to brAIn's development loop.

The request kinds are written down in two places that cannot import each
other (a Home Assistant integration and a service in brAIn's container), so
the only thing that keeps them equal is a test that reads both.
"""
import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from morph_env import MorphEnv

BASE = Path(__file__).resolve().parent.parent
MORPH = BASE / "brain" / "morph"
INTEGRATION = BASE / "brain" / "custom_components" / "brain" / "morph"


def _tuple(path: Path, name: str) -> tuple:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


class TestOneVersion(unittest.TestCase):

    def test_morph_is_served_under_brains_own_version(self):
        """Morph has no version of its own any more: the panel's modules are
        served under brAIn's, read off the integration's manifest."""
        const = (INTEGRATION / "const.py").read_text()
        self.assertIn("VERSION = _version()", const)
        self.assertIn('"manifest.json"', const)
        self.assertFalse((BASE / "morph").exists(), "the Morph add-on is retired")


class TestBrainRunsTheService(unittest.TestCase):

    def test_run_sh_starts_the_service_and_retires_the_old_add_on(self):
        run = (BASE / "brain" / "run.sh").read_text()
        main = run[run.index("main() {"):]
        self.assertLess(main.index("deploy_custom_integration"), main.index("retire_morph_addon"))
        self.assertLess(main.index("retire_morph_addon"), main.index("start_morph"))
        self.assertIn("/opt/morph/service/morphd.py", run)
        self.assertIn('MORPH_DATA="/data/morph"', run)
        self.assertIn('old_integration="/config/custom_components/morph"', run)
        # Stopped and kept from booting, never uninstalled: that deletes its data.
        self.assertIn('{"boot":"manual"}', run)
        self.assertNotIn("/uninstall", run)
        self.assertIn("COPY morph/ /opt/morph/", (BASE / "brain" / "Dockerfile").read_text())


class TestTheRequestVocabulary(unittest.TestCase):

    def test_every_kind_the_integration_sends_is_one_the_service_handles(self):
        sent = set(_tuple(INTEGRATION / "websocket.py", "WRITE_KINDS"))
        src = (MORPH / "service" / "morphd.py").read_text()
        handled = set(re.findall(r'kind == "([a-z_]+)"', src)) | {"undo_commit", "restore"}
        self.assertEqual(set(), sent - handled,
                         "a kind the panel can send and the service answers with 'unknown'")
        read_only = set(_tuple(MORPH / "service" / "morphd.py", "READ_ONLY_KINDS"))
        self.assertLessEqual(read_only, sent)

    def test_usage_kinds_agree(self):
        """The panel's usage log is filtered by the integration and read by
        the learning pass; a kind one side drops is a use the loop never
        learns from."""
        self.assertEqual(_tuple(INTEGRATION / "websocket.py", "USAGE_KINDS"),
                         _tuple(MORPH / "service" / "learning.py", "USAGE_KINDS"))

    def test_writes_are_admin_only(self):
        src = (INTEGRATION / "websocket.py").read_text()
        block = src[src.index('vol.Required("type"): "morph/request"'):]
        block = block[:block.index("async def")]
        self.assertIn("require_admin", block)


class TestNoHostSurface(unittest.TestCase):

    def test_morph_publishes_no_port_and_no_ingress(self):
        """Its page is a Home Assistant sidebar panel served by Core; the
        service answers only loopback, for run.sh's own health poll, and
        brAIn's config publishes nothing for it."""
        config = yaml.safe_load((BASE / "brain" / "config.yaml").read_text())
        self.assertNotIn("8096/tcp", config.get("ports") or {})
        src = (MORPH / "service" / "morphd.py").read_text()
        self.assertIn('"127.0.0.1"', src)
        self.assertNotIn('"0.0.0.0"', src)


class TestTheWireToBrainsLoop(unittest.TestCase):

    def test_brains_stream_reads_the_outbox_morph_writes(self):
        """Two processes, one file: Morph's ``devloop.publish`` writes it and
        brAIn's ``streams.morph`` reads it. Run the reader in its own
        interpreter, because both sides own a module called ``devloop``."""
        with MorphEnv() as env:
            env.devloop.note_fault("Layout", "Two sections overlapped at rest", "1440px")
            env.devloop.publish("0.1.0")
            outbox = env.paths.DEVLOOP_OUTBOX
            code = ("import json,sys; sys.path.insert(0, sys.argv[1]);"
                    "from devloop import streams;"
                    "print(json.dumps(streams.morph(sys.argv[2])))")
            out = subprocess.run(
                [sys.executable, "-c", code, str(BASE / "brain" / "panel"), str(outbox)],
                capture_output=True, text=True, timeout=60, check=True)
            rows = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertEqual(["Two sections overlapped at rest"], [r["what"] for r in rows])
            self.assertEqual("Morph · Layout", rows[0]["where"])

            gone = subprocess.run(
                [sys.executable, "-c", code, str(BASE / "brain" / "panel"),
                 str(env.root / "nowhere.json")],
                capture_output=True, text=True, timeout=60, check=True)
            self.assertEqual("null", gone.stdout.strip().splitlines()[-1],
                             "Morph absent is a skip, never an empty pass")


if __name__ == "__main__":
    unittest.main()
