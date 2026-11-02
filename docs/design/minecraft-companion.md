# The Minecraft companion: every line, many jobs, the whole world

Owner's words (November 2026), the spec:

> Invoking it every time is annoying. We only use chat for talking to it, so
> really every conversation should be interpreted as something to it. It
> really needs a good way to communicate through and track long and
> multiple requests: it can take a long time to do something but more and
> more requests keep coming in. They need to be triaged and understood if a
> new instance needs to be started or if it needs to be queued. It's also
> really unclear how kids interact with it since they don't type: there
> really needs to be an item you can point at something and it comes up with
> ideas. It needs to be omniscient in the server, understanding the entire
> build, what stuff is where, and if I say build a couch in this room, it
> can infer everything it needs to.

Decisions the owner made: only family plays on the server; a data pack (not
a plugin) for pointing; up to 5 jobs at once; children may build anything,
with no build rules (house control stays grown-ups' and the "Can ask for
anything" toggle's); the spyglass is for everyone, not only children.

The persona name is always ⚙ › Personality's (`rules.persona_name`). No
persona name ships in either add-on.

## The shape

```
 chat line ─┐                         ┌─ quick run (one per line, fast model, the player's session)
 spyglass  ─┼─► BRUH Minecraft event ─► brAIn faculty: the desk ─┤     replies now, and may open / amend / cancel a job
 pad answer ┘                         └─ jobs (≤ workers, default 5) ─ worker run (build model, long timeout,
                                                                         its own session, an inbox, progress)
 the atlas (BRUH Minecraft, background) ── read by both runs through minecraft_world atlas / room
```

### 1. Every line is for the companion (brAIn)

- Setting `every_line` in ⚙ › Minecraft, default **on**. On: every chat
  line from a person on the family list is for the companion; a leading
  name ("Vesper, …", "hey brain …") is still accepted and stripped. Off:
  today's wake-word rule (`rules.addressed`).
- Guests (not on the list) are not answered unless they name it.
- The quick run may answer with an empty `reply` for chatter that needs
  none ("lol", "brb", players talking to each other); nothing is said.
- No line is ever dropped. A line that arrives while that player's quick
  run is in flight waits and is handed to the next quick run with it
  (lines are coalesced, oldest first). `busy` and `spacing` canned lines
  are deleted.

### 2. The desk: quick runs and jobs (brAIn)

**Quick run** — one per (coalesced) line, per player serial, players in
parallel. Fast model (`chat_*`), timeout 60 s, game tools, and the
player's **session**: the CLI session id is kept per player and resumed
while the last line was under 20 minutes ago (the listener resumes on the
game channel without becoming a chat; a lost session starts fresh).
Schema adds to `reply`/`learned`:

```
job:    {title, brief, where?}         open a new job (where: room id, place or box)
amend:  {job, message}                 hand words to a queued/running job
cancel: {job}                          stop a job and undo what it changed
```

Context of every quick run: who is online (position, facing, the room and
building they are in from the atlas), the speaker's last spyglass point if
under 2 minutes old, **the job list** (id, who, title, status, queue
position, last progress), recent feed, per-person memory.

**Jobs** — `/config/.brain/minecraft/jobs.json`, the faculty its one
writer. `{id, person, player, title, brief, where, status
(queued|running|done|failed|cancelled), created, started, ended,
progress, inbox[], session, edits[], result}`; the newest 50 kept.

- Start now when fewer than `workers` jobs run (⚙, 1–5, default 5) and its
  `where` does not overlap a running job's; otherwise queue (FIFO) and say
  so with the position ("Next after the road").
- **Worker run**: build model (`build_*`), timeout 15 minutes, the game
  scope of the requester, a prompt that carries the job, the atlas
  context and the job id. It reports through `minecraft_job` (below), and
  checks its inbox between steps.
- Amend: a queued job's brief grows; a running job gets an inbox message.
- Cancel: the job's inbox says stop; when the run ends (or at once when
  queued) every edit recorded for the job is undone, newest first.
- On end: the requester hears one line (done / what went wrong) and the
  job is in brAIn's Feed with its undo.
- Progress: the requester's action bar (`companion_progress`).
- A restart of Home Assistant fails running jobs ("interrupted") and keeps
  queued ones.

**MCP tool `minecraft_job`** (game scopes only, never voice):
`progress {job, text, percent?}`, `inbox {job}` (new messages, marked
read), `list` (the job list). It calls the faculty's service
`brain.minecraft_job` (return_response), so the faculty stays the one
writer. `minecraft_world edit` gains an optional `job` that is recorded on
the edit so cancel can undo it.

