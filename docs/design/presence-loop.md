# The presence loop

The owner asked for the assistant they named (through ⚙ › Personality) to
*"develop itself and build relationships with the people in the house …
not over the top, but … the Jarvis or AI agent that feels present rather
than just being something running in the background."* This is what
shipped for that, and the rules it is held to. Code: `brain/panel/presence.py`
(the arithmetic and the store) and `server._presence_*` (the bus, the
nightly run, delivery). Tests: `tests/test_presence.py`,
`tests/test_presence_server.py`; the panel: `measure-settings`.

## What the household sees

- **It grows.** Once a night (03:00–06:00 house time, once a local day) one
  run (`presence` job: Sonnet, medium effort, may step down on a lighter
  plan and never steps up, through the run queue and the same three gates
  every scheduled run answers to) reads how the household answered its
  touches and messages, **what they said to it in Ask and what it answered**
  (the newest exchanges of the last three days, each side cut short, 7 KB in
  all), what they answered when asked how it should be, coming occasions
  from calendars they chose to share, and its persona, its paragraph and its
  recent growth. It was Haiku at low effort over conversation titles, and a
  personality reflected on that way did not change.
- **The paragraph.** The run hands back the WHOLE of *"how I have learned to
  be in this house"*, revised, or nothing: one paragraph in the first person,
  1,200 characters at most, kept in the personality file as `learned`
  (`{text, updated_at, by, history}`). It is the current state; the growth
  notes are the dated trail. Chat, the terminal, voice and
  `/config/CLAUDE.md` carry it whole (`personality.prompt_block`). A revision
  is refused whole, and the stored paragraph stands, when any sentence of it
  touches a sensitive attribute, judges a person, carries an entity id,
  names a voice, names the assistant instead of speaking as it, or says
  where a named person of the house was (`presence.learned_refusal`, the
  same `refusal_of` the notes answer to, sentence by sentence); the reason is
  logged and shown under the paragraph as the night's result. A revision
  that says what the current one says is not a new version
  (`same_paragraph`). The ten versions before the current one are kept, so
  ⚙ has **Undo** (one press back), **Edit** (the household's own correction,
  saved as theirs: `by: "household"`) and **Clear**. The name and the persona
  the household wrote are never rewritten by the assistant.
- **Growth notes.** The same run may write at most two short notes about
  what changed — into the personality's growth log, marked as its own
  (`by: "self"`), four a week at most, never one it has said before, never
  one that changes its voice.
- **It sounds like itself when it speaks unprompted.** The morning brief,
  the weekly report, the Resident's report on something it looked into and
  the wording of a notification that can wait are each handed
  `personality.voice_block()`: the name, the first 1,500 characters of the
  persona, the paragraph, and one fixed rule — tone and word choice only;
  every fact, number, name and recommendation stays what the data supports;
  no invented warmth about a problem; short stays short; safety is plain
  and first. An investigation on the safety lane gets no voice block at all
  (`server._voiced(plain=…)`), an escalating notification never reaches the
  wording run, and the rule-written house checks stay plain. No run was
  added for this.
- **It keeps in touch.** The same run proposes a few **touches** for
  tomorrow, each for one person, each with a one-sentence reason: a *welcome
  home*, a *morning* or *evening check-in*, a *follow-up* on something they
  asked about, or an *occasion*. They queue (two per person, 36 hours at
  most) and go when their window opens — or, for a welcome home, a few
  minutes after that person's `person.*` entity turns `home` after two hours
  or more away, seen on the event bus once per arrival.
- **Where a touch goes.** To the household's notify target only when that
  target is *that person's own* companion app (its device tracker is one of
  theirs) — a greeting for one person is never pushed to somebody else's
  phone; otherwise, aloud on a voice satellite in the freshest occupied room
  only while **Speak first** is on (the household's existing yes to brAIn
  speaking in a room), never a protected satellite, and never a follow-up.
  No channel, no touch. Words go through `personality.speak` with the
  assistant's name as the title.
