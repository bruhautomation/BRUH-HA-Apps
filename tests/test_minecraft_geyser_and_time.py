"""#591: Geyser's options reach Geyser, and the world's time is read.

Two problems a house saw on BRUH Minecraft 1.17.7 with Geyser 2.12.1 on
Paper 26.3:

* "Environment variable GEYSER_AUTH_TYPE does not match any config option"
  and the same for GEYSER_MTU on every start. Geyser (2.9+) reads every
  `GEYSER_*` variable in the server's environment as an override of the
  config path it spells (`GEYSER_JAVA_AUTH_TYPE`), so the add-on's own
  variables collided with that scheme and did nothing. The add-on now
  exports `BRUH_GEYSER_*` and writes the options into config.yml in
  whichever layout it is: old (`remote.auth-type`, a top-level `mtu`,
  `bedrock.motd1`) or new (`java.auth-type`, `advanced.bedrock.mtu`,
  `motd.primary-motd`), read off Geyser's own ConfigMigrations.
* The World time and World day sensors stayed unknown: a `time query`
  answer that is not exactly "The time is N" read as nothing. The parser
  now takes the shapes servers answer in, falls back to the bare command
  and then to level.dat's DayTime.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "bruh-minecraft-server"
SCRIPTS = ADDON / "scripts"
PATCHER = SCRIPTS / "patch-geyser-config.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


geyser = _load("test_geyser_patcher", PATCHER)
mcworld = _load("test_geyser_time_mcworld", ADDON / "panel" / "mcworld.py")

OLD = textwrap.dedent("""
    bedrock:
      port: 19132
      motd1: "Geyser"
      motd2: "Another Geyser server."
    remote:
      address: auto
      port: 25565
      auth-type: online
    floodgate-key-file: key.pem
    mtu: 1400
    advanced:
      mtu: 1400
""").lstrip()

# What Geyser 2.12 writes (config-version 11), trimmed.
NEW = textwrap.dedent("""
    bedrock:
      address: 0.0.0.0
      port: 19132
    java:
      address: 127.0.0.1
      port: 25565
      auth-type: online
    motd:
      primary-motd: "Geyser"
      secondary-motd: "Another Geyser server."
      passthrough-motd: true
    advanced:
      cache-images: 0
      bedrock:
        broadcast-port: 0
        compression-level: 6
        mtu: 1400
        validate-bedrock-login: true
    config-version: 11
