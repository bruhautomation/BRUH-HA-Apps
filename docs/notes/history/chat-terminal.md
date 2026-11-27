# brAIn: Ask (the chat and the terminal): history moved out of docs/notes/chat-terminal.md

What each rule in `docs/notes/chat-terminal.md` cost to learn. None of it is needed to follow the rules; it is here for the next person who wonders why a face switch, a registry rule or a title rule exists. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite; the rules they enforced still hold.

## Two faces and the switch

- **The face switch on both faces.** The classic face hid its own switch, and ⚙ called it *Opens as*, which a search for "terminal" or "chat" never found, so a house on the terminal face could not find the way back anywhere.
- **Ask is Claude Code's terminal.** Enforced by `tests/test_terminal_ask.py`.
- **Ask follows the saved face.** The panel used to flip its face to the terminal *locally* (`applyTermMode("classic")` inside `openInTerminal`) without saving it, so the next status refresh (`syncTermMode`, on usage moving because Claude had just run) put the saved face back and the person was left on an empty "New chat" while their question ran in a hidden tmux window.
- **One process owns a conversation.** That is a fact about the CLI, and it was *not* the reason the chat used to hold only one session (see the registry below).
- **Adopt.** Adopt used to be refused mid-answer, because losing an answer being written was judged worse than waiting for it; once adopt went through `registry.open`, nothing is stopped and the refusal went. `brain-terminal-start.sh` deletes the handoff file when it takes it up, so by the time somebody switched back, the record adopt was meant to prefer was usually gone, and "newest file" picked up whatever wrote last — which is why the panel keeps its own copy.

## One Claude Code, launched the same way

- **Parity.** The owner: *"Chat and terminal should behave the same."* The "What brAIn brings" page found the terminal got no per-message facts. `tests/test_ask_face_parity.py` built both launches and compared them field by field.
- **The project settings file.** The pre-approvals have been in `settings.local.json` since 2.11. The old allow-list (Bash, Write, Edit, every HA tool) used to be the project file itself; it moved to `/config/.brain/headless_settings.json`. Before this, `dangerously_skip_permissions: false` was close to a no-op and the chat's approval card could not appear.
- **What brAIn said lately.** A new conversation was told a count of things waiting, brAIn's health and the house's rhythm, so "what did you mean this morning?" landed on a blank.

## Sessions and the registry

- **One process per open conversation.** The registry was a module singleton, so switching was `stop()` + `--resume` and `resume()`/`set_model()` refused mid-answer with a 409 saying Claude was still responding — honest for one process, and the wrong shape for the question, because native Claude Code is one process per terminal tab and that is precisely what was being asked for.
- **Each viewer's conversation.** Every device used to act on one shared "attached" session: a phone in conversation A, a desktop opening B, and the phone's next message landed in B, because `send`, `stop`, the model picker and the approval answer all went to `registry.attached()` and `attach` broadcast `switched` to whoever was watching. `tests/test_ask_routing.py::TestEachViewerHasItsOwnConversation`.
- **No request waits out a spawn.** A send, an Ask and a Discuss that had to start a process used to hold the request through `START_GRACE` per spawn attempt (10 s, two or three attempts on a resume that falls back) — long enough for a proxy in front of ingress to give up.
- **No cap by default.** The owner asked for every conversation to be able to run at once. A stored 3 reading as no limit was the owner's decision: every settings save wrote the effective values back, so an install from before "No limit" held `chat_max_sessions: 3` whether or not anybody chose it.
- **A spawn watched until its first word.** The old behaviour was a chat that spawned, died silently, and errored on every send, while the restored resume id respawned the same failure forever.
- **`error_max_turns`.** "Start a new chat to carry on" was the old answer, and it charged the person's conversation for a per-process guard.
- **A run ended on purpose.** `tests/fake_claude_chat.py` answered an interrupt with `success`, which is why nothing saw that the CLI closes a stopped turn as `error_during_execution`.
- **Row states.** With several live conversations, "which of these is actually running" stopped being answerable by looking: a paused, a room-made and a context-lost conversation all rendered as a row with nothing on it. The old "Your next message resumes…" line and its **Resume now** were a second control for Send, cut in the redesign.
- **A reply answered off the drain.** The request drain awaited a Reply's Claude run (up to `REPLY_TIMEOUT_S`), so every ending ticked after a reply waited for the whole run.

## The stream and the transcript

- **`thinking_delta`.** Retro-inserting reasoning after its conclusion is what "the chat doesn't show thinking" actually was. The three dots used to show only until the first token.
- **A user turn the CLI wrote.** The replay's list of "not typed by a person" never had `<task-notification>`, so 4 KB of raw XML, literal `\n` and entities rendered as right-aligned bubbles the person had supposedly sent.
- **The display clip.** The same 4,000-character cut was applied to every user turn and every reply, and a request Morph hands brAIn runs to tens of thousands of characters with the person's own words LAST, so the one sentence that was the point of the conversation was never on screen. `tests/test_display_clip.py`, `tests/test_conversation_words_whole.py`.
- **The replay budget.** Measured on a real transcript, 92% of replay events were tool calls, so a 400-event window carried 3 of 17 user turns — which is what "switching faces loses messages" actually was.
- **One file per conversation.** A single transcript file was the shape of a single session.
- **Closing the one on screen.** `close` removed a background session from the listing and left the attached one in it, stopped but still held, so the delete answered with the same sentence the person had just obeyed.
- **Batch delete.** The panel's selection mode and the ⋯ conversations dialog were cut in the redesign (one list, one ⋯ per row); the batch route stayed.

