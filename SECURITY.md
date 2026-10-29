# Security policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/bruhautomation/BRUH-HA-Apps/security/advisories/new)
on this repository. That opens a thread only you and the maintainers can
see, and it is where a fix and an advisory can be prepared together.

What helps:

- Which add-on, and which version (the version shown in the Supervisor).
- What an attacker can do with it, and what access they need first — on
  the LAN, on the Home Assistant host, or already inside a container.
- The smallest steps that show it happening.

We will acknowledge within a week, and keep you updated as we work on a
fix. If you would like credit in the advisory, say so and give us the name
or handle to use.

## Supported versions

The latest released version of each add-on is the supported one. Home
Assistant only offers the version in `config.yaml`, so fixes ship as a
version bump and reach users through the normal add-on update.

## What these add-ons can reach

These add-ons run with real authority over a Home Assistant install, and
knowing where the boundaries are is most of knowing what counts as a bug.

**brAIn** runs Claude Code with read/write access to `/config`, and,
depending on the options you enable, to `/share`, `/media`, other add-ons'
configuration, and the Home Assistant API as an admin. It signs in to your
Anthropic account and stores that credential in the add-on's `/data`. It
is, by design, an agent that can change your home. The security boundary
is Home Assistant's own authentication: nothing brAIn exposes should be
reachable without it.
Capture (off by default) records what the analyst was sent and what it
answered, redacted as it is written, and keeps it in `/data`; nothing reaches
`/share` until a person presses Export, and nothing leaves the machine at all.
Claude Code runs as the unprivileged `claude` user while brAIn's panel runs as
root, and the panel has one route that changes file ownership: `POST /api/own`
hands a file under `/config` (or `/addon_configs`, `/share`, `/media` and
`/addons`, while the options that give brAIn those folders are on) to the
`claude` user and gives that owner write permission, so Claude can edit what Home Assistant or another add-on saved
as root. It answers only loopback, read off the socket rather than any header,
so only processes inside the add-on's own container (the edit and shell hooks
and `brain own`) can reach it. It checks the file it actually opened, refusing
special files, hard-linked files, anything outside those folders, `.storage`,
`.cloud`, brAIn's credentials, `secrets.yaml` and the recorder database; a
symbolic link is resolved once and its target has to pass the same checks. The
panel also re-owns, about once a minute and without the route, the top-level
YAML in `/config` (never a link, `secrets.yaml` or a hard-linked file) and each
add-on's own folder under `/addon_configs`.

**BRUH Minecraft** runs a JVM that loads third-party plugin jars, and it
uses `host_network: true` so Bedrock clients can find the server on the
LAN. Its management panel is gated to the Supervisor's own network; the
resource-pack path and a liveness endpoint are deliberately public.

**BRight** uses `host_network: true` so LIFX discovery — a UDP broadcast
whose replies come back to the sender's own address — works at all, which
puts its panel on a real port on the host. Every route is gated to the
Supervisor's own networks and loopback, matched on the connection's peer
address rather than on any header a caller can set, and **no prefix is
public**. It reads your music under `/media` and writes one file there (the
calibration click track, in `/media/bright/`), reads and writes its own
`/config/.bright/` for the integration bridge, and calls the Home Assistant
API to list entities, play media and toggle the switch-driven lights a show
uses. It holds no credential of its own. Its panel port is assigned by the
Supervisor rather than fixed.

**BRUH Print** takes `usb: true`, which maps the host's `/dev/bus/usb` into
the container so it can write raster data to a DYMO LabelWriter's bulk
endpoint. Its panel runs as **root**, because those device nodes carry the
host's own root:root ownership — there is no udev in the container to
re-own them — and a process at UID 1000 cannot open them for writing. That
is bounded rather than dismissed: no port is published, so the panel is
reachable only through ingress, and `panel_admin: true` means the caller is
already a Home Assistant admin who holds the Supervisor API. The file-IPC
bridge, which reads request files written from outside the container, runs
at UID 1000 and never touches USB. BRUH Print holds no credential of its
own, reads and writes its own `/data` and `/config/.bruh_print/`, and writes
one file under `/config/www/bruh_print/` (the Lovelace card).

**BRUH Bambu Studio** runs Bambu Studio on a virtual X screen inside its
container. The VNC server that reads that screen listens on **loopback
only** and has no password of its own, because the only route to it is the
panel's websocket bridge, which is behind ingress with `panel_admin: true`.
No port is published and there is no host networking. It holds one kind of
credential: each printer's LAN **access code**, kept in
`/data/secrets/printers.json` (mode 0600) and excluded from Home Assistant
backups. It talks to the printers outbound only (MQTT on 8883 and FTPS on
990, both TLS; the printers' certificates are self-signed per device and are
not verified, the access code being what authenticates). It downloads Bambu
Studio from Bambu Lab's GitHub releases over HTTPS and unpacks it without
mounting anything. Everything after the first-boot filesystem layout runs at
UID 1000. Starting a print, stopping one, raw G-code and slicing are refused
to a voice-level brAIn agent, and every acting tool is kept from brAIn's
unattended runs.

Its optional **Design** tab runs Python that brAIn writes (a CadQuery part
script). brAIn answers those requests with reading tools only and never
writes or runs anything itself; the add-on parses each script first and
refuses any import other than CadQuery, cadkit, math and numpy and any use of
`open`, `eval`, `getattr` or underscore attributes, then runs it in a
separate process with an empty environment (no `SUPERVISOR_TOKEN`), a CPU
time limit and a cap on what it may write. That check is a guard against a
model wandering, not a sandbox against an adversary: the words that drive it
come from an admin, in a panel only an admin can open.

