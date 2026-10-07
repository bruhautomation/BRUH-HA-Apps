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

Once an hour, brAIn reads its own fault list. That is the same list that opens
every problem report and the top of ⚙ › Diagnostics: a background service that
stopped, a run that keeps failing, a house check you keep marking wrong. For
each fault it:

1. **Files one issue**, and keeps using that issue for as long as the fault
   exists. "3 of 12 runs failed" and "4 of 13 runs failed" are the same fault,
   and the number changes in the issue rather than creating a new one.
2. **Waits for you first.** With *Ask before sending each new report* on (the
   default), a new report sits in ⚙ until you press **Send** or **Delete**.
   **View** shows exactly the text that would be sent. **Delete** means that
   fault is never reported.
3. **After that, only says when.** Once an issue exists, brAIn adds short
   comments that contain only dates and version numbers, and these are posted
   without asking:
   - *Not seen since …*: the fault stopped happening.
   - *Back again on brAIn x.y.z*: the fault returned. brAIn reopens the issue
     if you had closed it.
   - *Still happening on brAIn x.y.z*: an update came out and did not fix it.

   These comments are what tell you whether a fix actually worked on your
   house.

## What it can report

What the loop reports is split into **streams**, each with its own switch
under the main one, because each kind of evidence has its own privacy cost and
its own cost in Claude usage:

- **Faults** (available now): the fault list described above. It costs
  nothing to run.
- **Planned:** a UI/UX audit that uses the panel the way you do, aliased
  screenshots, gaps in the code, and ideas for new features.

The switch for a planned stream appears in ⚙ when that stream ships. Until
then nothing in brAIn does that work.

## What leaves your house, and what never does

**Sent**, inside the issue:

- the fault's description;
- brAIn's version and health verdict;
- an abridged diagnostics summary: versions, run counts by outcome, the last
  checks pass, and which background services are up.

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
- screenshots (this version takes none).

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

## Going further

Your reports repository is the input to a larger loop. A
[Claude Code routine](https://code.claude.com/docs/en/claude-code-on-the-web)
can be pointed at new issues there, reproduce each one as a failing test in a
fork of this repository, fix it and open a pull request. The *Still happening*
and *Not seen since* comments then tell you whether the release that followed
actually fixed it on your house. Setting that up is up to you and lives outside
the add-on.
