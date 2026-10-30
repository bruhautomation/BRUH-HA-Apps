import { html, nothing } from "lit";
import type { Control } from "../kinds/types";
import { ControlElement, defineOnce } from "./base";

type Toggle = Extract<Control, { kind: "toggle" }>;

/** An on/off switch. */
export class BcToggle extends ControlElement<Toggle> {
  private value(): boolean | null {
    return typeof this.optimistic === "boolean" ? this.optimistic : (this.control?.value ?? null);
  }

  private flip(): void {
    if (this.disabled) return;
    this.send(!this.value());
  }

  override render() {
    if (!this.control) return nothing;
    const value = this.value();
    // A locked or unavailable entity has no state to show, so it reads as unknown, never as off.
    if (value === null && this.disabled) return this.frame(html`<span class="reading">—</span>`);
    return this.frame(html`<button
      type="button"
      class="switch ${value === null ? "unknown" : ""}"
      role="switch"
      aria-checked=${value === true ? "true" : "false"}
      aria-labelledby="label"
      aria-disabled=${this.locked}
      aria-describedby=${this.describedBy()}
      @click=${() => this.flip()}
    ></button>`);
  }
}

defineOnce("bc-toggle", BcToggle);
