# Changelog

## 0.2.2

### Fixed

- **Printed designs get the printer's start and filament-change G-code.** Bambu Studio 2.x printer profiles keep their start, end and filament-change G-code in template files they include by name, and the profiles brAIn's designs were sliced with left those out for every printer model. They are now merged in, and a profile whose template is missing is refused with its name rather than sliced without its start-up G-code. (#328)
- **When Bambu Studio refuses to slice a design, you see why.** The message used to end at "run found error, return -2, exit…", which is Bambu Studio signing off, not the reason. The design conversation and the jobs list now show Bambu Studio's own error lines in full, every exit code the slicer can return is explained in plain words, and an "invalid parameters" refusal says which check failed (a plate number, the filament count, the nozzle mapping) and what to change. (#328)

## 0.2.1

### Fixed

- **A print never stops on settings Bambu Studio refuses.** 100 % infill in a grid (or gyroid, cubic, honeycomb…) pattern ended *grid doesn't work at 100% density*: Bambu Studio fills a solid part only with rectilinear, concentric or aligned rectilinear lines. Before every slice the settings are now checked against Bambu Studio's own rules, the profile's defaults included, and fixed where they disagree (100 % infill prints rectilinear; a spiral vase gets one wall, no infill, no top and no supports). The conversation says what was changed, and brAIn is told the rules so it does not ask for them. The error that did reach you showed `100%%`; it shows `100%` now.
- **Open in Bambu Studio opens the part as a project.** Bambu Studio loaded a designed part as geometry only, warning *The 3mf file has invalid config*, because the file named no printer. It now opens a copy that carries the printer's, process and filament settings for one of your printers (with the part's settings and one filament per colour), so the plate, the colours and the settings are there when it opens. Set a printer's model on the Printers tab for this.
- **brAIn's replies in the design conversation render as rich text.** Bold, italics, code, lists and headings show as formatting instead of asterisks and dashes.
- **The camera no longer flashes.** The printer card and the dashboard card blanked the picture while each new frame loaded, every second or two. A frame is now decoded before it replaces the one on screen, and a frame that fails to arrive leaves the last picture up.

## 0.2.0

### Added

- **The printer card shows the printer's camera.** Live, over your network: a P1 or A1 sends pictures on port 6000, an X1, P2S or H2 streams RTSPS on port 322 (switch on *LAN mode live view* on the printer). Light, pause and full-screen buttons sit on the picture, and Home Assistant gets a **Camera** entity per printer that the dashboard card shows too.
- **The printer card was redesigned.** The state and what the printer is doing inside it (levelling, heating, changing filament…), a progress ring, time left and the clock time it finishes, the picture of the job, temperature and fan tiles, and the AMS as spools: colour, material, filament name, how much is left, the tray **in use**, and the AMS humidity. The spool on the holder is shown as well. Each printer message (HMS code) links to Bambu Lab's page about it.
- **Refresh and Reconnect.** **Refresh** asks the printer for a full report, for after you change a spool; pressing a tray has the AMS read its tag again. **Reconnect** drops the connection and opens a new one. Both are also the `bruh_bambu.refresh` and `bruh_bambu.reconnect` services.
- **What is on the printer, with pictures.** *On the printer* lists the print jobs on its storage with each one's picture (read out of the file where it lies), to print again or delete.
- **Pictures in the Files tab.** A sliced 3MF shows its own plate picture; an STL, STEP or plain 3MF is drawn once and kept. Each row also shows its filament colours and grams, its time and its plates.
- **Every common print option, everywhere you print.** Build plate type, speed, bed levelling, flow and vibration calibration, first-layer inspection, timelapse and copies, plus the slicer settings: layer height, first layer, walls, top and bottom layers, infill and its pattern, wall generator, seam, ironing, supports (type, angle, from the plate only), brim and its width, skirt, **print by object**, prime tower, flush into infill or objects, spiral vase, fuzzy skin and nozzle temperature. They are offered in the Files tab's Print dialog, in **Manual print**, in `bruh_bambu.print_file` (`plate_type`, `speed`, `copies`, `settings`), and to brAIn in the conversation, all from one list.
- **brAIn designs for the printer and keeps you in the loop.** It knows each printer's build volume and nozzle, splits a part that does not fit, lays out copies and print-by-object jobs, and keeps a second colour to a few layers because every colour change purges filament (it says roughly what a wasteful design costs). It states its plan before it prints, sees which printers are busy and when they finish, and warns about a damp AMS. The conversation now shows the sliced time and filament per colour, then when the print started.
- **A Stage sensor** per printer, and the status sensor's attributes now include the stage, the AMS units, the tray in use, the spool holder, the fans and the HMS codes.

