# Help develop brAIn (the development loop)

brAIn includes an optional feature that turns the problems it finds on your
install into GitHub issues in a **private repository you own**. It exists to
speed up brAIn's development: the bugs that matter most are the ones that only
show up on real houses, and this is a way to collect them without anybody
having to notice, write up and paste a report.

**It is off by default, and nobody is expected to turn it on.** Nothing in this
feature runs, connects anywhere or sends anything until you switch it on. If you
never do, brAIn behaves exactly as if it were not there.

## What it does

brAIn looks at itself on a schedule you set and files what it finds as
issues. Each kind of evidence is a **stream** with its own switch, its own
schedule and its own **Run** button:

| Stream | What it files | On by default | Costs |
|---|---|---|---|
| **Faults** | The fault list from ⚙ › Diagnostics: a service that stopped, a run that keeps failing | yes, hourly | nothing |
| **Scorecard** | How right each house check was on this release. One issue per release, rewritten in place | yes, daily | nothing |
| **Wrongs** | A check you have marked Wrong at least 3 times and at least half the time, with the reasons you typed | yes, daily | nothing |
| **Unmet requests** | Things brAIn told you in the chat it could not do, once the same one has come up in two or more conversations | no | nothing |
| **House shape** | Counts only: how many lights, rooms and so on, and which features are on. Lets a UI audit match a real house | no | nothing |
| **Gaps** | Where brAIn falls short on this house, found by a read-only Claude run | no | one run |
| **Ideas** | Features this house would use, from a read-only Claude run | no | one run |

