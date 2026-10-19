# Changelog

## 0.1.0

### Added

- **Bambu Studio in the sidebar.** The add-on downloads Bambu Lab's own Linux build of Bambu Studio on first start, keeps it in `/data`, and runs it on a virtual screen you use from the Home Assistant sidebar through noVNC. It is started again if its window is closed. The version is the latest release unless you pin one.
- **Your Bambu Lab printers, in Home Assistant.** Add a printer by IP address, serial number and access code. The add-on keeps a LAN connection to it (MQTT on port 8883) and shows its state, progress, time left, temperatures, speed, chamber light and AMS trays.
- **Printing from anywhere.** Print a file from `/share/bambu` on any printer: a project that is not sliced yet is sliced first with Bambu Studio's own command line, uploaded to the printer over FTPS, and started. Pause, resume, stop, speed, chamber light, nozzle and bed temperatures, homing and G-code are all a press on the panel or a service call.
- **The `bruh_bambu` integration**: `print_file`, `slice_file`, `pause_print`, `resume_print`, `stop_print`, `set_speed`, `set_light`, `set_temperature`, `send_gcode`, `open_in_studio`, and three reads (`get_status`, `list_files`, `printer_files`), each answering with the add-on's reply and raising with its reason on a refusal. Five sensors per printer: status, progress, time left, nozzle and bed temperature.
- **brAIn can run the printers** through those services (its `bambu_status`, `bambu_print`, `bambu_control` and `bambu_slice` tools).
