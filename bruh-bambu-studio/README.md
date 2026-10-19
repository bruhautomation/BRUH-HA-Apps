# BRUH Bambu Studio

> ⚠️ **Experimental.** It works on the printers it has been tried on; expect
> rough edges, and keep Bambu Handy or the printer's screen within reach.

**Bambu Studio in your Home Assistant sidebar, and your Bambu Lab printers
under Home Assistant's control** — slice, print, pause, resume and watch prints
from the panel, a dashboard, an automation, or brAIn.

- **The real slicer.** Bambu Lab's own Bambu Studio, downloaded on first start
  and kept up to date, running on a virtual screen you use in the sidebar.
- **Printers on your LAN.** Add each printer by IP address, serial number and
  access code. Status, progress, time left, temperatures and AMS trays update
  live.
- **Print from anywhere.** Drop a model or a project into `/share/bambu`
  (Samba, the File Editor, or the panel's upload) and print it — unsliced
  projects are sliced first by Bambu Studio's own command line.
- **Full control.** Pause, resume, stop, speed, chamber light, temperatures,
  homing and G-code, on the panel and as `bruh_bambu.*` services.
- **Design parts with brAIn** (optional). With brAIn installed, a Design tab
  lets you describe a part, shape it in conversation, watch it in a 3D view
  with measuring, keep every version, and say *print it*: brAIn picks the
  printer, a tray for each colour and the settings, and starts the print. Or
  print it yourself, or open it in Bambu Studio.
- **brAIn drives it.** Ask brAIn to start the print, pause it, or tell you how
  long is left.
- **Printer cards** for Lovelace and for Morph: progress, time left,
  temperatures and AMS, with pause, resume, stop, speed and light.

**amd64 only.** Bambu Lab publishes Bambu Studio for Linux on x86-64 only, so
the add-on does not install on a Raspberry Pi or other ARM box.

📖 [Full documentation](DOCS.md)
