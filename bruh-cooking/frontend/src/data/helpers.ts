import { CookHistory } from "./history";

/**
 * The page's helpers: the temperature history the chart reads. It answers synchronously and fills
 * in later, so whoever draws subscribes with `onChange` to draw again. One per page rather than
 * per element, so the history outlives the element when Home Assistant swaps it out.
 */
export class PanelHelpers {
  readonly history: CookHistory;
  private readonly listeners = new Set<() => void>();

  constructor(now: () => number = Date.now) {
    this.history = new CookHistory(() => this.notify(), now);
  }

  /** Calls `listener` when history arrives; returns the unsubscribe function. */
  onChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const listener of [...this.listeners]) listener();
  }
}

export const panelHelpers = new PanelHelpers();