## The model and the context pill

- **`_spawned_model`.** Asking `session.model` is how the picker answered "already that model" about a session still running the old one, forever.
- **`model_label` in the response.** Waiting for the next `init` is how the picker looked like it did nothing.
- **One place for a model's name.** The panel had a second regex for it and the two drifted the way a second copy always does: it read `claude-haiku-4-5` as "Claude Haiku 4" and took the leading digits of a date stamp for a version, so `claude-3-5-sonnet-20241022` came out "Claude Sonnet 2". Every 4.x model of a family printed the same name, so a working selector was indistinguishable from one that did nothing.
- **The Default row.** Without ⚙ handing the label back, the highlighted row went on naming the model you had just replaced.
- **The context pill.** Summing every call's `usage` measured how hard Claude worked and reported a ten-tool turn as ten conversations. The table used to say 200K for every Opus and every Sonnet, which was true when it was written and was wrong for every model the add-on ran later. The two failures multiplied, and the pill routinely claimed several hundred percent of a window five times too small. Moving to Haiku left 42k being divided by 1M and reported as 4% of a window it fills 21% of, and it stayed wrong until something else happened to refresh it.

## Discussions and resolutions

- **Discuss opens a conversation.** It used to `reset` the attached session. That killed a busy chat's answer and its approval card. `ChatSession.finding_ts` was at first set by the Discuss route after its `reset`.
- **Resolutions.** Agreeing at the end of a discussion meant retyping the answer into the reason box.
- **A discussion acts when the switch is on.** It was "only changing Home Assistant asks" for a release, which in use meant a discussion answering *"press Plan to do that"* to somebody who had just asked for the change: the household's rule is that the chat does what it is asked, and a card's conversation is the chat. `tests/test_discuss_safety.py::TestWithTheSwitchOnADiscussionActsLikeTheChat`.

## The conversation list

- **The machines' pills.** The redesign moved the run-type chips into ⚙ › Diagnostics › Runs on the argument that they made the list of your conversations the place to audit the machines, and in use that buried them three presses deep, so they came back over the list. Your chats buried under forty voice turns was the original complaint.
- **An empty Ask on a phone.** The list page was "No chats yet." and a press before anybody could type, under two bare glyphs; ⤢ went with the folding bar.
- **The list on a phone.** The breakpoint was 1100 until the UI audit found a 1024 laptop paging between list and transcript with 700px unused. The strip above the composer used to follow `localStorage` rather than the conversation on screen.
- **Machine run titles.** A card run's first message is the prompt brAIn built, so the Cards list was a column of `INSIGHT CATEGORY: …` cut before the part that differs.
- **A word on a row (#1302).** Five green "Live" pills over chats nobody was using told a person nothing.
- **The overlap audit (#1256).** A row scrolled past the bottom of the list answered its whole box under the new-chat box and was reported as covering it.
- **The `::after` spacer (#1137).** Padding left the last row flush under the message box on an iPhone.

## Titles

- **The person's words, never the prompt (#882).** Ask-abouts, Personality's and Instructions' Ask, Talk it through and Morph's Ask line and Tell all opened with machine text, and the list showed it.
- **One small run after the first reply (#1119).** `short_title` can only cut the words typed, so prompts and typos ("You are …") were the list.

## The classic terminal

- **One handoff file per request.** The single `/data/terminal-handoff.json` was a race: two Asks in quick succession wrote over each other and the second window opened on the first one's words. `tests/test_ask_routing.py::TestTheHandoffArgument`.
- **The frame retry.** The frame was pointed at `terminal/` once and, if that caught the proxy's error page during a restart, kept it.
- **The phone's input.** Paste's refusal on `pointerdown` went into an empty catch — "I can't paste". Paste sent straight down the socket made every newline an Enter, and a two-line paste submitted its first line. The frame's baseline was grow-only: the panel folding its bar made the frame taller, and on a WebView that resizes for the keyboard the unfolded frame then read as "shrank for a keyboard", folded the bar, grew, unfolded — the old script flapped the bar ~45 times in a second after one keyboard close.
- **The microphone.** arecord's calls were read off the 2.1.307 bundle. `tests/test_voice_mic.py` ran the real stand-in against the real routes. The harness's unread pipe filling at 64 KB is how the first run measured audio "lost" that the CLI would have had.

## Layout of the Terminal tab

- **One thing floats.** Five translucent squares stacked over someone's output was the clutter the chat view exists to avoid.
- **Nothing folds the bar away (#834, #838).** The owner: *"Completely get rid of that so that this app looks great in either full screen or normal mode"*. Ask had a ⤢ "full-screen terminal" (`body.term-immersive`, `termChrome`, remembered in `localStorage['brain.termFull']`) and folded the header on its own whenever the composer took focus on a touch screen or the ttyd frame reported its keyboard (`brain-keyboard`). On a phone in the shell that took the tabs and ⚙ with it: a pinned ⤢ left the owner in Ask with no way out, and a tap on a tab from the composer landed on whatever was under the folded header (the fold came back on `touchend`, after the tap had missed). All of it went — the button, the class, the focus fold, the message from ttyd.
- **The keyboard lift.** Folding the bar was all the composer's focus did, and the owner typed blind under the keys.
- **The meta line.** The leftover negative margin clipped the last ~20px of the view — the model-and-context line, half-swallowed at every width and worst on a wide screen.
