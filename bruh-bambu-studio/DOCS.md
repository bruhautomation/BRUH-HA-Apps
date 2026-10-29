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
3. **Restart Home Assistant once.** Home Assistant loads the add-on's
   integration only when it starts, so until then there are no sensors, no
   camera, no services and no dashboard card. The **Printers** tab says so and
   has a **Restart Home Assistant** button, and Home Assistant shows a
   notification. After the restart the add-on sets the integration up by
   itself (it is under Settings → Devices & services, with a device per
   printer); the same happens after an update that changes it.

The add-on is **amd64 only**: Bambu Lab publishes Bambu Studio for Linux as an
x86-64 AppImage and nothing else.

## Adding a printer

**Settings › Printers** finds them for you (an empty Printers tab sends you
there). **Find printers** (it runs by itself the first time) lists every Bambu Lab printer
on the network Home Assistant is on, with its model, serial number and
address. Press **Add** and only the **access code** is left to type — it is on
the printer's screen in its network settings (LAN Only, or WLAN on the A1 and
P1). After **Save** the panel waits for the printer to answer and says whether
it did. A printer that is already added but has a new address offers
**Update address**, which keeps its access code. *Search a different network*
looks somewhere else, such as a separate IoT network (`192.168.2.0/24`).

The scan connects to port 8883 on each address and reads the certificate a
printer answers with — Bambu Lab's own, named for the printer's serial — so it
finds printers without broadcasts reaching the add-on and without an access
code. It covers each of Home Assistant's networks up to a /22 (a wider one is
narrowed to the /24 Home Assistant is in) and takes a few seconds.

To add one by hand, open *Add a printer by hand* and give:

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


## Files

Models and print files live in **`/share/bambu`** — reachable over Samba, from
the File Editor, from the panel's **Files** tab, and from Bambu Studio's own
Open dialog.

The Files tab lists what you brought in: uploads, imports, and what you save
from Bambu Studio into the folder. The add-on's own working files stay out of
it — the slices it makes on the way to a print (`/share/bambu/sliced`) and the
versions of designed parts (`/share/bambu/designs`). A designed part is listed
once, as its current version, with **Open design** instead of Delete. Each
file says whether it is sliced, how many plates it has, and (for sliced
files) the print time and filament weight.

- **Print** sends it to a printer. A project that is not sliced yet is sliced
  first with the settings saved in it. A bare model (an STL, a STEP, a 3MF
  from Printables) is sliced with Bambu Studio's own profiles for that
  printer, and you pick the AMS tray (or the external spool) it prints from.
- **Slice** slices a project without printing.
- **Open in Studio** opens it in the sidebar's Bambu Studio.

### Importing from a link

Paste a link into the box at the top of the Files tab and press **Import**:

- a **Printables** model page brings every model file on it (STL, 3MF, STEP)
  into `/share/bambu/imports/<model name>/`;
- a link straight to an `.stl`, `.3mf`, `.step`, `.obj` or `.amf` file
  downloads that file into `/share/bambu/imports/`.

**MakerWorld** (what Bambu Handy shares) only gives a model to a signed-in
Bambu account, so the add-on cannot fetch it for you. Open the **Studio** tab
instead, sign in on Bambu Studio's MakerWorld page, and open the model there —
it goes straight into the slicer. **Thingiverse** only gives files to apps
with a key; paste the link of the STL itself instead.

### What slices without the GUI

A **Bambu Studio project** (`.3mf` saved from Bambu Studio) carries its
printer, process and filament settings, so it slices exactly as it would in
the app. A **bare model** (`.stl`, `.step`, `.obj`) carries none, so slicing
one needs a machine and a process profile named the way Bambu Studio lists
them (`bruh_bambu.list_files` lists them under `profiles`). The machine may
also be one of your printers by the name you gave it: its **model** (set on
the Printers tab) picks the profile, never the words in its name, so a
printer called "Loft A1 mini shelf" that is an A1 slices for the A1's
256 mm bed. Every profile is handed to the slicer complete, with the bed
size its Bambu Studio family carries; a profile that does not say how big
the bed is is refused rather than sliced for a bed of the wrong size. When in doubt, open
the model in Bambu Studio, set it up, and save it as a project into
`/share/bambu`. **Print** (and `bruh_bambu.print_file`) does not need this: it
chooses the profiles itself from the printer's model and the tray's material.

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
   builds it, and shows it in a **3D view** in the colours it will print in —
   a white part is white, and a multi-colour part shows each body in its own
   colour, with a key under the view that hides or shows a body when you tap
   it. Orbit, pan and zoom (the **?** in the corner shows how, for touch and
   for a mouse), Iso / Top / Front / Right, **Measure** (tap two points for the
   distance and its X, Y, Z parts), wireframe, and the overall size. If a build
   fails, the error goes straight back to brAIn to fix (twice at most) before
   you see it.
