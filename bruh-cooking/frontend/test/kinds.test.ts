import { describe, expect, it } from "vitest";
import type { OvenState, SousVideState } from "../src/drawings/types";
import { kindModel } from "../src/kinds/index";
import type { Control, Section } from "../src/kinds/types";
import { contextFor } from "./context";

function sections(name: string, options = {}): Section[] {
  const ctx = contextFor(name, options);
  return kindModel(ctx.appliance).sections(ctx);
}

function control(list: Section[], section: string, id: string): Control | undefined {
  return list.find((each) => each.id === section)?.controls.find((each) => each.id === id);
}

describe("the Joule", () => {
  it.each([
    ["joule-idle", "idle", "Idle", "neutral"],
    ["joule-preheating", "preheating", "Preheating 69%", "warm"],
    ["joule-ready", "ready", "Ready for food", "green"],
    ["joule-cooking", "cooking", "Cooking", "warm"],
    ["joule-done", "done", "Done", "green"],
    ["joule-low-water", "error", "Low water level", "red"],
  ])("%s is %s", (name, phase, text, tone) => {
    const ctx = contextFor(name);
    const model = kindModel(ctx.appliance);
    expect(model.phase(ctx)).toBe(phase);
    expect(model.status(ctx)).toEqual({ text, tone });
    // The Joule has no display; its temperature sits on the container.
    expect(model.display(ctx)).toBeNull();
  });

  it("shows the water, the time left and when it ends", () => {
    const ctx = contextFor("joule-cooking");
    const rows = kindModel(ctx.appliance).infoRows(ctx);
    expect(rows[0]).toEqual({ label: "Water", value: "55.8° of 56°" });
    expect(rows[1].label).toBe("Time left");
    expect(rows[1].value).toMatch(/^1:12:00 · ends /);
  });

  it("asks for the food when it's ready", () => {
    const ctx = contextFor("joule-ready");
    const rows = kindModel(ctx.appliance).infoRows(ctx);
    expect(rows).toContainEqual({ label: "Next", value: "Add the food, then press Continue" });
    const cook = sections("joule-ready");
    const next = control(cook, "cook", "continue");
    expect(next).toMatchObject({ kind: "action", button: "Start the timer", disabled: false });
  });

  it("draws the bag once the food is in, and the low water", () => {
    const cooking = contextFor("joule-cooking");
    const state = kindModel(cooking.appliance).drawingState(cooking) as SousVideState;
    expect(state).toMatchObject({ running: true, food: true, heating: false, readout: "55.8°", error: null });
    const preheating = contextFor("joule-preheating");
    const heating = kindModel(preheating.appliance).drawingState(preheating) as SousVideState;
    expect(heating).toMatchObject({ heating: true, food: false, readout: "38.4°", targetReadout: "56°" });
    const low = contextFor("joule-low-water");
    expect((kindModel(low.appliance).drawingState(low) as SousVideState).error).toBe("low_water");
  });

  it("changes the running cook from its settings", () => {
    const list = sections("joule-cooking");
    expect(list.map((section) => section.id)).toEqual(["cook", "settings", "details"]);
    expect(list[1].title).toBe("This cook");
    const target = control(list, "settings", "target_temperature");
    expect(target).toMatchObject({ kind: "setpoint", value: 56, unit: "°C", step: 0.5, disabled: false, hint: "Changes the running cook." });
    expect(control(list, "cook", "stop")).toMatchObject({ button: "Stop", tone: "danger", confirm: "Stop the cook?" });
  });

  it("confirms a start with the settings", () => {
    const start = control(sections("joule-idle"), "cook", "start");
    expect(start).toMatchObject({ kind: "action", button: "Start", disabled: false });
    expect(start && "confirm" in start && start.confirm).toBe("Start the Joule Sous Vide at 60 °C until it's stopped?");
  });

  it("describes the drawing for a screen reader", () => {
    const ctx = contextFor("joule-cooking");
    expect(kindModel(ctx.appliance).describe(ctx)).toBe(
      "Joule Sous Vide clipped in a container of water. Water 55.8 °C, target 56 °C. Cooking. 1 hour, 12 minutes left. A bag of food is in the water.",
    );
  });

  it("follows the user's unit", () => {
    const ctx = contextFor("joule-cooking-us");
    expect(kindModel(ctx.appliance).infoRows(ctx)[0].value).toBe("132.4° of 132.8°");
  });
});

