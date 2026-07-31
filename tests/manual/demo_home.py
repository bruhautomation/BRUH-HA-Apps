"""The demo home's content: insight cards with real visualizations, a chat
transcript, and a memory document. Kept apart from seed_panel.py so the
cards can be edited without touching the wiring.

The HTML follows the same design system the real generation prompt hands to
Claude (categories.SYSTEM_PROMPT): one focused visual, inline CSS, system-ui,
light and dark via prefers-color-scheme, the fixed categorical hue order.
"""

VIZ_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  :root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
        --grid:#e1e0d9;--axis:#c3c2b7;--c1:#2a78d6;--c2:#008300;--c4:#eda100;
        --warn:#fab219;--crit:#d03b3b;--good:#0ca30c}
  @media (prefers-color-scheme: dark){:root{--bg:#1a1a19;--ink:#fff;
        --ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
        --c1:#3987e5;--c2:#008300;--c4:#c98500}}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:14px/1.45 system-ui,-apple-system,sans-serif}
  .wrap{padding:14px 16px 16px}
  .t{font-size:12px;color:var(--ink2);margin:0 0 10px;letter-spacing:.01em}
  text{font-family:system-ui,-apple-system,sans-serif}
  .ax{fill:var(--muted);font-size:10px}
  .lbl{fill:var(--ink2);font-size:11px}
  .num{font-variant-numeric:tabular-nums}
  @media (prefers-reduced-motion: no-preference){
    .grow{transform-origin:bottom;animation:g .7s ease-out both}
    @keyframes g{from{transform:scaleY(0)}to{transform:scaleY(1)}}
    .draw{stroke-dasharray:1200;stroke-dashoffset:1200;animation:d .8s ease-out both}
    @keyframes d{to{stroke-dashoffset:0}}
  }
</style></head><body><div class="wrap">"""
VIZ_FOOT = "</div></body></html>"


def _bars(rows, unit, hi_index):
    """Horizontal bars, one hue, magnitude by length."""
    top = max(r[1] for r in rows)
    out, y = [], 0
    for i, (name, val) in enumerate(rows):
        w = round(val / top * 430)
        fill = "var(--c4)" if i == hi_index else "var(--c1)"
        out.append(
            f'<rect class="grow" x="118" y="{y + 4}" width="{w}" height="18" rx="4" '
            f'fill="{fill}" style="animation-delay:{i * 60}ms"/>'
            f'<text class="lbl" x="110" y="{y + 18}" text-anchor="end">{name}</text>'
            f'<text class="lbl num" x="{124 + w}" y="{y + 18}">{val} {unit}</text>')
        y += 28
    return f'<svg viewBox="0 0 620 {y + 8}" width="100%" height="{y + 8}">' \
           + "".join(out) + "</svg>"


ENERGY_HTML = VIZ_HEAD + """
<p class="t">Electricity by device — last 30 days</p>
""" + _bars([("Dehumidifier", 41), ("Fridge", 22), ("Freezer", 14),
             ("Heat pump", 12), ("Living room TV", 6), ("Office TV", 4)],
            "kWh", 0) + """
<p class="t" style="margin:12px 0 0">Humidity in there has not been above 50% since 14 July.</p>
""" + VIZ_FOOT

HEALTH_HTML = VIZ_HEAD + """
<p class="t">Last time each device reported — 31 of 34 are healthy</p>
<svg viewBox="0 0 620 168" width="100%" height="168">
  <line x1="118" y1="140" x2="600" y2="140" stroke="var(--axis)" stroke-width="1"/>
  <text class="ax" x="118" y="156">24 Jul</text>
  <text class="ax" x="359" y="156" text-anchor="middle">28 Jul</text>
  <text class="ax" x="600" y="156" text-anchor="end">today</text>
  <text class="lbl" x="110" y="26" text-anchor="end">Back door battery</text>
  <line x1="118" y1="20" x2="238" y2="20" stroke="var(--c1)" stroke-width="2" class="draw"/>
  <circle cx="238" cy="20" r="4.5" fill="var(--crit)"/>
  <text class="lbl num" x="252" y="24" fill="var(--crit)">silent since 26 Jul</text>
  <text class="lbl" x="110" y="60" text-anchor="end">Loft temp 1</text>
  <line x1="118" y1="54" x2="178" y2="54" stroke="var(--c1)" stroke-width="2" class="draw"/>
  <circle cx="178" cy="54" r="4.5" fill="var(--warn)"/>
  <text class="lbl num" x="192" y="58" fill="var(--warn)">silent since 24 Jul</text>
  <text class="lbl" x="110" y="94" text-anchor="end">Loft temp 2</text>
  <line x1="118" y1="88" x2="178" y2="88" stroke="var(--c1)" stroke-width="2" class="draw"/>
  <circle cx="178" cy="88" r="4.5" fill="var(--warn)"/>
  <text class="lbl num" x="192" y="92" fill="var(--warn)">silent since 24 Jul</text>
  <text class="lbl" x="110" y="128" text-anchor="end">31 others</text>
  <line x1="118" y1="122" x2="600" y2="122" stroke="var(--c2)" stroke-width="2" class="draw"/>
  <circle cx="600" cy="122" r="4.5" fill="var(--good)"/>
</svg>
<p class="t" style="margin:10px 0 0">Both loft sensors went quiet the minute the Zigbee
coordinator moved from channel 15 to 20.</p>
""" + VIZ_FOOT

PRESENCE_HTML = VIZ_HEAD + """
<p class="t">"Home" according to the phone tracker vs. actually home — this week</p>
<svg viewBox="0 0 620 150" width="100%" height="150">
  <text class="lbl" x="110" y="34" text-anchor="end">Tracker says home</text>
  <text class="lbl" x="110" y="86" text-anchor="end">Really home</text>
  <line x1="118" y1="120" x2="600" y2="120" stroke="var(--axis)"/>
  <g class="draw">
    <rect x="118" y="20" width="52" height="20" rx="3" fill="var(--c1)"/>
    <rect x="196" y="20" width="6" height="20" rx="2" fill="var(--crit)"/>
    <rect x="238" y="20" width="6" height="20" rx="2" fill="var(--crit)"/>
    <rect x="286" y="20" width="6" height="20" rx="2" fill="var(--crit)"/>
    <rect x="352" y="20" width="6" height="20" rx="2" fill="var(--crit)"/>
    <rect x="430" y="20" width="170" height="20" rx="3" fill="var(--c1)"/>
    <rect x="118" y="72" width="52" height="20" rx="3" fill="var(--c2)"/>
    <rect x="430" y="72" width="170" height="20" rx="3" fill="var(--c2)"/>
  </g>
  <text class="ax" x="118" y="138">Mon</text>
  <text class="ax" x="290" y="138" text-anchor="middle">Wed</text>
  <text class="ax" x="600" y="138" text-anchor="end">Sun</text>
  <text class="lbl num" x="196" y="58" fill="var(--crit)">4 phantom arrivals, all under 90 s</text>
</svg>
""" + VIZ_FOOT

ASK_HTML = VIZ_HEAD + """
<p class="t">automation.night_bathroom_run — the 03:04 trace</p>
<svg viewBox="0 0 620 190" width="100%" height="190">
  <g class="draw">
    <line x1="60" y1="26" x2="60" y2="160" stroke="var(--axis)" stroke-width="2"/>
  </g>
  <circle cx="60" cy="30" r="6" fill="var(--c1)"/>
  <text class="lbl" x="80" y="34">03:04:22 — landing motion detected</text>
  <circle cx="60" cy="74" r="6" fill="var(--c2)"/>
  <text class="lbl" x="80" y="78">condition: sun below horizon — passed</text>
  <circle cx="60" cy="118" r="6" fill="var(--c2)"/>
  <text class="lbl" x="80" y="122">action: light.turn_on — no brightness given</text>
  <circle cx="60" cy="162" r="6" fill="var(--crit)"/>
  <text class="lbl" x="80" y="166" fill="var(--crit)">light restored 100%, its last evening value</text>
</svg>
<p class="t" style="margin:6px 0 0">The night scene sets 15%, but the automation never
says so — so the light comes back at whatever it was last set to.</p>
""" + VIZ_FOOT

CARDS = [
    {
        "id": "custom-1722", "category": "custom",
        "title": "Why did the hallway light come on at 3 am?",
        "question": "Why did the hallway light come on at 3am?",
        "summary": "automation.night_bathroom_run fired on landing motion and turned "
                   "the light on at 100% — it never sets a brightness, so it restored "
                   "the evening value.",
        "highlights": [
            {"label": "Fired at", "value": "03:04:22"},
            {"label": "Triggered by", "value": "Landing motion"},
            {"label": "Brightness", "value": "100%",
             "delta": "night scene is 15%", "status": "warning"},
        ],
        "html": ASK_HTML, "minutes_ago": 14, "tags": ["asked", "answered"],
    },
    {
        "id": "energy", "category": "energy",
        "title": "The dehumidifier is your quiet £12 a month",
        "summary": "The utility-room dehumidifier used more power than the fridge and freezer "
                   "combined, and humidity hasn't been above 50% since 14 July.",
        "highlights": [
            {"label": "Dehumidifier", "value": "41 kWh", "delta": "+86% vs the fridge",
             "status": "warning"},
            {"label": "Cycling", "value": "19 h/day"},
            {"label": "Costing", "value": "£11.70/mo", "delta": "at 28.6p"},
            {"label": "On a humidity trigger", "value": "£2.50/mo", "status": "good"},
        ],
        "html": ENERGY_HTML, "minutes_ago": 40,
        "tags": ["energy", "utility room", "£12/mo"],
    },
    {
        "id": "health", "category": "health",
        "title": "Three sensors have gone quiet this week",
        "summary": "The back door battery sensor died on 26 July at 8%, and both loft "
                   "sensors stopped the minute the Zigbee channel changed.",
        "highlights": [
            {"label": "Silent devices", "value": "3 of 34", "status": "serious"},
            {"label": "Back door battery", "value": "last seen 26 Jul",
             "delta": "at 8%", "status": "critical"},
            {"label": "Mesh quality", "value": "LQI 187", "delta": "+25 since the move",
             "status": "good"},
        ],
        "html": HEALTH_HTML, "minutes_ago": 112, "tags": ["health", "batteries", "zigbee"],
    },
    {
        "id": "presence", "category": "presence",
        "title": "The house thinks you're home when you aren't",
        "summary": "Ben's phone reported home four times this week while it was on the "
                   "office Wi-Fi — each under 90 seconds, and each turned the hallway light on.",
        "highlights": [
            {"label": "Phantom arrivals", "value": "4", "delta": "all under 90 s",
             "status": "warning"},
            {"label": "Lights triggered", "value": "4 afternoons"},
            {"label": "Phone was on", "value": "OfficeNet"},
        ],
        "html": PRESENCE_HTML, "minutes_ago": 240, "tags": ["presence", "needs a fix"],
    },
]


# --------------------------------------------------------------- findings
FINDINGS = [
    {"text": "automation.evening_lights fires at 3 pm on Wi-Fi presence flaps",
     "detail": "device_tracker.bens_phone reports home for under 90 seconds while the "
               "phone is on the office network. The presence trigger has no duration "
               "guard, so the hallway light came on on four afternoons this week.",
     "fix": "Add `for: 00:02:00` to the presence trigger in automation.evening_lights.",
     "severity": "warning", "fixable": True,
     "entity_id": "automation.evening_lights"},
    {"text": "sensor.back_door_battery has reported nothing since 26 July",
     "detail": "Last reading 8% on 26 July at 04:11, then silence. The door sensor "
               "itself still reports state, so this is the battery entity only — but "
               "the low-battery automation can no longer see it.",
     "fix": "Replace the CR2032 in the back door sensor; re-pair if it stays silent.",
     "severity": "serious", "fixable": False, "entity_id": "sensor.back_door_battery"},
    {"text": "Two loft sensors never rejoined after the Zigbee channel change",
     "detail": "Aqara WSDCGQ11LM ×2, silent since 24 July at 14:30 — the same minute "
               "the coordinator moved from channel 15 to channel 20.",
     "fix": "Re-pair both from the loft hatch, within range of the landing repeater.",
     "severity": "warning", "fixable": False},
    {"text": "13 entities belong to devices that no longer exist",
     "detail": "Left behind by the old Hue bridge and two removed Sonoff plugs. They "
               "show as unavailable on three dashboards.",
     "fix": "Run brain.delete_orphaned_entities — dry run first, it lists them.",
     "severity": "info", "fixable": True},
]


# ---------------------------------------------------------------- memory
MEMORY_MD = """# What I know about this home

## The household
- Ben and Sarah, plus a lurcher called Biscuit. Both work from home on Tuesdays
  and Thursdays; the house is empty Monday, Wednesday and Friday, 08:30-17:30.
- "The office" means the upstairs back bedroom, not the study downstairs.
- Sarah is a light sleeper. Nothing in the hallway should go above 15%
  brightness between 23:00 and 06:00.

## The house
- 1930s semi, solid brick, loft insulation retrofitted in 2021. The loft runs
  4-6 C colder than the rest of the house in winter, and that is why the
  landing radiator never satisfies.
- Heating is a Daikin 8 kW air-source heat pump on weather compensation. It is
  not a boiler, so "boost the heating" means raising the flow temperature.
- Electricity is Octopus Agile. The cheap window is usually 23:30-05:30.

## Devices and their quirks
- The garage fridge is meant to run 24/7. Its draw looking abnormal at 3 am is
  the defrost cycle, not a fault. (Confirmed by Ben, 12 July.)
- The utility-room dehumidifier has no schedule and never had one.
- The Zigbee coordinator moved from channel 15 to 20 on 24 July 2026.
- Two Shelly 1PMs in the kitchen are named for the previous owner's layout
  ("dining spot", "breakfast bar") and neither matches where they actually are.

## Conventions to keep
- Automations get a `# why:` comment on the first line. Ben reads these.
- Never rename an entity_id without asking - several are referenced in a
  Node-RED flow I cannot see.
- Notifications go to notify.mobile_app_bens_phone, never to persistent
  notifications, unless it is a safety issue.
"""

PENDING_FACTS = [
    "The 'garden' lights are actually the side return, not the back garden.",
    "The guest room is used as a home gym on weekday mornings.",
    "Octopus Agile tariff; the cheap window is usually 23:30-05:30.",
]

HYPOTHESES = [
    ("Biscuit sets off the living-room motion sensor during the day, which is why "
     "the away-lighting automation never engages.", "presence"),
    ("The loft sensors only feed the winter frost automation, so their being "
     "offline in July is not urgent - right?", "device reliability"),
]


# ------------------------------------------------------- chat transcript
def chat_events():
    """A conversation in the Terminal tab's chat face, as the panel sees it."""
    ev, seq = [], 0

    def add(obj):
        nonlocal seq
        seq += 1
        ev.append({"seq": seq, **obj})

    add({"type": "user",
         "text": "The hallway light came on at 3am again. Find out why and fix it."})
    add({"type": "thinking",
         "text": "Start from the logbook around 03:00 rather than guessing at "
                 "automations — I want the event that actually fired, then its trace."})
    add({"type": "tool", "id": "t1", "name": "get_logbook",
         "summary": "light.hallway",
         "input": '{\n  "entity_id": "light.hallway",\n  "hours": 24\n}'})
    add({"type": "tool_result", "id": "t1", "ok": True,
         "text": "03:04:22  light.hallway turned on\n"
                 "          triggered by automation.night_bathroom_run\n"
                 "03:06:51  light.hallway turned off"})
    add({"type": "tool", "id": "t2", "name": "get_automation_trace",
         "summary": "automation.night_bathroom_run",
         "input": '{\n  "automation_id": "automation.night_bathroom_run"\n}'})
    add({"type": "tool_result", "id": "t2", "ok": True,
         "text": "trigger: binary_sensor.landing_motion -> on\n"
                 "condition: sun below horizon -> true\n"
                 "action: light.turn_on {entity_id: light.hallway}\n"
                 "  result: state on, brightness 255"})
    add({"type": "text",
         "text": "Found it. `automation.night_bathroom_run` calls `light.turn_on` with "
                 "no brightness, so the hallway light comes back at whatever it was "
                 "last set to — 100%, from the evening scene. Your night scene is 15%.\n\n"
                 "I'll add the brightness to the action. Memory says Sarah is a light "
                 "sleeper and the hallway is capped at 15% overnight, so that's the "
                 "value I'll use."})
    add({"type": "tool", "id": "t3", "name": "Edit",
         "summary": "/config/automations.yaml",
         "input": '{\n  "file_path": "/config/automations.yaml"\n}'})
    add({"type": "tool_result", "id": "t3", "ok": True,
         "text": "  - service: light.turn_on\n"
                 "    target: {entity_id: light.hallway}\n"
                 "+   data: {brightness_pct: 15, transition: 2}"})
    add({"type": "tool", "id": "t4", "name": "Bash",
         "summary": "ha check", "input": '{\n  "command": "ha check"\n}'})
    add({"type": "tool_result", "id": "t4", "ok": True,
         "text": "automations.yaml: OK\nconfiguration valid"})
    add({"type": "tool", "id": "t5", "name": "call_service",
         "summary": "automation.reload",
         "input": '{\n  "domain": "automation",\n  "service": "reload"\n}'})
    add({"type": "tool_result", "id": "t5", "ok": True, "text": "ok"})
    add({"type": "text",
         "text": "Done — the automation now sets 15% with a 2-second fade, the YAML "
                 "validates and I've reloaded automations. The old file is snapshotted, "
                 "so `brain undo` puts it back if you'd rather it didn't fade."})
    add({"type": "result", "duration_ms": 24100, "turns": 6})
    return ev
