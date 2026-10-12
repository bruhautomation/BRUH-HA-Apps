"""Morph as an add-on: its three version numbers, the request vocabulary
the integration and the service share, and the wire to brAIn's
development loop.

The request kinds and the version are each written down in two or three
places that cannot import each other (a Home Assistant integration, an
add-on service, a manifest), so the only thing that keeps them equal is a
test that reads all of them.
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
MORPH = BASE / "morph"
INTEGRATION = MORPH / "custom_components" / "morph"


def _tuple(path: Path, name: str) -> tuple:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


class TestOneVersion(unittest.TestCase):

    def test_config_manifest_const_and_changelog_agree(self):
        config = yaml.safe_load((MORPH / "config.yaml").read_text())["version"]
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())["version"]
        const = re.search(r'^VERSION = "([^"]+)"', (INTEGRATION / "const.py").read_text(), re.M)
        changelog = re.search(r"^## (\S+)", (MORPH / "CHANGELOG.md").read_text(), re.M)
        self.assertEqual(config, manifest)
        self.assertEqual(config, const.group(1))
        self.assertEqual(config, changelog.group(1))


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
        service answers only loopback, for run.sh's own health poll."""
        config = yaml.safe_load((MORPH / "config.yaml").read_text())
        self.assertFalse(config.get("ingress"))
        self.assertFalse(config.get("ports"))
        self.assertFalse(config.get("host_network"))
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