3. Keep talking to change it. Every change that builds is a new **version**:
   the chips under the view switch between them, and *Keep working from vN*
   makes an older one the base for the next change. Nothing is overwritten.
4. **Print** offers three ways:
   - **Auto print** — brAIn chooses the printer (one that is online and
     idle), the AMS tray for every body (the material first, then the closest
     colour), and the settings, and starts the print. It asks first only when
     something it needs is missing: no idle printer, a colour or material that
     is not loaded (it says which to load), or a printer whose last print may
     still be on the plate. You can also just say *print it* in the
     conversation — brAIn starts prints from the chat, and the add-on says
     how it went there.
   - **Manual print** — choose the printer, the tray for each body, and every
     print option (below) yourself, starting from what brAIn suggests.
   - **Open in Bambu Studio** — opens that version on the Studio tab, to set
     it up and print it from Bambu Studio itself. It opens as a project with
     the settings of one of your printers (the first with its model set on the
     Printers tab), so Bambu Studio does not load it as geometry only.

   A part in several colours is several bodies that touch (a logo on a cube
   is two bodies), and each body prints from its own tray, so those colours
   need to be loaded in the AMS; the external spool holds one filament and
   suits a one-colour part. Printing uses Bambu Studio's own profiles for
   that printer and each tray's filament, puts the settings over them, slices
   with Bambu Studio's command line, uploads and starts. Set the printer's
   **model** on the Printers tab so the right profiles are chosen.

   brAIn can set every print option itself when you ask — *print it by
   object*, *four copies*, *ironing on top*, *on the textured plate* — and
   designs around the printer: it keeps parts inside the printer's build
   volume (and splits one that is too big), lays out copies, and keeps a
   second colour to a few layers because every colour change purges
   filament, saying roughly what a wasteful choice costs. It says its plan
   before it prints, and the conversation shows the sliced time and filament
   (per colour) and when the print starts.

Every part lives in `/share/bambu/designs/<part>/` — its conversation, each
version's `design.py`, STEP, 3MF and STL — so you can open the STEP in
Onshape or Fusion, or the 3MF in Bambu Studio, and come back to the
conversation days later from the parts list: it resumes the same brAIn
conversation (which also appears in brAIn's own chat list).

brAIn answers design requests with reading tools only; it never writes files
or runs anything itself. The add-on runs the script it writes in a separate
process with no Home Assistant token and a time limit, after checking it
imports nothing but CadQuery, cadkit, math and numpy.

## The Printers tab

Each printer is one card:

- **Camera.** The printer's own camera, over your network. A P1 or A1 sends
  pictures on port 6000; an X1, P2S or H2 streams RTSPS on port 322 and only
  with **LAN mode live view** switched on in the printer's own settings (the
  card says so when it is off). The camera runs while somebody is looking and
  stops a little after. Buttons on the picture switch the chamber light,
  pause the camera, and show it full screen.
- **The print.** State and stage (levelling, heating, changing filament…),
  a progress ring, time left and the clock time it finishes, the layer, and
  the picture of the job when it was sent from here. Pause/Resume and Stop
  (press twice) beside it, and the speed under it.
- **A finished print** stays on the card until its part is off the plate:
  the add-on notices the plate being cleared by itself (see *Plate clear*
  below), or press **Plate is clear**. The printer then says *Ready*.
- **Readings.** Nozzle, bed and chamber temperatures and the fans.
- **AMS.** Every tray as a spool showing its colour, material, name and how
  much is left, the one feeding the nozzle marked *in use*, the AMS humidity
  (4 or 5 of 5 is worth drying), and the spool on the holder. Press a tray to
  have the AMS read its tag again.
- **⋯** holds **Refresh** (asks the printer for a full report, after changing
  a spool), **Reconnect** (drops the connection and opens a new one) and
  **Remove printer**.
- **Printer messages** link each HMS code to Bambu Lab's page about it.
- **On the printer** lists the print jobs on its storage, newest first, with
  their size and date, to print again or (from **⋯**) delete.

