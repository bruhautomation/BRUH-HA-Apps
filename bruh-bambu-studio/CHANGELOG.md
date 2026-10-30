# Changelog

## 0.4.3

### Changed

- **An update asks for a restart only when it needs one.** The panel compares the integration code Home Assistant loaded with what was just installed, so a version-only update shows no restart banner or notification, and the printer card follows its own file so a card change needs only a page reload. The first update with this change still asks once. The card's retry also now runs on Home Assistant's event loop, where it belongs.

## 0.4.2

### Fixed

- **Restart Home Assistant no longer says it failed while Home Assistant is restarting.** Home Assistant often stops before it answers the restart request, and the panel read that silence as an error after 15 seconds; it now says Home Assistant is restarting, and says it failed only when the request never reached Home Assistant (#550).

## 0.4.1

### Changed

- **The version is one line under the 3D view** — which version, its size, its weight and how many warnings — and what changed, the warnings, the dimensions and the other versions open from it. It stays open or closed as you left it. The "Overall" size line under the view is gone (the size is in that line).
- **More room for the conversation on a phone.** The body pills share the view tools' row, the view is a little shorter, and the message box starts one line tall and grows as you type.

### Fixed

- **Failure detection's i stays open** until its ✕, the i again or Escape: the printer card's redraw every four seconds was closing it. It also fits the window — on a phone it sits inside the screen, and a long explanation scrolls inside itself.

## 0.4.0

### Added

- **A Settings tab.** The printers you added, **Find printers** and *Add a printer by hand*, print failure detection's settings for each printer and where its alerts go, brAIn's model and your standing instructions, the 3D view's drag direction, and the Home Assistant card all live there now, out of the way of the printers. While Home Assistant owes a restart, a banner on the Printers tab still offers it.
- **Choose brAIn's model.** One for Design conversations and one for print checks (*brAIn's choice*, Haiku, Sonnet, Opus or Fable).
- **Your standing instructions for brAIn.** *Designing* is added to every Design conversation (units, wall thickness, fillets, screw clearances…) and *Printing* is followed whenever brAIn picks print settings or starts a print (plate, layers, walls, infill, brims, materials…). What you say in a conversation still wins, and the built-in instructions they add to can be read underneath.
- **The plate is watched after a print, even with failure detection off.** Only once a print has finished (nothing is looked at while it runs), a picture a minute or so says when the part has been taken off, and the finished print leaves the card: the printer says *Ready*. **Plate is clear** says so by hand, and that plate is kept as the empty plate the next finish is compared with, so later prints clear by themselves without asking brAIn.
- **An i on failure detection** says when brAIn looks (the moments in the G-code, sudden changes, after a doubt, Check now, the finish), what the free checks between looks do, and how it copes with a moving bed.
- **↓ Latest** in a Design conversation scrolled up, back to the newest message.
- **Home Assistant's Plate clear sensor works with failure detection off**, since the plate watch now does.

### Changed

- **One header row.** On a phone the panel's name is dropped (Home Assistant's own bar already says it) and the five tabs share one row with their icons, so there is no second header under Home Assistant's.
- **A cleaner, denser layout throughout.** Quieter filled buttons, one spacing and radius scale, Refresh, Reconnect and Remove in the printer's **⋯** menu, Pause and Stop beside the print, the speed as a select, smaller readings, and each file in the library one row with **Print** and a **⋯** for the rest.
- **Where it looks reads as a timeline.** Layer 1 to the last layer, *Now* at the layer it is on, a key (planned, looked fine, doubt, failure, missed), and the next look said under it. A dot says what it is for when pressed. "11/8 looks" is now "3 of 8 planned looks done · 8 extra", which is what it counted.
- **On the printer is a list, newest first**, with each job's date and size and **Print**; its pictures, which rarely arrived, are gone. The first eight are shown, and the rest on **Show all**.
- **The Design tab fits the window.** On a desktop the view and the conversation are side by side at the window's height; on a phone the part fills the screen under the bar, the conversation scrolls inside itself under the 3D view, and **▾** folds the view away for a long conversation. 3MF, STEP and Delete are in the part's **⋯**. The versions row shows once there are two.
- **Invert vertical drag is the default** (dragging down raises the view). Turn it off in Settings › 3D view for Fusion 360's way.

### Fixed

- **A look is no longer a picture of a moving bed.** Each look takes four frames about a second apart and brAIn is shown the sharpest; brAIn is also told that a smear or a plate that has moved is not a failure.
- **A part's age no longer reads "20756 days ago"** when it has no time.

## 0.3.3

### Added

