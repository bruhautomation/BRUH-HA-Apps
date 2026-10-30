# BRUH Cooking

Breville+ and Sage cooking appliances — the ChefSteps Joule, the Joule Turbo
and the Joule Oven Air Fryer Pro — in Home Assistant and brAIn. Start, stop
and watch a cook, fill in a preset, and get told when the water is ready or
the food is done.

- **brAIn drives it.** Ask brAIn in chat or by voice: *"Heat the Joule for a
  medium-rare steak"*, *"How long is left on the oven?"*, *"Stop the sous
  vide"*. brAIn's `cooking_status` and `cooking_control` tools use this
  add-on's services. **BRUH Cooking requires brAIn**, and won't start without
  it.
- **Every appliance as a device**: status, temperature, time left, cook end,
  preheat, target temperature, cook time, the Cook switch, Continue, and the
  oven's mode, convection, level, keep warm and door.
- **A sidebar panel** that draws each appliance as it is, with every control,
  a temperature chart and presets.

It uses the same Breville cloud as the Breville+ Cooking app. It's unofficial,
and isn't affiliated with or endorsed by Breville.

See [DOCS.md](DOCS.md) for setup, the entities, services, brAIn and safety.

BRUH Cooking's integration and panel are derived from
[kedube/ha-breville-cooking](https://github.com/kedube/ha-breville-cooking)
by kedube, and, like it, are licensed under the GNU GPL v3.0 ([LICENSE](LICENSE)).
