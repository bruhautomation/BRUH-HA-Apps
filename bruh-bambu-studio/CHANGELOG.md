# Changelog

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
