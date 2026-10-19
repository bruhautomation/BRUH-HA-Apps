# GardenRX

A spray decision engine for a home orchard and garden, as a Home Assistant
add-on. It tracks crops and varieties and their phenological stage, the
weather and what it means for spraying, spray coverage and pre-harvest
intervals, a treatment-product reference built from the labels, your stock,
a tank-mix planner, and harvests — in Home Assistant's sidebar, with cards for
your dashboards.

- **The whole app in the sidebar**, through ingress.
- **Your data stays in Home Assistant**: one SQLite file in the add-on, in
  every backup.
- **Harvest, spray and stock cards** for Lovelace and Morph, and services to
  log a harvest or mark a queued spray done from an automation, a button or a
  voice assistant.

See [DOCS.md](DOCS.md) for setup and the card and service reference.