While Home Assistant owes a restart to load the integration, a banner at the
top of the tab offers it.

## Settings

Everything set once, out of the way of the printers:

- **Printers** — the printers added, **Find printers** and *Add a printer by hand*.
- **Print failure detection** — where alerts go, and for each printer: on or
  off, *Warn and pause* or *Only warn*, the sensitivity, the chamber light, and
  *Notice when the plate is cleared*.
- **brAIn** — the model a design conversation runs on and the one print
  checks run on (*brAIn's choice* leaves it to brAIn's own plan; Haiku is the
  cheapest, Opus the most capable), and your standing instructions:
  *Designing* is added to every Design conversation (units, wall thickness,
  fillets, screw clearances…) and *Printing* is followed whenever brAIn picks
  print settings or starts a print with Auto print (plate, layer height,
  walls, infill, brims, materials…). What you say in a conversation still
  wins. *brAIn's built-in design instructions* shows what they are added to.
- **3D view** — *Invert vertical drag* (on by default: dragging down raises
  the view; off, dragging down lowers it as Fusion 360 does). Remembered on
  this browser.
- **Home Assistant** — whether the integration is set up, the restart when one
  is owed, and how to add the dashboard cards.

## Print failure detection

Turn on **Failure detection** on a printer's card on the Printers tab (its
**i** says when it looks and how it copes with a moving bed).
While that printer prints, the add-on watches its camera and brAIn looks at
the print at the moments it is most likely to go wrong.

