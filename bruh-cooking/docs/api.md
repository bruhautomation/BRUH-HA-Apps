# Breville+ cloud API

This is the cloud API that the Breville+ Cooking app uses to control
appliances, as far as it's known. It's unofficial: Breville doesn't publish it
and can change it at any time. It was worked out from the Breville+ Cooking
Android app (`com.breville.cookingapp` 1.96.0) and from traffic between this
integration and a real Joule.

The code is in [`api.py`](../custom_components/bruh_cooking/api.py)
(login, REST and websocket) and
[`appliance.py`](../custom_components/bruh_cooking/appliance.py) (reading
each model's state and building its requests). Neither imports Home Assistant,
so both can be reused elsewhere.

Each part of the API is marked as one of:

- **Verified**: tried on a real appliance in October 2026: a Joule (CSJ100:
  hardware J5, firmware 123, Wi-Fi firmware 52), or where it says so, a Joule
  Oven (BOV950, firmware 1.10.21) baking.
- **From the app**: read from the app's code. Nobody has tried it on a real
  appliance yet.

Contents: [Overview](#overview) · [Brands](#brands) ·
[Logging in](#logging-in) · [Appliance list](#appliance-list) ·
[Commands](#commands) · [Live updates](#live-updates) ·
[Appliance state](#appliance-state) · [Timers](#timers) · [Limits](#limits) ·
[Not covered](#not-covered) · [Sources](#sources) ·
[Helping verify](#helping-verify)

## Overview

| Purpose | URL |
|---|---|
| Login (Auth0) | `https://my.breville.com/oauth/token` |
| Account API | `https://iot-api.breville.com/user` |
| Appliance API | `https://iot-api.breville.com/appliance/v1` |
| Live updates (websocket) | `wss://iot-api-ws.breville.com/applianceProxy` |

A client uses them in this order:

1. Log in with the account's email and password to get an `id_token`.
2. List the appliances on the account.
3. Open the websocket and subscribe to each appliance. The cloud sends the
   appliance's full state, then every change.
4. Send commands over REST. Most return an empty body, and their effect shows up
   on the websocket.

## Brands

| Brand | Auth0 `client_id` | App channel | Status |
|---|---|---|---|
| Breville | `A2IYXGeuX1g8s049YEri6WC6hu2wlrMZ` | `brevilleJoule` | Verified |
| Sage (UK, Europe and the UAE) | `Vp1NuYQ76uhbslASYk0iRRbeHUIsrGDa` | `sageJoule` | From the app |

The app channel goes in the REST `app` header and in websocket subscriptions.
Everything else, including the hosts, realm, audience and scope, is the same for
both brands. Sage's app (`com.sageappliances.cooking`) is a separate app built
from the same code with the brand fixed. Nothing in the appliance list says
which brand an account belongs to, so the user has to choose.

## Logging in

### Password login

**Verified.** Send a `POST` to `https://my.breville.com/oauth/token`:

```json
{
  "client_id": "A2IYXGeuX1g8s049YEri6WC6hu2wlrMZ",
  "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
  "username": "user@example.com",
  "password": "…",
  "realm": "Salesforce",
  "scope": "openid profile email offline_access",
  "audience": "https://iden-prod.us.auth0.com/userinfo"
}
```

The response is Auth0's usual token response, with an `id_token`, an
`access_token` and, because of `offline_access`, a `refresh_token`.

Breville's API authenticates with the `id_token`, not the access token. The
`id_token` is a JWT issued by `https://my.breville.com/`, with the `client_id`
as its audience. Its claims are `sub`, `email`, `email_verified`, `name`,
`nickname`, `picture`, `customer_id`, `https://breville.com/crm_user_id`,
`iat`, `exp` and `updated_at`. `sub` is the user ID that account URLs use.

Failures come back in Auth0's format, `{"error": …, "error_description": …}`.
The integration handles them like this:

| `error` | Meaning |
|---|---|
| `invalid_grant` | Wrong email or password. |
| `access_denied`, `unauthorized_client` | Login refused. |
| `mfa_required` | The account uses multi-factor authentication. Neither the app nor this integration can log in to it. |

### Refreshing the token

**From the app.** Send a `POST` to the same URL:

```json
{
  "client_id": "A2IYXGeuX1g8s049YEri6WC6hu2wlrMZ",
  "grant_type": "refresh_token",
  "refresh_token": "…"
}
```

The response has a new `id_token`. If it has no new `refresh_token`, keep the
old one. The integration refreshes when the `id_token` is within 5 minutes of
its `exp`. It also refreshes once after any 401, then retries the request.

### REST headers

**Verified.** Every REST request carries:

```text
Accept: application/json
sf-id-token: <id_token>
Authorization: Bearer <id_token>
app: brevilleJoule
```

The app sends the token in `sf-id-token`. This integration also sends it as a
bearer token.

## Appliance list

**Verified.** `GET https://iot-api.breville.com/user/v2/user/{sub}/appliances`

```json
{
  "appliances": [
    {
      "serialNumber": "…",
      "model": "CSJ100",
      "name": "Kitchen Joule",
      "itemNumber": "…",
      "pairingType": "wifi",
      "circulatorId": "…"
    }
  ],
  "ownedModels": ["CSJ100"]
}
```

- `serialNumber` identifies the appliance in every other call.
- `name` is the name given to it in the app.
- `pairingType` was `wifi` for a Joule on Wi-Fi.
- A Joule also has a `circulatorId`, which the
  [Bluetooth key](#joule-bluetooth-key) endpoint uses.
- Every appliance on the account is listed, including models this integration
  doesn't support, such as espresso machines. The integration skips them.

Nothing tells a client that an appliance was added or removed, so the
integration fetches the list again every 30 minutes.

`GET https://iot-api.breville.com/appliance/v1/appliances/{serial}/model`
returns the appliance's model, as `{"model": …}` (**Verified**). The
integration doesn't use it.

## Commands

Commands are `POST` requests to
`https://iot-api.breville.com/appliance/v1/appliances/{serial}/{action}`, with a
JSON body and the [REST headers](#rest-headers). Timestamps in the bodies are
Unix time in milliseconds. A successful command returns an empty body, except
`load-manual-recipe`, and the appliance's reaction arrives on the
[websocket](#live-updates).

| Action | Purpose | Joule (CSJ100) | Joule Turbo (BSV600), Joule Oven (BOV950) |
|---|---|---|---|
| [`load-manual-recipe`](#start-a-cook) | Start a cook | Verified | Verified on the oven; from the app for the Joule Turbo |
| [`send-csj-message`](#change-a-joule-cook) | Change a running Joule cook | Verified | Not used |
| [`update-cook`](#change-a-cook-on-newer-appliances) | Change a running cook | Not used | From the app for the Joule Turbo; the app doesn't offer it for the oven, which ignored it |
| [`finish-wait`](#food-in-food-out) | Food is in, or food is out | Verified | From the app for the Joule Turbo; the app doesn't use it for the oven, which ignored it |
| [`send-step`](#go-on-to-the-next-step) | Go on to the next step of the running recipe | Not used | Verified on the oven, which the app continues this way; from the app for the Joule Turbo |
| [`stop-recipe`](#stop-a-cook) | Stop the cook | Verified | Verified on the oven; from the app for the Joule Turbo |

Several commands include the appliance's firmware, copied from its
[reported state](#appliance-state):

- Joule: `{"commFirmware": espFirmwareVersion, "ctrlFirmware": firmwareVersion}`
- Joule Turbo and Joule Oven: `{"commFirmware": firmware.comm_mcu,
  "ctrlFirmware": firmware.host_mcu}`, plus `teFirmware` when the appliance
  reports one.

### Start a cook

`load-manual-recipe` starts a cook, the same way as a manual cook in the app.
This starts a Joule at 55 °C for 30 minutes:

```json
{
  "applianceModel": "CSJ100",
  "firmware": {"commFirmware": "52", "ctrlFirmware": "123"},
  "payload": {
    "locale": "en-US",
    "steps": [
      {
        "defaultAutostart": false,
        "holdingTemperature": 55.0,
        "phases": [{"mode": "sousVide", "temperatureCelsius": 55.0, "seconds": 1800}],
        "stepType": "default",
        "title": "",
        "type": "sousVideSteps"
      }
    ]
  },
  "timestamp": 1792804189503
}
```

- `locale` is a language and country, such as `en-US` or `de-DE`. The
  integration sends Home Assistant's.
- `steps` is the recipe, in each model's format below.
- The app can also send `userDefinedParams`. The integration never does.

The cloud turns the steps into a recipe and runs it on the appliance. It
returns the recipe as `{"recipe": {…}}`, with `id`, `className`, `version`,
`locales`, `applicableDevicesSlugs`, `overallDisplay` (per model) and `steps`.

#### Joule steps

**Verified.** A Joule recipe has one step with one phase, as in the example
above.

- To hold the temperature until stopped, leave out `seconds` and add
  `"skipTimer": true` to the phase.
- Temperatures are in °C, rounded to 0.1, from 20 to 98 °C.
- With `"defaultAutostart": false`, the Joule waits for the food once it's at
  temperature (`programStep` 2), and [`finish-wait`](#food-in-food-out) starts
  the timer. With `true`, the timer starts as soon as the water is at
  temperature.

#### Joule Turbo steps

**From the app.** The step has the same fields as a Joule's, but two phases: a
preheat with `"seconds": 0`, then the cook. These phases cook at 57.5 °C for
90 minutes:

```json
{
  "phases": [
    {"mode": "sousVide", "temperatureCelsius": 57.5, "seconds": 0},
    {"mode": "sousVide", "temperatureCelsius": 57.5, "seconds": 5400}
  ]
}
```

To hold the temperature, the second phase is
`{"mode": "sousVide", "temperatureCelsius": 57.5, "skipTimer": true, "seconds": 0}`.
Temperatures go from 20 to 92 °C.

#### Joule Oven steps

**Verified** on a Joule Oven: every mode in the table below started as sent;
bake, air fry and broil (level 3, High) ran to the end, and so did keep warm
after a cook, to the end of its hour. The cloud accepted the steps and returned them with `sound`,
`enableNotification`, `notificationTitle` and `notificationBody` added to each
phase. The oven then waited for someone to press Start (`physicalButtonPress`).
With `"defaultAutostart": true`, its timer started by itself after preheating
and the oven turned off when the timer ran out.

An oven recipe (`"type": "ovenSteps"`) has these steps, in this order:

1. **Preheat**, for modes that preheat: the cook phase with `"seconds": 0`,
   `"defaultAutostart": false` and `"onComplete": "stayOn"`. If the timer
   should start by itself after preheating, the preheat and cook phases go in a
   single step with `"defaultAutostart": true` instead.
2. **Cook**: the cook phase, with `"onComplete": "turnOff"`, or `"keepWarm"`
   when the phase asks to keep warm and the mode allows it.
3. **A bit more** (`"stepType": "aBitMore"`): the cook phase again. This is the
   extra time the app offers when a cook ends. Its `seconds` are
   `max(minimum, min(maximum, factor × cook seconds))`, without rounding. The
   factor, minimum and maximum depend on the mode; see `OVEN_MODES` in
   [`appliance.py`](../custom_components/bruh_cooking/appliance.py).
4. **Keep warm** (`"stepType": "keepWarm"`), when the mode allows keeping warm
   and the cook phase didn't ask for it: 3600 seconds in `warm` mode with
   convection on, at `min(temperature, 70)` °C, then `"onComplete": "turnOff"`.

Every step except keep warm also has `onCompleteTemperature`, which is
`min(temperature, 70)` (70 for broil and slow cook). It also has a
`rackPosition` such as `["6"]`, left out for modes without one. The cook phase
has these fields:

| Field | Value |
|---|---|
| `mode` | The mode, from the table below. |
| `temperatureCelsius` | Whole degrees °C, for modes with a temperature. The oven rounds it to its own steps: 93 became 95 °C, or 200 °F on an oven set to °F. |
| `level` | Instead of a temperature: broil 1 (low), 2 (medium) or 3 (high); slow cook 1 (low) or 2 (high). |
| `seconds` | The cook time. Ovens can't skip the timer, and the shortest time is 1 minute. |
| `convection` | `off`, `on` or `super`. |
| `frozen` | `on` or `off`. Only pizza, cookies and reheat offer it. |
| `keepWarm` | `true` to keep the food warm after the cook. |
| `rotateRemind` | `false`. |

Baking at 180 °C for 30 minutes gives these steps:

```json
[
  {
    "stepType": "default", "defaultAutostart": false, "onComplete": "stayOn",
    "onCompleteTemperature": 70, "rackPosition": ["6"], "title": "", "type": "ovenSteps",
    "phases": [{"mode": "bake", "convection": "on", "rotateRemind": false, "temperatureCelsius": 180, "seconds": 0, "frozen": "off", "keepWarm": false}]
  },
  {
    "stepType": "default", "onComplete": "turnOff",
    "onCompleteTemperature": 70, "rackPosition": ["6"], "title": "", "type": "ovenSteps",
    "phases": [{"mode": "bake", "convection": "on", "rotateRemind": false, "temperatureCelsius": 180, "seconds": 1800, "frozen": "off", "keepWarm": false}]
  },
  {
    "stepType": "aBitMore", "onComplete": "turnOff",
    "onCompleteTemperature": 70, "rackPosition": ["6"], "title": "", "type": "ovenSteps",
    "phases": [{"mode": "bake", "convection": "on", "rotateRemind": false, "temperatureCelsius": 180, "seconds": 360, "frozen": "off", "keepWarm": false}]
  },
  {
    "stepType": "keepWarm", "onComplete": "turnOff", "title": "", "type": "ovenSteps",
    "phases": [{"mode": "warm", "convection": "on", "temperatureCelsius": 70, "seconds": 3600}]
  }
]
```

These are the modes that can be started remotely. Each one was tried on a
Joule Oven, along with Frozen food on a pizza, convection off and super, broil
levels 1 and 2, and slow cook level 1. `appliance.mode` is the number the oven
reports while it's in that mode.

| Mode | `appliance.mode` | Temperature (°C) | Time | Preheat | Rack | Convection | Keep warm |
|---|---|---|---|---|---|---|---|
| `bake` | 3 | 50–250, default 165 | default 30 min, max by temperature | yes | 6 | off/on/super (default on) | yes |
| `airFry` | 8 | 150–250, default 205 | default 18 min, max 1 h | yes | 3 | super | yes |
| `roast` | 4 | 50–250, default 205 | default 1 h, max by temperature | yes | 6 | off/on/super (default on) | yes |
| `broil` | 2 | level 1–3, default 3 | default 10 min, max 20 min | no | 1 | off | yes |
| `pizza` | 6 | 150–250, default 205 | default 16 min, max 1 h | yes | 7 | off/on/super (default on) | yes |
| `cookies` | 10 | 100–250, default 165 | default 11 min, max 1 h | yes | 5 | off/on/super (default on) | yes |
| `reheat` | 9 | 70–250, default 165 | default 15 min, max 2 h | no | – | off/on/super (default on) | yes |
| `slowCook` | 11 | level 1 (low) or 2 (high) | low 4–72 h (default 8 h), high 2–12 h (default 6 h) | no | 8 | on | yes |
| `proof` | 7 | 27–38, default 29 | default 1 h, max 24 h | no | – | off/on/super (default on) | no |
| `warm` | 5 | 45–120, default 70 | default 1 h, max by temperature | no | – | off/on/super (default on) | no |
| `dehydrate` | 12 | 30–80, default 52 | default 12 h, max 72 h | no | 3 | off/on/super (default super) | no |
| `bottomBake` | 13 | 50–250, default 165 | default 30 min, max by temperature | yes | 6 | off/on/super (default on) | yes |
| `bottomBroil` | 14 | level 1–3, default 3 | default 10 min, max 20 min | no | 1 | off | yes |
| `outerTopBroil` | 15 | level 1–3, default 3 | default 10 min, max 20 min | no | 1 | off | yes |
| `middleTopBroil` | 16 | level 1–3, default 3 | default 10 min, max 20 min | no | 1 | off | yes |

"Max by temperature" means up to 4 hours at 200 °C and above, 8 hours from
150 °C, 12 hours from 100 °C, and 72 hours below that.

Appliances report some other `appliance.mode` values for modes that can only
be started on the appliance itself. The oven reports 0 toast (seen for a toast
started on the oven), 1 bagel, 19 keep warm and 26 crispy reheat. The Joule
Turbo reports 23 sous vide and 24 turbo.

The app's code also has `gentleBroil` (Crispier Air Fry, 17), which it sets
up like `bake`, and `windyBroil` (Convection Broil, 18), set up like `broil`,
but the app doesn't offer either one for the oven (checked in the iOS app). A
Joule Oven accepted either one and waited for Start, but pressing Start sent it
back to `idle`: for a moment with `appliance.mode` 17 or 18, then 3. So the
integration doesn't offer them either.

### Change a Joule cook

**Verified.** `send-csj-message` passes a message to the Joule's own command
protocol. To change the temperature or time of the running cook, send a
`startProgramRequest`:

```json
{
  "messageType": "startProgramRequest",
  "message": {
    "circulatorProgram": {
      "setPoint": 60.0,
      "cookTime": 2700,
      "programType": 1,
      "programMetadata": {"cookId": "0123456789abcdef0123456789abcdef", "guideId": "manual_example"},
      "turboCookState": 0
    }
  }
}
```

- `programType` is `1` (automatic) for a timed cook, or `0` (manual) to hold
  the temperature. A manual program has no `cookTime`.
- `cookTime` is the reported `timeRemaining` once the timer is running, so the
  timer carries on from where it was. Before that, it's the reported
  `cookTime`.
- Copy `cookId` and `guideId` from the reported state, or the Joule treats it
  as a different cook.
- On an idle Joule this only loads the program; it doesn't start heating. Use
  [`load-manual-recipe`](#start-a-cook) to start a cook.

### Change a cook on newer appliances

**From the app.** The Joule Turbo uses `update-cook`. For a running Joule Oven
cook, the app offers only "View cook" and "Stop", with no way to change the
temperature or time, so the integration doesn't change running oven cooks
either.

```json
{
  "model": "BOV950",
  "step": 1,
  "updates": [
    {"name": "cookSetPoint", "value": 210},
    {"name": "cookTime", "value": 600}
  ],
  "uuid": "…"
}
```

- `step` is the reported `currentStep`, and `uuid` is the reported `cookUUID`.
  The app uses these for a cook it didn't start itself.
- The update names are `cookSetPoint`, `cookTime` and `autoStartTimer`. The
  app sends °C, converted from °F without rounding (375 °F is
  `190.55555555555554`), and seconds: after an edit it checks the timer's
  `down_from_n` against the value.
- On a Joule Oven baking with the timer running, a `cookSetPoint` and a
  `cookTime` update each returned 200, but the oven kept its setpoint and
  timer.

### Food in, food out

`finish-wait` (**Verified** on a Joule) is the app's on-screen button. When the
appliance is at temperature and waiting for the food, it starts the timer.
When the cook is done and waiting for the food to come out, it tells the
appliance the food is out.

```json
{"applianceModel": "CSJ100", "timestamp": 1792804189503}
```

The app (`useFinishWaitCommand`) adds where the cook is, and skips the request
if `cookUUID`, `currentStage` or `currentStep` is missing:

```json
{
  "applianceModel": "BSV600",
  "timestamp": 1792884279277,
  "cookUuid": "…",
  "firmware": {"commFirmware": "…", "ctrlFirmware": "…"},
  "stageIndex": 0,
  "stepIndex": 0,
  "wait": {"user": 2}
}
```

- `cookUuid`, `stageIndex` and `stepIndex` are the reported `cookUUID`,
  `currentStage` and `currentStep`. When `recipe` is an object, its `stg` and
  `stp` come first, and its `phase` is sent as `phaseIndex`.
- `wait` is always `{"user": 2}`.

The app only uses `finish-wait` for the Joule and Joule Turbo
(`doesApplianceSupportFinishWaitCommand`). A Joule Oven waiting for the food
after preheating answered both the short body and this one with 200, but
didn't start its timer. For the oven, the app's button goes on to the next
step instead.

### Go on to the next step

**Verified** on a Joule Oven. For an oven waiting after preheating, the app's
button (`NextRecipeStep`) sends `send-step` for the next cook step. The oven
answered 204 No Content, went on to the cook step within a few seconds, and
started its timer:

```json
{
  "applianceModel": "BOV950",
  "firmware": {"commFirmware": "1.10.131", "ctrlFirmware": "1.10.21", "teFirmware": "2.4.0"},
  "recipeId": "manual_5VQzGkAXTefbvToVRjZ5oU",
  "stepIndex": 1,
  "timestamp": 1792892582012
}
```

- `recipeId` is the reported `recipe`, or its `id` when it's an object.
- `stepIndex` is the first step after `currentStep` that isn't "a bit more",
  keep warm, or a preheat (a single phase of 0 seconds). For a manual cook
  that's waiting after its preheat step, that's the cook step:
  `currentStep + 1`.

### Stop a cook

**Verified** on a Joule and a Joule Oven. The oven answered 204 No Content and
went to `stopped`, then `idle`, within a few seconds. A cook started on the
oven's own panel stopped too: a toast went straight to `idle`, and a bake
reported `active` once more with `heater.state` 0 first.

```json
{
  "applianceModel": "CSJ100",
  "firmware": {"commFirmware": "52", "ctrlFirmware": "123"},
  "reason": 1,
  "timestamp": 1792804189503
}
```

`reason` is 0 (complete), 1 (cancel) or 2 (error). The integration sends 1.

### Joule Bluetooth key

Not used by this integration, and not tried here.
`POST https://iot-api.breville.com/appliance/v1/appliance/{serial}/get-csj-secret-key`
(note `appliance`, not `appliances`) with `{"circulatorId": …}` returns
`{"secretKey": …}`, in hex or base64. This is the key a Joule uses to accept
Bluetooth connections. The app saves keys with `persist-csj-secret-key`.
These details come from the app and from the
[ficusk/ha-joule](https://github.com/ficusk/ha-joule) fork, which uses the key
for Bluetooth control. Treat the key like a password.

## Live updates

**Verified.** Open `wss://iot-api-ws.breville.com/applianceProxy` with these
headers:

```text
sf-id-token: <id_token>
Authorization: Bearer <id_token>
```

A 401 during the handshake means the token has expired. Refresh it and try
again.

The client sends JSON messages:

| Message | Purpose | Status |
|---|---|---|
| `{"action": "addAppliance", "serialNumber": "…", "app": "brevilleJoule", "model": "CSJ100"}` | Subscribe to an appliance. | Verified |
| `{"action": "removeAppliance", "serialNumber": "…"}` | Unsubscribe. | From the app |
| `{"action": "ping"}` | Keep the connection open. | From the app |

After `addAppliance`, the cloud sends a `stateReport` with the full state, then
a stream of updates. Subscribe again on every new connection.

The app checks the connection every 5 seconds and pings when nothing has been
sent or received for 15 seconds. After a drop, it reconnects after 5 seconds,
then waits 1.8 times longer before each retry. The integration caps the wait at
5 minutes.

The cloud's messages look like this:

```json
{
  "serialNumber": "…",
  "messageType": "stateReport",
  "version": 722,
  "data": {"reported": {"state": "IDLE", "programStep": 0, "bathTemp": 54.5}}
}
```

| `messageType` | Contents | Status |
|---|---|---|
| `stateReport` | The full state in `data.reported`, replacing what came before. `version` is an integer that counts up. | Verified |
| `changeReport` | Part of the state in `data.reported`. Merge it in, key by key, including nested objects. | From the app |
| `applianceDataPoint` | The live state, flat in `data`. Merge it in. On a Joule, `version` is a string of epoch milliseconds. | Verified |
| `syncCookHistoryReport` | Cook history. `data.document` lists `{className, contentId, cookUuid, timestamp}`. | Verified |
| `buttonPressResult`, `timelineReport`, `syncCarouselReport`, `syncFavoritesReport`, `cookHistoryModifiedNotification`, `pong` | Used by the app, and ignored by the integration. | From the app |

A Joule sends `applianceDataPoint` messages every few seconds, with a
`stateReport` from time to time.

### Out-of-order messages

Messages can arrive out of order. During a Wi-Fi drop, a Joule's `stateReport`
version 788 (`OFFLINE`) arrived before version 787 (still `ACTIVE`). The
integration drops stale messages like this:

- **Joule:** drop a `stateReport` whose version is lower than the last one.
  Every Joule state has a `timestamp`: the Joule's uptime in milliseconds. Drop
  any update that is up to 2 minutes older than the newest one seen. A bigger
  jump back means the Joule restarted, so accept it. Don't compare versions
  across message types: `applianceDataPoint` versions are epoch milliseconds,
  while `stateReport` versions are a counter.
- **Joule Turbo and Joule Oven** (from the app): drop any message whose
  `version` isn't newer than the last one of the same `messageType`.

## Appliance state

### Joule

**Verified.** A Joule reports these fields, in `data.reported` or flat in
`data`:

| Field | Type | Meaning |
|---|---|---|
| `state` | string | `OFFLINE`, `ONLINE`, `IDLE`, or `ACTIVE` while running a cook. `ONLINE` shows briefly while a Joule reconnects. An `OFFLINE` Joule keeps reporting its last state. |
| `programStep` | int | 0 none, 1 preheating, 2 waiting for the food, 3 cooking, 4 waiting for the food to come out, 5 error, 6 updating firmware. Values 5 and 6 are from the app. |
| `bathTemp` | float | Water temperature, °C. |
| `setPoint` | float | Target temperature, °C, as a 32-bit float such as `58.900001525878906`. An idle Joule may still report its last cook's. |
| `cookTime` | int | Timer length, in seconds. |
| `timeRemaining` | int | Seconds left. 0 until the timer starts, then it counts down while `programStep` is 3. |
| `cookId` | string | 32 hex digits identifying the cook. |
| `guideId` | string | `manual_<id>` for manual cooks. |
| `programId`, `timerId` | string | IDs of the program and its timer. |
| `timestamp` | int | The Joule's uptime when it sampled the state, in milliseconds. |
| `programStartedTimestamp`, `setPointReachedTimestamp`, `dropFoodTimestamp`, `cookFinishedTimestamp` | int | Uptime of each event, in milliseconds. |
| `programStartedUnixTimestamp`, `circulatorStoppedUnixTimestamp` | int | Unix time in milliseconds. |
| `errorState` | int | Not 0 when there's an error, which `eventReason` then describes. |
| `eventType`, `eventReason`, `eventTimestamp` | int | The last event. Reasons are below. |
| `maxTemp` | float | About 98.6 °C, probably the highest temperature it allows. |
| `hardwareOptions` | int | Bit flags. 0x10000 means UL-certified; see [Limits](#limits). |
| `firmwareVersion`, `espFirmwareVersion`, `hardwareVersion` | string | Controller firmware, Wi-Fi module firmware and hardware revision, such as `J5`. |
| `model`, `macAddress`, `circulatorAddress` | string | The model and the Joule's addresses. |

Fields that only apply to a cook are null or missing without one.

`eventReason` values, from the app: 2 button pressed, 3 low water level,
4 tipped over, 5 overheating, 6 power loss, 7 heater thermistor failure, 8 bath
thermistor failure, 12 stuck motor, 14 firmware crash. Only 0 has been seen.

### Joule Turbo and Joule Oven

Both use the same layout. A real Joule Oven (firmware 1.10.21) confirmed the
parts marked **Oven**; the rest are from the app.

| Field | Meaning |
|---|---|
| `state` | **Oven:** `idle`; `physicalButtonPress` (after a remote start, waiting for someone to press Start); `active`; `virtualButtonPress` (waiting for the app, see below); and briefly `stopped` after [`stop-recipe`](#stop-a-cook). Keeping warm after a cook, it stays `active`, with `appliance.mode` 19 (keep warm), a new 3600-second timer and `temp_sp` 70 (`temp_sp_f` 160, `temp_sp_m` 65). From the app: `offline`, `asleep`, `ready`, `busy`, `warming` (keeping warm) and `onboarding`. |
| `heater` | **Oven:** `cur_temp` and `temp_sp` in °C, `temp_sp_f` in °F, `temp_sp_m` (see below), and `state`: 0 off, 1 preheating, 2 heating, 3 finished. A broil, which runs at a level, reports the three setpoints as 0, and doesn't preheat. The app also reads a `heaters` list. |
| `temperature` | Older Joule Turbo firmware: `current` and `setpoint`, in °C. |
| `timers` | **Oven:** `[null, null]` while no timer runs, including during preheat. The app's cook timer is the one with `id` 1, or else the first one; the oven's has `id` 0. See [Timers](#timers). Older Joule Turbo firmware has a single `timer`. |
| `appliance` | **Oven:** `mode` (a number from the [mode table](#joule-oven-steps)), `frozen` (1 for a frozen pizza), `rotate_state`, `preset` and `cook_segment`. A broil or slow cook reports its level as `preset`, 1 to 3 as sent, in six cooks. Other modes started remotely set it to 0; a bake started on the oven kept the last cook's, and a toast set 3. |
| `door` | **Oven:** a number, 1 when closed and 0 when open. The app also reads `door.state`. |
| `motor` | **Oven:** the convection fan as a number: 0 off, 1 on, 2 super. The app also reads `motors[0].state`. |
| `cfg` | **Oven:** settings, including `temp_unit` (1 on an oven set to °F) and `vol`. |
| `errors[]` | Entries of `{code, ts}`. Codes are below. |
| `firmware` | **Oven:** `commFirmware`, `ctrlFirmware` and `teFirmware`. The app also reads `comm_mcu` and `host_mcu`. |
| `name`, `serialNumber` | **Oven:** the appliance's name, which contained its serial number, and its serial number. |
| `cookUUID` | **Oven:** the running cook, for [`update-cook`](#change-a-cook-on-newer-appliances). |
| `currentStep` | **Oven:** index of the running recipe step, 0 while preheating. Some firmware reports `recipe.stp` instead. |
| `recipe`, `currentStage`, `currentInstruction`, `currentStepState` | **Oven:** during a cook, the recipe's ID and where the cook is in it. |
| `sys`, `ota` | **Oven:** CPU temperature and restart details, and the firmware update state. |
| `onboardingState` | `notStarted` while the appliance is being set up. |

While it waits for Start, the oven leaves `heater`, `motor` and `appliance` out
of its state. It sent a full `stateReport` every 10 to 20 seconds while
heating, and no `changeReport` or `applianceDataPoint` messages.

A cook started on the oven's own panel has a `cookUUID`, but no `recipe`,
`currentStage`, `currentStep`, `currentInstruction` or `currentStepState`. Its
timer is there from the start: a bake preheating had a reset timer (`state` 0)
for its 960 seconds, and a toast's timer ran from the first report.
[`stop-recipe`](#stop-a-cook) stops it too.

The oven keeps a setpoint in each unit, rounded to its own steps: a cook sent
as 93 °C reported `temp_sp` 95 and `temp_sp_f` 200, and 205 °C (401 °F)
reported 400 °F. When `cfg.temp_unit` is 1, the integration shows the target
from `temp_sp_f`.

`cur_temp` is the oven's own sensor, which it holds near `temp_sp_m` rather
than the setpoint: 161 °C for a 175 °C (350 °F) bake, and 191 °C for 205 °C.
Keeping warm, with `temp_sp_m` 65, it settled at 52 to 58 °C once it had
cooled from the cook.
The app's preheat progress bar is `cur_temp / (temp_sp_m − 15)`, or
`cur_temp / (0.9 × temp_sp_m)` at 150 °C and below. But the app counts
preheating as done once `heater.state` is 2 or 3, which the oven decides for
itself. It looks like `cur_temp` reaching `temp_sp_m − 15`, or 5 minutes,
whichever comes first: three 175 °C bakes from a cold oven each ended
preheating 300 seconds after it began, at a `cur_temp` of 91, 95 and 106 °C
(once about a minute before the oven beeped); a 205 °C air fry from a warm
oven ended after 254 seconds, as `cur_temp` reached 176 °C; and from an oven
already hot, within seconds. While idle, the oven stops updating
`cur_temp` after a while: it still reported 59 °C six hours after a cook.

`virtualButtonPress` came in two cases:

- **Waiting for the food** after preheating, when the timer doesn't start by
  itself: `currentStepState` `done`, `heater.state` 2 and no timer. The app
  goes on with [`send-step`](#go-on-to-the-next-step). Pressing Start on the
  oven at this point cancelled the cook: the oven went idle without a beep.
- **The cook is over:** when the timer ran out, the oven beeped and turned
  off. The first report still had the timer, with no time left; each of the
  four times, it reached Home Assistant within 2 seconds of the timer's end.
  A second later `heater.state` was 0, the timers were `null`, and
  `temp_sp_f` was worked out again from `temp_sp` (350 became 345). The cook
  then stayed open for about 10 minutes, until [`stop-recipe`](#stop-a-cook),
  which made the oven beep once and go idle. In the app, this is when it
  offers "a bit more" and "keep warm". Keep warm's hour ended the same way,
  with `appliance.mode` still 19 and `currentInstruction` 20 (14 at the end of
  a cook).

Error codes, from the app:

| Code | Meaning | Code | Meaning |
|---|---|---|---|
| 11202 | Heater thermistor failure | 29102 | Tipped over |
| 11210 | Bath thermistor failure | 29104 | Firmware crash |
| 16102 | Bad motor | 31101 | Water leakage |
| 16103 | Stuck motor | 31102 | Low water level |
| 22101 | Heater broken | 31103 | Current leakage |
| 29101 | Door open | | |

## Timers

**Joule (verified):** `cookTime` is the timer's length. `timeRemaining` is 0
until the timer starts, then counts down.

**Joule Turbo and Joule Oven (verified on the oven):** each timer has these
fields:

| Field | Meaning |
|---|---|
| `id` | 0 on the oven. The app takes the timer with `id` 1, or else the first one. |
| `state` | 0 reset, 1 running, 2 paused. The oven paused its timer while the door was open. |
| `down_from_n` | The timer's length, in seconds. 388803 means there's no timer, and the appliance holds until stopped (from the app). |
| `now` | Seconds left when the appliance sampled the timer. |
| `timestamp` | When it sampled it, in Unix seconds. |
| `usage` | On the oven, 6 for a cook's timer and 5 for keep warm's; otherwise unknown. |

A running timer ends at `timestamp + now`. The app works out the time left from
that, so a late message still gives the right time. A paused timer has `now`
seconds left. The oven only sent new `timestamp` and `now` values when the
timer started, paused or carried on. Its cook ended at exactly `timestamp +
now`. One other project reads `timestamp` as the time the timer started, but
the oven's timers show it's the time `now` was sampled.

## Limits

| Appliance | Temperature | Longest cook |
|---|---|---|
| Joule (CSJ100) | 20–98 °C | 96 hours |
| Joule Turbo (BSV600) | 20–92 °C | 96 hours |
| Joule Oven Air Fryer Pro (BOV950) | By mode; see the [mode table](#joule-oven-steps) | 72 hours, less in most modes |

- These are the app's limits, and the integration checks them before sending a
  cook. Nobody knows whether the cloud checks them too.
- UL-certified Joules (sold in North America) need a press of their top button
  before they'll hold above 85 °C. The app calls this a compliance press. The
  Joule reports UL certification as bit 0x10000 of `hardwareOptions`.
- Turbo mode isn't covered. Nobody has worked out how the app requests it, and
  guessing at heater commands isn't safe.

## Not covered

- **Multi-factor authentication:** login returns `mfa_required`, and the app
  has no way to continue from there.
- **BOV970 and BOV870 ovens:** the app knows the models, but has no controls
  for them.
- **Espresso machines:** these use the same hosts, but a different Auth0 client
  and app channel (`brevilleCoffee` or `sageCoffee`). See
  [Sage Coffee](https://github.com/simonjgreen/sageha).
- **Bluetooth:** apart from the [key](#joule-bluetooth-key), Bluetooth isn't
  part of the cloud API. For a Joule, see
  [ChefSteps Joule Sous Vide](https://github.com/acato/ha-joule).

## Sources

- **The app:** the Breville+ Cooking Android app 1.96.0, disassembled from its
  Hermes bytecode. Comments in `api.py` and `appliance.py` name the app
  functions that each part follows.
- **A real Joule:** traffic between
  [`scripts/breville_probe.py`](../scripts/breville_probe.py) and a Joule, in
  October 2026.
- **Other projects:** these use the same cloud and agree on the shared parts:
  - [xuio/homeassistant-breville-joule](https://github.com/xuio/homeassistant-breville-joule):
    Joule Turbo state fields.
  - [simonjgreen/sagecoffee](https://github.com/simonjgreen/sagecoffee): login
    and websocket.
  - [ficusk/ha-joule](https://github.com/ficusk/ha-joule): the Bluetooth key.

## Helping verify

If you have a Joule Turbo, a Joule Oven or a Sage account, you can help move
these parts from "From the app" to "Verified". Download the integration's
diagnostics. They include the last 50 websocket messages for each appliance
and the last 20 requests, with personal details removed. Then attach them to a
report, as described in
[Testing an appliance](../README.md#testing-an-appliance). The probe script
records the same traffic without Home Assistant.
