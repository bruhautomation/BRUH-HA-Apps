# BRUH Cooking

BRUH Cooking puts Breville+ and Sage cooking appliances in Home Assistant and
hands them to brAIn: start and stop cooks, change the temperature and timer,
fill in a preset, and get told when the water is ready or the food is done. A
sidebar panel draws each appliance as it is, with every control. It uses the
same Breville cloud as the Breville+ Cooking app; it's unofficial, and isn't
affiliated with or endorsed by Breville.

## Requirements

- **brAIn.** BRUH Cooking is built to be driven by brAIn, and the add-on
  won't start without it: install brAIn from this repository first. If brAIn
  is removed later, BRUH Cooking stops too (the integration stays in Home
  Assistant until you remove it).
- Home Assistant 2026.2 or newer.
- The account you use in the Breville+ Cooking app, or in Sage's version of
  it. Accounts with multi-factor authentication aren't supported.
- The appliance set up in the app and connected to Wi-Fi. A Joule set to
  "Bluetooth only" can't be reached.

## Setting up

1. Install and start brAIn, if it isn't already.
2. Install **BRUH Cooking** and start it. It copies the `bruh_cooking`
   integration into `/config/custom_components`.
3. Restart Home Assistant once, so it loads the integration.
4. Under **Settings → Devices & services**, BRUH Cooking is waiting under
   *Discovered*. Press **Add**, log in with your email and password, and
   choose your brand: Sage in the UK, Europe and the UAE, and Breville
   elsewhere. Each supported appliance on the account becomes a device, named
   as in the app.

Your password is only sent to Breville. Home Assistant keeps a login session,
not the password, and asks you to log in again if the session expires. To add
another account, add the integration again.

The add-on keeps the integration deployed: an update to the add-on brings the
new integration with it (restart Home Assistant to load it), and a deleted
`custom_components/bruh_cooking` folder is put back within ten minutes. Turn
off *Home Assistant integration* in the add-on's options to stop it copying
anything.

BRUH Cooking's `bruh_cooking` integration is a renamed copy of the HACS
integration `bruh_cooking`, so the two can be installed side by side; use
one or the other for an account, not both.

## brAIn

brAIn reaches the appliances through two tools, listed only while the
`bruh_cooking` integration is in Home Assistant:

