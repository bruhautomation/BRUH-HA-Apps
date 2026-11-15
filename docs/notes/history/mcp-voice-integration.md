# brAIn: MCP server, voice and the HA integration: history moved out of docs/notes/mcp-voice-integration.md

What an old release did, how a bug was found and the owner's own words, taken out of the note so it states each rule as it stands now. Each fragment below is the text that was cut, word for word; the rule it led to is in the note.

## Voice exposure and agent levels

> , and until 2.3 it had no effect on brAIn: the area map listed every controllable entity and the MCP server would read or act on any of them, so un-exposing the front door lock did nothing a person could see — the design page names it as the real surprise for an integration that registers as a voice assistant

> `tests/test_assist_exposure.py` drives Core's rule over shapes copied from its answers, the gate through the chokepoints and never the helper, the pool's env into a real spawn, and the listener's route as the subprocess it is.

> 2.9 gave each agent a level and kept the add-on's `assist_tool_access` and `assist_exposure` as the answer for an agent set to "Follow the add-on" — two settings on two screens for one question, and the add-on-wide one was the one that looked authoritative. 2.10 removed both options:

> `tests/test_assist_exposure.py` asserts the options are gone from `config.yaml`, the translations and every script, and drives the shell half with the old env vars set to prove they no longer do anything.


## A failure crosses the boundary: what the listener used to write

> The listener wrote `status: completed` on every result and the bridge read `.result` and nothing else, so an expired login reached `brain.run_task` as an answer, `brain.ask` as `{response: <apology>, data: None}` (which `| default(false)` reads as a real "no"), and an insight job as that morning's report.

> `tests/test_task_failures.py` drives the real `process_task` into the real bridge.


## Voice context

> `extra_system_prompt` and a chat log, and brAIn dropped all four.

