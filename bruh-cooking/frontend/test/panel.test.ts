// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from "vitest";
import "../src/bruh-cooking-panel";
import type { ApplianceCard } from "../src/card/appliance-card";
import type { Control } from "../src/kinds/types";
import "../src/controls/select";
import "../src/views/presets";
import type { Presets } from "../src/views/presets";
import { fakeHass, type FakeHass } from "./fixtures/hass";
import { FIXTURES } from "./fixtures/panel";

type Panel = HTMLElement & { hass: unknown; route: unknown; panel: unknown; updateComplete: Promise<boolean> };

async function settle(element: Element | null | undefined): Promise<void> {
  // Lit renders asynchronously, and each nested element renders after its parent.
  for (let round = 0; round < 6; round++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    const all = [element, ...deep(element)];
    await Promise.all(all.map((each) => (each as { updateComplete?: Promise<unknown> } | null)?.updateComplete));
  }
}

function deep(root: Element | null | undefined): Element[] {
  const found: Element[] = [];
  const walk = (node: Element | ShadowRoot | null | undefined) => {
    if (!node) return;
    for (const child of Array.from(node.children ?? [])) {
      found.push(child);
      walk(child);
      walk((child as Element).shadowRoot);
    }
  };
  walk(root);
  walk(root?.shadowRoot);
  return found;
}

function find<T extends Element = Element>(root: Element, selector: string): T | undefined {
  return deep(root).find((each) => each.matches(selector)) as T | undefined;
}