- **Measure snaps the way Fusion's does.** Near a corner, the middle of an edge, an edge, the centre of a flat face or a face, the pick takes that point, and a marker says which. The distance is drawn on the line at its middle, the ΔX, ΔY and ΔZ legs are dashed in the axes' colours and listed under the view, a face beside a point gives the distance square to the face, and two faces or two edges give the angle between them. The last five measurements stay listed until **Clear**; Escape starts the current one again. On a phone a tap snaps from a little further away.
- **Change a body's colour from its dot.** The dot on a body's pill under the 3D view offers the AMS trays' colours first, then any colour, and **Back to brAIn's colour**. The colour is saved on the part and is what that body prints in: Print starts from the tray closest to it, Open in Bambu Studio names it, and brAIn is told it on the next message (it stands down once brAIn writes a colour of its own for that body). The name still hides or shows the body.
- **Invert vertical drag**, in the 3D view's **?**, puts the vertical turn back the old way round. It is remembered on this browser.

### Changed

- **Dragging down lowers the view**, and dragging up raises it, as Fusion 360's turn does by default. One finger on a phone moves the same way.

### Fixed

- **The body pills and the measurements are on screen in full screen**, with the view, rather than left behind under it.

## 0.3.2

### Added

- **The 3D view moves the way Fusion 360's does.** Drag (or Shift + middle-drag) turns the part about the point you grab, middle-drag or right-drag slides it, the wheel zooms toward the pointer rather than the middle, and a double-click puts a point in the middle. On a phone one finger turns, two fingers slide and a pinch zooms toward your fingers. The view keeps Z up and never flips over the top, and the part sits on a bed that reads like the printer's.
- **Home and named views that move rather than jump.** Home goes back to the corner view with the whole part in sight, and Top, Front, Right and Iso turn to that side, each framing the whole part.
- **A bigger 3D view.** **Full screen** fills the screen with the view and its tools (it fills the window where Home Assistant's frame refuses full screen), and Escape or **‹ Leave full screen** leaves. On a desktop the view starts taller and its bottom edge drags to make it taller still.

### Changed

- **The dashboard card is compact.** Each printer is its name and state on one line, the camera, the progress with the time left, failure detection's line (or its alert with the buttons that answer it), the temperatures and Pause or Resume. Stop, speed, the light, Refresh, Reconnect and the AMS trays are behind the printer's ⋯, which opens in the card. A printing printer with an open alert is about 400 px tall, down from about 560.
- **The printer card on the Printers tab is laid out by what matters now.** The name and Refresh/Reconnect across the top, then the camera, the job and its controls, the temperatures and the filament, with failure detection and the printer's storage beside them on a wide screen. Removing a printer is in the card's ⋯ menu rather than a ✕ beside Refresh. The speed is shown once (its switch), the stage once (in the job), and an AMS's four trays fit on one row on a phone.
- The Design tab says a version's size once, and the 3MF and STEP downloads look like the buttons beside them.

### Fixed

- **No green bar through the camera.** The progress line drawn along the bottom of the camera picture is gone (the progress ring says it), a frame cut short is never shown (the last whole one stays), and a camera that encodes 1080 rows as 1088 no longer shows the eight extra rows as a green band along the bottom.
- **The camera picture fits its box.** The box takes the stream's own shape (16:9, 4:3) instead of a fixed 16:9, so nothing is letterboxed, stretched or cropped.
- **Files on the printer show their pictures.** The pictures were read all at once, and a printer serves one storage session well, so most failed and were shown as "3MF" for good. They are now read one at a time, a read that fails is tried again, a read cut short is never remembered as "no picture", a printer that never answers the end of a read no longer stalls the next one, and pictures remembered as missing by an earlier version are read again. A file with no picture shows a quiet plate, not a word.
- **An A1's AMS Lite reports no humidity.** The AMS Lite is open to the room and has no humidity or temperature sensor, but the printer's report still carries a number for it, which showed as a humidity chip on the Printers tab, a reading in Home Assistant and a figure brAIn was told. A1 and A1 mini (and any AMS the report itself calls an AMS Lite) now report none; a real AMS on an X1, P1 or H2 keeps its humidity and temperature.

## 0.3.1

### Fixed

- **A bare model sliced for an A1 is sliced for the A1's 256 mm bed.** Slicing an STL with a printer profile named directly handed Bambu Studio the profile without the family settings it builds on, so the bed size never arrived: the slice used a 200 mm bed, moved the part to its middle and refused anything wider. Profiles are now handed over complete, a printer can be named by the name you gave it (its model chooses the profile, not the words in its name), and a profile that does not say how big the bed is is refused, naming the printer. (#430)

## 0.3.0

### Added

- **Print failure detection.** A switch on each printer's card on the Printers tab. While a print runs, brAIn looks at the camera at the moments a print is most likely to fail and compares what it sees with Bambu Studio's picture of the finished plate and with its previous look. When something may be wrong it tells you, with **Ignore** and **Pause print**; when the print has clearly failed (spaghetti, a part come loose, a blob on the nozzle, nothing coming out) it pauses the printer and tells you, with **Resume — not a failure** and **Stop print**. Choose *Only warn* if it should never pause, and Relaxed, Balanced or Careful for how often it looks and how sure it must be.
- **It looks where prints fail, not every few seconds.** The print's own G-code is read when it starts, and the looks are planned for the first layer, a few millimetres up, the layer where the part narrows sharply, the first bridges and overhangs, supports, a colour change, a part getting tall and thin, the last layers, and once in any long stretch with nothing else. A print of 8 looks on Balanced; anything doubtful gets a second look a few minutes later, and a doubt the second look clears closes itself. The card shows the plan as dots along the print's layers.
- **Free checks run all the time, without brAIn:** a covered lens or a dark chamber (everything stands down and says so, and the chamber light can be turned on to see), a camera picture that has stopped changing, a sudden change on the plate (which asks brAIn to look now), and the printer's own camera alerts.
- **Plate clear.** After a print it watches for the plate being cleared, comparing it with the empty plate it saw before the first layer, or asking brAIn once when it changes. **It's clear** on the card says so by hand.
- **In Home Assistant:** per printer a **Failure detection** sensor, **Print problem**, **Plate clear** and **Camera covered** binary sensors, and a **Last print check** camera with the frame brAIn judged. A notification goes to Home Assistant and, if you choose a phone in the detection settings, to the phone with the picture and the buttons that answer it. Services `bruh_bambu.check_print`, `print_alert_action` and `set_failure_detection`, and a `bruh_bambu_print_alert` event. The dashboard card shows detection too.
- brAIn's looks need **brAIn 3.8.8 or later**, which hands it the pictures; with an older brAIn the free checks run and brAIn's looks answer that they could not see.

### Fixed

- **Downloaded 3MF and STEP files have their names.** A part downloaded from the Design tab was saved as `file` with no extension; it is now saved as the part's name, its version and its kind, such as `Wall hook v3.3mf`.

## 0.2.6

### Added

- **Design and print a part from Home Assistant.** Three new services, `bruh_bambu.design_part` (a new part from a description, or a change to one), `bruh_bambu.design_status` (how a part is doing: built, still working, brAIn's reply, any print) and `bruh_bambu.print_part` (print a part on a printer), run the Design tab's own conversation and its own Slice and print. brAIn's chat and voice use them to make a part and send it to the printer when asked. Without brAIn, `design_part` says brAIn is needed. (#375)

### Fixed

- **Starting a design without brAIn no longer leaves an empty part behind.** The Design tab now checks for brAIn before it makes the part.

## 0.2.5

### Added

- **Bambu Studio works on a phone.** On a touch screen the Studio tab has controls like a remote desktop app: tap to click, hold to right-click, two fingers to zoom and move around. A toolbar switches one finger between moving the view, dragging (for sliders and the 3D view) and scrolling, Fit goes back to the whole screen, and Keyboard opens the phone's keyboard with Backspace and Enter beside it. With a mouse the tab is unchanged. (#374)

## 0.2.4

### Changed

- **A print starts without asking whether the plate is clear.** A printer that is idle, finished or failed is taken to be ready, and brAIn starts on it straight away. A printer that is printing or paused is still refused, and the refusal says which. (#371)

### Fixed

- **Printing more than one copy works.** Asking for two or more copies of a designed part failed with "can not set repetitions when slice all". Bambu Studio only repeats a plate for its own project files, so copies of anything else are now laid out as copies on the plate before slicing, and arranged by Bambu Studio. A print-in-place part stays in one piece. (#367, #328)
- **A command the printer refuses is reported as refused.** Printers with Bambu's newer authorization firmware turn down commands unless Developer Mode is on, and raise "MQTT Command verification failed, please update Studio or Handy". The add-on used to report those commands as done. It now says the printer refused, and that Developer Mode needs turning on under Settings › LAN only mode › Developer mode on the printer. The Printers tab and the status sensor explain the code too, and say that updating Bambu Studio will not help. (#368)

## 0.2.3

### Fixed

- **Printed designs get the printer's start and filament-change G-code.** Bambu Studio 2.x printer profiles keep their start, end and filament-change G-code in template files they include by name, and the profiles brAIn's designs were sliced with left those out for every printer model. They are now merged in, and a profile whose template is missing is refused with its name rather than sliced without its start-up G-code. (#328)
- **When Bambu Studio refuses to slice a design, you see why.** The message used to end at "run found error, return -2, exit…", which is Bambu Studio signing off, not the reason. The design conversation and the jobs list now show Bambu Studio's own error lines in full, every exit code the slicer can return is explained in plain words, and an "invalid parameters" refusal says which check failed (a plate number, the filament count, the nozzle mapping) and what to change. (#328)

## 0.2.2

### Fixed

- **The printer card's camera no longer flickers between frames.** 0.2.1 decoded each frame off screen and then gave its address to the picture on show, which still left that picture empty for a moment while it loaded. Each frame now loads into a second picture behind the one on screen, and the two change places only once it is ready, so the picture you see is never part-way through loading.

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
