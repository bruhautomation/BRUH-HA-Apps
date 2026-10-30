import { html, nothing } from "lit";
import { formatCountdown } from "../kinds/common";
import type { Control } from "../kinds/types";
import { ControlElement, defineOnce } from "./base";
import { readingStyles } from "./reading";

type Countdown = Extract<Control, { kind: "countdown" }>;

/** Time left, ticking every second while the timer runs and holding while it's paused. */
export class BcCountdown extends ControlElement<Countdown> {
  static override styles = [...ControlElement.styles, readingStyles];

  private timer: ReturnType<typeof setTimeout> | undefined;

  override connectedCallback(): void {
    super.connectedCallback();
    this.tick();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    clearTimeout(this.timer);
    this.timer = undefined;
  }

  // On the second, so the countdown changes with the panel's clock and the appliance's own.
  private readonly tick = (): void => {
    this.requestUpdate();
    this.timer = setTimeout(this.tick, 1000 - (Date.now() % 1000) + 5);
  };

  override render() {
    const control = this.control;
    if (!control) return nothing;
    const ms = control.end !== null ? control.end - Date.now() : control.seconds !== null ? control.seconds * 1000 : null;
    // Not a live region: it changes every second. The view announces what matters.
    return this.frame(html`<span class="reading" role="timer" aria-live="off">${ms === null ? "—" : formatCountdown(ms)}</span>`);
  }
}

defineOnce("bc-countdown", BcCountdown);
