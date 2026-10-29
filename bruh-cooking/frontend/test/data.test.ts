import { describe, expect, it } from "vitest";
import { Announcer, announcementKey } from "../src/a11y/announcer";
import { groupByArea } from "../src/data/appliances";
import { latestCook, parseRows, points, thin } from "../src/data/history";
import { presetFits, presetName, presetSummary } from "../src/data/presets";
import { parseRoute, routePath } from "../src/data/route";
import { makeTranslate } from "../src/i18n";
import type { Preset } from "../src/types";
import { atTemperatureSince, niceTicks, valueAt } from "../src/views/chart";
import { SHARED_DATA } from "./context";
import { fakeHass } from "./fixtures/hass";
import { FIXTURES, SHARED } from "./fixtures/panel";

const t = makeTranslate("en");
const preset = (id: string): Preset => SHARED.presets.find((each) => each.id === id)!;

describe("presets", () => {
  const joule = FIXTURES["joule-idle"].appliance;
  const oven = FIXTURES["oven-idle"].appliance;

  it("fit the appliance's kind and limits", () => {
    const sousVide = SHARED.presets.filter((each) => presetFits(each, joule, SHARED_DATA.modes));
    const ovenPresets = SHARED.presets.filter((each) => presetFits(each, oven, SHARED_DATA.modes));
    expect(sousVide).toHaveLength(15);
    expect(ovenPresets).toHaveLength(13);
    const hot: Preset = { ...preset("vegetables"), id: "hot", builtin: false, name: "Hot", settings: { temperature_c: 95, duration_s: 600 } };
    expect(presetFits(hot, joule, SHARED_DATA.modes)).toBe(true);
    expect(presetFits(hot, { ...joule, limits: { ...joule.limits, max_temp_c: 92 } }, SHARED_DATA.modes)).toBe(false);
  });

  it("read in the user's unit, oven ones as round numbers", () => {
    const celsius = fakeHass([FIXTURES["joule-idle"]]);
    const fahrenheit = fakeHass([FIXTURES["oven-idle"]]);
    expect(presetSummary(celsius, t, preset("steak_medium_rare"), SHARED_DATA.modes)).toBe("56 °C · 1 h 30 min");
    expect(presetSummary(fahrenheit, t, preset("steak_medium_rare"), SHARED_DATA.modes)).toBe("132.8 °F · 1 h 30 min");
    expect(presetSummary(fahrenheit, t, preset("frozen_pizza"), SHARED_DATA.modes)).toBe("Pizza · 400 °F · 16 min · Frozen");
    expect(presetSummary(celsius, t, preset("frozen_fries"), SHARED_DATA.modes)).toBe("Air fry · 205 °C · 20 min");
    expect(presetSummary(fahrenheit, t, preset("salmon_fillets"), SHARED_DATA.modes)).toBe("Broil · High · 8 min");
    expect(presetSummary(celsius, t, preset("short_ribs"), SHARED_DATA.modes)).toBe("57 °C · 2 d");
  });

  it("are named in the user's language, or by the admin who saved them", () => {
    expect(presetName(t, preset("pulled_pork"))).toBe("Pulled pork shoulder");
    expect(presetName(makeTranslate("en"), { ...preset("cake"), builtin: false, name: "Gran's sponge" })).toBe("Gran's sponge");
  });
});