> (it returned the caller's `None`, so on cores without a chat log nothing ever continued)

> `tests/test_voice_context.py` drives a satellite turn through the real entity, the real bridge's file IPC and the real pool, and asserts the room is in what the fake CLI was handed.


## A turn that reached a tool, and the reaper

> The pool's fallback for a worker that died was a one-shot of the same request, which is right for a worker that died before touching anything and wrong for one that had already called `control_light` — the one-shot starts from a session with no record of it, so a toggle happened twice.

> `test_voice_run_contract`'s `_quiet_turn` is that stream, driven through `Worker.ask` and `Pool.process_full`.

> "(spare+partial) — partial" after 14 seconds said a turn broke and nothing of how.

> — a warm worker last used just under five minutes ago, or an adopted spare (whose `last_used` is its creation), took a request and was SIGKILLed by the next tick: `partial (worker ended: stdout closed, exit -9)` (#609)


## A narrow task scope: the #621 stories

> `tests/test_task_tool_scope.py` drives the lifted function.

> (`TestTheScopeDoesNotDependOnWhatIsInConfig`)

> **It came back after 4.2.5 because `-P` was not isolation** (#621 again):

> The reason did already reach the journal row's `error` (`TestTheReasonReachesTheJournalRow` drives the refusal block into a real journal file), so a house report with the bare sentence came from a cause that printed nothing — now a status (`tests/test_task_scope_refusals.py`).


## The dashboard echo

> `get_dashboard` answered `url_path or "default"` in all four of its exits, which says nothing a caller did not already know and cannot tell *I asked for nothing and got the default* from *I asked for a dashboard called default* — and `lovelace/config` has never heard of `"default"`, so passing back the word the answer printed came out as **Dashboard not found: default**. The documented workflow is fetch, edit, save, and `brain.update_dashboard` takes exactly that literal for the default dashboard (`power_tools._dashboard_key` maps it and `None` to the same storage key), so one half of the pair handed out a token the other rejected and the round trip broke at its first step. The report is now what was actually read


## ESPHome, Music Assistant and the add-ons

> `tests/test_esphome.py` drives the dashboard half against a real aiohttp server speaking the protocol and the ingress half against a fake Supervisor that refuses a request without the cookie.

> `tests/test_music_assistant.py` drives it against a real aiohttp server speaking the protocol, auth refusals and scope codes included.

> `tests/test_mcp_bruh_addons.py` fakes Core at the WebSocket and drives the real chokepoint.


## The Minecraft world read

> The owner wanted to know what is going on in the world and what the companion builds (#573), so `minecraft_status`

> beside who is on, never an error in its place. `tests/test_mcp_minecraft_world.py`.


## The companion and the desk

> `tests/test_brain_minecraft_faculty.py`, `tests/test_minecraft_companion.py`, `tests/test_mcp_minecraft_world.py`.

> The `busy`/`spacing` canned lines and `TALK_SPACING`/`COMMAND_SPACING` are gone, and so is the "Hmm…" said before every run — with every line coming in it would have answered "lol".

> ; `tests/test_minecraft_talk_timeout.py`; the house's 2026-11-09 report)

> "teleport along the builds" ran as a quick run, the listener stopped it at `TALK_TIMEOUT` less `TIMEOUT_MARGIN` (45 s) with some teleports done, and the bridge's `BrainRunError(code="timeout")` fell into the catch-all that set `brain_down_until` — so for `BRAIN_RETRY` (5 min) every next line was `down`, reply "", nothing attempted, and the line itself said nothing because it had not named the companion. Now a listener timeout

> `tests/test_minecraft_desk.py`, `tests/test_minecraft_game_scope.py`, `tests/test_minecraft_session_resume.py`, `tests/test_brain_minecraft_faculty.py`, `tests/test_minecraft_chat_scope.py`.

> **The handover** of the 1.17.7 engine's family list is unchanged.


## Jobs and their boss bars

> Waiting on the inbox was the only stop before, and with an hour's window a worker that never read it ran on.

> A job ended at 92% and its bar stayed on screen for days.


## BRUH Sight: the owner's words and the 1.19.x placement

> The owner: *"It's really unresponsive and slow and like you can't see what it is doing. It says it can't see the actual server"*, then *"I want the add on to be able to represent Vesper when it's thinking so you can see the stream of thought … Make sure it's not super annoying. It could be represented over vesper's allay or be shown in an item."*

> , the owner in 1.19.2: *"everybody should be able to see everybody elses vesper"*. It was owner-only in 1.19.0–1.19.1, which a child playing beside another could not see.

> : the owner, of 1.19.0 — *"Vesper the ally disappears. It should stay close to what it is building if there is a stream of thought over it."* While

> (1.19.2, the owner: *"Can vesper stay close to where it is building rather than staying in the players top right corner?"*)

> (1.19.1 placed it by `getDirection()`, which pinned it to the top right of the screen)

> ; `tests/test_minecraft_sight.py` runs the Java pattern over the panel's own commands)


## Edits

> The owner, of a refusal to redecorate a room: *"Vesper should be able to do literally anything … It should understand the build, what it was asked, and then do it. Users can undo it if they don't like it."*


## Capabilities per person

> The owner: *"I'm getting stuff like <the companion> can't trigger lights from the chat, but then it actually does … It could be different per user."* The capability paragraph was a fixed text per scope — a trusted run read "a house change may wait for a person's approval" with YOLO on, and a worker had no word on linking the game to the house (one gave up asking for "a link from the game to the house"). It is now one function


## Skins

> The house's working recipe was SkinsRestorer's `skin set <JavaName|textures.minecraft.net link> <player>` over RCON; the companion had no tool for it, guessed Java names and sent players to websites.

> **And a finished game turn was recorded "down"**: the listener read the model's own reply for sign-in phrases ("not logged in", "please log in" — words a skin conversation uses) and wrote `failed/auth`, which the bridge raises and `_quick` turns into `CANNED["down"]`. Those checks now apply only when


## A house change asked for in the game

> The per-person toggle's report asked for the change to show in brAIn's Feed with Undo and a note that it came from Minecraft and who. The ledger row a trusted run wrote said `channel: minecraft_trusted`, which History did not know, so it read as from nowhere; it now carries

> The add-on used to stamp `verified: false` on that line and `tests/` fired `player=None, verified=True`, a shape it never sent: a test of an event is the event the sender builds, not the one the receiver was written for. And `ha_mcp_server._mc_online` answered `(None, "")` when `get_status` itself failed, so `say`, `edit` and `build` at a player iterated the None ("'NoneType' object is not iterable" reached the model); every failure now returns a sentence, and the callers test the sentence.


## What a device shows as

> `tests/test_mcp_device_types.py` drives them through the real dispatcher with Core faked at the WebSocket.


## The voice service allow-list: the failure that led to it

> - **The failure.** The exposure gate asked about the entities a call named, so a call naming none passed it with the Supervisor's admin token behind it. A default voice agent, the kitchen satellite's, could run `homeassistant.restart`, `hassio.host_shutdown`, `update.install` and `brain.create_user {admin: true}`, while the same `reload_config` was refused as a tool. `homeassistant.turn_off {}` on voice reached every entity in the house: the exposure gate had nothing to check, and Core reads it as "all".

> A deny-list of admin domains lists only the ones somebody thought of, and every integration installed afterwards brings more.


## get_history and the logbook

> - The MCP tests could not see the bug: they mocked `ha_api_request` and grepped the endpoint. `tests/test_mcp_history_query.py` drives the real request against a real HTTP server.

> - The logbook returned `result[:50]` of a window Core answers oldest first, which is the part of "what just happened" nobody asked about. Its test asserted only the count, which both cuts satisfy.


## The ledger directory

> Its `makedirs` grew a stray `/config` on every machine the suite ran on.


## Lovelace reach: what the owner was told

> — and the owner was still told brAIn "can't change config", because the words around them refused: Morph's Ask bar told the house's agent "You cannot change the dashboard", a Tell was told a dashboard is "never a Lovelace dashboard", a whole-house voice agent was told it "cannot edit files … say it needs the brAIn chat", a read-only reply "you can change nothing" with no route, and only the terminal's CLAUDE.md named the service. Now the server's


## ESPHome

> The Builder protocol was read off esphome-device-builder 1.15.0's source rather than guessed, and `tests/test_esphome.py` drives both against real aiohttp servers run as an in-memory

> and a WebSocket handshake against a web page failed every install in milliseconds while HTTP listing kept working


## Maps

> The owner asked for maps of the builds "fully hands off" instead of being teleported around.


## Tests the note used to name (the files no longer exist)

- brAIn is Home Assistant's AI Task entity, read-only and vali: `tests/test_ai_task_attachments.py`
- A plugin's answer to a console command is on the console, an: `tests/test_minecraft_world_scripts.py`
- A job is stopped at once, ends partly done rather than faile: `tests/test_minecraft_job_hour.py`
- A job is stopped at once, ends partly done rather than faile: `tests/test_task_refusal_and_stop.py`
- brAIn's half of BRUH Minecraft 1.19.7: a dimension, a waited: `tests/test_mcp_minecraft_dimension.py`
- brAIn's half of BRUH Minecraft 1.19.7: a dimension, a waited: `tests/test_minecraft_skin_service.py`
- brAIn's half of BRUH Minecraft 1.19.7: a dimension, a waited: `tests/test_minecraft_signal_note.py`
- The companion sees the live game and shows what it is thinki: `tests/test_minecraft_sight.py`
- The companion sees the live game and shows what it is thinki: `tests/test_minecraft_thoughts.py`
- Anyone verified in the game may change anything in it, and t: `tests/test_minecraft_companion_edit.py`
- What a game run may do is built for that person this minute,: `tests/test_minecraft_capabilities.py`
- A skin is one console command the game may send, and what th: `tests/test_minecraft_skins.py`
- A house change asked for in the game says so, and who asked,: `tests/test_minecraft_feed.py`
- Which entities reach the voice assistants and each HomeKit B: `tests/test_mcp_assistant_exposure.py`
- brAIn edits Lovelace dashboards from every face that may act: `tests/test_lovelace_reach.py`
- brAIn changes part of a dashboard by path, and a dashboard's: `tests/test_edit_dashboard.py`
