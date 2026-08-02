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

Both add-ons run with real authority over a Home Assistant install, and
knowing where the boundaries are is most of knowing what counts as a bug.

**brAIn** runs Claude Code with read/write access to `/config`, and,
depending on the options you enable, to `/share`, `/media`, other add-ons'
configuration, and the Home Assistant API as an admin. It signs in to your
Anthropic account and stores that credential in the add-on's `/data`. It
is, by design, an agent that can change your home. The security boundary
is Home Assistant's own authentication: nothing brAIn exposes should be
reachable without it.

**BRUH Minecraft** runs a JVM that loads third-party plugin jars, and it
uses `host_network: true` so Bedrock clients can find the server on the
LAN. Its management panel is gated to the Supervisor's own network; the
resource-pack path and a liveness endpoint are deliberately public.

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
- `dangerously_skip_permissions: true` removes Claude's confirmation
  prompts. The option says so, and defaults to off.
- Minecraft plugins you install run with the server's full authority. The
  AppArmor profile limits what that means for the *host*, not for the
  world.

## Hardening we already apply

- AppArmor profiles on both add-ons, denying mount, kernel module
  loading, raw sockets, kernel tunables and the Docker socket.
- The brAIn terminal port is unpublished by default and requires HTTP
  Basic auth when published.
- The Minecraft panel refuses management requests that did not arrive
  through the Supervisor.
- Credentials are excluded from Home Assistant backups via
  `backup_exclude`.
- Claude Code runs as an unprivileged user (UID 1000), not root.
- Background listeners use an explicit tool allow-list rather than
  `--dangerously-skip-permissions`.
- CI runs secret, injection and quoting checks (`tests/test_security.py`),
  CodeQL, shellcheck and hadolint on every pull request.
