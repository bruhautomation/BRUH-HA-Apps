# BRUH Task Manager

Task Manager for Home Assistant OS: what each app is using, and a way to
restart or stop what is running too hard. It opens in the sidebar as
**Task Manager**.

It works at two levels. **Level 1** is on from the moment you install it and
needs nothing from you. **Level 2** is off until you turn it on, and asks you
to change one security setting first. Read [Level 2](#level-2-every-process)
before you do.

## The top bar

Four figures for the whole machine: **CPU** (with the last few minutes as a
line), **Memory** (used of total), **Load** (the 1-minute load average beside
the number of CPUs), and how long the machine has been **Up**.

## Level 1: every app

The **Apps** tab lists every app, Home Assistant, the Supervisor and the
Supervisor's plugins (DNS, audio and so on), busiest first. For each one:

- **CPU** — its share of the whole machine. 50% on a four-core machine is
  two cores' worth. The line under it is the last few minutes.
- **Memory**, and **network** and **disk** traffic per second.
- **Restart**, **Stop** and **Start**. Each asks first, and the question says
  what will happen: which Home Assistant integrations talk to the app (they
  will show as unavailable while it is down), whether its sidebar panel will
  stop opening, and whether it starts again at boot. Home Assistant and the
  Supervisor can be restarted but not stopped. BRUH Task Manager does not
  offer to stop itself.

Level 1 uses the Supervisor's own figures — the same ones behind Settings →
System → Hardware — and needs no special permission.

## Level 2: every process

Level 2 lists every process on the machine — Home Assistant's Python and the
ffmpeg it starts for a camera, each app's programs, the Supervisor, Docker,
the operating system's services — grouped by the app it belongs to.

### What it needs

1. Turn on **Show every process** on the Settings tab (or the *Level 2: show
   every process* option on the Configuration tab).
2. Turn **Protection mode off** on this add-on's **Info** page. Only you can
   do this; an add-on cannot change its own Protection mode.
3. **Restart** the add-on, because Protection mode only takes effect when the
   add-on starts.

The Settings tab ticks off each step as it is done, and says which one is
missing.

### What turning Protection mode off does

- It lets **this one add-on see every process** on the machine and its
  command line. Command lines occasionally contain a password somebody typed
  into a setting.
- It lets this add-on **send signals to processes in other apps**, which is
  how End process works.
- It does **not** let it read other apps' passwords or tokens: its security
  profile blocks reading another process's environment and memory, whatever
  Protection mode says.
- It does **not** open any network port, and changes nothing about your other
  apps.
- The add-on store shows this add-on's **security rating as 5** instead of 6.
  That is because it *asks* for the process list at all, and is the same
  whether Protection mode is on or off.

When you are finished, switch Level 2 off and turn Protection mode back on.
If Protection mode is off but Level 2 is switched off, the add-on reads
nothing and says so in its log and on the Settings tab.

### Reading the Processes tab

Each app is a group with its total CPU, memory and number of processes; open
one to see its processes, busiest first. **Memory** is resident memory (what
is in RAM now). Where the operating system lets the add-on read it, it is
*proportional* memory instead, which splits shared libraries fairly between
the processes using them; hover the figure to see which. Kernel threads are
hidden unless you tick **Kernel threads**.

A group called **Unknown container** is a container the add-on could not
match to an app. It is shown, but nothing in it can be ended.

## Ending a process

**Allow ending processes** is a second switch on the Settings tab, off by
default, and only available with Level 2 on. With it on, **End** appears on
processes that belong to an app.

- **End asks the process to stop** (SIGTERM), so it can save and exit cleanly.
- If it is still running five seconds later, **Force end** is offered
  (SIGKILL), which stops it immediately without letting it save anything.
- **Never offered** for Home Assistant, the Supervisor, Supervisor plugins,
  the operating system, the kernel, BRUH Task Manager itself, an unknown
  container, or the process that keeps an app running (its init or process
  supervisor). Each of those says why in words, and where there is a gentler
  answer — Restart on the Apps tab — it says that instead.
- Anything on your **Never end these** list is never offered either. One
  entry per line: a process name or an app's slug; wildcards work
  (`mosquitto`, `*_frigate`).

**Could ending a process break something?** Ending a helper process inside
an app (a worker, an ffmpeg stream, an editor's extension host) usually
leaves the app running; many restart the helper themselves. Ending an app's
main program usually stops the app, and the Supervisor restarts it if its
watchdog is on. That is why the add-on refuses the processes whose loss
would take down the machine, and why **Restart** on the Apps tab is the
better answer when you are not sure. Some apps' own security profiles refuse
signals from other apps; when that happens the add-on says so and points at
Restart.

Every process ended and every app restarted is written to the add-on's log.

## Runaway apps

An app using at least the **threshold** share of the machine's CPU (default
80%) for at least the **time** (default 10 minutes) is marked as running away:
a banner on the panel, a mark on its row, and the **Runaway app** binary
sensor turns on. A short burst, like an update or a backup, does not count,
and a reading the Supervisor could not take does not reset the clock.
**Nothing is stopped automatically.** What to do is your decision, or an
automation's.

## Home Assistant integration

With **Home Assistant integration** on (the default), the add-on installs the
`bruh_task_manager` integration and Home Assistant offers to set it up. It
adds, on one *BRUH Task Manager* device:

| Entity | What it is |
|---|---|
| CPU | The whole machine's CPU, % |
| Memory used | The whole machine's memory, % (used and total bytes as attributes) |
| Busiest app | The name of the app using the most CPU; its slug, CPU and memory, and the top ten, as attributes |
| Busiest app CPU | That app's CPU, % |
| Runaway app | On while an app is running away; the apps (with their slugs), the threshold and the time as attributes |

The measurements go unavailable if the add-on stops measuring. **Runaway
app** goes *unknown* rather than off, with the reason as an attribute,
because "the add-on could not look" is not "nothing is running hot".

An automation that restarts a runaway app uses Home Assistant's own action:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.bruh_task_manager_runaway_app
    to: "on"
actions:
  - action: hassio.addon_restart
    data:
      addon: "{{ state_attr('binary_sensor.bruh_task_manager_runaway_app', 'apps')[0].slug }}"
```

Home Assistant itself and the Supervisor are never listed as an app's slug
here; `hassio.addon_restart` only restarts apps.

## Options

| Option | Default | What it does |
|---|---|---|
| Home Assistant integration | on | Install the companion integration and its sensors |
| Level 2: show every process | off | See [Level 2](#level-2-every-process) |
| Level 2: allow ending processes | off | See [Ending a process](#ending-a-process) |
| Never end these | empty | Process names or app slugs never offered End |
| Runaway threshold | 80 | % of the machine's CPU |
| Runaway time | 10 | Minutes above the threshold |
| Measure every | 5 | Seconds between measurements |
| Log level | info | The add-on's own logging |

Everything except the integration switch and the log level can also be
changed on the panel's Settings tab, and takes effect without a restart.