""").lstrip()


def _run_managed(text: str, *args: str) -> tuple[subprocess.CompletedProcess, str]:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.yml"
        cfg.write_text(text)
        proc = subprocess.run([sys.executable, str(PATCHER), "--managed", str(cfg), *args],
                              capture_output=True, text=True, check=False)
        return proc, cfg.read_text()


class TestTheOptionsGoIntoTheFile(unittest.TestCase):
    def test_the_new_layout_gets_the_new_keys(self):
        proc, text = _run_managed(NEW, "offline", "1200", "false", "Our World", "Sub")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "new")
        data = yaml.safe_load(text)
        self.assertEqual(data["java"]["auth-type"], "offline")
        self.assertEqual(data["advanced"]["bedrock"]["mtu"], 1200)
        self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], False)
        self.assertEqual(data["motd"]["primary-motd"], "Our World")
        self.assertNotIn("remote", data)
        self.assertNotIn("mtu", data)
        # Everything Geyser wrote that the add-on does not own survives.
        self.assertEqual(data["config-version"], 11)
        self.assertEqual(data["advanced"]["bedrock"]["compression-level"], 6)
        self.assertIs(data["motd"]["passthrough-motd"], True)

    def test_the_old_layout_keeps_its_keys_and_loses_the_stray_mtu(self):
        proc, text = _run_managed(OLD, "floodgate", "1200", "true", "Our World", "Sub")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "old")
        data = yaml.safe_load(text)
        self.assertEqual(data["remote"]["auth-type"], "floodgate")
        self.assertEqual(data["mtu"], 1200)
        self.assertEqual(data["bedrock"]["motd1"], "Our World")
        # 1.17.7 staged `advanced.mtu`, which no Geyser reads.
        self.assertNotIn("mtu", data["advanced"])
        self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], True)
        self.assertEqual(data["floodgate-key-file"], "key.pem")

    def test_it_is_idempotent_and_quotes_the_motd(self):
        _, once = _run_managed(NEW, "floodgate", "1400", "true", 'Dad\'s "World"', "Sub")
        _, twice = _run_managed(once, "floodgate", "1400", "true", 'Dad\'s "World"', "Sub")
        self.assertEqual(once, twice)
        self.assertEqual(yaml.safe_load(once)["motd"]["primary-motd"], 'Dad\'s "World"')

    def test_bad_values_are_refused(self):
        for args in (("sometimes", "1400", "true", "a", "b"),
                     ("online", "lots", "true", "a", "b"),
                     ("online", "1400", "maybe", "a", "b")):
            proc, text = _run_managed(NEW, *args)
            self.assertEqual(proc.returncode, 64, args)
            self.assertEqual(text, NEW)


class TestNoGeyserVariableReachesTheServer(unittest.TestCase):
    def test_run_sh_exports_no_geyser_prefixed_variable(self):
        run = (ADDON / "run.sh").read_text()
        exported = " ".join(re.findall(r"export ([A-Z_ \\\n]+)", run))
        self.assertNotRegex(exported, r"(?<![A-Z_])GEYSER_")
        self.assertIn("BRUH_GEYSER_AUTH_TYPE", exported)
        self.assertIn("BRUH_GEYSER_MTU", exported)

    def test_no_script_reads_the_old_names(self):
        for path in [ADDON / "run.sh", *SCRIPTS.glob("*.sh")]:
            text = path.read_text()
            for var in ("GEYSER_AUTH_TYPE", "GEYSER_MTU"):
                self.assertNotRegex(text, rf"\$\{{?{var}\b", f"{path.name} reads ${var}")

    def test_a_fresh_install_is_staged_in_the_new_layout(self):
        source = (SCRIPTS / "install-bedrock-support.sh").read_text()
        body = source[source.index("configure_geyser() {"):]
        self.assertIn("java:\n  auth-type: ${auth_type}", body)
        self.assertIn("advanced:\n  bedrock:", body)
        self.assertIn("    mtu: ${mtu}", body)
        self.assertNotIn("\nremote:", body)


class FakeSession:
    def __init__(self, replies):
        self.replies = replies
        self.asked = []

    def command(self, cmd):
        self.asked.append(cmd)
        reply = self.replies.get(cmd, "Unknown or incomplete command, see below for error")
        if isinstance(reply, Exception):
            raise reply
        return reply


class TestTheWorldTime(unittest.TestCase):
    REPLIES = [
        ("The time is 6000", 6000),
        ("§7The time is §a18000", 18000),
        ("The time of minecraft:overworld is 6000 ticks", 6000),
        ("Time: 13,500", 13500),
        ("13500", 13500),
        ("The current day is 37", 37),
        ("Daytime is 1200 ticks.", 1200),
        ("Unknown or incomplete command, see below for error", None),
        ("Incorrect argument for command", None),
        ("", None),
        ("time query <daytime|gametime|day>", None),
    ]

    def test_realistic_replies(self):
        for reply, want in self.REPLIES:
            self.assertEqual(mcworld.parse_time(reply), want, reply)

    def _collector(self, tmp, replies, nbt=None):
        col = mcworld.WorldCollector(
            rcon_factory=lambda: None, server_dir=Path(tmp), out_path=Path(tmp) / "world.json",
            read_nbt=nbt)
        col.session = FakeSession(replies)
        return col

    def test_the_namespaced_command_first_then_the_bare_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = self._collector(tmp, {
                "time query daytime": "The time of minecraft:overworld is 6000 ticks",
                "time query day": "The time of minecraft:overworld is 12"})
            col._poll_time(100.0)
            self.assertEqual(col.world_time["daytime"], 6000)
            self.assertEqual(col.world_time["day"], 12)
            self.assertEqual(col.world_time["clock"], "12:00")
            self.assertEqual(col.world_time["source"], "server")
            self.assertEqual(col.session.asked[:2],
                             ["minecraft:time query daytime", "time query daytime"])

    def test_a_server_that_will_not_say_falls_back_to_the_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = self._collector(tmp, {}, nbt=lambda path: {"Data": {"DayTime": 3 * 24000 + 18000}})
            col._poll_time(100.0)
            self.assertEqual(col.world_time["daytime"], 18000)
            self.assertEqual(col.world_time["day"], 3)
            self.assertEqual(col.world_time["phase"], "night")
            self.assertEqual(col.world_time["source"], "save")

    def test_nothing_readable_leaves_it_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = self._collector(tmp, {})
            col._poll_time(100.0)
            self.assertIsNone(col.world_time)


if __name__ == "__main__":
    unittest.main()
