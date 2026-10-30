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
  cheap run (`presence` job: Haiku, low effort, never stepped up, through
  the run queue and the same three gates every scheduled run answers to)
  reads how the household answered its touches and messages, what they asked
  it about lately (conversation titles only), coming occasions from calendars
  they chose to share, and its persona and recent growth. It may write at most
  two short **growth notes** about how it should be — into the personality's
  growth log, marked as its own (`by: "self"`), four a week at most, never
  one it has said before, never one that changes its voice, and never a
  change to the name or persona the household wrote.
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
- **⚙ › Personality › How *name* is growing**: its own growth notes
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
  names, the titles of conversations they had with it, how they answered its
  messages, opted-in calendars. No transcripts, no locations, no sensors
  about a person.
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
(`/data/presence.json`, and the growth notes in the personality) is kept and
shown, and every piece of it can be removed in ⚙ › Personality.
