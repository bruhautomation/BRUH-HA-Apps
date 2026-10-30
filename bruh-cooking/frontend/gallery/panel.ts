import "./freeze-time";
import "../src/bruh-cooking-panel";
import { fakeHass } from "../test/fixtures/hass";
import { FIXTURES } from "../test/fixtures/panel";

// Query: fixtures (comma-separated names from tests/fixtures/panel), path ("" for the overview,
// or "/device-oven"), theme (light or dark), lang, units (metric or us_customary), admin (0 for a
// user), narrow (1 for the phone layout), width.
const params = new URLSearchParams(location.search);
const names = (params.get("fixtures") ?? "oven-cooking,joule-cooking-us").split(",").filter(Boolean);
const fixtures = names.map((name) => FIXTURES[name]).filter(Boolean);
const dark = params.get("theme") === "dark";
document.documentElement.dataset.theme = dark ? "dark" : "light";
document.documentElement.lang = params.get("lang") ?? "en";
const units = params.get("units");
const hass = fakeHass(fixtures, {
  dark,
  language: params.get("lang") ?? "en",
  admin: params.get("admin") !== "0",
  units: units === "metric" || units === "us_customary" ? units : undefined,
});
const panel = document.createElement("bruh-cooking-panel") as unknown as HTMLElement & Record<string, unknown>;
panel.hass = hass;
panel.narrow = params.get("narrow") === "1";
panel.route = { prefix: "/bruh-cooking", path: params.get("path") ?? "" };
panel.panel = { title: params.get("title") ?? "Breville+" };
document.querySelector("#frame")!.append(panel);
(window as unknown as { __hass: unknown }).__hass = hass;
setTimeout(() => {
  (window as unknown as { __panelReady: boolean }).__panelReady = true;
}, 400);