### 3. Who may do what (brAIn)

- Every family member, child or grown-up, verified, gets the **game
  scope** (`minecraft`): the game tools, including `edit` (undoable) and
  shapes. `edit` is no longer refused on that channel. Voice still may not
  edit.
- `minecraft_trusted` is unchanged: a grown-up with "Can ask for anything"
  gets house tools on top.
- Children: no build rules. Kept: bedtime, the privacy rule (a reply naming
  another child), and no house control ever. The `minecraft_talk`
  (no tools) path is removed.
- An unverified name still runs nothing.

### 4. The atlas (BRUH Minecraft)

`panel/atlas.py`, a background indexer over the region files (`mcmap`):

- **Chunk summaries**, cached in `.bruh-world/atlas/`: per chunk, the
  region header timestamp it was read at, the surface height per column,
  counts of "placed" blocks (not natural terrain), and block entities with
  position (signs with their text, chests, beds, banners). Only chunks
  whose timestamp changed are re-read. Work is bounded per pass so the
  panel never stalls.
- **Buildings**: connected clusters of placed blocks (planks, bricks,
  glass, doors, wool, concrete, …), each with a box, a name (sign, zone,
  learned label or "the build by spawn") and its rooms.
- **Rooms**: enclosed air volumes inside a building (flood fill bounded by
  solid blocks, capped), each with floor y, floor area and the free floor
  cells, doors, windows, light, the furniture-like blocks in it (beds,
  chests, tables made of slabs/stairs, carpets), the wall/floor/ceiling
  palette, and a guessed kind (bedroom: bed; kitchen: furnace/smoker;
  storage: chests) unless labelled.
- **Roads/paths**: runs of path, gravel, cobble or slab strips between
  buildings.
- **Labels**: `label_place {target, name, by}` stores a name for a room,
  building or point ("this is Ben's room"); signs label what they are in.
- The world layout of every server version is read: vanilla/Paper before
  26.1 (`world/region`, `DIM-1`, `world_nether`) and 26.1+
  (`world/dimensions/minecraft/<dim>/region`). LZ4 chunks are read.

Services (bruh_minecraft, return_response):

- `atlas {player? | x,z,dimension?, radius?, query?}` → the buildings and
  roads near, `here` (building/room the player or point is in), and a
  text search over labels.
- `room {player? | room? | x,y,z}` → one room in full (as above).
- `label_place {room? | building? | x,y,z, name, by}`.
- `companion_edit` gains `shapes` (below) and `job`.
- `companion_progress {to, text, percent?}` → the action bar.
- `ask_choice` takes 2–3 options, each with an optional `item` (an icon
  shown on the pad).
- `give_spyglass {player, name}` → gives one named spyglass unless the
  player already holds one.

World snapshot (`get_world`): each online player gains `yaw`, `pitch`,
and `room` / `building` (atlas ids and names).

### 5. Shapes (BRUH Minecraft)

`companion_edit.shapes`: a list of
`{kind, block, …}` expanded to cells server-side before the undo snapshot:

- `line {from, to, radius, radius_end?}` — a tapering trunk or branch;
- `ellipsoid {center, radii, hollow?}`;
- `blob {center, radius, density 0–1, seed}` — foliage, rock, bushes;
- `cylinder {base, height, radius, radius_top?, hollow?}`;
- `box {from, to, hollow?}`.

Cells are written as `fill` runs along x, not one `setblock` each. One edit
may be up to 131,072 cells; larger jobs call `edit` more than once.
Undo is the same as any edit.

### 6. The spyglass (both)

- BRUH Minecraft installs a small data pack (`bruh_companion`) into the
  world's `datapacks/`: a `minecraft.used:minecraft.spyglass` objective
  and a tick function that tags a player who used one. The panel polls the
  tag over RCON about once a second (one command while nobody is
  pointing), reads that player's eye position and rotation, saves, and
  ray-casts through the region data to the first solid block (≤ 96
  blocks), then clears the tag. Works for Bedrock players through Geyser.
- Event `bruh_minecraft_point {player, name, verified, dimension, target:
  {x, y, z, block} | null, room?, building?}`.
- brAIn: a point becomes the speaker's "this/that" for 2 minutes. If no
  line comes within 8 s, the companion looks and offers 2–3 ideas: a
  short line in chat and choice pads with item icons; a pad answer (or
  "1/2/3" typed) opens that idea as a job. Every family member gets the
  spyglass named "<persona>'s Spyglass" when they join (setting
  `spyglass`, default on).