**BRUH Task Manager** asks for `hassio_role: manager`, the narrowest role
that can restart or stop another app, and for `host_pid: true`. The
Supervisor only applies `host_pid` while the user has switched the add-on's
**Protection mode off**; with it on (the default) the container has its own
process list like any other. Its own `process_view` option is off by
default too, so nothing reads the host's processes until a person has
turned both switches. With both on it can see every process on the machine
and its command line, and send signals; its AppArmor profile denies reading
any other process's environment or memory (`/proc/*/environ`, `/proc/*/mem`,
`/proc/*/root`), so other apps' tokens stay out of reach, and the kernel
also asks the receiving app's profile before a signal is delivered. End
process is a third switch, off by default, and is refused in code for Home
Assistant, the Supervisor, its plugins, the operating system, the kernel,
any container it cannot name, and each app's own init. The panel runs as
root so a signal can reach root processes; no port is published, ingress is
authenticated and the panel is `panel_admin: true`. The add-on rates 5 in
the store rather than 6, which is `host_pid`'s cost and is said on its
Settings page.

**BRUH Cooking** is a shell script with `hassio_role: default`: it reads
`/supervisor/info` to find brAIn, posts its discovery, and copies the
`bruh_cooking` integration into `/config`. It publishes no port and has no
panel of its own. The integration runs inside Home Assistant Core and talks
to Breville's cloud with the account's login session, which is kept in the
config entry rather than the password; its diagnostics redact the account's
email, names, ids, tokens, serial numbers and network addresses. Anyone who
can use Home Assistant can start and stop a cook through the appliance's
entities, as with any switch; untested models are monitor-only until an
admin allows control, and saving or deleting a preset is admin-only.

Things we consider vulnerabilities:

- Any management endpoint answering a caller who has not authenticated to
  Home Assistant.
- Anything that escapes an add-on container to the host.
- Credential disclosure — the Anthropic OAuth token, the RCON password,
  the terminal password, `SUPERVISOR_TOKEN` — to a lower-privileged
  caller, a log, or a backup.
- Command or path injection reachable from a non-admin input, including
  from a voice command or an automation payload.

Things that are working as intended, and are documented rather than fixed:

- An admin using the brAIn terminal can run anything the container can.
  That is what the terminal is.
- brAIn has one role, not per-user roles. Every Home Assistant admin sees
  the same panel, the same chat session, the same memory, and the same
  **Fix it** button — the panel is `panel_admin: true`, and "admin" is
  the entire access model. There is no per-admin separation to bypass,
  so two admins seeing each other's chats is by design; if that matters
  in your household, HA's own user roles are the boundary to use.
- `dangerously_skip_permissions: true` ("Let brAIn act without asking", also
  in the panel's ⚙ → Terminal & chat) removes Claude's confirmation prompts in
  the terminal and the chat. The option says so, says where the guard on
  protected entities stops for a shell command, and defaults to off.
- Minecraft plugins you install run with the server's full authority. The
  AppArmor profile limits what that means for the *host*, not for the
  world.
- BRight sends LIFX packets to bulbs on your LAN without authenticating to
  them. That is the LIFX LAN protocol: it has no authentication, and any
  device on the network can already drive those bulbs.
- BRUH Print's panel runs as root inside its container, for the reason
  above. An admin who can reach that panel can already reach the Supervisor
  API, so it does not widen what an authenticated caller can do — but it
  does mean a bug in the panel is a root bug in that container, which is
  why it is worth reporting.
- BRUH Print writes to whatever DYMO printer is on the USB bus. It has no
  way to authenticate to one; USB printers do not offer that.
- BRUH Task Manager with Level 2 on and Protection mode off can see every
  process's command line, which occasionally carries a password somebody
  typed into an app's setting. That is what showing a process means; the
  Settings page says so before the switch is turned on, and the environment
  and memory, where secrets usually live, stay denied.

## Hardening we already apply

- AppArmor profiles on all four add-ons, denying mount, kernel module
  loading, raw sockets, kernel tunables and the Docker socket. BRUH Print's
  additionally names `/dev/bus/usb` explicitly rather than leaving it to the
  blanket `file,` rule, so a future edit narrowing that rule cannot silently
  take away the one capability the add-on exists for.
- The brAIn terminal port is unpublished by default and requires HTTP
  Basic auth when published.
- The Minecraft and BRight panels refuse requests that did not arrive
  through the Supervisor. BRight's has no public prefix at all.
- Every path BRight is handed from the wire — a folder to scan, a track to
  play — is confined to `/media` before any filesystem call.
- Every image a BRUH Print label references is resolved and checked against
  its own uploads folder before it is opened: a label file is data from
  outside, even when the outside is the person's own laptop.
- Credentials are excluded from Home Assistant backups via
  `backup_exclude`.
- Claude Code runs as an unprivileged user (UID 1000), not root.
- Background listeners use an explicit tool allow-list rather than
  `--dangerously-skip-permissions`.
- CI runs secret, injection and quoting checks (`tests/test_security.py`),
  shellcheck, hadolint, and AppArmor profile validation on every pull
  request. CodeQL runs too, on any public clone of this repository —
  code scanning is free on public repositories and a paid add-on on
  private ones, so the job stands itself down while a repository is
  private rather than reporting a billing state as a failure.
