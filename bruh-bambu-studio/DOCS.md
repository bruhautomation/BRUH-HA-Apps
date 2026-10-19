# BRUH Bambu Studio

> ⚠️ **Experimental.** Keep Bambu Handy or the printer's own screen within
> reach the first few times you start a print from Home Assistant.

## Installing

1. Install the add-on and start it. The first start downloads Bambu Studio
   (about 220 MB) from Bambu Lab's GitHub releases and unpacks it into the
   add-on's own storage; the **Studio** tab shows the progress. Later starts
   use the copy already downloaded.
2. Open **Bambu Studio** in the sidebar. The slicer runs on a virtual screen
   inside the add-on and the page shows it. Sign in to your Bambu account
   there if you want cloud features; nothing below needs it.
3. Accept the **BRUH Bambu Studio** integration Home Assistant offers under
   Settings → Devices & services, so the services and sensors appear.

The add-on is **amd64 only**: Bambu Lab publishes Bambu Studio for Linux as an
x86-64 AppImage and nothing else.

## Adding a printer

On the **Printers** tab, open *Add a printer* and give:

- the printer's **IP address** (the printer's screen shows it under Network —
  give it a fixed address in your router so it does not move);
- its **serial number** (Settings → Device on the printer);
- its **access code** (the LAN settings page on the printer).

On recent firmware a printer only accepts commands from anything other than
Bambu's own apps with **LAN-only mode** and **Developer mode** switched on.
Without them the printer still reports its status, and a command comes back
with *"The printer did not confirm it"*.

The access code is stored apart from everything else and is **left out of
Home Assistant backups**. After restoring a backup, add the code again.

The add-on is not on your host network, so it cannot discover printers by
itself; that is why the address is typed.

## Files

Models and print files live in **`/share/bambu`** — reachable over Samba, from
the File Editor, from the panel's **Files** tab, and from Bambu Studio's own
Open dialog. Sliced print files are saved in `/share/bambu/sliced`.

On the Files tab each file says whether it is sliced, how many plates it has,
and (for sliced files) the print time and filament weight.

- **Print** sends it to a printer. A project that is not sliced yet is sliced
  first with the settings saved in it.
- **Slice** slices a project without printing.
- **Open in Studio** opens it in the sidebar's Bambu Studio.

### What slices without the GUI

A **Bambu Studio project** (`.3mf` saved from Bambu Studio) carries its
printer, process and filament settings, so it slices exactly as it would in
the app. A **bare model** (`.stl`, `.step`, `.obj`) carries none, so slicing
one needs a machine and a process profile named the way Bambu Studio lists
them (`bruh_bambu.list_files` lists them under `profiles`). When in doubt, open
the model in Bambu Studio, set it up, and save it as a project into
`/share/bambu`.

## Services

| Service | What it does |
|---|---|
| `bruh_bambu.get_status` | Every printer's state, progress, time left, temperatures, speed, light and AMS, plus the latest jobs |
| `bruh_bambu.list_files` | The files in `/share/bambu` |
| `bruh_bambu.printer_files` | What is on a printer's own storage |
| `bruh_bambu.print_file` | Print a file (sliced first if needed) |
| `bruh_bambu.slice_file` | Slice a project or model |
| `bruh_bambu.pause_print` / `resume_print` / `stop_print` | Control the current print |
| `bruh_bambu.set_speed` | silent, standard, sport or ludicrous |
| `bruh_bambu.set_light` | Chamber light on or off |
| `bruh_bambu.set_temperature` | Nozzle (up to 300 °C) or bed (up to 120 °C) target; refused while printing |
| `bruh_bambu.send_gcode` | Up to 32 lines of G-code; refused while printing |
| `bruh_bambu.open_in_studio` | Open a file in the sidebar's Bambu Studio |

`printer` can be left out when there is only one printer; with two or more it
is the printer's name or serial number. Every service answers with the
add-on's reply, and a refusal ("Workshop X1C is already printing") is raised
with its reason, so it shows in the automation trace.

```yaml
action: bruh_bambu.print_file
data:
  file: sliced/benchy.gcode.3mf
  printer: Workshop X1C
```

## Sensors

Each printer gets a device with five sensors: **Status** (the printer's own
word — idle, prepare, running, pause, finish, failed — with everything else as
attributes, and *offline* when it is not reporting), **Progress**, **Time
left**, **Nozzle temperature** and **Bed temperature**.

## brAIn

With brAIn installed, its tools `bambu_status`, `bambu_print`,
`bambu_control` and `bambu_slice` drive the printers through the services
above, so "how long is left on the print?", "pause the printer" and "print the
benchy on the X1C" work from the chat, the terminal and voice. A voice agent
may check on a print, pause, resume, change the speed and the light; starting
or stopping a print, slicing and raw G-code are refused by voice, because a
misheard sentence there is filament and hours.

## Options

| Option | |
|---|---|
| `enable_ha_integration` | Deploy the `bruh_bambu` integration and its bridge |
| `bambu_studio_version` | `latest`, or a release tag such as `v02.08.02.61` |
| `appimage_url` | A direct AppImage link to use instead of the GitHub release |
| `screen_resolution` | The virtual screen's size, `WIDTHxHEIGHT` |
| `log_level` | The add-on's own logging |

## Troubleshooting

- **The Studio tab stays black or says Bambu Studio closed.** Its last output
  is under *What it last printed* on that tab. The slicer draws with software
  OpenGL, so a large model's 3D view is slow; slicing is unaffected.
- **"The printer refused the access code."** The code changes when LAN mode is
  switched off and on; read it from the printer again.
- **Commands do nothing.** Switch on LAN-only mode and Developer mode on the
  printer.