**Where it looks.** When a print starts, its G-code is read (from the library
when the print was sent from here, from the printer's storage otherwise), and
the looks are planned layer by layer:

- the first layer, once it is down — most failed prints fail here;
- a couple of millimetres up, where a part that is going to come loose has;
- the layer where the part narrows sharply (a wide base becoming a thin column);
- the first bridges and overhangs, and where supports start;
- a colour or filament change;
- the height where a part gets tall for its base and could wobble or be knocked over;
- the last layers;
- and one routine look in any long stretch with nothing else planned.

Relaxed plans 5 looks a print, Balanced 8 and Careful 13, never two within a
few minutes. The card shows the plan as dots along the print's layers, from
layer 1 to the last, with *Now* at the layer it is on and a key under it:
hollow is planned, green looked fine, amber a doubt, red a failure, dashed
missed. Press a dot for what that look is for; the next one is said under
the line. "3 of 8 planned looks done · 2 extra" counts the extra looks a
doubt or a sudden change asked for too. When the file cannot be read the
looks are spread by layer instead, and the card says so.

**A moving bed.** The bed and the toolhead move while it prints (an A1's bed
slides front to back, every bed drops at each layer), so one frame is often a
smear. A look takes a burst of four frames about a second apart and sends
brAIn the sharpest, and brAIn is told a smear or a moved plate is not a
failure. A look it still cannot judge is never a failure; it looks again
later. The chamber light on gives the sharpest pictures.

**What brAIn is shown.** The camera now, Bambu Studio's picture of the
finished plate (what the print should become), and the frame from its last
look, with the layer, the height the part should have reached and why this
moment was chosen. Its run is read-only.

**What happens.**

- *Looks fine* — nothing.
- *Unsure* — nobody is told; brAIn looks again a few minutes later.
- *Warning* (something looks wrong but the print may still be fine) — you are
  told, with **Ignore** (no more warnings about that problem for the rest of
  the print) and **Pause print**. It looks again soon, and closes the warning
  itself if the print looks fine.
- *Failure* (spaghetti, a part come loose or knocked over, a blob on the
  nozzle, nothing coming out) — the printer is **paused** and you are told,
  with **Resume — not a failure** (the same problem then only warns for the
  rest of the print) and **Stop print**. With *Only warn* chosen it is never
  paused. Stringing and warping only ever warn.

**Free checks, all the time.** These need no brAIn and cost nothing:

- **A covered lens or a dark chamber.** A flat picture, or a black one with
  the chamber light on, is a covered lens; a black one with the light off is a
  dark chamber. Either way nothing is checked until it can see again, and the
  card says why. *Turn the chamber light on to see* (on by default) turns the
  light on once per print when it is dark.
- **A frozen camera** — a picture that has stopped changing is not judged.
- **A sudden change on the plate** — the toolhead is taken out of the picture
  and a jump far beyond this print's usual change asks brAIn to look now.
- **The printer's own camera** — an HMS message from the printer's camera
  asks brAIn to look now; without brAIn it is raised as a warning.

Without brAIn the free checks still run and the card says *Watching (basic)*.
brAIn's own pause and usage budget apply to every look nobody pressed for;
**Check now** always asks.

**Plate clear.** Only once a print has finished, and even with failure
detection off, it watches (a picture a minute or so, for up to 12 hours) for
the plate being cleared: it compares the plate with an empty plate it has
seen before — the one before the first layer, or the plate as it was the last
time it was cleared — or, with none known yet, asks brAIn once when the plate
changes. Once clear, the finished print leaves the card. **Plate is clear** on
the card says so by hand. *Notice when the plate is cleared* (Settings) turns
this off.

**Alerts.** Every warning and failure is a Home Assistant notification and a
`bruh_bambu_print_alert` event. Choose a phone under **Settings › Print
failure detection › Alerts go to** and it is also sent to the phone, with the frame brAIn judged
and buttons that answer it. An alert that is answered or clears takes its
notification with it.

## Print options

Every way of printing offers the same options, from one list: the **Print**
dialog on the Files tab, **Manual print** for a designed part, the
`print_file` service, and brAIn in the conversation.

- **When it starts:** the build plate on the printer (textured PEI, smooth
  PEI, cool, engineering, or whatever is on it), the speed, bed levelling,
  flow calibration, vibration compensation, first-layer inspection,
  timelapse, and how many **copies** (arranged on the plate).
- **Slicer settings** (for a model sliced here): layer height and first
  layer, walls, top and bottom layers, infill and its pattern, wall generator,
  seam, ironing, supports (type, overhang angle, from the plate only), brim and
  its width, skirt, **print order** (*by object* prints each part to the end
  before the next), prime tower, flush into infill or objects, spiral vase,
  fuzzy skin and the nozzle temperature. An empty field keeps Bambu Studio's
  own profile for that printer and filament.

A file that is already sliced prints as it was sliced; more than one copy
slices it again.

## The printer card

The add-on installs one card in two places:

- **Lovelace:** add *BRUH Bambu printers* from the card picker
  (`type: custom:bruh-bambu-card`). With no options it shows every printer;
  `entity: sensor.workshop_x1c_status` shows one. `show_ams: false` and
  `show_controls: false` trim it.
- **Morph:** with Morph installed, the same card is in `/config/morph/cards`
  and is used as `type: custom:morph-bambu-printer`, in Morph's own look.

It shows the camera, the stage, progress, time left and the finish time, the
layer, temperatures and AMS trays (the one in use marked), with Pause/Resume,
Stop (press twice), speed, the chamber light, Refresh, and Reconnect when the
printer is not answering. `show_camera: false` leaves the camera out. With
print failure detection on it shows what detection is doing and, during an
alert, what brAIn saw with Ignore and Pause (or Resume and Stop);
`show_detection: false` leaves that out.

The card is in the card picker once the integration is set up (see
*Installing*); Morph picks it up within two minutes of being installed.

## Services

| Service | What it does |
|---|---|
| `bruh_bambu.get_status` | Every printer's state, progress, time left, temperatures, speed, light and AMS, plus the latest jobs |
| `bruh_bambu.list_files` | The files in `/share/bambu` |
| `bruh_bambu.printer_files` | What is on a printer's own storage |
| `bruh_bambu.print_file` | Print a file (sliced first if needed; `slot`/`material` choose the filament for a bare model; `plate_type`, `speed`, `copies` and `settings` are the print options above) |
| `bruh_bambu.slice_file` | Slice a project or model |
| `bruh_bambu.pause_print` / `resume_print` / `stop_print` | Control the current print |
| `bruh_bambu.set_speed` | silent, standard, sport or ludicrous |
| `bruh_bambu.set_light` | Chamber light on or off |
| `bruh_bambu.set_temperature` | Nozzle (up to 300 °C) or bed (up to 120 °C) target; refused while printing |
| `bruh_bambu.send_gcode` | Up to 32 lines of G-code; refused while printing |
| `bruh_bambu.open_in_studio` | Open a file in the sidebar's Bambu Studio |
| `bruh_bambu.find_printers` | The Bambu Lab printers on the network, and which are added already |
| `bruh_bambu.import_url` | Import a model from a Printables page or a file link; answers with the new files' paths |
| `bruh_bambu.refresh` | Ask a printer for a full report now |
| `bruh_bambu.reconnect` | Drop the connection to a printer and open a new one |
| `bruh_bambu.design_part` | Describe a part and brAIn designs it (or name a part in `part` and say what to change in `message`); answers as soon as brAIn has started, with the part's id and name. Needs brAIn |
| `bruh_bambu.design_status` | A designed part's latest version, whether brAIn is still on it, its last reply, whether it built and any print of it; every part when none is named |
| `bruh_bambu.print_part` | Print a designed part — the Design tab's Slice and print — on a printer, with `copies`, `slot` and print `settings` |
| `bruh_bambu.check_print` | Have brAIn look at the print now (failure detection on, the camera able to see) |
| `bruh_bambu.print_alert_action` | Answer an alert: `ignore`, `pause`, `resume` (a false alarm), `stop`; or `plate_clear` / `plate_occupied`. `alert` names the alert so an old answer is refused |
| `bruh_bambu.set_failure_detection` | Turn detection on or off for a printer, and set `mode` (pause or warn), `sensitivity` (low, medium, high), `light`, `plate` and the `notify` service alerts go to |

`printer` can be left out when there is only one printer; with two or more it
is the printer's name or serial number. Every service answers with the
add-on's reply, and a refusal ("Workshop X1C is already printing") is raised
with its reason, so it shows in the automation trace. The three design
services answer with data only (`response_variable:`), and a part is named
by its id or its name. Designing takes minutes, so `design_part` answers when
brAIn has started and `design_status` says when the version has built.

```yaml
action: bruh_bambu.print_file
data:
  file: imports/rotor.stl
  printer: Workshop X1C
  plate_type: textured_pei
  copies: 4
  settings:
    layer_height: 0.16
    walls: 4
    print_sequence: by object
```

## Sensors

Each printer gets a device with a **Camera** and six sensors: **Status** (the
printer's own word — idle, prepare, running, pause, finish, failed — with
everything else as attributes, and *offline* when it is not reporting),
**Stage** (what it is doing inside that: levelling, heating, changing
filament…), **Progress**, **Time left**, **Nozzle temperature** and **Bed
temperature**.

With print failure detection on, the device also has **Failure detection**
(off, idle, watching, looking, basic, warning, failure, covered, dark, frozen,
no_camera — with the last look, the next one and any open alert as
attributes), **Print problem** (on while an alert is open; `level` says
warning or failure), **Plate clear**, **Camera covered**, and a **Last print
check** camera showing the frame brAIn last judged.

```yaml
# Flash the office light when a print has a problem.
triggers:
  - trigger: state
    entity_id: binary_sensor.workshop_x1c_print_problem
    to: "on"
actions:
  - action: light.turn_on
    target: { entity_id: light.office }
    data: { flash: long }
```

## brAIn

With brAIn installed, its tools `bambu_status`, `bambu_print`,
`bambu_control` and `bambu_slice` drive the printers through the services
above, so "how long is left on the print?", "pause the printer" and "print the
benchy on the X1C" work from the chat, the terminal and voice. A voice agent
may check on a print, pause, resume, change the speed and the light; starting
or stopping a print, slicing and raw G-code are refused by voice, because a
misheard sentence there is filament and hours.

The design services are how brAIn designs and prints a part from anywhere
it is asked — "design a 4 cm wall hook and print it" — through the same
Design tab conversation and the same Slice and print, so the part, its
versions and its print are on the Design tab afterwards.

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

- **No sensors, services or card in Home Assistant.** Restart Home Assistant
  once (the Printers tab and Settings have the button). The add-on sets the integration up
  by itself after that.
- **The camera says it was refused.** On an X1, P2S or H2, switch on LAN mode
  live view in the printer's settings. On a P1 or A1, check LAN mode is on.
- **A slice fails with "the file carries a setting value it rejects".** The
  message now ends with the setting Bambu Studio named; please report it.

- **The Studio tab stays black or says Bambu Studio closed.** Its last output
  is under *What it last printed* on that tab. The slicer draws with software
  OpenGL, so a large model's 3D view is slow; slicing is unaffected.
- **"The printer refused the access code."** The code changes when LAN mode is
  switched off and on; read it from the printer again.
- **Commands do nothing.** Switch on LAN-only mode and Developer mode on the
  printer.
- **"The printer refused the command" / HMS 0500-0500-0001-0007.** Firmware with
  Bambu's authorization refuses commands from Home Assistant unless Developer
  Mode is on (Settings › LAN only mode › Developer mode). The printer's own
  message says to update Bambu Studio or Bambu Handy; that does not apply here.
