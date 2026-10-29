import type { Translate } from "../i18n";
import type { Phase } from "../kinds/types";

export interface Observed {
  id: string;
  name: string;
  phase: Phase;
  /** The error in the Error sensor's words, for an error. */
  error?: string | null;
}

/** What to announce when an appliance moves from one phase to another; null for nothing. */
export function announcementKey(before: Phase, after: Phase): string | null {
  if (before === after) return null;
  switch (after) {
    case "ready":
      return "announce.ready";
    case "cooking":
      // Straight from preheating when the timer starts by itself.
      return before === "preheating" ? "announce.preheated" : null;
    case "done":
      return "announce.done";
    case "door_open":
      return "announce.door_open";
    case "press_start":
      return "announce.press_start";
    case "error":
      return "announce.error";
    case "offline":
      return "announce.offline";
    default:
      return null;
  }
}

/**
 * Follows each appliance's phase and says the changes that matter: ready for food, preheated,
 * done, the door opening, Start to press, an error and going offline. Temperatures and timers
 * aren't announced: they change all the time. Nothing is said for an appliance's first phase.
 */
export class Announcer {
  private readonly phases = new Map<string, Phase>();

  observe(appliances: readonly Observed[], t: Translate): string | null {
    const messages: string[] = [];
    for (const appliance of appliances) {
      const before = this.phases.get(appliance.id);
      this.phases.set(appliance.id, appliance.phase);
      if (before === undefined) continue;
      const key = announcementKey(before, appliance.phase);
      if (key) messages.push(t(key, { name: appliance.name, error: appliance.error ?? "" }));
    }
    return messages.length ? messages.join(" ") : null;
  }
}
