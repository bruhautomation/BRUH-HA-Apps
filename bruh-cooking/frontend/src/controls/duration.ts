import { html, nothing } from "lit";
import { formatDuration } from "../kinds/common";
import type { Control } from "../kinds/types";
import { ControlElement, defineOnce } from "./base";

type Duration = Extract<Control, { kind: "duration" }>;

/** A cook time in minutes: the presets, and a custom time in hours and minutes. */
export class BcDuration extends ControlElement<Duration> {
  static override properties = { custom: { state: true } };

  declare custom: boolean;

  constructor() {
    super();
    this.custom = false;
  }

  private value(): number | null {
    return typeof this.optimistic === "number" ? this.optimistic : (this.control?.value ?? null);
  }

  private choose(minutes: number): void {
    const control = this.control;
    if (!control || this.disabled || !Number.isFinite(minutes)) return;
    const value = Math.min(control.max, Math.max(control.min, Math.round(minutes)));
    this.custom = false;
    if (value !== this.value()) this.send(value);
  }

  private readonly onSubmit = (event: Event): void => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const hours = form.querySelector<HTMLInputElement>("input[name=hours]");
    const minutes = form.querySelector<HTMLInputElement>("input[name=minutes]");
    if (!hours || !minutes || !hours.checkValidity() || !minutes.checkValidity()) {
      (hours?.checkValidity() === false ? hours : minutes)?.reportValidity();
      return;
    }
    const total = Number(hours.value || 0) * 60 + Number(minutes.value || 0);
    const control = this.control;
    if (control && (total < control.min || total > control.max)) {
      minutes.setCustomValidity(this.t("ctl.out_of_range", { min: this.minutes(control.min), max: this.minutes(control.max) }));
      minutes.reportValidity();
      minutes.setCustomValidity("");
      return;
    }
    this.choose(total);
  };

  private minutes(value: number): string {
    return value === 0 ? (this.control?.zero ?? this.t("ctl.off")) : formatDuration(this.t, value * 60);
  }

  override render() {
    const control = this.control;
    if (!control) return nothing;
    const value = this.value();
    const presets = [...new Set(control.presets)].filter((minutes) => minutes >= control.min && minutes <= control.max);
    const custom = value !== null && !presets.includes(value);
    const disabled = this.disabled;
    const describedBy = this.describedBy();
    const hours = value === null ? "" : String(Math.floor(value / 60));
    const minutes = value === null ? "" : String(value % 60);
    return this.frame(
      html`<div class="chips" role="group" aria-labelledby="label">
          ${presets.map(
            (minutes) => html`<button
              type="button"
              class="bc-button"
              aria-pressed=${minutes === value ? "true" : "false"}
              aria-disabled=${this.locked}
              aria-describedby=${describedBy}
              @click=${() => this.choose(minutes)}
            >
              ${this.minutes(minutes)}
            </button>`,
          )}
          <button
            type="button"
            class="bc-button"
            aria-pressed=${custom ? "true" : "false"}
            aria-expanded=${this.custom && !disabled ? "true" : "false"}
            aria-disabled=${this.locked}
            aria-describedby=${describedBy}
            @click=${() => {
              if (!this.disabled) this.custom = !this.custom;
            }}
          >
            ${this.t("ctl.custom")}
          </button>
        </div>
        ${this.custom && !disabled
          ? html`<form class="chips custom" @submit=${this.onSubmit}>
              <label
                ><input
                  name="hours"
                  type="number"
                  inputmode="numeric"
                  min="0"
                  max=${Math.floor(control.max / 60)}
                  step="1"
                  .value=${hours}
                  aria-label=${this.t("ctl.hours")}
                /><span aria-hidden="true">${this.t("ctl.h")}</span></label
              >
              <label
                ><input
                  name="minutes"
                  type="number"
                  inputmode="numeric"
                  min="0"
                  max="59"
                  step="1"
                  .value=${minutes}
                  aria-label=${this.t("ctl.minutes")}
                /><span aria-hidden="true">${this.t("ctl.min")}</span></label
              >
              <button type="submit" class="bc-button primary">${this.t("ctl.set")}</button>
            </form>`
          : nothing}`,
      { stacked: true, aside: value === null ? null : this.minutes(value) },
    );
  }
}

defineOnce("bc-duration", BcDuration);
