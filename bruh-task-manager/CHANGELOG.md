# Changelog

## 0.1.3

### Changed

- **The add-on says when Home Assistant needs a restart, and only then.** It compares the integration code Home Assistant loaded with what was just installed and says so in its log only when they differ. The first update with this change still asks once.

## 0.1.2

### Security

- **A name sent to the panel cannot forge a line in the add-on's log.** The app name and action a Restart or Stop request carries are written to the log with line breaks and other control characters replaced.

## 0.1.1

### Fixed

- **Level 2 could not start.** With Protection mode off, the add-on stopped
  at boot with `s6-overlay-suexec: fatal: can only run as pid 1`. Level 2
  shares the machine's process list, so the add-on is no longer process 1,
  and the base image's start-up program (s6-overlay) refuses to run
  anywhere else. The add-on now starts its own script directly.
- The Protection mode check uses bashio's new name, so the log no longer
  warns that `bashio::addon.protected` is deprecated.
- Start-up warnings no longer have doubled spaces where the text wrapped.

## 0.1.0

### Added

- **Level 1, apps.** CPU, memory, network and disk for every app, Home
  Assistant, the Supervisor and its plugins, measured by the Supervisor and
  updated every few seconds, with a history line per app. Restart, Stop and
  Start, each asking first and saying what it will cost (integrations that
  talk to the app, its sidebar panel, whether it starts again at boot).
- **Level 2, every process** — off by default. Switched on in Settings, and
  in effect once Protection mode is turned off on the add-on's Info page.
  Every process on the machine, grouped by the app it belongs to, with its
  CPU, memory and command line. The Settings page says what turning
  Protection mode off does, and ticks off the three steps.
- **End process** — a second switch, off by default. Only for processes
  inside apps; never Home Assistant, the Supervisor, its plugins or the
  operating system. Asks the process to stop first, and offers Force end
  only if it is still running five seconds later. A "Never end these" list.
- **Runaway apps.** An app above a CPU threshold for long enough is marked
  in the panel and turns on a Home Assistant binary sensor. Nothing is
  stopped automatically.
- **Home Assistant integration** with sensors for the machine's CPU and
  memory, the busiest app and its CPU, and the runaway binary sensor.

### Security

- The AppArmor profile denies reading any other process's environment or
  memory, so Level 2 cannot see other apps' tokens or passwords.
- The add-on rates 5 in the add-on store, not 6: `host_pid` costs two points
  whether or not Protection mode lets it take effect.
