# BRUH Bambu Studio

> ⚠️ **Experimental.** It works on the printers it has been tried on; expect
> rough edges, and keep Bambu Handy or the printer's screen within reach.

**Bambu Studio in your Home Assistant sidebar, and your Bambu Lab printers
under Home Assistant's control** — slice, print, pause, resume and watch prints
from the panel, a dashboard, an automation, or brAIn.

- **The real slicer.** Bambu Lab's own Bambu Studio, downloaded on first start
  and kept up to date, running on a virtual screen you use in the sidebar.
- **Printers on your LAN.** Found on your network; give each its access code.
  The camera, the stage, progress, time left, temperatures, fans and AMS
  spools (the one in use, humidity) update live, with Refresh and Reconnect.
- **Print from anywhere.** Drop a model or a project into `/share/bambu`
  (Samba, the File Editor, or the panel's upload) and print it — unsliced
  projects are sliced first by Bambu Studio's own command line.
- **Full control.** Pause, resume, stop, speed, chamber light, temperatures,
  homing and G-code, and every common print option (build plate, print by
  object, copies, supports, brim, ironing, layer height…), on the panel and as
  `bruh_bambu.*` services.
- **Design parts with brAIn** (optional). With brAIn installed, a Design tab
  lets you describe a part, shape it in conversation, watch it in a 3D view
  with measuring, keep every version, and say *print it*: brAIn picks the
  printer, a tray for each colour and the settings, and starts the print. Or
  print it yourself, or open it in Bambu Studio.
- **Print failure detection.** brAIn looks at the camera at the moments a
  print is most likely to fail — planned from the print's own G-code: the
  first layer, where the part narrows, bridges, colour changes, a part
  getting tall — compares it with what the print should look like, warns you
  (Ignore or Pause) and pauses a print that has failed. Free checks catch a
  covered lens, a frozen camera, a sudden change on the plate, and when the
  plate has been cleared. Sensors, a Last print check camera and phone alerts
  with buttons in Home Assistant.
- **brAIn drives it.** Ask brAIn to start the print, pause it, or tell you how
  long is left.
- **Printer cards** for Lovelace and for Morph: the camera, progress, time
  left, temperatures and AMS, with pause, resume, stop, speed, light and
  refresh.

**amd64 only.** Bambu Lab publishes Bambu Studio for Linux on x86-64 only, so
the add-on does not install on a Raspberry Pi or other ARM box.

📖 [Full documentation](DOCS.md)
