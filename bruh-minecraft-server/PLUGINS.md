# Plugin command reference

A practical, copy-pasteable reference for every plugin shipped by the
**BRUH Minecraft Server** add-on. Each section opens with what the
plugin actually does, then lists the commands you'll reach for daily,
plus a few "killer combo" recipes that show the plugin at its best.

> **Tip:** an interactive version of this page — searchable, with
> per-command parameter inputs and one-click copy — is hosted at
> [bruhautomation.com/bruh-minecraft/commands](https://bruhautomation.com/bruh-minecraft/commands).
> The same data, in a friendlier interface.

**Conventions:**

- Commands are written with a leading `/` (the way you type them
  in-game). From the **server console** drop the slash.
- `<required>` parameters are mandatory; `[optional]` ones are not.
- `@p` = nearest player, `@a` = all players, `@s` = the executor, in
  vanilla target-selector syntax.
- Many commands need OP. Make yourself OP from the panel's **Players**
  tab (or set `initial_ops:` in the add-on options) before testing.

**Table of contents**

- [EssentialsX](#essentialsx) — homes, warps, /tpa, /heal, kits, chat
- [EssentialsX Chat](#essentialsx-chat) — chat formatting + prefixes
- [LuckPerms](#luckperms) — permissions and groups
- [WorldEdit](#worldedit) — terraforming and mass edits
- [WorldGuard](#worldguard) — region protection
- [CoreProtect](#coreprotect) — block-history forensics
- [Multiverse-Core](#multiverse-core) — multiple worlds
- [GriefPrevention](#griefprevention) — golden-shovel claims
- [mcMMO](#mcmmo) — RPG-style skill leveling
- [ChestSort](#chestsort) — auto-sort containers
- [VeinMiner](#veinminer) — break a whole vein in one swing
- [spark](#spark) — performance profiler
- [Geyser-Spigot](#geyser-spigot) — Bedrock ↔ Java bridge
- [Floodgate](#floodgate) — Bedrock players without Java accounts
- [ViaVersion / ViaBackwards](#viaversion--viabackwards) — protocol bridges

---

## EssentialsX

The Swiss-army knife of Bukkit/Paper plugins: homes, warps, teleport
requests, kits, chat utilities, vanish, repair, and ~150 other
commands. If you've played on a public server, EssentialsX is what
made it feel polished.

### Teleporting

| Command | What it does |
|---|---|
| `/sethome [name]` | Save your current location as a personal home. Default name = `home`. |
| `/home [name]` | Teleport to a saved home. With no arg, goes to your default home. |
| `/delhome <name>` | Remove a saved home. |
| `/homes` | List all your homes. |
| `/spawn` | Teleport to the world's main spawn. |
| `/setspawn` | Set the spawn point at your current location. (op) |
| `/tpa <player>` | Ask `<player>` to teleport you to them. They run `/tpaccept` to confirm. |
| `/tpahere <player>` | Ask `<player>` to teleport TO you. |
| `/tpaccept` / `/tpdeny` | Respond to a teleport request. |
| `/back` | Return to your last death/teleport location. |
| `/warp <name>` | Teleport to a public warp. |
| `/setwarp <name>` | Create a public warp at your location. (op) |
| `/delwarp <name>` | Delete a warp. (op) |
| `/warps` | List all warps. |
| `/jump` | Teleport up to ~50 blocks in the direction you're looking. |
| `/tppos <x> <y> <z> [yaw] [pitch]` | Teleport to absolute coordinates. (op) |
| `/getpos` | Print your current coordinates and facing. |

### Health, gamemode, items

| Command | What it does |
|---|---|
| `/heal [player]` | Restore health, hunger, fire, poison. (op) |
| `/feed [player]` | Restore hunger only. (op) |
| `/god [player]` | Toggle invulnerability. (op) |
| `/fly [player]` | Toggle creative-style flight. (op) |
| `/gm <0\|1\|2\|3>` | Survival / Creative / Adventure / Spectator. Aliases: `/gms /gmc /gma /gmsp`. |
| `/repair <hand\|all>` | Repair held item or every item in your inventory. (op) |
| `/more` | Set the held stack to its max stack size. (op) |
| `/give <player> <item> [amount]` | Give items. (op) |
| `/skull <player>` | Get a player head item with that player's skin. |
| `/hat` | Wear whatever you're holding as a hat. |
| `/clearinventory <player> [item]` | Empty a player's inventory (or just one item). (op) |
| `/itemdb [hand]` | Show the namespaced ID of the item you're holding. |
| `/kit [name]` | Open the kit GUI, or claim a specific kit. Configure in `plugins/Essentials/kits.yml`. |
| `/spawnmob <type>[:variant][,type:variant…] [count]` | Spawn one or more mobs. (op) |
| `/lightning [player]` | Strike where you're looking, or a player. (op) |
| `/eco give\|take\|set <player> <amount>` | Adjust a player's balance. (op) |

### Chat & social

| Command | What it does |
|---|---|
| `/msg <player> <message>` | Private message. Aliases: `/m /tell /w /pm`. |
| `/r <message>` | Reply to your last DM. |
| `/mail send <player> <message>` | Persistent mail (delivered when offline). |
| `/mail read` / `/mail clear` | Read / wipe your inbox. |
| `/me <action>` | Third-person chat (`* Steve waves`). |
| `/broadcast <message>` | Server-wide announcement. (op) |
| `/nick [player] <nickname\|off>` | Set a chat nickname. (op required to nick others) |
| `/realname <nickname>` | Find the real account behind a nickname. |
| `/seen <player>` | Last login + IP + total play time. (op for IP) |
| `/list` | Currently online players. |
| `/afk [reason]` | Mark yourself AFK with an optional reason. |
| `/socialspy [player]` | See all DMs (op power; useful for moderating). (op) |
| `/vanish` | Toggle invisibility (you still appear in `/list`). (op) |
| `/ignore <player>` | Block messages from a player. |
| `/mute <player> [duration] [reason]` | Mute someone. (op) |

### Punishment & moderation

| Command | What it does |
|---|---|
| `/kick <player> [reason]` | Kick a player. (op) |
| `/ban <player> [reason]` | Permanent ban. (op) |
| `/tempban <player> <duration> [reason]` | Time-limited ban (`30m`, `2h`, `1d`, `1w`). (op) |
| `/banip <ip\|player>` | Ban by IP. (op) |
| `/unban <player>` | Lift a ban. (op) |
| `/warp <player> <duration>` *(via Essentials' jail)* | See `/jail` if installed. |

### Killer combos

```
# Hand a friend a stacked endgame loadout
/give Ben13765 netherite_pickaxe{Enchantments:[{id:efficiency,lvl:5},{id:unbreaking,lvl:3},{id:fortune,lvl:3}]} 1
/give Ben13765 elytra{Unbreakable:1b} 1
/give Ben13765 firework_rocket 64

# Set up a "tour" you can run for new players
/setwarp spawn-fountain
/setwarp shop-district
/setwarp pvp-arena
/setwarp end-portal
# Then in-game:  /warp shop-district
```

**Permissions cheat-sheet** (grant via LuckPerms):
- `essentials.fly` — `/fly`
- `essentials.heal` — `/heal`
- `essentials.repair` — `/repair`
- `essentials.tp.others` — `/tp` other players
- `essentials.kit.<name>` — claim a specific kit
- `essentials.*` — everything (typically only the `admin` group)

**Files:**
- `/config/minecraft-worlds/<world>/plugins/Essentials/config.yml` — main config
- `/config/minecraft-worlds/<world>/plugins/Essentials/kits.yml` — kits
- `/config/minecraft-worlds/<world>/plugins/Essentials/userdata/<uuid>.yml` — per-player

---

## EssentialsX Chat

Adds chat formatting (color codes), per-group prefixes/suffixes, and
hooks into LuckPerms for the `prefix` / `suffix` metadata. Few new
commands — most of the value is invisible (it makes chat look like a
real server).

### What this enables

- `&c`, `&l`, `&n`, `&o` color/format codes work in chat for users with
  `essentials.chat.color` permission.
- LuckPerms group prefixes appear automatically:
  `/lp group vip meta setprefix 100 "&6[VIP] "` → players in `vip` show
  as `&6[VIP] &fSteve` in chat.
- Per-channel chat (toggle `local-chat` in `Essentials/config.yml`):
  - `/local <message>` (alias `/l`) — only people within range hear.
  - `/global <message>` (alias `/g`) — server-wide.

### Setup recipe

```
# 1. Create groups with chat formatting
/lp creategroup vip
/lp group vip meta setprefix 100 "&6[VIP] &r"
/lp group vip meta setsuffix 100 " &7(Patron)"
/lp group vip permission set essentials.chat.color true

# 2. Put someone in the group
/lp user Ben13765 parent set vip

# 3. They can now use color codes
# In chat: "Hello &c&lEVERYONE" → "Hello EVERYONE" with red bold formatting
```

---

## LuckPerms

The de-facto permissions system for Bukkit/Paper. Replaces the old
"PermissionsEx" / "GroupManager" plugins. Users belong to **groups**;
groups have **permissions** and **metadata** (prefix, suffix, weight).

### The one command you need

```
/lp editor
```

Generates a one-time URL to a web UI where you can edit every group,
permission, prefix, and user assignment with a graphical interface.
Click "Apply" and it gives you a paste command to run back in-game.
Use this. It's so much easier than the in-game commands below.

### Groups

| Command | What it does |
|---|---|
| `/lp creategroup <name>` | Create a new group. |
| `/lp deletegroup <name>` | Delete it. |
| `/lp listgroups` | List all groups. |
| `/lp group <name> info` | Group details. |
| `/lp group <name> permission set <node> <true\|false>` | Grant/revoke a permission. |
| `/lp group <name> permission unset <node>` | Remove a permission entry entirely. |
| `/lp group <name> parent add <other-group>` | Make this group inherit another. |
| `/lp group <name> meta setprefix <weight> "<prefix>"` | Chat prefix (with formatting codes). |
| `/lp group <name> meta setsuffix <weight> "<suffix>"` | Chat suffix. |
| `/lp group <name> meta setweight <number>` | Higher weight = wins prefix conflicts. |
| `/lp group <name> rename <new-name>` | Rename. |

### Users

| Command | What it does |
|---|---|
| `/lp user <player> info` | Show a user's groups and explicit permissions. |
| `/lp user <player> parent set <group>` | Set their PRIMARY group (replaces existing primaries). |
| `/lp user <player> parent add <group>` | Add a SECONDARY group. |
| `/lp user <player> parent remove <group>` | Remove a group. |
| `/lp user <player> permission set <node> <true\|false>` | Grant/revoke a per-user permission. |
| `/lp user <player> permission unset <node>` | Remove the entry. |
| `/lp user <player> meta setprefix <weight> "<prefix>"` | Per-user prefix (overrides group). |
| `/lp user <player> clear` | Wipe a user's groups + permissions to default. |

### Debug & maintenance

| Command | What it does |
|---|---|
| `/lp tree` | Visualise the entire permission tree in chat. |
| `/lp verbose record on` | Log every permission check; turn off with `record off`. Then `verbose paste` gives a URL with the log. |
| `/lp sync` | Sync data across servers (multi-server installs only). |
| `/lp reload` | Reload the config. |

### Killer combos

```
# Bootstrap a sensible permission set on a brand-new server
/lp creategroup default
/lp creategroup vip
/lp creategroup mod
/lp creategroup admin

# Inheritance: admin > mod > vip > default
/lp group vip parent add default
/lp group mod parent add vip
/lp group admin parent add mod

# Default everyone-allowed perms
/lp group default permission set essentials.help true
/lp group default permission set essentials.spawn true
/lp group default permission set essentials.sethome true
/lp group default permission set essentials.home true
/lp group default permission set essentials.warp true

# VIPs get fly + heal + colored chat
/lp group vip permission set essentials.fly true
/lp group vip permission set essentials.heal true
/lp group vip permission set essentials.chat.color true
/lp group vip meta setprefix 50 "&6[VIP] &r"

# Mods get bans/kicks
/lp group mod permission set essentials.ban true
/lp group mod permission set essentials.kick true
/lp group mod permission set essentials.mute true
/lp group mod meta setprefix 75 "&2[MOD] &r"

# Admins get everything
/lp group admin permission set * true
/lp group admin meta setprefix 100 "&c[ADMIN] &r"

# Make yourself an admin
/lp user <yourname> parent set admin
```

**Files:**
- `/config/minecraft-worlds/<world>/plugins/LuckPerms/config.yml`
- `/config/minecraft-worlds/<world>/plugins/LuckPerms/luckperms-h2-v2.mv.db` — H2 storage by default

---

## WorldEdit

Terraforming superpowers. Select a region with the wooden axe (or
`//pos1` / `//pos2`), then run a transformation. Single best plugin
for spawn-building.

### Selection

| Command | What it does |
|---|---|
| `//wand` | Give yourself the wooden axe (left-click = pos1, right-click = pos2). |
| `//pos1` / `//pos2` | Set selection corner at your current position. |
| `//hpos1` / `//hpos2` | Set corner at the block you're looking at. |
| `//sel <type>` | Change selection shape: `cuboid` (default), `extend`, `poly`, `ellipsoid`, `sphere`, `cyl`, `convex`. |
| `//size` | Show selection dimensions and volume. |
| `//count <block>` | Count blocks of a type in selection. |
| `//distr` | Block distribution histogram. |
| `//expand <amount> [direction]` | Grow the selection. `up`, `down`, `me` (where you're looking). |
| `//contract <amount> [direction]` | Shrink it. |
| `//shift <amount> [direction]` | Slide the selection. |

### Filling and replacing

| Command | What it does |
|---|---|
| `//set <block>` | Fill selection with a block. |
| `//replace [from] <to>` | Replace blocks. With one arg, replaces all non-air. With two, only converts `<from>`. |
| `//walls <block>` | Build vertical walls around the selection (no roof, no floor). |
| `//faces <block>` | Build all six faces (walls + floor + roof). |
| `//hollow [thickness]` | Hollow out a solid selection. |
| `//overlay <block>` | Place a block on top of every grass/dirt/stone in selection (e.g. snow caps). |
| `//naturalize` | Layer dirt + grass on top of stone (makes raw terrain look natural). |
| `//paste [-a] [-o]` | Paste clipboard at your position. `-a` ignores air; `-o` pastes at original coords. |
| `//copy` | Copy selection to clipboard. |
| `//cut` | Cut to clipboard (replaces with air). |
| `//rotate <yaw> [pitch] [roll]` | Rotate clipboard. `//rotate 90` = quarter-turn around vertical. |
| `//flip [direction]` | Mirror the clipboard. |

### Shapes

| Command | What it does |
|---|---|
| `//sphere <block> <radius>` | Solid sphere centered on you. |
| `//hsphere <block> <radius>` | Hollow sphere. |
| `//cyl <block> <radius> <height>` | Solid vertical cylinder. |
| `//hcyl <block> <radius> <height>` | Hollow cylinder. |
| `//pyramid <block> <size>` | Solid pyramid. |
| `//hpyramid <block> <size>` | Hollow pyramid. |

### Terrain

| Command | What it does |
|---|---|
| `//forestgen <size> <type> <density>` | Spawn a forest patch (`//forestgen 50 birch 0.4`). |
| `//pumpkins [size]` | Pumpkin patches. |
| `//green [radius]` | Spread grass + flowers across dirt in radius. |
| `//snow [radius]` | Snow caps on terrain. |
| `//thaw [radius]` | Melt snow + ice. |
| `//ex [radius]` | Extinguish all fire within radius. |
| `//drain [radius]` | Drain water within radius. |
| `//fixwater [radius]` | Fix flowing water → still-water in radius. |
| `//fixlava [radius]` | Same for lava. |
| `//caves [size]` | Generate caves through your selection. |

### Brushes

Brushes turn your held tool into a "paint" tool — right-click to apply.

| Command | What it does |
|---|---|
| `//brush sphere <block> <radius>` | Right-click anywhere → places a sphere. |
| `//brush cyl <block> <radius> <height>` | Right-click → cylinder. |
| `//brush smooth <radius> [iterations]` | Right-click → smooths terrain. |
| `//brush erode <radius>` | Right-click → realistic erosion. |
| `//brush gravity <radius>` | Right-click → all blocks above fall to fill gaps. |
| `//mat <block>` | Change the brush's material. |
| `//size <radius>` | Change the brush's radius (yes, same name as the selection-info command — context-dependent). |
| `//gmask <mask>` | Global mask: brushes only affect matching blocks. `//gmask !#existing` = only paint air. |
| `/none` | Remove the brush from the held tool. |

### Misc

| Command | What it does |
|---|---|
| `//undo [count]` | Undo your last operation (or N operations). |
| `//redo [count]` | Redo. |
| `//unstuck` | Move out of a block (rescue command if you WorldEdit yourself into a wall). |
| `//thru` | Pass through walls (like `/jump`'s ranged blink). |
| `//ascend [count]` | Teleport up to the next platform. |
| `//descend [count]` | Teleport down to the next platform. |
| `//schem save <name>` | Save selection to a `.schem` file. |
| `//schem load <name>` | Load a `.schem` into your clipboard. |
| `//schem list` | List schematics. |
| `//regen` | Regenerate selection from world seed (resets terrain). |

### Killer combos

```
# Lava castle in 30 seconds
//pos1                                         # mark a corner
# walk 30 blocks  //pos2
//walls obsidian                               # outer walls
//set 0,1                                      # fill inside with air + glowstone (ratio 0:1)
//gmask !#existing
//replace 0 lava                               # turn the air into lava using a mask

# Hollow out a solid sphere into a dome
# Reselect the bounding box of the sphere first
//hollow

# Nuke griefing — restore a 200×200 patch from world seed
//pos1                                         # corner of the messed-up area
//pos2                                         # opposite corner
//regen

# Save a build, copy it elsewhere
//pos1 / //pos2                                # select the build
//copy
//schem save my-castle
# later, in another world:
//schem load my-castle
//paste
```

**Permissions to grant via LuckPerms:**
- `worldedit.*` — everything (admin only)
- `worldedit.selection.*` + `worldedit.region.set` — basic builders
- `worldedit.brush.*` — brush commands

---

## WorldGuard

Region-based protection. Select an area, name it, set rules. Used to
lock down spawn, mark PvP arenas, prevent creeper holes, and so on.

### Defining regions

| Command | What it does |
|---|---|
| `//wand` | WorldEdit selection wand (WorldGuard regions are made from WE selections). |
| `/rg define <name>` | Create a region from your current WE selection. |
| `/rg redefine <name>` | Update an existing region's bounds. |
| `/rg remove <name>` | Delete a region. |
| `/rg info <name>` | Show region details. |
| `/rg list` | List regions in the current world. |
| `/rg select <name>` | Re-select a region's bounds in WorldEdit. |
| `/rg setpriority <name> <number>` | Higher priority overrides lower for overlapping regions. |
| `/rg setparent <name> <parent>` | Inherit flags from a parent region. |

### Membership

Members can build inside a region; owners can edit the region's settings.

| Command | What it does |
|---|---|
| `/rg addmember <region> <player>` | Add a member. Use `-g <group>` for whole groups. |
| `/rg removemember <region> <player>` | Remove. |
| `/rg addowner <region> <player>` | Add an owner (more powerful than member). |
| `/rg removeowner <region> <player>` | Remove an owner. |

### Flags (the actually-useful part)

```
/rg flag <region> <flag> <value>
```

Common flags:

| Flag | Values | Effect |
|---|---|---|
| `pvp` | `allow` / `deny` | PvP inside the region. |
| `mob-spawning` | `allow` / `deny` | Hostile mob spawns. |
| `creeper-explosion` | `allow` / `deny` | Creeper damage to terrain. |
| `tnt` | `allow` / `deny` | TNT explosions. |
| `enderman-grief` | `allow` / `deny` | Enderman block-stealing. |
| `entry` | `allow` / `deny` | Whether non-members can enter. |
| `exit` | `allow` / `deny` | Whether members can leave. |
| `build` | `allow` / `deny` | Block placing/breaking. |
| `chest-access` | `allow` / `deny` | Open containers. |
| `interact` | `allow` / `deny` | Right-click anything (buttons, doors, etc.). |
| `keep-inventory` | `allow` / `deny` | Drop items on death? |
| `game-mode` | `survival` / `creative` / `adventure` / `spectator` | Auto-switch on entry. |
| `fly` | `allow` / `deny` | Allow flight. |
| `greeting` | `<message>` | Title shown when entering. |
| `farewell` | `<message>` | Title shown when leaving. |
| `time-lock` | `<ticks>` | Freeze time inside the region. |
| `weather-lock` | `clear` / `rain` / `thunder` | Freeze weather. |

### The "global" region

Every world has an invisible `__global__` region that covers everything.
Set flags here to apply server-wide:

```
/rg flag __global__ creeper-explosion deny       # globally disable creeper holes
/rg flag __global__ enderman-grief deny          # endermen can't pick up blocks
/rg flag __global__ tnt deny                     # no random TNT chaos
```

### Killer combos

```
# Lock down spawn
//wand                                          # select the spawn area with WE
/rg define spawn
/rg flag spawn pvp deny
/rg flag spawn mob-spawning deny
/rg flag spawn build deny -g default            # default group can't build
/rg flag spawn build allow -g admin             # admins still can
/rg flag spawn keep-inventory allow             # spawn = no death penalty
/rg flag spawn greeting "&aWelcome to spawn!"
/rg flag spawn farewell "&7See you later"

# PvP arena
//pos1 / //pos2 (select the arena cube)
/rg define pvp-arena
/rg flag pvp-arena pvp allow
/rg flag pvp-arena keep-inventory allow         # players don't lose gear on death
/rg flag pvp-arena game-mode survival
/rg flag pvp-arena entry allow

# VIP-only build zone
/rg define vip-plot
/rg flag vip-plot build deny
/rg addmember vip-plot -g vip                   # only the vip group can build
```

**Permissions:**
- `worldguard.region.*` — manage regions
- `worldguard.flag.*` — set flags
- Members/owners are scoped per-region; no global perm needed.

---

## CoreProtect

Logs every block change, container transaction, and player action. The
single most important plugin if you ever get griefed — you can rewind
time on any area.

### Inspector mode

```
/co i
```

Toggles inspector mode. While on:
- **Left-click a block** → see who placed/broke it and when.
- **Right-click a chest** → see who took or deposited what.
- **Left-click air** → check who placed the block in front of you.

Run `/co i` again to turn it off.

### Lookup syntax

```
/co lookup u:<user> t:<time> r:<radius> b:<block> a:<action> w:<world> e:<exclude>
```

All parameters are optional; combine as needed.

| Param | Example | Meaning |
|---|---|---|
| `u:` | `u:Steve`, `u:#none`, `u:Steve,Ben` | Filter by user. `#none` = no filter, prefix `!` to exclude. |
| `t:` | `t:1d`, `t:6h`, `t:30m`, `t:7w` | Time window: y/M/w/d/h/m/s. |
| `r:` | `r:50`, `r:#world` | Radius around your position, or `#world` for whole world. |
| `b:` | `b:diamond_ore`, `b:#wood` | Block filter. `#tag` for material tags. |
| `a:` | `a:block`, `a:click`, `a:container`, `a:kill`, `a:chat`, `a:command`, `a:session`, `a:-block` | Action filter. Prefix `-` to exclude. |
| `w:` | `w:world_nether` | World filter. |

### Common queries

```
/co lookup u:GrieferDude t:1d                   # everything they did in 24h
/co lookup b:diamond_ore t:7d r:#world          # global diamond mining for the week
/co lookup a:container t:3h r:30                # who opened any chest near me in last 3h
/co lookup a:chat u:Steve t:1h                  # what did Steve say in chat recently
/co lookup a:command t:1d                       # all command usage in 24h
/co lookup a:kill u:Steve t:1w                  # Steve's kills this week
/co lookup r:#world a:session t:1d              # everyone's logins
```

### Rollback / restore

```
/co rollback <lookup-syntax>
```

Same parameters as `lookup`, but actually undoes the matched changes.
**Always do a `lookup` first** to verify what you're about to revert.

```
/co rollback u:GrieferDude t:6h r:100           # undo 6h of one user's work, 100-block radius
/co rollback a:block t:2h r:#world              # nuclear option: revert ALL block changes server-wide for 2h

/co restore <lookup-syntax>                     # opposite of rollback (redoes what rollback undid)
```

### Maintenance

| Command | What it does |
|---|---|
| `/co status` | Show database stats. |
| `/co reload` | Reload config. |
| `/co purge t:30d` | Delete logs older than 30 days. **Frees disk space — important on long-running servers.** |
| `/co consumer pause` / `/co consumer resume` | Pause/resume the background log writer (for debugging). |

### Killer combos

```
# Catch + revert grief in one shot
/co i                                           # turn on inspector
# left-click the broken block, see the username
/co lookup u:<username> t:1d r:#world           # what else did they do
/co rollback u:<username> t:1d r:#world         # undo it all
/ban <username> grief                           # boot them

# "Who took my diamonds?"
/co i                                           # inspector on
# right-click the chest where the diamonds went missing
# CoreProtect prints a transaction history with every withdrawal/deposit
```

**Files:**
- `/config/minecraft-worlds/<world>/plugins/CoreProtect/config.yml`
- `/config/minecraft-worlds/<world>/plugins/CoreProtect/database.db` — SQLite database

---

## Multiverse-Core

Run multiple Minecraft worlds inside one server: a survival main world,
a creative side world, a void-flat building world, etc. Switch between
them with `/mv tp`.

### Worlds

| Command | What it does |
|---|---|
| `/mv create <name> <env> [-t <type>] [-s <seed>] [-g <generator>]` | Create a new world. `<env>` is `normal`, `nether`, or `end`. |
| `/mv import <folder> <env>` | Import an existing world folder under MV management. |
| `/mv remove <name>` | Unregister a world (does NOT delete files). |
| `/mv delete <name>` | Permanently delete a world's files. (irreversible) |
| `/mv list` | List all loaded worlds. |
| `/mv info <name>` | World details. |
| `/mv load <name>` / `/mv unload <name>` | Load/unload at runtime. |
| `/mv reload` | Reload MV configs. |

`<type>` for `/mv create` includes `flat`, `largeBiomes`, `amplified`.
`<generator>` is for plugins like CleanRoomGenerator (void worlds).

### Teleport

| Command | What it does |
|---|---|
| `/mv tp <world>` | Teleport yourself to that world's spawn. |
| `/mv tp <player> <world>` | Teleport someone else. |
| `/mvtp <world>` | Same, shorter alias. |
| `/mv setspawn` | Set the current world's spawn at your location. |

### Properties (`/mv modify set <prop> <value> [world]`)

Most useful properties:

| Property | Values | Effect |
|---|---|---|
| `gamemode` | `survival`, `creative`, `adventure`, `spectator` | Force gamemode on entry. |
| `difficulty` | `peaceful`, `easy`, `normal`, `hard` | Per-world difficulty. |
| `monsters` | `true` / `false` | Hostile mob spawning. |
| `animals` | `true` / `false` | Passive mob spawning. |
| `pvp` | `true` / `false` | World-level PvP toggle. |
| `hunger` | `true` / `false` | Hunger drain. |
| `keepspawninmemory` | `true` / `false` | Keep spawn chunks loaded. |
| `allowweather` | `true` / `false` | Weather changes. |
| `time` | tick number or `day` / `night` | Lock world time. |
| `currency` | `material id` or `-1` | Per-world economy currency (with vault). |
| `respawn` | world name | Where players respawn from this world. |

### Killer combos

```
# Survival main + creative side world that resets weekly
/mv create creative normal -g VOID
/mv modify set gamemode creative creative
/mv modify set difficulty peaceful creative
/mv modify set monsters false creative
/mv modify set animals false creative
/mv modify set keepspawninmemory false creative
# Players use /mv tp creative to switch worlds; /spawn returns them to main

# Hardcore world for the brave
/mv create hardcore normal -s -1
/mv modify set difficulty hard hardcore
/mv modify set respawn world hardcore           # die in hardcore → respawn in main world

# Build sandbox for admins
/mv create build flat -t flat -g VOID
/mv modify set gamemode creative build
```

**Files:**
- `/config/minecraft-worlds/<world>/plugins/Multiverse-Core/config.yml`
- `/config/minecraft-worlds/<world>/plugins/Multiverse-Core/worlds.yml` — registered worlds
- Sub-worlds live as siblings of your main world folder.

---

## GriefPrevention

The "golden shovel" claim system. Players use a golden shovel to mark
plots they own; only they (and added trusts) can build inside.

### Claiming

In-game actions:
- **Right-click ground with a golden shovel** → start a claim corner.
- **Right-click another corner** → finalize the claim.
- **Right-click an existing claim with a stick** → see its info.

| Command | What it does |
|---|---|
| `/claim` | Create a claim around your position (alternative to shovel). |
| `/abandonclaim` | Abandon the claim you're standing in. |
| `/abandonallclaims` | Abandon ALL your claims (refunds claim blocks). |
| `/claimslist` | Show all your claims and total claim blocks. |
| `/claimsinfo` | Info on the claim you're standing in. |
| `/extendclaim <amount>` | Extend the claim in the direction you're facing. |

### Trust

Three levels: **Container** (chests/doors), **Build** (place/break), **Manager** (everything except sell).

| Command | What it does |
|---|---|
| `/trust <player>` | Build trust. |
| `/containertrust <player>` | Container trust. |
| `/permissiontrust <player>` | Manager trust. |
| `/untrust <player>` | Revoke all trust. |
| `/trustlist` | Show who's trusted in this claim. |
| `/accesstrust <player>` | Door/button trust only. |

### Admin

| Command | What it does |
|---|---|
| `/adjustbonusclaimblocks <player> <amount>` | Add/remove claim blocks. (op) |
| `/deleteclaim` | Force-delete the claim you're standing in. (op) |
| `/deleteallclaims <player>` | Wipe a user's claims. (op) |
| `/restorenature` | Regen terrain in current chunk to natural state. (op) |
| `/restorenatureaggressive` | Same, but more thorough. (op) |
| `/transferclaim <player>` | Transfer ownership. (op) |
| `/gpreload` | Reload config. (op) |

---

## mcMMO

RPG-style skill leveling: every action you do (mining, woodcutting,
swords, archery, ...) levels up an associated skill, which unlocks
passive bonuses and active abilities.

### Stats

| Command | What it does |
|---|---|
| `/mcstats` | Your levels in every skill. |
| `/<skill>` | Detailed info on a specific skill (e.g. `/mining`, `/woodcutting`). |
| `/mctop [skill]` | Server leaderboard. |
| `/mcrank [player]` | Rank for a player. |
| `/inspect <player>` | View another player's mcMMO stats. |
| `/mccooldown` | See ability cooldowns. |
| `/mcability` | Toggle ability use on right-click. |

### Party play

| Command | What it does |
|---|---|
| `/party create <name>` | Make a party. |
| `/party join <name>` | Join an existing party. |
| `/party invite <player>` | Invite. |
| `/party kick <player>` | Kick. |
| `/p <message>` | Party chat. |
| `/ptp <player>` | Teleport to a party member. |
| `/pc` | Toggle party chat. |

### Skills (default 16)

`acrobatics`, `alchemy`, `archery`, `axes`, `excavation`, `fishing`,
`herbalism`, `mining`, `repair`, `salvage`, `smelting`, `swords`,
`taming`, `tridents`, `unarmed`, `woodcutting`.

### Active abilities

Each skill has a "super ability" you trigger by holding the right tool
and right-clicking:

- **Mining → Super Breaker**: pickaxe goes through stone like butter.
- **Woodcutting → Tree Feller**: chops a whole tree at once.
- **Excavation → Giga Drill Breaker**: shovel speed + drop bonuses.
- **Swords → Serrated Strikes**: bleed AOE.
- **Axes → Skull Splitter**: AOE damage.

### Admin

| Command | What it does |
|---|---|
| `/mmoedit <player> <skill> <level>` | Set a player's skill level. (op) |
| `/addxp <player> <skill> <amount>` | Award XP. (op) |
| `/mcremove <player>` | Wipe a player's mcMMO data. (op) |
| `/mcrefresh <player>` | Reset cooldowns. (op) |

---

## ChestSort

Auto-sorts chest contents. The single best quality-of-life plugin
ever made.

| Command | What it does |
|---|---|
| Open chest, then **left-click outside it with empty hand** | Sort the open chest. |
| `/chestsort` | Toggle auto-sort on every chest you open. |
| `/invsort` | Sort your own inventory. |
| `/chestsort <player>` | Toggle for another player. (op) |
| `/chestsort reload` | Reload config. (op) |

**Files:**
- `/config/minecraft-worlds/<world>/plugins/ChestSort/config.yml` — customize the sort categories.

---

## VeinMiner

Sneak (hold Shift) + break a single ore → the whole connected vein
breaks. Cuts mining time in half.

| Command | What it does |
|---|---|
| `/veinminer toggle` | Toggle for yourself. |
| `/veinminer pattern <pattern>` | Switch break-pattern. `default` follows the vein; others may diagonal-skip. |
| `/veinminer blocklist add <category> <block>` | Add a block to vein-mining. |
| `/veinminer blocklist remove <category> <block>` | Remove. |
| `/veinminer blocklist list <category>` | Show what's in a category. |
| `/veinminer reload` | Reload config. (op) |

Categories include `pickaxe`, `axe`, `shovel`, `hoe`. Adding a block to
a category lets the matching tool vein-mine it.

**Files:**
- `/config/minecraft-worlds/<world>/plugins/Veinminer/blocks.json` — full vein list (add wood, leaves, netherrack, etc.)

---

## spark

The performance profiler. When the server feels laggy, this is what
you run **before** asking why.

### Performance health

| Command | What it does |
|---|---|
| `/spark tps` | Current TPS (target: 20.00). Below 18 = noticeable lag. |
| `/spark tps detailed` | Per-world TPS breakdown. |
| `/spark health` | Memory, CPU, disk, GC stats. |
| `/spark ping` | Network ping for online players. |

### Profiling

| Command | What it does |
|---|---|
| `/spark profiler --timeout 60` | 60-second CPU profile. Posts a web link with a flame graph. |
| `/spark profiler --timeout 30 --thread tick` | Profile only the main tick thread. |
| `/spark profiler --timeout 60 --only-ticks-over 100` | Only sample slow ticks. |
| `/spark profiler stop` | Stop a running profile early. |

### Memory

| Command | What it does |
|---|---|
| `/spark heapsummary` | Snapshot of what's using memory. |
| `/spark heapdump` | Full heap dump. (large file; for advanced debugging) |
| `/spark gc` | Trigger a garbage-collection summary. |

**Reading a profile:** spark gives you a URL like `https://spark.lucko.me/<id>`.
The flame graph shows percentage of time spent in each method. Wide
bars = where time is going. Look for unfamiliar plugin names = misbehaving plugin.

---

## Geyser-Spigot

Bridges Minecraft Bedrock Edition (iOS, Android, Switch, Xbox, PS,
Win10/11) to your Java server. Without Geyser, Bedrock players can't
join Java servers. With it, they connect to UDP `19132` and play
seamlessly.

### Commands

| Command | What it does |
|---|---|
| `/geyser version` | Geyser version + supported Java/Bedrock protocols. |
| `/geyser reload` | Reload Geyser config. |
| `/geyser dump` | Generate a debug dump (URL); useful when reporting bugs. |
| `/geyser connectiontest <ip>:<port>` | Test if a Bedrock client could reach the server from outside. |
| `/geyser stop` | Stop Geyser without stopping the server. |

### Configuration the add-on manages

These are set via the add-on options panel and applied automatically:

- `auth-type` (offline / floodgate / online): how Bedrock users are authenticated.
- `validate-bedrock-login`: whether to require Xbox-signed JWT (set to `false` for `offline`).
- `mtu`: UDP packet size (lower if iOS hangs on connect).
- `motd1` / `motd2`: server list display lines.

**Files:**
- `/config/minecraft-worlds/<world>/plugins/Geyser-Spigot/config.yml`

---

## Floodgate

Companion to Geyser. Lets Bedrock players join with their Bedrock
username (no Java/Mojang account required) by tagging them with a
prefix character (default: `.`).

Only installed when `geyser_auth_type` is `floodgate` or `auto` with
`online_mode: true`.

### Commands

| Command | What it does |
|---|---|
| `/floodgate linkaccount <java-username>` | Link a Bedrock player to a Java account. (Bedrock player runs this) |
| `/floodgate unlinkaccount` | Unlink. |
| `/floodgate whitelist <bedrock-name>` | Whitelist a Bedrock player by Bedrock name. (op) |

---

## ViaVersion / ViaBackwards

Protocol bridges. ViaVersion lets clients on a **newer** Minecraft
version connect to an older server (e.g. a Java 26.1 client joining a
1.21.11 Paper server). ViaBackwards is the opposite — older clients
connecting to a newer server.

### Commands

| Command | What it does |
|---|---|
| `/viaversion list` | Online players + their protocol versions. |
| `/viaversion info` | Server protocol version. |
| `/viaversion autoteam <enable\|disable>` | Auto-team conflicting clients. |
| `/viaversion reload` | Reload config. |

### What this fixes for you

If you see this kick message:

> **Outdated server! I'm still on 1.21.11**

…that's a Java client on a newer Minecraft version trying to connect
to your older Paper server. ViaVersion translates the protocol, and
the connection just works. The add-on installs both ViaVersion and
ViaBackwards automatically (`install_viaversion: true`,
`install_viabackwards: true` are the defaults from 1.5.2 onward).

---

## "Demo to your kids" recipes

**Lava castle in 30 seconds:**
```
//pos1                  # corner 1
# walk 30 blocks
//pos2                  # corner 2
//walls obsidian
//set 0,1               # mix of air + glowstone
//gmask !#existing
//replace 0 lava        # turn the air into lava using a mask
```

**Instant minigame arena:**
```
//hsphere quartz_block 25 0
# (now standing inside a 25-block-radius hollow quartz dome)
//pos1 / //pos2          # full bounds
/rg define arena
/rg flag arena pvp allow
/rg flag arena keep-inventory allow
/rg flag arena game-mode survival
/spawnmob zombie 30
```

**"Caught red-handed":**
```
/co i
# left-click the broken thing
/co lookup u:<griefer> t:1h r:#world
/co rollback u:<griefer> t:1h r:#world
/ban <griefer> grief
```

**Spawn town with VIP plots:**
```
# 1. Lock the central spawn area
//wand                                          # WE select 50×50 around spawn
/rg define town-square
/rg flag town-square build deny -g default
/rg flag town-square build allow -g vip
/rg flag town-square pvp deny
/rg flag town-square keep-inventory allow
/rg flag town-square greeting "&aWelcome to spawn town!"

# 2. Plot 1
//wand
/rg define plot-1
/rg setpriority plot-1 5                        # higher than town-square
/rg addmember plot-1 Steve
/rg flag plot-1 build allow

# 3. Repeat for each plot
```
