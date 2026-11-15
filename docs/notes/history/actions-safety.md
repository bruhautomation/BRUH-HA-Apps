# brAIn: changing the house safely: history moved out of docs/notes/actions-safety.md

What each rule in `docs/notes/actions-safety.md` cost to learn: measurements, bug stories, owner quotes and pointers to tests. None of it is needed to follow the rules; it is here for the next person who wonders why a rule exists. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite; the rules they enforced still hold. Each entry is the text as it stood in the note, cut out of the bullet named in its heading.

## A playbook's identity included a list the snapshot might not have been able to fetch

- Measured: flipping only that field moves all three keys and drops `freeze` entirely, since it is notify-only. Both passes look successful in the log, which is why it reads as the add-on simply ignoring a decline with nothing to point at.
- — while this one did not. The fixture could not see it either: it built a snapshot with no `available` map at all, so every test ran the one case the producer must stand down on.
- had the same class of instability one door over and now rounds

## A press that changes a house says what it will change FIRST

- `tests/test_fix_plan.py` pins it by driving the routes with `run_agent` rigged to FAIL the test unless a case opts in, and by driving the REAL writers for the undo — the journal line out of `brain-edit-snapshot.py`'s own `main` over a real PreToolUse payload, the ledger row out of `ha_mcp_server.record_action` — because those are processes the panel cannot import, and a shape written down twice is a shape that drifts.

## Fix plans: tests and ledger pointers

- The test drives `ha_mcp_server._read_before` and `record_action` to hold the shapes equal.
- Every chokepoint test that asserted exactly one Core request now counts service POSTs.

## A trusted person in Minecraft

- , `tests/test_minecraft_trusted.py`)
- The owner: *"I want Vesper to do anything a grown up asks it in game or not … make it per user toggle, not just all grown ups"*, and *"I was getting approve this in brain responses but I have no idea where that would even go in brain."* The trust model:

## The action gate

- `tests/test_run_queue.py` exempts exactly `_gate_decide`.

## "Let brAIn act without asking" reaches the action gate too

- , `tests/test_one_brain.py`)
- `tests/test_action_gate.py::TestTheSwitchReachesTheGate` drives both interactive channels, a task channel, a floor and the cache with the switch on.

## YOLO mode is the owner's opt-in to no restrictions

- , and `tests/test_yolo_mode.py` holds them equal
- Asked-for scenes became a card to accept whatever either switch said, and the reply and Morph surfaces drafted rules untyped, so the switch never reached them (`tests/test_scenes_act_and_naming.py`).

## brAIn's own surfaces need no press, YOLO or not

- `tests/test_house_auto_undo.py` pins the texts and the undo.

## A rule in a sentence is drafted, SIMULATED, then offered

- `intents.py` armed a one-off and answered every standing sentence with a refusal card telling somebody to ask some other way; this is the other way.
- , and `tests/test_authoring.py` drives `build` over each refusal and `case_line` over each shape of answer

## A file Claude cannot write is brAIn's to fix

- A run ended *"Run sudo chown claude /config/scenes.yaml /config/scripts.yaml and I'll apply the rest."*
- `tests/test_file_ownership.py` drives the route's validation over real links, FIFOs, hard links and a `0444` file, and the same checks in every tree, the real `h_own` over a loopback `TestServer` (and a non-loopback request carrying `X-Forwarded-For: 127.0.0.1`, which gets a 403), the real edit hook as an unprivileged uid against the real route leaving a root-owned `0444` `scenes.yaml` writable, the shell hook as a subprocess against a stub panel and against none, the `/addon_configs` sweep, one driven scheduler tick with insights off, and `own_ha_config` lifted out of the real `run.sh` under `errexit`/`nounset`/`pipefail` with a failing `chown` and a hard link. `test_insights_addon`'s scheduler-tick helpers stand the sweep down, so the suite never chowns a real `/config`.

## protected_entities has a second chokepoint

- For a Bash command it allows, it also hands the tree paths the command names to the `claude` user before it runs (the ownership bullet above); a command it refuses asks nothing.

## A trial is the difference between a suggestion and a change

- — the test that was supposed to hold that passed under both implementations until its fixture had two consecutive samples above the bar
- — but **bypassing it copied the way it asked**, and that was three modules pasting `','.join(ids)` into a URL after a `?` while `_rest_get`'s own docstring said not to and said why. On the replay
- ; `tests/test_ha_history_query.py` drives it against a real aiohttp server, because the valueless flags Core wants are the detail a hand-written expectation gets wrong in exactly the way the code did, and it greps for the old shape so a fourth copy cannot come back
- **And the image did not ship Jinja** — the template branch carried `# pragma: no cover — the image ships jinja2` and the Dockerfile installed no such package, so every template trigger refused on every real install while three tests passed on machines that happened to have Jinja from somewhere else: **a comment cannot fail**, which is the `pop`-line failure with the grep replaced by prose. `py3-jinja2` is in the image, `jinja2` is in the test requirements, and both are asserted separately, because the tests run where pip installed it and the add-on runs where apk did.
- **1.42.0 shipped the lifecycle and not the two steps that make it mean anything** — "Try it for a week" set a status and an end date and nothing ever looked at the week (`trial_due` and `record_trial` had no caller outside their own tests), and Accept recorded a status and never created the automation.
- (the test asserts the prefix is byte-identical, not that it still parses)
- in `tests/test_shadow.py`,

## A playbook / healing / byte splice / scenes: stories and pointers

- , where it was a plain subtraction answering no at every minute after midnight: forty-five minutes of window became nine on a five-minute poll, and a panel restarted at 23:55 woke after the night was over
- Six refusals, each a test naming its mutation.
- : `routines.to_config` drops its `alias` for exactly this reason
- 1.44.0's writer appends and never rewrites; two of 1.46.0's producers have to change
- The invariant is fuzzed — `tests/test_entry_edit_fuzz.py` generates a hundred and twenty files out of a grammar of the shapes a person's file really holds and drives the real `remove_entry`/`replace_entry` over every entry in each.
- a house whose scenes read "Kitchen - Dim" got "Morning — Kitchen" beside them, and a second scene for a mood the room already had; the separator
- , so `test_scenes` scopes its check to what the module *emits* rather than to its comments
- Two things it found by using them: **`shadow.passes` did not wrap midnight** on a `time` condition (Core reads `after > before` as "tonight until tomorrow morning", and testing the two bounds separately answers False at every instant of such a window — so a `not`-wrapped one passes at every instant instead), and **`would_do` did not look inside a `choose`**, so `_protected_refusal` saw no service calls in one and passed it vacuously.
- , and eight adds measured **four** distinct ids