- **It asks.** ⚙ › Personality › **Shape *name*** is the assistant leading
  (the owner: *"brain can ask questions to tune and get feedback … It should
  lead those conversations"*). Three parts, all in its own words:
  - **One question at a time**, with why it is asking, two to four answers
    to press when the question has natural ones, a box to say it your way,
    **Skip** and **Don't ask this**. The nightly run writes them (`questions`
    in its schema: three a night at most, six waiting at most, two weeks to
    live, each grounded in something it was shown, best as a contrast
    between two ways it could have said something it really said). They are
    read as strictly as everything else it writes (`parse_questions`:
    `refusal_of`, no name of anybody in the house, nothing like a question
    already answered, skipped, retired or waiting). A house that has
    answered nothing gets a shipped starter set of seven (`STARTERS`), in
    order, only while the run has none of its own waiting. Never a list:
    answering shows a one-line acknowledgement and the next.
  - **Things it said lately** (`said_lately`): the last week's touches, the
    opening sentence of the morning brief and the weekly report, and each
    notification whose words the dispatcher wrote (a message the fixed
    composer assembled has no voice to judge), three at a time, newest
    first, each with **More like this**, **Less like this** and **Say it
    differently**; a line with a verdict is never offered again.
  - **Talk it through**: one press opens an Ask conversation (`POST
    /api/ask`, the saved face) whose prompt tells it to lead — one question
    at a time, two contrasting ways of saying a real thing, say back what it
    will change — and to record each thing it learned with `brain tune
    "<asked>" "<answered>"` (`POST /api/presence/tuning`). No MCP tool.
  Every answer from all three lands in `tuning.answers` (sixty kept), is
  listed under **What you have told *name*** with Remove, and is in the next
  reflection's prompt, where it outranks what the run infers. **Take this in
  now** (shown while an answer is newer than `tuning.absorbed_at`) makes the
  same run on a press — same job, same queue, the same three gates, the
  same refusals — and takes only the paragraph from it; when no run can be
  made it says why and nothing changes. ⚙'s list row for Personality says
  "*name* has 2 questions for you"; there is no phone push and no new kind
  of notification.
- **⚙ › Personality › How *name* is growing**: the paragraph first, with
  when it last changed and whose words it is (Undo, Edit, Clear), then its
  own growth notes
  (Remove), the touches it has in mind per person (Skip, Never — that kind
  for that person), what each person likes from it (Remove), kinds a person
  asked for less of (Restore), and the last eight touches with when, who,
  what kind, what happened and why (Less like this).

## The budget (code, not prompt)

| Rule | Number |
| --- | --- |
| Touches per person per local day | 1 |
| Touches per person per 7 days | 3 |
| Touches in the whole house per day | 3, at least 90 minutes apart |
| Hours | 08:00–21:00 local, and never inside the quiet hours |
| Away | never to a person who is not `home` |
| After arriving | nothing for 20 minutes except the welcome home itself |
| An arrival worth a word | away 2 hours or more; a tracker flapping within 30 minutes is the same arrival |

Small on purpose: one a day is the most a good housemate would say
unprompted, and three a week leaves most days quiet. A touch the budget
refuses waits for its window or expires; it is never squeezed in.

## How it learns

Phone touches carry three buttons — **Thanks**, **Not now**, **Less like
this** — under their own action prefix (`brain_presence.<verb>.<id>`), which
neither the findings' request reader nor the Resident's reply reader takes.
The delivery ledger (kind `presence`) supplies the rest: a swipe is
*cleared*, a day with no answer is *ignored*.

- **Not now** stops touches to that person for the rest of the day, at once.
- **Less like this** retires that kind for that person, at once; Restore in
  ⚙ brings it back.
- A kind's score (thanks +1, swipe or not now −1, ignored −½) reaching −2
  retires it by itself — two swipes, or four days of silence.
- Three unwanted touches in a row pause that person for a week.
- The next night's run is shown all of it per person, and told never to
  propose a retired kind (and code refuses one if it does).

## Relationships, not surveillance

- It reads only what brAIn already has and the household gave it: person
  names, the household's own exchanges with brAIn in Ask, how they answered
  its messages, what they answered about how it should be, opted-in
  calendars. No locations, no sensors about a person.
- **It reads what was said to it in Ask.** This is new, so plainly: the
  nightly run is handed the household's own recent messages to brAIn and
  brAIn's replies — only conversations a person started (the chat and the
  terminal), never a run brAIn made by itself and never the tool traffic —
  read from the transcripts on this machine, clipped (280 characters of
  what was said, 360 of the answer, fourteen exchanges, 7 KB) and sent to
  the same Claude sign-in the conversation itself used. Nothing about it
  goes to the development loop or anywhere else, and nothing of it is
  stored: what is kept is the paragraph, which code reads sentence by
  sentence before it is written. Switching off the **Learning loop** (or
  Personality) in ⚙ › Features stops the run, and so the reading.
- The paragraph is held to the notes' rules and one more: no sentence that
  names somebody of the house and says where they were, went or are.
- The run's answer is read strictly (`parse_reflection`): anything off the
  schema, about somebody not in the house, over length, with an entity id,
  about a sensitive attribute (health, body, sleep, mood, beliefs, politics,
  sexuality or gender, ethnicity or status, money, relationships, death) or
  judging a person is refused, not softened. Notes are what a person *likes*
  from brAIn — three per person, 120 characters, removable.
- Nothing is written to the Resident's verdict log, the scorecard or the
  facts store (`outcomes._is_person_scope`'s rule); the module imports none
  of them.

## Turning it off

⚙ › Features: switch off **Personality** or the **Learning loop**. Either
one off and nothing runs — the bus hook returns before it reads anything,
the nightly pass asks nothing, nothing is sent. What is stored
(`/data/presence.json`, and the growth notes and the paragraph in the
personality) is kept and shown, and every piece of it can be removed in
⚙ › Personality. The paragraph already written is still carried by Ask and
voice while Personality is on; Clear empties it.