describe("the oven", () => {
  it.each([
    ["oven-idle", "idle", "Idle", "neutral"],
    ["oven-press-start", "press_start", "Press Start on the oven", "amber"],
    ["oven-preheating", "preheating", "Preheating 71%", "warm"],
    ["oven-ready", "ready", "Ready for food", "green"],
    ["oven-cooking", "cooking", "Cooking", "warm"],
    ["oven-door-open", "door_open", "Door open", "amber"],
    ["oven-finished", "done", "Done", "green"],
  ])("%s is %s", (name, phase, text, tone) => {
    const ctx = contextFor(name);
    const model = kindModel(ctx.appliance);
    expect(model.phase(ctx)).toBe(phase);
    expect(model.status(ctx)).toEqual({ text, tone });
  });

  it("shows its display as the oven does", () => {
    const display = (name: string) => {
      const ctx = contextFor(name);
      return kindModel(ctx.appliance).display(ctx);
    };
    expect(display("oven-idle")).toEqual({ text: "Off", caption: null, dim: true });
    expect(display("oven-preheating")).toEqual({ text: "219°", caption: "Bake · 350°", dim: false });
    expect(display("oven-cooking")).toEqual({ text: "7:48", caption: "Air fry · 400°", dim: false });
    expect(display("oven-finished")).toMatchObject({ text: "Done", dim: true });
  });

  it("lights its own display's segments as the oven does", () => {
    const lcd = (name: string) => {
      const ctx = contextFor(name);
      return (kindModel(ctx.appliance).drawingState(ctx) as OvenState).lcd;
    };
    // Asleep while idle.
    expect(lcd("oven-idle")).toBeNull();
    // Waiting for Start: pale, the cook's settings and the rack, PRESS START.
    expect(lcd("oven-press-start")).toMatchObject({ lit: false, mode: "bake", temp: "329", unit: "F", rack: 6, prompt: "press_start" });
    expect(lcd("oven-preheating")).toMatchObject({ lit: true, prompt: "preheating", rack: 6 });
    // Cooking: orange, the time left in minutes and seconds.
    expect(lcd("oven-cooking")).toMatchObject({
      lit: true, mode: "air_fry", temp: "400", unit: "F", time: "7:48", timeUnits: "min_sec", convection: "super", rack: null, prompt: null,
    });
    expect(lcd("oven-cooking-metric")).toMatchObject({ temp: "205", unit: "C" });
    expect(lcd("oven-finished")).toMatchObject({ lit: false, time: "donE", timeUnits: null });
  });

  it("keeps the cook's food in the oven while it keeps warm", () => {
    const ctx = contextFor("oven-keeping-warm");
    const model = kindModel(ctx.appliance);
    expect(model.phase(ctx)).toBe("keeping_warm");
    expect(model.status(ctx).text).toBe("Keeping warm");
    expect(model.drawingState(ctx)).toMatchObject({
      mode: "bake", rack: 6, accessory: "roasting_pan", food: "croissants", elements: "low",
      lcd: { lit: true, mode: "keep_warm", temp: null, time: "59:58", timeUnits: "min_sec" },
    });
  });

  it("counts down while the timer runs, and holds while the door is open", () => {
    const later = contextFor("oven-cooking", { seconds: 30 });
    expect(kindModel(later.appliance).display(later)?.text).toBe("7:18");
    const paused = contextFor("oven-door-open", { seconds: 30 });
    expect(kindModel(paused.appliance).display(paused)?.text).toBe("6:42");
  });

  it("draws the mode's rack, accessory, food and elements", () => {
    const idle = contextFor("oven-idle");
    expect(kindModel(idle.appliance).drawingState(idle)).toMatchObject({
      mode: "bake", rack: 6, accessory: "roasting_pan", food: null, elements: null, fan: "off", door_open: false,
    });
    const cooking = contextFor("oven-cooking");
    expect(kindModel(cooking.appliance).drawingState(cooking)).toMatchObject({
      mode: "air_fry", rack: 3, accessory: "air_fry_basket", food: "fries", elements: "top", fan: "super", light: true,
    });
    const door = contextFor("oven-door-open");
    const open = kindModel(door.appliance).drawingState(door) as OvenState;
    expect(open).toMatchObject({ door_open: true, food: "fries", elements: null, light: true });
    const start = contextFor("oven-press-start");
    expect((kindModel(start.appliance).drawingState(start) as OvenState).start_prompt).toBe(true);
  });

  it("can't change a running cook", () => {
    const list = sections("oven-cooking");
    const settings = list.find((section) => section.id === "settings")!;
    expect(settings.note).toBe("A running oven cook can't be changed. Stop it to change the settings.");
    expect(settings.controls.every((each) => each.disabled)).toBe(true);
    // Stopping always works.
    expect(control(list, "cook", "stop")).toMatchObject({ disabled: false });
  });

  it("tells where it holds its sensor, below the setpoint", () => {
    const reading = control(sections("oven-cooking"), "cook", "current_temperature");
    expect(reading).toMatchObject({ value: "370 °F", hint: "It holds its sensor at 376 °F, below the setpoint." });
  });

  it("offers Finish once it has turned itself off", () => {
    const finish = control(sections("oven-finished"), "cook", "stop");
    expect(finish).toMatchObject({ button: "Finish", confirm: null, tone: "primary" });
  });

  it("offers only the settings the mode has", () => {
    const ids = sections("oven-idle")
      .find((section) => section.id === "settings")!
      .controls.map((each) => each.id);
    expect(ids).toEqual(["oven_mode", "target_temperature", "cook_time", "convection", "keep_warm", "auto_start_timer"]);
  });

  it("keeps an appliance nobody has tested to monitoring, with a way for admins to allow it", () => {
    const fixture = contextFor("oven-idle");
    const ctx = { ...fixture, appliance: { ...fixture.appliance, tested: false, control_allowed: false } };
    const start = kindModel(ctx.appliance)
      .sections(ctx)
      .find((section) => section.id === "cook")!
      .controls.find((each) => each.id === "start");
    expect(start).toMatchObject({
      disabled: true,
      reason: "Control of the Joule Oven Air Fryer Pro hasn't been tested yet, so Home Assistant only monitors it.",
      link: { text: "Allow control in the integration's options", href: "/config/integrations/integration/bruh_cooking" },
    });
  });

  it("describes the drawing for a screen reader", () => {
    const ctx = contextFor("oven-cooking");
    expect(kindModel(ctx.appliance).describe(ctx)).toBe(
      "Joule Oven Air Fryer Pro in brushed stainless steel. Cooking. Air fry, 400°. Inside 370 °F. 8 minutes left. " +
        "Rack in position 3 with fries on the air fry basket. The fan is on high.",
    );
  });
});
