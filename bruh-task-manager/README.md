# BRUH Task Manager

> ⚠️ **Experimental.**

**What is using your Home Assistant machine, and a way to stop it.** Task
Manager for Home Assistant OS, in the sidebar.

- **Level 1, every app (the default).** CPU, memory, network and disk for each
  app, Home Assistant, the Supervisor and its plugins, measured by the
  Supervisor every few seconds. Restart, Stop and Start, each asking first
  and saying what it will cost.
- **Level 2, every process (off until you turn it on).** Every process on the
  machine, grouped by the app it belongs to, with its CPU, memory and
  command line. Needs Protection mode turned off on this add-on's Info page;
  the Settings tab says exactly what that does before you do it.
- **End process (off until you turn it on).** Only for processes inside
  apps — never Home Assistant, the Supervisor or the operating system. It
  asks the process to stop, and offers Force end only if it did not.
- **Runaway apps.** An app above a CPU threshold for long enough is marked,
  and a Home Assistant binary sensor turns on for your automations.

📖 [Full documentation](DOCS.md)