async function mount(names: string[], path = ""): Promise<{ panel: Panel; hass: FakeHass }> {
  const hass = fakeHass(names.map((name) => FIXTURES[name]));
  const panel = document.createElement("bruh-cooking-panel") as Panel;
  panel.hass = hass;
  panel.route = { prefix: "/bruh-cooking", path };
  panel.panel = { title: "Breville+" };
  document.body.append(panel);
  await settle(panel);
  return { panel, hass };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("the panel", () => {
  it("shows every appliance on the overview", async () => {
    const { panel } = await mount(["oven-cooking", "joule-cooking-us"]);
    const cards = deep(panel).filter((each) => each.matches("bc-appliance-card")) as ApplianceCard[];
    expect(cards).toHaveLength(2);
    expect(panel.shadowRoot!.querySelector(".title")!.textContent).toBe("Breville+");
    expect(panel.shadowRoot!.querySelector(".toolbar .icon-button")).toBeNull();
  });

  it("opens the only appliance straight away, without a way back", async () => {
    const { panel } = await mount(["joule-cooking"]);
    expect(find(panel, "bc-overview")).toBeUndefined();
    expect(find(panel, "bc-appliance-view")).toBeDefined();
    expect(panel.shadowRoot!.querySelector(".title")!.textContent).toBe("Countertop");
    expect(panel.shadowRoot!.querySelector('[aria-label="Back"]')).toBeNull();
  });

  it("has a way back from an appliance when there are more", async () => {
    const { panel } = await mount(["oven-cooking", "joule-cooking-us"], "/device-oven");
    expect(find(panel, "bc-appliance-view")).toBeDefined();
    expect(panel.shadowRoot!.querySelector('[aria-label="Back"]')).not.toBeNull();
  });

  it("names each card's button and describes its drawing", async () => {
    const { panel } = await mount(["oven-cooking", "joule-cooking-us"]);
    const card = deep(panel).find((each) => each.matches("bc-appliance-card"))!;
    const button = card.shadowRoot!.querySelector("button.open")!;
    expect(button.textContent!.trim()).toBe("Kitchen Oven");
    expect(button.getAttribute("aria-describedby")).toBe("status hint");
    const drawing = card.shadowRoot!.querySelector(".drawing")!;
    expect(drawing.getAttribute("role")).toBe("img");
    expect(drawing.getAttribute("aria-label")).toMatch(/^Joule Oven Air Fryer Pro in brushed stainless steel\. Cooking\./);
  });

  it("announces what changes, not every reading", async () => {
    const { panel, hass } = await mount(["joule-preheating", "oven-idle"]);
    const region = () => panel.shadowRoot!.querySelector('[aria-live="polite"]')!.textContent!.trim();
    expect(region()).toBe("");
    (panel as unknown as { hass: FakeHass }).hass = hass.withStates({ "sensor.countertop_temperature": { state: "40.1" } });
    await settle(panel);
    expect(region()).toBe("");
    (panel as unknown as { hass: FakeHass }).hass = hass.withStates({ "sensor.countertop_status": { state: "ready" } });
    await settle(panel);
    expect(region()).toBe("Countertop is ready for food.");
  });
});

describe("the mode tiles", () => {
  const control: Control = {
    kind: "select",
    id: "oven_mode",
    label: "Mode",
    action: { type: "select", entity_id: "select.kitchen_oven_mode" },
    value: "bake",
    tiles: true,
    options: [
      { value: "bake", label: "Bake" },
      { value: "air_fry", label: "Air fry" },
      { value: "roast", label: "Roast" },
    ],
  };

  it("are a listbox the arrows move through, picking only with Enter", async () => {
    const select = document.createElement("bc-select") as HTMLElement & { control: Control };
    select.control = control;
    const values: unknown[] = [];
    select.addEventListener("bc-value", (event) => values.push((event as CustomEvent).detail.value));
    document.body.append(select);
    await settle(select);
    const list = select.shadowRoot!.querySelector('[role="listbox"]')!;
    const options = [...list.querySelectorAll<HTMLElement>('[role="option"]')];
    expect(options.map((each) => each.getAttribute("aria-selected"))).toEqual(["true", "false", "false"]);
    expect(options.map((each) => each.tabIndex)).toEqual([0, -1, -1]);
    options[0].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(options.map((each) => each.tabIndex)).toEqual([-1, 0, -1]);
    expect(values).toEqual([]);
    options[1].dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(values).toEqual(["air_fry"]);
  });
});

describe("errors", () => {
  it("are shown in the user's language, not the server's", async () => {
    // Home Assistant writes the message in the server's language (English here); the user reads German.
    const hass = fakeHass([FIXTURES["oven-idle"]], {
      language: "de",
      failWith: {
        code: "service_validation_error",
        message: "Stop the cook before changing this setting.",
        translation_domain: "bruh_cooking",
        translation_key: "stop_cook_first",
        translation_placeholders: {},
      },
      backend: {
        "component.bruh_cooking.exceptions.stop_cook_first.message": "Stoppe den Garvorgang, bevor du diese Einstellung änderst.",
      },
    });
    const panel = document.createElement("bruh-cooking-panel") as Panel;
    panel.hass = hass;
    panel.route = { prefix: "/bruh-cooking", path: "" };
    panel.panel = { title: "Breville+" };
    document.body.append(panel);
    await settle(panel);
    const tile = find<HTMLElement>(panel, '[role="option"][aria-selected="false"]')!;
    tile.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await settle(panel);
    expect(hass.calls.some((call) => call.kind === "service")).toBe(true);
    expect(find(panel, '.error[role="alert"]')?.textContent).toBe("Stoppe den Garvorgang, bevor du diese Einstellung änderst.");
  });

  it("fall back to the server's words without a translation", async () => {
    const hass = fakeHass([FIXTURES["oven-idle"]], {
      failWith: { code: "home_assistant_error", message: "The Breville cloud didn't answer." },
    });
    const panel = document.createElement("bruh-cooking-panel") as Panel;
    panel.hass = hass;
    panel.route = { prefix: "/bruh-cooking", path: "" };
    panel.panel = { title: "Breville+" };
    document.body.append(panel);
    await settle(panel);
    const tile = find<HTMLElement>(panel, '[role="option"][aria-selected="false"]')!;
    tile.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await settle(panel);
    expect(find(panel, '.error[role="alert"]')?.textContent).toBe("The Breville cloud didn't answer.");
  });
});

describe("presets", () => {
  it("fill in the settings and hand focus on, starting nothing", async () => {
    const hass = fakeHass([FIXTURES["joule-idle"]]);
    const presets = document.createElement("bc-presets") as Presets;
    presets.hass = hass;
    presets.appliance = FIXTURES["joule-idle"].appliance;
    presets.presets = hass.message.presets;
    let applied = 0;
    presets.addEventListener("bc-preset-applied", () => applied++);
    document.body.append(presets);
    await settle(presets);
    const buttons = [...presets.shadowRoot!.querySelectorAll<HTMLButtonElement>("button.apply")];
    expect(buttons).toHaveLength(15);
    const rare = buttons.find((each) => each.textContent!.includes("Steak, rare"))!;
    rare.click();
    await settle(presets);
    expect(hass.calls).toContainEqual({
      kind: "ws",
      data: { type: "bruh_cooking/panel/apply_preset", device_id: "device-joule", preset_id: "steak_rare" },
    });
    expect(hass.calls.some((call) => call.kind === "service")).toBe(false);
    expect(applied).toBe(1);
    expect(presets.shadowRoot!.querySelector('[role="status"]')!.textContent).toBe(
      "Filled in from Steak, rare. Press Start when you're ready.",
    );
  });

  it("wait while a cook is under way", async () => {
    const hass = fakeHass([FIXTURES["joule-cooking"]]);
    const presets = document.createElement("bc-presets") as Presets;
    presets.hass = hass;
    presets.appliance = FIXTURES["joule-cooking"].appliance;
    presets.presets = hass.message.presets;
    presets.cooking = true;
    document.body.append(presets);
    await settle(presets);
    const first = presets.shadowRoot!.querySelector<HTMLButtonElement>("button.apply")!;
    expect(first.getAttribute("aria-disabled")).toBe("true");
    first.click();
    await settle(presets);
    expect(hass.calls.filter((call) => call.data.type === "bruh_cooking/panel/apply_preset")).toEqual([]);
  });
});

describe("the setpoint", () => {
  it("steps along its grid, snapping a value that's off it", async () => {
    await import("../src/controls/setpoint");
    const stepper = document.createElement("bc-setpoint") as HTMLElement & { control: Control; updateComplete: Promise<unknown> };
    stepper.control = {
      kind: "setpoint",
      id: "target_temperature",
      label: "Temperature",
      action: { type: "number", entity_id: "number.kitchen_oven_target_temperature" },
      value: 329,
      min: 122,
      max: 482,
      step: 5,
      unit: "°F",
    };
    document.body.append(stepper);
    await settle(stepper);
    const [down, up] = [...stepper.shadowRoot!.querySelectorAll<HTMLButtonElement>(".stepper button")];
    const shown = () => stepper.shadowRoot!.querySelector("output")!.textContent!.replace(/\s+/g, "");
    up.click();
    await settle(stepper);
    expect(shown()).toBe("330°F");
    up.click();
    await settle(stepper);
    expect(shown()).toBe("335°F");
    down.click();
    down.click();
    down.click();
    await settle(stepper);
    expect(shown()).toBe("320°F");
  });
});
