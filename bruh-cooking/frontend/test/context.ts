import { makeTranslate } from "../src/i18n";
import { makeContext, sharedFrom } from "../src/kinds/index";
import type { ApplianceContext } from "../src/kinds/types";
import { fakeHass, type FakeOptions } from "./fixtures/hass";
import { FIXTURES, SHARED } from "./fixtures/panel";

export const SHARED_DATA = sharedFrom(SHARED.oven_modes, SHARED.presets);

/** A kind model's context for one fixture, at the moment its states were written. */
export function contextFor(name: string, options: FakeOptions & { seconds?: number } = {}): ApplianceContext {
  const fixture = FIXTURES[name];
  if (!fixture) throw new Error(`No fixture ${name}`);
  const hass = fakeHass([fixture], options);
  const now = Date.parse(fixture.now) + (options.seconds ?? 0) * 1000;
  return makeContext(fixture.appliance, hass, makeTranslate(options.language ?? "en"), now, SHARED_DATA);
}
