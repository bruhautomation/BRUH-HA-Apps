import { html, nothing } from "lit";
import type { Control } from "../kinds/types";
import { ControlElement, defineOnce, icon, icons } from "./base";

type Setpoint = Extract<Control, { kind: "setpoint" }>;

/** How long after the last press the stepper sends its value, so several presses make one call. */
export const COMMIT_DELAY_MS = 600;

/** Writes a number with a fixed count of decimals, in the user's number format. */
export type NumberFormatter = (value: number, decimals: number) => string;

const fixed: NumberFormatter = (value, decimals) => value.toFixed(decimals);

function decimals(step: number): number {
  const text = String(step);
  return text.includes(".") ? text.length - text.indexOf(".") - 1 : 0;
}

function round(value: number, step: number): number {
  return Number(value.toFixed(decimals(step)));
}

/** A setpoint: minus and plus around the value and its unit, sent 600 ms after the last press. */
export class BcSetpoint extends ControlElement<Setpoint> {
  static override properties = { formatNumber: { attribute: false } };

  /** The user's number format (a decimal comma, say); plain digits when unset. */
  declare formatNumber: NumberFormatter | undefined;
  private commitTimer: ReturnType<typeof setTimeout> | undefined;

  override disconnectedCallback(): void {
    // Leaving the view right after a press still sends it; the view's listener is on this element.
    if (this.commitTimer !== undefined) this.commit();
    super.disconnectedCallback();
  }

  private shown(): number | null {
    return typeof this.optimistic === "number" ? this.optimistic : (this.control?.value ?? null);
  }

  private bump(direction: number): void {
    const control = this.control;
    if (!control || this.disabled) return;
    const value = this.shown();
    // With no value yet, the first press starts from the middle of the range. A value off the step's
    // grid (165 °C shown as 329 °F, with 5° steps) moves to the grid first: 330, then 335.
    const step = control.step;
    const grid = (x: number) => round(Math.round(x / step) * step, step);
    let start: number;
    if (value === null) start = control.min + Math.round((control.max - control.min) / 2 / step) * step;
    else if (grid(value) === round(value, step)) start = value + direction * step;
    else {
      const snapped = direction > 0 ? Math.ceil(value / step) * step : Math.floor(value / step) * step;
      start = snapped + (direction - Math.sign(direction)) * step;
    }
    const next = Math.min(control.max, Math.max(control.min, round(start, step)));
    // At a limit the button stays focusable (see render), and a press there does nothing.
    if (next === value) return;
    this.optimistic = next;
    clearTimeout(this.commitTimer);
    this.commitTimer = setTimeout(() => this.commit(), COMMIT_DELAY_MS);
  }

  private commit(): void {
    clearTimeout(this.commitTimer);
    this.commitTimer = undefined;
    const value = this.optimistic;
    if (typeof value !== "number") return;
    if (value === this.control?.value) {
      this.clearOptimistic();
      return;
    }
    this.send(value);
  }

  private readonly onKey = (event: KeyboardEvent): void => {
    // Arrows step once; Page Up and Page Down ten steps, for the oven's wide range.
    const direction =
      event.key === "ArrowUp" || event.key === "ArrowRight"
        ? 1
        : event.key === "ArrowDown" || event.key === "ArrowLeft"
          ? -1
          : event.key === "PageUp"
            ? 10
            : event.key === "PageDown"
              ? -10
              : 0;
    if (!direction) return;
    event.preventDefault();
    this.bump(direction);
  };

  override render() {
    const control = this.control;
    if (!control) return nothing;
    const value = this.shown();
    const disabled = this.disabled;
    // A button at its limit or locked is only marked so: disabling it would drop the keyboard's focus.
    const atMin = value !== null && value <= control.min;
    const atMax = value !== null && value >= control.max;
    const describedBy = this.describedBy();
    return this.frame(html`
      <div class="stepper ${this.commitTimer !== undefined ? "draft" : ""}" role="group" aria-labelledby="label" @keydown=${this.onKey}>
        <button
          type="button"
          aria-label=${this.t("ctl.decrease")}
          aria-disabled=${atMin || disabled ? "true" : nothing}
          aria-describedby=${describedBy}
          @click=${() => this.bump(-1)}
        >
          ${icon(icons.minus)}
        </button>
        <!-- No setpoint (an oven that's off) reads as a blank display, not as a number. -->
        <output aria-live="polite" class=${value === null ? "empty" : nothing}>
          ${value === null ? "--" : (this.formatNumber ?? fixed)(value, decimals(control.step))}<span class="unit">${control.unit}</span>
        </output>
        <button
          type="button"
          aria-label=${this.t("ctl.increase")}
          aria-disabled=${atMax || disabled ? "true" : nothing}
          aria-describedby=${describedBy}
          @click=${() => this.bump(1)}
        >
          ${icon(icons.plus)}
        </button>
      </div>
    `);
  }
}

defineOnce("bc-setpoint", BcSetpoint);