describe("history", () => {
  it("reads compressed and full rows", () => {
    expect(parseRows([{ s: "55.1", lu: 1792951200 }, { state: "on", last_changed: "2026-10-25T18:00:00Z" }, null, { s: 3 }])).toEqual([
      { state: "55.1", at: 1792951200000 },
      { state: "on", at: Date.parse("2026-10-25T18:00:00Z") },
    ]);
  });

  it("finds the latest cook, through a dropped connection", () => {
    const at = (minutes: number) => minutes * 60_000;
    const changes = [
      { state: "off", at: at(0) },
      { state: "on", at: at(10) },
      { state: "off", at: at(40) },
      { state: "on", at: at(60) },
      { state: "unavailable", at: at(70) },
      { state: "on", at: at(71) },
    ];
    expect(latestCook(changes, at(90))).toEqual({ start: at(60), end: null });
    expect(latestCook([...changes, { state: "off", at: at(95) }], at(100))).toEqual({ start: at(60), end: at(95) });
    expect(latestCook([{ state: "off", at: 0 }], at(1))).toBeNull();
  });

  it("keeps readings that are numbers, thinned evenly", () => {
    const list = points([
      { state: "50", at: 1 },
      { state: "unknown", at: 2 },
      { state: "51.5", at: 3 },
    ]);
    expect(list).toEqual([
      { at: 1, value: 50 },
      { at: 3, value: 51.5 },
    ]);
    const many = Array.from({ length: 5000 }, (_, index) => ({ at: index, value: index }));
    const kept = thin(many, 100);
    expect(kept).toHaveLength(100);
    expect(kept[0]).toEqual(many[0]);
    expect(kept[99]).toEqual(many[4999]);
  });
});

describe("the chart", () => {
  const target = [
    { at: 0, value: 56 },
    { at: 100, value: 57 },
  ];

  it("reads a stepped target at a moment", () => {
    expect(valueAt(target, -1)).toBeNull();
    expect(valueAt(target, 50)).toBe(56);
    expect(valueAt(target, 100)).toBe(57);
  });

  it("knows since when the water has been at temperature", () => {
    const current = [
      { at: 10, value: 40 },
      { at: 20, value: 55.7 },
      { at: 30, value: 56.2 },
      { at: 40, value: 55.9 },
    ];
    expect(atTemperatureSince(current, target, 0.5)).toBe(20);
    expect(atTemperatureSince([...current, { at: 50, value: 50 }], target, 0.5)).toBeNull();
  });

  it("puts round ticks around the values, the target inside them", () => {
    expect(niceTicks(19.2, 57, 4)).toEqual([10, 20, 30, 40, 50, 60]);
    expect(niceTicks(61, 410, 4)).toEqual([0, 100, 200, 300, 400, 500]);
  });
});

describe("routes", () => {
  it("parses and builds the panel's paths", () => {
    expect(parseRoute("")).toEqual({ view: "overview" });
    expect(parseRoute("/abc")).toEqual({ view: "appliance", deviceId: "abc" });
    expect(parseRoute("/a%2Fb?x=1")).toEqual({ view: "appliance", deviceId: "a/b" });
    expect(routePath(undefined, { view: "overview" })).toBe("/bruh-cooking");
    expect(routePath("/bruh-cooking/", { view: "appliance", deviceId: "a/b" })).toBe("/bruh-cooking/a%2Fb");
  });
});

describe("grouping", () => {
  it("puts ovens before sous vide in an area, and no area last", () => {
    const oven = FIXTURES["oven-idle"].appliance;
    const joule = FIXTURES["joule-idle"].appliance;
    const loose = { ...joule, device_id: "loose", name: "Aardvark" };
    const hass = fakeHass([FIXTURES["joule-idle"], FIXTURES["oven-idle"]]);
    hass.devices.loose = { id: "loose", name: "Aardvark", name_by_user: null, area_id: null };
    const groups = groupByArea([loose, joule, oven], hass);
    expect(groups.map((group) => group.name)).toEqual(["Kitchen", null]);
    expect(groups[0].appliances.map((entry) => entry.name)).toEqual(["Kitchen Oven", "Countertop"]);
  });
});

describe("announcements", () => {
  it("say what matters, once it changes", () => {
    expect(announcementKey("preheating", "ready")).toBe("announce.ready");
    expect(announcementKey("preheating", "cooking")).toBe("announce.preheated");
    expect(announcementKey("ready", "cooking")).toBeNull();
    expect(announcementKey("cooking", "cooking")).toBeNull();
    const announcer = new Announcer();
    expect(announcer.observe([{ id: "a", name: "Countertop", phase: "preheating" }], t)).toBeNull();
    expect(announcer.observe([{ id: "a", name: "Countertop", phase: "ready" }], t)).toBe("Countertop is ready for food.");
    expect(announcer.observe([{ id: "a", name: "Countertop", phase: "error", error: "Low water level" }], t)).toBe(
      "Countertop: Low water level.",
    );
  });
});