### Fixed

- **The integration, the sensors and the cards appear without hunting for them.** Home Assistant loads the integration only when it starts, and nothing said so. The Printers tab now has a **Home Assistant** card that says whether the integration is set up and offers **Restart Home Assistant** when it is not loaded yet; Home Assistant shows a notification too. After the restart the add-on sets the integration up by itself. The card says how to add the dashboard card, and Morph gets its card within two minutes of being installed (it used to wait for an add-on restart).
- **A slice that Bambu Studio rejects names the setting.** A two-colour print stopped with *the file carries a setting value it rejects* and nothing else. The message now ends with the setting and the reason Bambu Studio printed.
- **The Print choices line up.** The three cards under **Print** had their text centred by the button, so a short one sat indented; they are left-aligned cards with icons now, with Auto print marked as recommended.

## 0.1.6

### Fixed

- **Bambu Studio no longer closes when a print starts.** Its built-in web pages (the print and device dialogs are pages) asked the graphics card for their buffers, the container may not open `/dev/dri/card0` (*libEGL warning: failed to open /dev/dri/card0: Permission denied*), and the page's process died and took Bambu Studio with it. They draw in software now.
- **A print from the panel slices on its own.** The headless slice behind Auto print, Manual print and the conversation keeps its own Bambu Studio settings folder, so it no longer writes to the one the window in the sidebar has open. On a machine short of memory, the window is closed while the slice runs and opens again, on the same file, when it ends; the Studio tab says so meanwhile. Printing stays on your network: the slice runs here, the file goes to the printer over FTPS and the print starts over MQTT, with no Bambu cloud involved.
- **A slice that was killed says so.** A slice ended by running out of memory or by a crash now names that, instead of only an exit number.

## 0.1.5

### Fixed

- **Designed parts slice again.** Every print of a designed part, from Auto print, Manual print or the conversation, stopped with *Bambu Studio could not slice it (exit 239): run found error, return -17*. The slicer settings brAIn hands Bambu Studio did not say which of Bambu Studio's own printer and process profiles they came from, so its command line could not tell that the process suits the printer and refused it. They name it now.
- **A failed slice says why in words.** The panel reads Bambu Studio's exit code (*the process profile does not list this printer as compatible*, *part of the model is over the edge of the bed*, and others) instead of quoting its log line.

## 0.1.4

### Added

- **brAIn starts the print from the conversation.** Say *print it* (or press **Auto print**) and brAIn picks the printer, the AMS tray for every body and the settings, and starts the print; the conversation says how it went. It asks first only when something it needs is missing: no idle printer, a colour or material that is not loaded, or a printer whose last print may still be on the plate. It used to answer that it could not start a print and send you to the Print button.
- **Print offers three ways.** **Auto print** hands it all to brAIn, **Manual print** is the print dialog, and **Open in Bambu Studio** opens that version on the Studio tab to set up and print there.
- **Multi-colour parts print in their colours.** Each body of a designed part now prints from its own AMS tray: the design's 3MF names a filament per body, and the print dialog picks a tray for each body by colour (and says which colour is not loaded).

### Changed

- **A designed part's 3MF is one object with a part per body.** Bambu Studio arranged each body as its own object, so a print-in-place part could come apart on the plate. Versions built before 0.1.4 still print, in one filament.

## 0.1.3

### Added

- **Find printers on your network.** The Printers tab looks for Bambu Lab printers on the network Home Assistant is on (and does so by itself the first time it is empty), listing each one's model, serial and address. **Add** fills in everything but the access code, and after **Save** the panel says whether the printer answered. A printer that has moved to a new address offers **Update address**, keeping its access code. `bruh_bambu.find_printers` does the same from an automation. It reads the certificate each printer's MQTT port answers with, so it works without broadcasts reaching the add-on.

### Fixed

- **Bambu Studio no longer stops on "Switching language failed".** The image had no locales, so Bambu Studio could not switch to English (or any other language) and, on a first start, closed. It now has a locale for every language Bambu Studio ships, and starts in English.

## 0.1.2

### Added

