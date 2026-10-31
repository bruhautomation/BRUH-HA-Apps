#!/usr/bin/env python3
""""Can ask for anything": a grown-up the family trusts gets brAIn's chat from
Minecraft's chat.

The owner: "I want Vesper to do anything a grown up asks it in game or not …
make it per user toggle, not just all grown ups", and house actions FOLLOW
"Let brAIn act without asking": on, it acts; off, the change waits for a
person — and it waits somewhere real ("I was getting approve this in brain
responses but I have no idea where that would even go in brain"): a Yes/No
question in brAIn › Today and on the phone, answered back in the game.

Driven here, each against the real code:

  * the rules — the toggle is a grown-up's alone, read off for a child even
    when a file says otherwise, and missing (older settings, the handover)
    reads as off;
  * the faculty — toggle off: the `minecraft` scope; toggle on with a name
    the server checked: `minecraft_trusted` and who asked; toggle on and the
    name not checked: never the trusted scope;
  * the listener — `minecraft_trusted` runs on its own channel, with the
    chat's widening when the switch is on and exactly `house` when it is off;
  * the action gate — Minecraft tools pass, a house change acts with the
    switch on and is filed as an approval with it off, the floors still deny;
  * the approval — it is a case on Today with Yes/No, Yes runs exactly the
    call and the game hears "Done", No and an hour without an answer tell the
    game it was not approved;
  * the MCP server — game modes and any console command reach the server on
    the trusted channel and are refused on the guarded one, whose wording
    points at the setting and never at approving;
  * ⚙ › Minecraft — the toggle is drawn on a grown-up's row only.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "brain" / "ha-mcp-server"))
sys.path.insert(0, str(REPO / "brain" / "panel"))

import findings_store  # noqa: E402
import ha_mcp_server as m  # noqa: E402
import minecraft_companion as mcp  # noqa: E402
from test_action_gate import PFX, GateCase  # noqa: E402
from test_brain_minecraft_faculty import FacultyCase, mc  # noqa: E402
from test_mcp_bruh_addons import Base, FakeCore  # noqa: E402
from test_task_tool_scope import LISTENER, flags_for  # noqa: E402

rules = mcp.rules
DAD = "BenMC13765"
MUM = "MumPlays"
KAZ = ".Kaz8044"
OUTSIDE = rules.CANNED["outside"]


# ---------------------------------------------------------------------------
# The rules and the settings
# ---------------------------------------------------------------------------
class TestTheToggleIsAGrownUpsAlone(unittest.TestCase):
    def setUp(self):
        self.shared = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.shared, True)
        (self.shared / "personality.json").write_text(json.dumps({"name": "Juniper"}))
        for p in (patch.object(mcp, "_thinking", lambda: "normal"),
                  patch.object(mcp, "_chat_agent_model", lambda: "")):
            p.start()
            self.addCleanup(p.stop)

    def test_save_and_load_round_trip(self):
        mcp.save({"people": [
            {"person": "Dad", "role": "reader", "players": [DAD], "trusted": True},
            {"person": "Mum", "role": "reader", "players": [MUM]}]}, str(self.shared))
        people = {p["person"]: p for p in mcp.load(str(self.shared))["people"]}
        self.assertIs(people["Dad"]["trusted"], True)
        self.assertIs(people["Mum"]["trusted"], False)
        on_disk = json.loads((self.shared / "minecraft" / "settings.json").read_text())
        self.assertIs(on_disk["people"][0]["trusted"], True)

    def test_a_child_with_the_flag_set_is_read_as_off(self):
        (self.shared / "minecraft").mkdir()
        (self.shared / "minecraft" / "settings.json").write_text(json.dumps({
            "saved_at": 1, "people": [
                {"person": "Kaz", "role": "child", "players": [KAZ], "trusted": True}]}))
        kaz = mcp.load(str(self.shared))["people"][0]
        self.assertIs(kaz["trusted"], False)
        roster = rules.Roster(mcp.load(str(self.shared))["people"])
        self.assertIs(roster.who(KAZ)["trusted"], False)
        # And the panel's own save never keeps it either.
        mcp.save({"people": [{"person": "Kaz", "role": "child", "players": [KAZ],
                              "trusted": True}]}, str(self.shared))
        self.assertIs(mcp.load(str(self.shared))["people"][0]["trusted"], False)

    def test_older_settings_and_the_handover_default_to_off(self):
        (self.shared / "minecraft").mkdir()
        (self.shared / "minecraft" / "handover.json").write_text(json.dumps({
            "family": [{"person": "Dad", "role": "reader", "players": [DAD]}],
            "settings": {"enabled": True}}))
        dad = mcp.load(str(self.shared))["people"][0]
        self.assertIs(dad["trusted"], False)
        (self.shared / "minecraft" / "settings.json").write_text(json.dumps({
            "saved_at": 1, "people": [{"person": "Dad", "role": "reader", "players": [DAD]}]}))
        self.assertIs(mcp.load(str(self.shared))["people"][0]["trusted"], False)

    def test_only_true_turns_it_on(self):
        for value in ("yes", 1, "true", None):
            people = rules.clean_people([{"person": "Dad", "role": "reader",
                                          "players": [DAD], "trusted": value}])
            self.assertIs(people[0]["trusted"], False, value)


# ---------------------------------------------------------------------------
# The faculty: which scope a chat line gets
# ---------------------------------------------------------------------------
TRUSTING = [
    {"person": "Dad", "role": "reader", "players": [DAD], "trusted": True},
    {"person": "Mum", "role": "reader", "players": [MUM]},
    {"person": "Kaz", "role": "child", "players": [KAZ], "trusted": True},
]


class TestWhichScopeALineGets(FacultyCase):
    settings = {"enabled": True, "people": TRUSTING, "saved_at": 1, "greet": False}

    def test_toggle_off_is_the_game_scope_and_its_prompt_points_at_the_setting(self):
        self.join(MUM)
        self.chat(MUM, "Juniper, turn on the kitchen lights")
        turn = self.brain.asked[-1]
        self.assertEqual(turn["tools"], "minecraft")
        self.assertNotIn("speaker", turn)
        self.assertIn(OUTSIDE, turn["prompt"])
        self.assertNotIn("approve", turn["prompt"].lower())

    def test_toggle_on_and_a_checked_name_is_the_chats_reach(self):
        self.join(DAD)
        self.chat(DAD, "Juniper, put me in creative and turn the porch light on")
        turn = self.brain.asked[-1]
        self.assertEqual(turn["tools"], mc.TRUSTED_TOOLS)
        self.assertEqual(turn["speaker"], {"person": "Dad", "player": DAD})
        prompt = turn["prompt"]
        # The person's words are the request; everything else is data.
        self.assertIn("ARE this person's request", prompt)
        self.assertIn("other players' chat", prompt)
        self.assertIn('"message":{"untrusted":true,', prompt)
        # Understand, then do — and say how to undo it.
        for words in ("minecraft_command", "minecraft_world look", "minecraft_world edit",
                      "Do not ask questions", "Keep every change undoable",
                      "‘Juniper undo’"):
            self.assertIn(words, prompt)
        # None of the companion's own building limits are put to it.
        self.assertNotIn("never in a protected place", prompt)
        self.assertNotIn("natural ground", prompt)
        self.assertTrue(self.talks()[0]["trusted"])

    def test_toggle_on_and_a_name_nobody_checked_is_never_trusted(self):
        self.join(DAD)
        # The add-on did not say (an older one): the game's own scope.
        self.clock.t += 10
        self.event("chat", player=DAD, name=DAD, text="Juniper, open the garage")
        self.assertEqual(self.brain.asked[-1]["tools"], "minecraft")
        # The server said it does not check: nothing runs at all.
        n = len(self.brain.asked)
        self.chat(DAD, "Juniper, open the garage", verified=False,
                  advance=rules.TALK_SPACING + 1)
        self.assertEqual(len(self.brain.asked), n)

    def test_a_child_with_the_flag_is_still_words_only(self):
        self.join(KAZ)
        self.chat(KAZ, "Juniper, make me creative")
        self.assertEqual(self.brain.asked[-1]["tools"], "minecraft_talk")


# ---------------------------------------------------------------------------
# The listener
# ---------------------------------------------------------------------------
class TestTheListenerScope(unittest.TestCase):
    def test_read_alone_it_is_exactly_house(self):
        rc, trusted = flags_for("minecraft_trusted")
        self.assertEqual(rc, 0, trusted)
        rc, house = flags_for("house")
        self.assertEqual(trusted, house)
        deny = dict(zip(trusted[::2], trusted[1::2]))["--disallowedTools"].split(",")
        for tool in ("Bash", "Write", "Edit", "WebFetch", "Read"):
            self.assertIn(tool, deny)
        allow = dict(zip(trusted[::2], trusted[1::2]))["--allowedTools"].split(",")
        for tool in ("call_service", "minecraft_command", "minecraft_player",
                     "minecraft_world", "control_light"):
            self.assertIn("mcp__home-assistant__" + tool, allow)

    def test_the_switch_decides_it_on_the_games_own_channel(self):
        src = LISTENER.read_text(encoding="utf-8")
        block = src.split('if [ "$task_tools" = "minecraft_trusted" ]; then', 1)[1]
        block = block.split("\n    fi\n", 1)[0]
        self.assertIn("export BRAIN_CHANNEL=minecraft_trusted", block)
        self.assertIn("unset BRAIN_PERSON_WORDS", block)
        self.assertIn("brain_perms_flag", block)
        on, off = block.split("\n        else\n", 1)
        self.assertIn("task_acts=true", on)
        self.assertIn('task_tools=""', on)
        self.assertIn('task_tools="house"', off)
        # Who asked rides to the gate, as plain names only.
        self.assertIn("BRAIN_MINECRAFT_PLAYER", block)
        self.assertIn("tr -cd 'A-Za-z0-9_.*'", block)
        # The chat's own widening never re-labels it as the chat.
        self.assertIn('[ "$BRAIN_CHANNEL" != "minecraft_trusted" ]', src)

    def test_the_scope_runs_the_switch_branch_for_real(self):
        """The block lifted out of the listener and run in bash, with the
        switch on and off."""
        src = LISTENER.read_text(encoding="utf-8")
        start = src.index('    local task_acts=""\n    if [ "$task_tools" = "minecraft_trusted" ]')
        end = src.index("    # Somebody asked for this and the switch is on", start)
        body = src[start:end].replace("    local ", "    ")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        work = tmp / "task.json"
        work.write_text(json.dumps({"speaker": {"player": "Ben;rm", "person": "Dad"}}))
        for flag, want_tools, want_acts in (("--dangerously-skip-permissions", "", "true"),
                                            ("", "house", "")):
            script = (f'work_file="{work}"\ntask_tools=minecraft_trusted\n'
                      f'brain_perms_flag() {{ printf "%s" "{flag}"; }}\n'
                      + body +
                      '\nprintf "%s|%s|%s|%s" "$task_tools" "$task_acts" '
                      '"$BRAIN_CHANNEL" "$BRAIN_MINECRAFT_PLAYER"\n')
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                 timeout=30, check=False).stdout
            self.assertEqual(out, f"{want_tools}|{want_acts}|minecraft_trusted|Benrm", flag)


# ---------------------------------------------------------------------------
# The action gate and the approval
# ---------------------------------------------------------------------------
LIGHT = (PFX + "call_service", {"domain": "light", "service": "turn_on",
                                "data": {"entity_id": "light.k1"}})


class TrustedGateCase(GateCase):
    def setUp(self):
        super().setUp()
        self.shared = Path(self.tmp.name) / "shared"
        (self.shared / "minecraft").mkdir(parents=True)
        (self.shared / "personality.json").write_text(json.dumps({"name": "Juniper"}))
        self.told: list[tuple[str, dict]] = []
        self.sent: list[tuple] = []
        self.ran: list[tuple] = []
        self.run_ok = True
        self.switch = False
        srv = self.server

        async def call(domain, service, data, timeout=15):
            self.told.append((f"{domain}.{service}", data))
            return {}

        async def notify(rows, *a, **k):
            self.sent.append((rows, a, k))
            return True

        def run_call(tool, args, timeout=0):
            self.ran.append((tool, args))
            return self.run_ok

        for p in (patch.object(self.ha_data, "call_with_response", call),
                  patch.object(srv, "_send_notification", notify),
                  patch.object(srv, "_findings_notify_target",
                               lambda: ("notify.mobile_app_dad", "info")),
                  patch.object(srv, "eff_skip_permissions", lambda: self.switch),
                  patch.object(srv.minecraft_approvals, "run_call", run_call),
                  patch.object(srv.minecraft_companion, "SHARED_DIR", str(self.shared))):
            p.start()
            self.addCleanup(p.stop)

    def trusted(self, tool, args, speaker=None):
        speaker = speaker or {"player": DAD, "person": "Dad"}

        async def body(client):
            res = await client.post("/api/gate", json={
                "tool": tool, "input": args, "channel": "minecraft_trusted",
                "words": [], "session_id": "s", "contract": None, "speaker": speaker})
            self.assertEqual(res.status, 200)
            out = await res.json()
            await asyncio.sleep(0)          # let the phone's send run
            return out
        return self.drive(body)

    def approvals(self):
        return [f for f in findings_store.list_all() if f.get("source") == "minecraft_approval"]

    def press(self, verb):
        row = self.approvals()[0]

        async def body(client):
            res = await client.post(f"/api/case/f:{row['ts']}/{verb}", json={})
            return res.status, await res.json()
        return self.drive(body)

    def game_lines(self):
        return [d["message"] for s, d in self.told if s == "bruh_minecraft.companion_say"]


class TestTheGateOnTheTrustedChannel(TrustedGateCase):
    def test_every_minecraft_tool_passes_without_a_card(self):
        for tool, args in ((PFX + "minecraft_player", {"player": DAD, "action": "gamemode",
                                                       "value": "creative"}),
                           (PFX + "minecraft_command", {"command": "gamemode creative " + DAD}),
                           (PFX + "minecraft_world", {"action": "edit", "value": "a bed"}),
                           (PFX + "minecraft_teleport", {"player": DAD, "to_player": MUM})):
            out = self.trusted(tool, args)
            self.assertEqual((out["decision"], out["path"]), ("allow", "minecraft_trusted"), tool)
        self.assertEqual(self.model_calls, [])
        self.assertEqual(self.approvals(), [])

    def test_with_the_switch_on_a_house_change_acts(self):
        self.switch = True
        out = self.trusted(*LIGHT)
        self.assertEqual((out["decision"], out["path"]), ("allow", "switch"))
        self.assertEqual(self.approvals(), [])
        self.assertEqual(self.model_calls, [])

    def test_with_the_switch_off_it_waits_in_today_and_on_the_phone(self):
        out = self.trusted(*LIGHT)
        self.assertEqual((out["decision"], out["path"]), ("deny", "minecraft_approval"))
        self.assertIn(rules.APPROVAL_LINES["sent_phone"], out["reason"])
        self.assertNotIn("approve it in brAIn", out["reason"])
        rows = self.approvals()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "question")
        self.assertIn("Dad asked in Minecraft: light.turn_on on light.k1", row["text"])
        self.assertEqual(row["minecraft_approval"]["input"], LIGHT[1])
        # On Today, as a Yes / No question.
        feed = self.server._cases_payload()
        case = next(c for c in feed["cases"] if c["source"] == "minecraft_approval")
        labels = [a["label"] for a in case["answers"]]
        self.assertEqual(labels[0], "Yes")
        self.assertIn("No", labels)
        # And on the phone, with the same Yes / No buttons.
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.server.notify_router.actions_for(
            self.sent[0][0], "notify.mobile_app_dad")[0]["title"], "Yes")
        # The same call asked again is the one already waiting.
        self.trusted(*LIGHT)
        self.assertEqual(len(self.approvals()), 1)
        self.assertEqual(self.model_calls, [])
        # And the record ⚙ › Minecraft lists.
        self.assertEqual(mcp.view(str(self.shared))["approvals"][0]["status"], "waiting")

    def test_with_no_phone_it_names_today_alone(self):
        with patch.object(self.server, "_findings_notify_target", lambda: ("", "info")):
            out = self.trusted(*LIGHT)
        self.assertIn(rules.APPROVAL_LINES["sent_today"], out["reason"])
        self.assertEqual(self.sent, [])

    def test_the_floors_still_deny(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "lock.*"
        self.switch = True
        out = self.trusted(PFX + "control_lock", {"entity_id": "lock.back", "action": "unlock"})
        self.assertEqual((out["decision"], out["path"]), ("deny", "floor"))
        self.assertEqual(self.approvals(), [])

    def test_the_guarded_game_channel_is_unchanged(self):
        out = self.ask(*LIGHT, ["please"], channel="minecraft")
        self.assertEqual(out["decision"], "deny")
        self.assertIn("Can ask for anything", out["reason"])
        self.assertEqual(self.approvals(), [])


class TestTheApprovalEnds(TrustedGateCase):
    def test_yes_runs_exactly_the_call_and_the_game_hears_done(self):
        self.trusted(*LIGHT)
        status, _ = self.press("do")
        self.assertEqual(status, 200)
        self.assertEqual(self.ran, [LIGHT])
        self.assertEqual(self.game_lines(), ["Done: light.turn_on on light.k1."])
        to = [d["to"] for s, d in self.told if s == "bruh_minecraft.companion_say"]
        self.assertEqual(to, [[DAD]])
        self.assertEqual(self.approvals(), [])
        self.assertEqual(mcp.view(str(self.shared))["approvals"][0]["status"], "done")

    def test_a_yes_that_does_not_work_says_so(self):
        self.run_ok = False
        self.trusted(*LIGHT)
        self.press("do")
        self.assertIn("didn't work", self.game_lines()[0])

    def test_no_does_nothing_and_the_game_hears_it_was_not_approved(self):
        self.trusted(*LIGHT)
        status, _ = self.press("wrong")
        self.assertEqual(status, 200)
        self.assertEqual(self.ran, [])
        self.assertEqual(self.game_lines(), [
            "That wasn't approved in brAIn: light.turn_on on light.k1."])

    def test_an_hour_without_an_answer_expires_it(self):
        self.trusted(*LIGHT)
        later = self.approvals()[0]["minecraft_approval"]["expires_at"] + 1
        n = self.drive(lambda _c: self.server._expire_minecraft_approvals(later))
        self.assertEqual(n, 1)
        self.assertEqual(self.ran, [])
        self.assertIn("Nobody approved that in brAIn in time", self.game_lines()[0])
        self.assertEqual(self.approvals(), [])

    def test_a_yes_after_the_hour_is_not_carried_out(self):
        self.trusted(*LIGHT)
        row = self.approvals()[0]
        with patch.object(self.server.time, "time",
                          lambda: row["minecraft_approval"]["expires_at"] + 5):
            self.press("do")
        self.assertEqual(self.ran, [])


class TestTheApprovedCallRunsThroughTheMcpServer(unittest.TestCase):
    """`run_call` is the MCP server's own tools/call, so every chokepoint
    inside the tool still stands; driven against the real server process."""

    def test_a_refusal_inside_the_tool_is_not_a_success(self):
        import minecraft_approvals as ma
        env = {"BRAIN_PROTECTED_ENTITIES": "light.*", "SUPERVISOR_TOKEN": ""}
        with patch.dict(os.environ, env):
            ok = ma.run_call(PFX + "call_service",
                             {"domain": "light", "service": "turn_on",
                              "data": {"entity_id": "light.k1"}}, timeout=60)
        self.assertFalse(ok)

    def test_the_description_is_built_from_the_call(self):
        import minecraft_approvals as ma
        self.assertEqual(ma.describe(*LIGHT), "light.turn_on on light.k1")
        self.assertEqual(ma.describe(PFX + "control_lock",
                                     {"entity_id": "lock.back", "action": "unlock"}),
                         "lock unlock on lock.back")


# ---------------------------------------------------------------------------
# The MCP server: the raw path and the wording
# ---------------------------------------------------------------------------
class ServerCore(FakeCore):
    def __call__(self, payload, timeout=15):
        if payload.get("type") == "call_service" and payload.get("domain") == "bruh_minecraft":
            service = payload["service"]
            self.calls.append((("bruh_minecraft", service), payload.get("service_data")))
            if service == "companion_edit":
                return {"response": {"action": {"id": "20261031-eeeeee",
                                                "text": "Juniper changed a bedroom"},
                                     "changed": 3, "note": "Changed 3 blocks."}}
            if service in ("rcon_command", "set_gamemode"):
                return {"response": {"reply": "Set own game mode to Creative Mode"}}
        return super().__call__(payload, timeout)


class TestTheRawPath(Base):
    def setUp(self):
        super().setUp()
        self.core.__class__ = ServerCore
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "minecraft").mkdir()
        (root / "minecraft" / "settings.json").write_text(json.dumps({
            "enabled": True, "saved_at": 1, "people": TRUSTING}))
        (root / "personality.json").write_text(json.dumps({"name": "Juniper"}))
        p = patch.object(m, "MC_SHARED_DIR", str(root))
        p.start()
        self.addCleanup(p.stop)

    def channel(self, word):
        p = patch.dict(os.environ, {"BRAIN_CHANNEL": word})
        p.start()
        self.addCleanup(p.stop)

    def services(self):
        return [k[1] for k, _ in self.core.calls if k[0] == "bruh_minecraft"]

    def test_a_trusted_run_reaches_gamemode_and_any_console_command(self):
        self.channel("minecraft_trusted")
        got = m.minecraft_command("gamemode creative DadCraft42")
        self.assertNotIn("error", got)
        self.assertIn("rcon_command", self.services())
        got = m.minecraft_player("DadCraft42", "gamemode", "creative")
        self.assertNotIn("error", got)
        self.assertIn("set_gamemode", self.services())
        self.assertIsNone(m._minecraft_chat_refusal("light", "turn_on"))

    def test_the_guarded_channel_refuses_them_pointing_at_the_setting(self):
        self.channel("minecraft")
        for got in (m.minecraft_command("gamemode creative DadCraft42"),
                    m.minecraft_player("DadCraft42", "gamemode", "creative"),
                    m.minecraft_world("edit", "a bed", blocks=[{"x": 0, "y": 64, "z": 0,
                                                                "block": "red_bed"}]),
                    m.call_service("light", "turn_on", {"entity_id": "light.k1"})):
            self.assertIn(OUTSIDE, got["error"])
            self.assertNotIn("approve that", got["error"])
        self.assertNotIn("rcon_command", self.services())
        self.assertNotIn("companion_edit", self.services())

    def test_a_trusted_redecorate_goes_straight_to_the_edit_and_names_the_undo(self):
        self.channel("minecraft_trusted")
        got = m.minecraft_world("edit", "Dad's bedroom", player="DadCraft42", blocks=[
            {"x": 1, "y": 0, "z": 0, "block": "red_bed[facing=east,part=foot]"},
            {"x": 2, "y": 0, "z": 0, "block": "red_bed[facing=east,part=head]"},
            {"x": 3, "y": 0, "z": 0, "mode": "remove"}])
        self.assertTrue(got["done"])
        self.assertEqual(got["id"], "20261031-eeeeee")
        self.assertIn("undo", got["undo"])
        key, data = self.core.calls[-1]
        self.assertEqual(key, ("bruh_minecraft", "companion_edit"))
        self.assertEqual(data["player"], "DadCraft42")
        self.assertEqual(data["blocks"][2], {"x": 3, "y": 0, "z": 0, "mode": "remove"})

    def test_look_is_open_to_the_guarded_game_scope_too(self):
        self.channel("minecraft")
        self.assertIn(("bruh_minecraft", "look_blocks"), m.MINECRAFT_CHAT_SERVICES)
        self.assertIn("look", m.MINECRAFT_CHAT_ACTIONS)

    def test_voice_may_not_edit_or_look(self):
        self.voice()
        self.assertIn("Voice assistant", m.minecraft_world("edit", "x")["error"])
        self.assertIn("Voice assistant", m.minecraft_world("look", "0 64 0")["error"])
        for service in ("companion_edit", "look_blocks"):
            self.assertIn(("bruh_minecraft", service), m.VOICE_ADMIN_SERVICES)


class TestNoGuardedSentenceSaysApprove(unittest.TestCase):
    """The 4.0.29 sentence sent the owner looking for an approval that did
    not exist. Nothing on the guarded path says "approve" any more."""

    def test_every_guarded_refusal(self):
        import gate
        for text in (gate.MINECRAFT_OUTSIDE, m.MINECRAFT_CHAT_REFUSAL, OUTSIDE):
            self.assertNotIn("approve", text.lower())
        self.assertEqual(gate.MINECRAFT_OUTSIDE_LINE, OUTSIDE)
        self.assertEqual(m.MINECRAFT_OUTSIDE_LINE, OUTSIDE)
        src = (REPO / "brain" / "custom_components" / "brain" / "minecraft.py").read_text(
            encoding="utf-8")
        self.assertNotIn("approve that in brAIn", src)


class TestTheHookCarriesWhoAsked(unittest.TestCase):
    def test_only_on_the_trusted_channel(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_gate_hook_trusted", REPO / "brain" / "scripts" / "brain-action-gate.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        env = {"BRAIN_MINECRAFT_PLAYER": DAD, "BRAIN_MINECRAFT_PERSON": "Dad"}
        with patch.dict(os.environ, env):
            self.assertEqual(hook.speaker("minecraft_trusted"),
                             {"player": DAD, "person": "Dad"})
            self.assertIsNone(hook.speaker("chat"))
            self.assertIsNone(hook.speaker("minecraft"))


# ---------------------------------------------------------------------------
# ⚙ › Minecraft
# ---------------------------------------------------------------------------
class TestTheToggleIsDrawnOnGrownUpRowsOnly(unittest.TestCase):
    def setUp(self):
        self.js = (REPO / "brain" / "panel" / "app.js").read_text(encoding="utf-8")

    def fn(self, name):
        start = self.js.index(f"function {name}(")
        return self.js[start:self.js.index("\n}\n", start)]

    def test_the_row_draws_it_only_for_a_grown_up(self):
        row = self.fn("mcPersonRow")
        self.assertIn('${p.role === "reader" ? mcTrustedToggle(p, i) : ""}', row)
        toggle = self.fn("mcTrustedToggle")
        self.assertIn("Can ask for anything", toggle)
        self.assertIn('data-k="trusted"', toggle)
        self.assertIn("doesn't check accounts", toggle)
        self.assertIn("isn't used", toggle)

    def test_the_save_sends_it_for_a_grown_up_only_and_a_role_change_redraws(self):
        read = self.fn("mcReadPeople")
        self.assertIn('trusted: v("role") === "reader" && !!(trusted && trusted.checked)', read)
        self.assertRegex(self.js, re.compile(
            r't\.dataset\.k !== "role"\) return;\s*\$\("#mcPeople"\)\.innerHTML = '
            r'mcReadPeople\(\)\.map\(mcPersonRow\)'))

    def test_trusted_runs_and_approvals_are_listed(self):
        render = self.fn("renderMinecraft")
        self.assertIn("(can ask for anything)", render)
        self.assertIn("Asked to approve", render)


if __name__ == "__main__":
    unittest.main()