- **`cooking_status`** — what each appliance is doing (state, temperature,
  time left, the oven's mode and door, an error) and what its next cook would
  be; with `presets: true`, the presets each one can cook.
- **`cooking_control`** — `start` (an appliance by name, a preset, and any of
  temperature, minutes, mode, convection, level, keep warm and start timer
  automatically), `stop` and `continue` (the food is in, or out).

So *"Start the Joule for chicken breast"*, *"Set the oven to air fry at 400
for 20 minutes"*, *"Is the water ready?"* and *"Stop the oven"* all work in
brAIn's chat and terminal, and by voice. brAIn's rules for changing the house
apply: an unattended brAIn run (an insight card, a check) can read the
appliances but never starts, stops or continues one, and in chat a start or a
stop passes brAIn's action gate like any other change.

Voice may read, start, stop and continue. Starting a cook remotely is what
this add-on is for, and the appliances themselves are the last check: the
Joule Oven waits for Start to be pressed on its panel before it heats, and
UL-certified Joules wait for their top button before a cook above 85 °C. See
[Safety](#safety).

When brAIn doesn't say which appliance and there's more than one, it's asked
which; a name brAIn doesn't recognise is refused with the names there are.

## Supported appliances

| Appliance | Model | Status |
|---|---|---|
| ChefSteps Joule Sous Vide | CSJ100 | Tested on a real appliance |
| Joule Turbo Sous Vide | BSV600 | Built from the app's code; untested |
| Joule Oven Air Fryer Pro | BOV950 | Tested on a real oven: all 15 modes start, and bake, air fry and broil were run to the end, with Continue after preheating and Keep warm. Cooks started on the oven itself show up and can be stopped |

Untested appliances are monitor-only until you allow control in the
integration's [options](#options). Sage-branded appliances, sold in the
UK, Europe and the UAE, are supported the same way, but nobody has tried a
Sage account yet.

Other appliances on the account are ignored. For espresso machines, use the
[Sage Coffee](https://github.com/simonjgreen/sageha) integration instead. It's
in the HACS default store; check its README for the models it supports.

## Options

**Allow control of untested appliances** is off at first. The Joule Turbo
hasn't been tried on a real appliance, so until you turn it on, Home Assistant
only shows its status and can stop a cook, not start or change one. To turn it on, go to **Settings → Devices & services → BRUH
Cooking → Configure**.

**Show in the sidebar** is on at first. It adds the
[sidebar panel](#sidebar-panel) for everyone who uses Home Assistant. Turn it
off to hide this account's appliances from the panel; the panel leaves the
sidebar once no account shows it.

## Sidebar panel

**BRUH Cooking** in the sidebar shows
each appliance as a drawing of the real thing, with what it's doing:

- **Overview:** a card for each appliance, grouped by area, with its status,
  the oven's display, and the temperature and time left. With only one
  appliance, the panel opens straight to it.
- **Drawings:** drawn from measurements of Breville's own photos. The Joule
  is clipped in a clear container of water, which circulates while it cooks,
  steams as it warms, and holds the bag of food once it's in. The oven shows
  its display as the real one does, the rack at the mode's position with the
  mode's accessory, the food while it cooks, the elements glowing as the mode
  uses them, and the fan turning. Its finish, brushed or black stainless, comes
  from the appliance.
- **Full view:** everything the entities offer: Start, Stop and Continue, the
  settings for the next cook, a chart of the cook's temperature against its
  target, and the appliance's details.
- **Presets:** built-in sous vide and oven presets fill in the settings; Start
  starts the cook. Administrators can save the current settings as a preset,
  and rename, update or delete saved ones. Saved presets are shared with
  everyone.
- **Screen readers:** every drawing is described in words, changes such as
  "ready for food" and "done" are announced, and everything works from the
  keyboard.

Anyone who can use Home Assistant can use the panel, as they can the
appliance's entities, and the same rules apply: untested appliances are
monitor-only unless you allow control, a running oven cook can't be changed,
and Stop always works.

The built-in presets follow published guidance: USDA FSIS, the FDA Food Code
and Douglas Baldwin's sous vide tables. Their times assume pieces about 1 in
(25 mm) thick; thicker ones need longer. Sous vide cooks some foods below the
USDA's minimum temperatures and holds them there long enough instead, and not
every preset pasteurizes: the steak presets don't, and the salmon, white fish
and shrimp presets need seafood that's safe to eat raw. Presets are a starting
point. Follow a trusted cooking guide, especially when cooking for anyone who
is pregnant, very young, older or has a weakened immune system.

## Languages

The integration's screens, entity names and messages, and the sidebar panel,
follow your Home Assistant language. They're available in English, German,
French, Dutch, Spanish, Simplified Chinese, Italian, Polish and Swedish. Oven
modes use the Breville+ app's names where those are accurate. The printing in
the panel's drawings, such as the oven's display, stays as it is on the
appliance. If you're a native speaker and something reads wrong, please edit
`custom_components/bruh_cooking/translations/<language>.json` (or, for the
sidebar panel, `frontend/src/i18n/<language>.json`) and open a pull request.

## Entities

Every appliance has:

| Entity | Type | What it does |
|---|---|---|
| Status | Sensor | What the appliance is doing: Idle, Preheating, Ready for food, Cooking, Done, Keeping warm, Press the button on the appliance, Error, Updating or Offline. |
| Temperature | Sensor | The water or oven temperature. Unknown while the oven is idle, since it stops updating it. |
| Time remaining | Sensor | Time left on the timer. |
| Cook end | Sensor | When the timer will finish. |
| Cooking | Binary sensor | On from the start of a cook to its end, including preheating and waiting for the food. |
| Problem | Binary sensor | On while the appliance reports an error. |
| Error | Sensor (diagnostic) | The error, such as Low water level or Tipped over. |
| Preheat | Sensor | How far preheating has got, in percent, from the temperature, as the Breville+ app works it out. An oven also ends preheating after 5 minutes, so once Home Assistant has seen it start, its Preheat counts that time too. It never goes back during a preheat. Unknown when the appliance isn't preheating. |
| Target temperature | Number | The temperature for the next cook, or of the running one. |
| Cook time | Number | The timer in minutes, for the next cook or the running one. For sous vide, 0 holds the temperature until you stop it. While an oven preheats it's unknown, because the oven only reports its timer once preheating is done. |
| Cook | Switch | Turn on to start a cook with these settings, and off to stop it. |
| Continue | Button | Tells the appliance the food is in, which starts the timer, or that it's out. Available only while the appliance is waiting for this. |
| Start timer automatically | Switch (configuration) | Starts the timer as soon as the temperature is reached, instead of waiting for **Continue**. On at first for the oven, as in the app. |

The oven also has:

| Entity | Type | What it does |
|---|---|---|
| Mode | Select | Bake, Air fry, Roast, Broil, Pizza and 10 other modes. Choosing one resets the other settings to that mode's defaults. |
| Convection | Select | The fan: Off, On or Super, as the mode allows. |
| Level | Select | Broil intensity (Low, Medium or High) or slow-cook level (Low or High). These modes use it instead of Target temperature. |
| Keep warm | Switch (configuration) | Keeps the food warm when the cook finishes. |
| Frozen food | Switch (configuration) | Cooks from frozen, for the modes that offer it: Pizza, Cookies and Reheat. Choosing a mode sets it to that mode's default. |
| Door | Binary sensor | Whether the door is open. |
| Active mode | Sensor | The mode of the running cook, including cooks started on the oven. |

Settings for the next cook are kept in Home Assistant, survive restarts, and
go to the appliance only when a cook starts. Changing settings in the
Breville+ app doesn't change them here.
While a cook runs, **Target temperature** and **Cook time** show the running
cook, and on a sous vide changing them changes it. On the oven, **Mode**,
**Convection** and **Level** show it too, even for a cook started on the oven
itself. As in the app, a running oven cook can't be changed: its **Cook time** shows the cook's length, and all
of its settings can only be changed while it's idle. Like the app, the
integration keeps to each model's temperature and time limits.

### A sous vide cook, step by step

1. Set **Target temperature** and **Cook time**, then turn on **Cook**.
   Status changes to Preheating.
2. At temperature, Status changes to Ready for food. Put the food in and press
   **Continue** to start the timer. With **Start timer automatically** on, the
   timer starts without waiting for **Continue**.
3. While the food cooks, **Time remaining** counts down and **Cook end** shows
   when it will finish.
4. When the timer ends, Status changes to Done. Take the food out and press
   **Continue**, or turn off **Cook**.

After a remote start, the oven waits for you to press Start on its panel, just
as it does when you start a cook from the Breville+ app. Until then, Status
shows Press the button on the appliance.

If the oven's timer doesn't start by itself, press **Continue** once Status
shows Ready for food. Pressing Start on the oven at that point cancels the
cook.

The oven decides for itself when preheating is done: when its sensor is
within 15 °C (27 °F) of the temperature it holds it at, or after 5 minutes,
whichever comes first. From a cold start that's usually the 5 minutes, so
Status can show Ready for food while Temperature still reads low. The
Breville+ app counts preheating as done at the same moment. **Preheat** counts
the 5 minutes too, so it nears 100% as preheating ends, unless Home Assistant
started partway through; then it goes by the temperature alone. In an oven
that's still warm from a broil, the sensor can cool before it heats; Preheat
holds rather than going back.

When the oven's timer runs out, the oven turns itself off. Status changes to
Done and **Cooking** turns off, but the cook stays open on the oven, so
**Cook** stays on. Turn off **Cook** to close it. The app's "a bit more" and
"keep warm" choices at this point aren't available here.

With **Keep warm** on, the oven keeps the food warm for an hour once the timer
runs out, at 160 °F (70 °C). Status shows Keeping warm, **Active mode**
keep_warm, and **Time remaining** counts down the hour; **Mode** and **Cook
time** still show the cook's. When the hour is up, the oven turns off and
Status changes to Done, the same as at the end of a cook. Turn off **Cook** to
stop keeping warm sooner.

While it cooks, the oven's Temperature reads lower than its target. The oven
holds its own sensor below the setpoint: about 320 °F (160 °C) for a 350 °F
bake. Keeping warm at 160 °F, once it had cooled from the cook, it settled at
about 125–136 °F (52–58 °C).

## Services

### Start cook (`bruh_cooking.start_cook`)

Starts a cook with the settings you give, without changing the appliance's
entities. Target the appliance's **Cook** switch.

| Field | Description |
|---|---|
| `temperature` | Target temperature, in your Home Assistant unit. |
| `duration` | Cook time, such as `"01:30:00"`. For sous vide, leave it out to hold the temperature until you stop it. |
| `mode` | Oven only: the mode, such as `bake`, `air_fry`, `roast` or `broil`. |
| `convection` | Oven only: `off`, `on` or `super`. |
| `level` | Oven only: `low`, `medium` or `high` for broil modes, and `low` or `high` for slow cook. |
| `auto_start_timer` | Start the timer once the temperature is reached. |
| `keep_warm` | Oven only: keep the food warm when the cook finishes. |

Fields you leave out come from the appliance's entities. If you set `mode`,
they come from that mode's defaults instead, apart from `auto_start_timer` and
`keep_warm`.

```yaml
action: bruh_cooking.start_cook
target:
  entity_id: switch.joule_cook
data:
  temperature: 57
  duration: "01:30:00"
```

The standard actions work too. For example, `switch.turn_on` on **Cook**
starts a cook with the entities' settings, `switch.turn_off` stops it, and
`button.press` presses **Continue**.

### The services brAIn calls

These name the appliance instead of targeting an entity, answer with what
happened, and raise with a sentence on every refusal. `appliance` is the
appliance's name (yours in Home Assistant, or the app's), its device ID or
its serial; leave it out when the account has one appliance.

| Service | Fields | Answers |
|---|---|---|
| `bruh_cooking.get_status` | `appliance` (optional) | `appliances`: each one's state, temperatures, time left, mode, door, error, whether control is allowed, and its next cook |
| `bruh_cooking.get_presets` | `appliance` (optional) | `presets`: the built-in and saved presets, with the appliances each fits |
| `bruh_cooking.start` | `appliance`, `preset`, and the `start_cook` fields | what was started, and for the oven that it waits for Start on its panel |
| `bruh_cooking.stop` | `appliance` | whether there was a cook to stop |
| `bruh_cooking.continue_cook` | `appliance` | Continue pressed; refused unless the appliance is waiting for it |

A start over a running cook is refused rather than replacing it. Settings
given beside a `preset` change the preset's.

```yaml
action: bruh_cooking.start
data:
  appliance: Joule
  preset: steak_medium_rare
response_variable: cook
```

## Examples

These examples assume an appliance named Joule. Your entity IDs follow the
appliance's name in the Breville+ app.

Get a notification when the water is ready for the food:

```yaml
alias: Joule ready for food
triggers:
  - trigger: state
    entity_id: sensor.joule_status
    to: ready
actions:
  - action: notify.notify
    data:
      message: The water is at temperature. Add the food and press Continue.
```

Get a notification 10 minutes before the cook ends:

```yaml
alias: Joule almost done
triggers:
  - trigger: time
    at:
      entity_id: sensor.joule_cook_end
      offset: "-00:10:00"
actions:
  - action: notify.notify
    data:
      message: Ten minutes to go.
```

Heat the water before you get home, and hold it at temperature:

```yaml
alias: Preheat the Joule
triggers:
  - trigger: time
    at: "17:30:00"
actions:
  - action: bruh_cooking.start_cook
    target:
      entity_id: switch.joule_cook
    data:
      temperature: 57
```

## Safety

Cooks start remotely, with nobody nearby. Only start a sous vide when it's in
water, and an oven only when there's nothing inside that shouldn't be heated.
For a delayed start, don't leave raw food sitting in unheated water.
UL-certified Joules (North America) wait for a press of their top button
before cooks above 85 °C, and the Joule Oven waits for a press of Start before
it heats.

## Data updates

Home Assistant keeps one connection open to Breville's cloud, which pushes
changes as they happen, usually within a second or two. If the connection
drops, it reconnects by itself: first after 5 seconds, then less often, up to
5 minutes apart. Entities are unavailable while it's disconnected.

It also checks the account's list of appliances every 30 minutes. New
appliances appear by themselves. Ones that have left the account become
unavailable, and you can then delete them from their device page.

## Known limitations

- The BSV600 hasn't been tried on a real appliance, so it's monitor-only
  unless you allow control in the [options](#options).
- A running oven cook's temperature and time can't be changed. The Breville+
  app can't change them either.
- Nobody has tried a Sage account yet.
- Accounts with multi-factor authentication can't log in.
- The BSV600's Turbo mode isn't offered.
- The oven's Toast, Bagel and Crispy reheat modes can't be started from Home
  Assistant, though **Active mode** shows them. Neither can Crispier air fry
  and Convection broil. The Breville+ app's code has them, but the app doesn't
  offer them, and sent from the cloud, either one made the oven go back to
  idle when Start was pressed.
- The BOV970 and BOV870 ovens aren't supported. The Breville+ app itself has
  no controls for them yet.
- Appliances added to the account can take up to 30 minutes to appear.
- There's no local control. Breville can change its cloud at any time, which
  could break this integration. For Bluetooth control of a CSJ100 Joule, see
  [ChefSteps Joule Sous Vide](https://github.com/acato/ha-joule).

## Troubleshooting

- **The add-on stops at start and says brAIn is required:** install and start
  brAIn, then start BRUH Cooking again.
- **Entities are unavailable:** Home Assistant can't reach Breville's cloud,
  and keeps trying. If Status shows Offline instead, the appliance itself is
  off or disconnected; check it in the Breville+ app.
- **Asked to log in again:** the Breville session expired. Follow the prompt
  in **Settings → Devices & services** and enter your password.
- **A new appliance is missing:** it appears within 30 minutes. To add it
  straight away, go to **Settings → Devices & services → BRUH Cooking**,
  then ⋮ → **Reload**.
- **A removed appliance is still listed:** once it's gone from your account,
  open its device page and delete it.
- **Starting a cook says it hasn't been tested:** see [Options](#options).
- **Anything else:** on the same page, choose **Enable debug logging**,
  reproduce the problem, then choose **Disable debug logging** to download the
  log.

When you report a problem (or ask brAIn to, with its development loop on),
attach the integration's diagnostics: go to **Settings → Devices & services →
BRUH Cooking**, then ⋮ → **Download diagnostics**. The file contains each
appliance's raw state and its last 50 messages from Breville's cloud, plus
Home Assistant's last 20 requests to the cloud. Your email, name and account
IDs, login tokens, appliance names, serial numbers and network addresses are
removed wherever they appear. Look the file over before posting it publicly.

## Credits and licence

BRUH Cooking's integration, sidebar panel and protocol notes
([docs/api.md](docs/api.md)) are derived from
[kedube/ha-breville-cooking](https://github.com/kedube/ha-breville-cooking),
whose author recovered the protocol from the Breville+ Cooking Android app,
and whose README thanks [CityDweller](https://github.com/CityDweller) for
testing the Joule Oven Air Fryer Pro on a real oven. Like the original, this
add-on is licensed under the GNU GPL v3.0 ([LICENSE](LICENSE)).

Breville, Breville+, Sage, ChefSteps and Joule are trademarks of their owners.
BRUH Cooking uses the names only to say which appliances it works with.
