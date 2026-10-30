// @vitest-environment happy-dom
import { render } from "lit";
import { describe, expect, it } from "vitest";
import { variants as oven } from "../gallery/variants/oven";
import { variants as sousVide } from "../gallery/variants/sous-vide";
import { ApplianceCard } from "../src/card/appliance-card";
import { renderDrawing } from "../src/drawings/index";
import { ApplianceView } from "../src/views/appliance-view";

const ALL = [...sousVide, ...oven];

function draw(index: number, theme: "light" | "dark" = "light"): SVGSVGElement {
  const variant = ALL[index];
  const host = document.createElement("div");
  render(renderDrawing({ ...variant.input, uid: `t${index}`, theme, reducedMotion: true, pixelHeight: 300 }), host);
  const svg = host.querySelector("svg");
  if (!svg) throw new Error(`${variant.id} drew no svg`);
  return svg;
}

describe("drawings", () => {
  it.each(ALL.map((variant, index) => [variant.id, index] as const))("%s draws one svg with its own ids", (_id, index) => {
    for (const theme of ["light", "dark"] as const) {
      const svg = draw(index, theme);
      expect(svg.getAttribute("viewBox")).toMatch(/^-?[\d.]+ -?[\d.]+ [\d.]+ [\d.]+$/);
      expect(svg.getAttribute("aria-hidden")).toBe("true");
      // Several drawings share a shadow root, so every id carries the drawing's uid.
      const ids = [...svg.querySelectorAll("[id]")].map((element) => element.id);
      expect(ids.filter((id) => !id.startsWith(`t${index}-`))).toEqual([]);
      expect(new Set(ids).size).toBe(ids.length);
      // Every url(#…) points at one of them.
      const references = [...svg.outerHTML.matchAll(/url\(#([^)]+)\)/g)].map((match) => match[1]);
      expect(references.filter((id) => !ids.includes(id))).toEqual([]);
      expect(svg.outerHTML).not.toMatch(/NaN|undefined|Infinity/);
    }
  });

  it("animates nothing when motion is reduced", () => {
    const index = ALL.findIndex((variant) => variant.id === "joule-hot");
    const still = draw(index);
    expect(still.querySelector("style")).toBeNull();
    expect(still.querySelector('[class*="-wisp"], [class*="-ripple"]')).toBeNull();
    // (happy-dom drops an SVG <style>'s text, so the classes stand in for it; scripts/render.mjs
    // --motion shows the animation in Chrome.)
    const host = document.createElement("div");
    render(renderDrawing({ ...ALL[index].input, uid: "m", theme: "light", reducedMotion: false }), host);
    expect(host.querySelector("style")).not.toBeNull();
    expect(host.querySelectorAll(".m-wisp").length).toBeGreaterThan(0);
    expect(host.querySelectorAll(".m-ripple").length).toBe(3);
  });

  it("uses no class the card's or the full view's styles also style", () => {
    // The drawing sits in the card's shadow root, so a class the card styles (its readout is
    // `.lcd`) would restyle part of the drawing too.
    const sheets = [ApplianceCard.styles, ApplianceView.styles].flat(Infinity) as Array<{ cssText: string }>;
    const styled = new Set(sheets.flatMap((sheet) => [...sheet.cssText.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((match) => match[1])));
    const used = new Set<string>();
    ALL.forEach((_, index) => {
      for (const element of draw(index).querySelectorAll("[class]")) {
        for (const name of element.getAttribute("class")?.split(/\s+/) ?? []) {
          if (name && !name.startsWith(`t${index}-`)) used.add(name);
        }
      }
    });
    expect([...used].filter((name) => styled.has(name))).toEqual([]);
  });

  it("desaturates an appliance that's offline", () => {
    const index = ALL.findIndex((variant) => variant.id === "oven-bake-offline");
    expect(draw(index).getAttribute("style")).toContain("grayscale");
  });
});