- **Import a model from a link.** The Files tab has a box for a link: a Printables model page brings every model file on it into `/share/bambu/imports`, and a link to an `.stl`, `.3mf`, `.step`, `.obj` or `.amf` file downloads it. `bruh_bambu.import_url` does the same from an automation. MakerWorld (what Bambu Handy shares) needs a signed-in Bambu account, so it says to open the model from Bambu Studio's MakerWorld page on the Studio tab instead.
- **Bare models print.** An STL, a STEP or a 3MF from Printables is sliced with Bambu Studio's own profiles for the printer, and the print dialog asks which AMS tray (or the external spool) to use. `print_file` takes `slot`, `material` and `colour` for the same; with no tray named it picks the best-matching one.
- **The 3D view shows the part in its colours.** brAIn now gives every body the colour it prints in, and the view draws it that way: a white part is white, a multi-colour part shows each colour, and older versions use the colour brAIn suggested for printing. A key under the view hides or shows a body when you tap it.
- **How to move the 3D view.** A **?** in the corner of the view explains the touch gestures on a phone and the mouse controls on a computer. It opens by itself the first time.

### Changed

- **The Files tab lists what you brought in.** The add-on's own slices and every version of a designed part are no longer in it; a designed part is listed once, as its current version, with **Open design**, and its Print opens the design's own print dialog.
- **A missing library is named, not restarted.** Before starting Bambu Studio the add-on checks every library it needs. If the image lacks one, the Studio tab lists which ones and says to update the add-on or pin an older Bambu Studio, instead of starting a slicer that stops on its first line, over and over.

### Fixed

- **Bambu Studio 2.x starts.** It links WebKitGTK 4.1 and the image only had 4.0, so it stopped on start with `libwebkit2gtk-4.1.so.0: cannot open shared object file`. The image now has both, plus the other system libraries Bambu Studio's Linux build links.

## 0.1.1

### Fixed

- **The add-on image builds.** The CAD tools Design with brAIn uses were pinned to a release of networkx that needs Python 3.12, and the add-on runs Python 3.11, so the image could not be built and 0.1.0 could not be installed. They are pinned to versions that install on 3.11.
- **The panel starts.** It used an aiohttp feature newer than the aiohttp in the add-on's image, so once the image did build, the panel would have stopped on its first line. It now runs on the image's own version.

## 0.1.0

### Added

- **Bambu Studio in the sidebar.** The add-on downloads Bambu Lab's own Linux build of Bambu Studio on first start, keeps it in `/data`, and runs it on a virtual screen you use from the Home Assistant sidebar through noVNC. It is started again if its window is closed. The version is the latest release unless you pin one.
- **Your Bambu Lab printers, in Home Assistant.** Add a printer by IP address, serial number and access code. The add-on keeps a LAN connection to it (MQTT on port 8883) and shows its state, progress, time left, temperatures, speed, chamber light and AMS trays.
- **Printing from anywhere.** Print a file from `/share/bambu` on any printer: a project that is not sliced yet is sliced first with Bambu Studio's own command line, uploaded to the printer over FTPS, and started. Pause, resume, stop, speed, chamber light, nozzle and bed temperatures, homing and G-code are all a press on the panel or a service call.
- **The `bruh_bambu` integration**: `print_file`, `slice_file`, `pause_print`, `resume_print`, `stop_print`, `set_speed`, `set_light`, `set_temperature`, `send_gcode`, `open_in_studio`, and three reads (`get_status`, `list_files`, `printer_files`), each answering with the add-on's reply and raising with its reason on a refusal. Five sensors per printer: status, progress, time left, nozzle and bed temperature.
- **Design parts with brAIn** (optional, needs brAIn with its Automation integration on). A Design tab: describe a part, and brAIn writes it as a parametric CadQuery script that the add-on checks and builds into STEP, 3MF and STL; a 3D view with orbit, view presets, measuring and wireframe; a version for every change that builds, and any version can be the base for the next; build failures go back to brAIn to fix before you see them; a parts list you can reopen to carry on the same conversation; and **Print**, which shows brAIn's recommended material, colour and slicing settings (editable), picks the best-matching AMS tray, chooses Bambu Studio's own profiles for the printer, slices and starts.
- **A printer card for Lovelace and for Morph** (`custom:bruh-bambu-card`, `custom:morph-bambu-printer`): progress, time left and finish time, layer, temperatures and AMS, with pause, resume, two-press stop, speed and light.
- **brAIn can run the printers** through those services (its `bambu_status`, `bambu_print`, `bambu_control` and `bambu_slice` tools).
