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

## Design with brAIn (optional)

With [brAIn](../brain/) installed and its **Automation integration** on, a
**Design** tab appears. Without brAIn the tab is not there (or, if you have
parts already, it shows them and says why it cannot chat) and nothing else
in the add-on changes.

1. Press **New part** and describe it: what it is for, what it fits, sizes you
   know. brAIn picks sensible defaults, says them, and asks only what it
   cannot guess (a mating size, a clearance) — its questions are buttons you
   can tap to answer.
2. brAIn writes the part as a parametric CadQuery script; the add-on checks it,
   builds it, and shows it in a **3D view**: orbit, pan and zoom, Iso / Top /
   Front / Right, **Measure** (tap two points for the distance and its X, Y, Z
   parts), wireframe, and the overall size. If a build fails, the error goes
   straight back to brAIn to fix (twice at most) before you see it.
3. Keep talking to change it. Every change that builds is a new **version**:
   the chips under the view switch between them, and *Keep working from vN*
   makes an older one the base for the next change. Nothing is overwritten.
4. **Print** asks which printer, then shows how brAIn would print it — the
   material and colour it suggests and why, layer height, walls, infill,
   supports and brim, all editable — and the AMS trays with the best match
   picked. *Slice and print* chooses Bambu Studio's own profiles for that
   printer and filament, puts the settings over them, slices with Bambu
   Studio's command line, uploads and starts. Set the printer's **model** on
   the Printers tab so the right profiles are chosen.

Every part lives in `/share/bambu/designs/<part>/` — its conversation, each
version's `design.py`, STEP, 3MF and STL — so you can open the STEP in
Onshape or Fusion, or the 3MF in Bambu Studio, and come back to the
conversation days later from the parts list: it resumes the same brAIn
conversation (which also appears in brAIn's own chat list).

brAIn answers design requests with reading tools only; it never writes files
or runs anything itself. The add-on runs the script it writes in a separate
process with no Home Assistant token and a time limit, after checking it
imports nothing but CadQuery, cadkit, math and numpy.

## The printer card

The add-on installs one card in two places:

- **Lovelace:** add *BRUH Bambu printers* from the card picker
  (`type: custom:bruh-bambu-card`). With no options it shows every printer;
  `entity: sensor.workshop_x1c_status` shows one. `show_ams: false` and
  `show_controls: false` trim it.
- **Morph:** with Morph installed, the same card is in `/config/morph/cards`
  and is used as `type: custom:morph-bambu-printer`, in Morph's own look.

It shows progress, time left and the finish time, the layer, temperatures and
AMS trays, with Pause/Resume, Stop (press twice), speed and the chamber light.

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
| `install_lovelace_card` | Put the printer card in the dashboard card picker |
| `install_morph_card` | Put the printer card in Morph's cards folder, when Morph is installed |
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