**What do you want to fix?** is the eighth: say it the way you would to a
person ("the settings page is too crowded", "the brief never mentions the
boiler") and press **Send**. One read-only Claude run works out what is
really wrong behind it, and files **one** issue (two if you named two
separate problems) with your words quoted, the real problem, and what
"fixed" looks like. An issue about a screen is labelled `devloop:ux`, which
tells the cloud half to drive and screenshot that pane before and after the
fix: the house never takes screenshots.

Two daily caps keep it in proportion. Both refuse rather than queue up:

- **Issues a day** (default 10): past it, new reports wait for tomorrow.
- **Claude runs a day** (default 4): covers Gaps, Ideas and *What do you
  want to fix?*.
  Scheduled runs also stop when automatic insights are paused or the usage
  budget is spent. A **Run** press skips the budget but still counts
  against this cap.

For each finding brAIn:

1. **Files one issue**, and keeps using that issue for as long as the finding
   exists. "3 of 12 runs failed" and "4 of 13 runs failed" are the same fault,
   and the number changes in the issue rather than creating a new one.
2. **Waits for you first.** With *Ask before sending each new report* on (the
   default), a new report sits in ⚙ until you press **Send** or **Delete**.
   **View** shows exactly the text that would be sent. **Delete** means that
   finding is never reported.
3. **After that, only says when.** For faults and wrongs, brAIn adds short
   comments that contain only dates and version numbers, and these are posted
   without asking:
   - *Not seen since …*: it stopped happening.
   - *Back again on brAIn x.y.z*: it returned. brAIn reopens the issue if it
     had been closed.
   - *Still happening on brAIn x.y.z*: an update came out and did not fix it.

   These comments are what tell anyone whether a fix actually worked on your
   house. A stream you switch off never claims anything stopped: it was not
   looking.
4. **Says how much it matters.** Every new issue opens with a short
   **Impact** section: how often it was seen and over how many days, how
   many rows or runs it touched where brAIn knows, and what you did about it
   (marked Wrong, confirmed). When the day's cap holds reports back, the most
   impactful are sent first.
5. **Listens to the answer.** Whoever works through your reports closes each
   issue with a label: fixed, declined, not brAIn's, or a duplicate. Once an
   hour brAIn reads those back, using the same issue listing it already
   reads, and shows the tally beside each stream. A Gaps, Ideas, *What do you want to fix?* or
   Unmet report closed as declined, not brAIn's or a duplicate is never filed
   again, even reworded. If 6 of a stream's last 8 closed reports were noise
   like that, the stream runs half as often (but at least once a
   fortnight), and ⚙ says so with an **Undo**. A fix
   is never counted as noise, and a fixed fault that comes back is still
   reported as *Back again*.

The same controls are in the terminal as `brain devloop status`,
`brain devloop run [stream]` and `brain devloop look "<what to fix>"`.

## What leaves your house, and what never does

**Sent**, inside the issue:

- the finding's description;
- for **Unmet requests**, the sentence brAIn answered with when it could
  not do something, and how many times and in how many conversations it
  said it. What you typed is not sent;
- for **Gaps** and **Ideas**, what the Claude run wrote; for *What do you
  want to fix?*, your words and what the run wrote;
- brAIn's version and health verdict;
- an abridged diagnostics summary: versions, run counts by outcome, the last
  checks pass, and which background services are up;
- the Impact section's counts.

**Replaced with aliases before sending:** every entity id, friendly name and
room name. `light.bedroom_lamp` becomes `light.light_07`, *Master Bedroom*
becomes *Room 3*, and so on.

- The numbering is stable, so two issues about the same light can be matched
  up.
- The map from aliases back to real names stays in `/data/devloop/aliases.json`
  on your box. It is never sent.
- File names (`server.py`) and service names (`light.turn_on`) are left as
  they are, because they say nothing about your home and a developer needs
  them.

**Never sent:**

- credentials of any kind: Claude, Home Assistant or GitHub tokens, and
  anything else credential-shaped;
- `secrets.yaml`;
- camera images;
- where people are;
- your memory document as a whole;
- screenshots. The house takes none. The cloud UX audit described below
  screenshots brAIn's test fixtures, never your panel.

Even with aliases, a fault list describes the *shape* of a home. That is why
reports only go to a **private** repository, and brAIn refuses to send to a
public one.

## Turning it on

1. Create a **private** repository on GitHub, for example
   `you/brain-house-reports`.
2. Create a **fine-grained personal access token**: GitHub → Settings →
   Developer settings → Fine-grained tokens.
   - **Repository access:** *Only select repositories*, then just that one.
   - **Repository permissions:** **Issues: Read and write**. *Metadata:
     Read-only* is added automatically. Add nothing else.
   - **Expiration:** your choice. When the token lapses, brAIn shows the
     error in ⚙ and stops sending until you paste a new one.
3. In brAIn, open ⚙ › Diagnostics › **Developer** › **Help develop brAIn**.
   Switch it on, enter `owner/repo` and the token, and press **Save**, then
   **Recheck**.

Where the token is kept:

- It goes in `/data/secrets`, which Home Assistant backups leave out.
- The panel never shows it again; it only says that one is saved.
- It can do nothing but read and write issues in that one repository. In
  particular it cannot change any code.

## Sharing a report with the brAIn project

Your reports stay in your repository. If one looks like a brAIn bug and you are
happy to share it, open an issue on
[bruhautomation/BRUH-HA-Apps](https://github.com/bruhautomation/BRUH-HA-Apps/issues)
and paste the parts you are comfortable with. You are never expected to share
anything; this feature is only here to make that easier if you want to.

## Going further: brAIn fixing itself

Your reports repository can be the input to a loop that needs nobody in it.
This repository ships the cloud half:

- `.claude/skills/fix-from-house/SKILL.md`: instructions for a scheduled
  [Claude Code routine](https://code.claude.com/docs/en/claude-code-on-the-web).
  Each run works until every open issue is closed: it reproduces each one as
  a failing test, fixes them in a few pull requests grouped by area, and
  merges each when CI is green. An issue it should not fix is closed with
  the reason. It also watches the house's *Back again* comments and reverts
  a fix that did not hold.
- `.claude/devloop.json`: names the reports repository, and the files an
  automated pull request may never touch (the action gate, protected
  entities, credentials, permissions, the MCP server, and the loop itself).
- `devloop-guard`: a CI check that fails any `devloop/` pull request that
  touches one of those files, loosens its own list, changes more than the
  version in `config.yaml`, or skips or deletes a test. A refused pull
  request is labelled `needs-human` and left for a person.

With the add-on's **Auto update** on in Home Assistant, a merged fix reaches
the house that reported it. The house's next *Not seen since* or *Back
again* says whether it worked. Running that loop against the public
repository means every fix ships to everybody who installed brAIn, so it is
for whoever maintains that repository. Anyone else should point it at a
fork.
