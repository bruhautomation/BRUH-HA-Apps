import { html, nothing, type PropertyValues } from "lit";

import type { Control } from "../kinds/types";
import { ControlElement, defineOnce, icon, icons } from "./base";

type Select = Extract<Control, { kind: "select" }>;

/** Up to this many options show side by side; more go in a dropdown. */
export const SEGMENTED_MAX = 5;

const MOVES = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

/** Keys a closed native select applies a new value for at once: arrows and typed letters. */
function changesValue(event: KeyboardEvent): boolean {
  if (event.altKey || event.ctrlKey || event.metaKey) return false;
  return MOVES.has(event.key) || (event.key !== " " && [...event.key].length === 1);
}

/** Keys that open a native select's list. */
function opensList(event: KeyboardEvent): boolean {
  const alt = event.altKey && (event.key === "ArrowDown" || event.key === "ArrowUp");
  return alt || event.key === " " || event.key === "Enter" || event.key === "F4";
}

/** A choice of options: segmented pills for a few, a dropdown for more. */
export class BcSelect extends ControlElement<Select> {
  private value(): string | null {
    return typeof this.optimistic === "string" ? this.optimistic : (this.control?.value ?? null);
  }

  private pick(option: string): void {
    if (this.disabled || option === this.value()) return;
    this.send(option);
  }

  /**
   * Every change of a native select acts on the appliance, and a closed one changes on a typed
   * letter or an arrow key: typing "o" on a baking oven's Cooking mode would pick Off. Those keys
   * open the list instead, where a choice applies only with Enter or a click. Space, Enter and
   * Alt+Down open it as usual.
   */
  private readonly onKey = (event: KeyboardEvent): void => {
    const select = event.currentTarget as HTMLSelectElement & { showPicker?: () => void };
    if (this.disabled) {
      // Locked but focusable, so its reason is read out: it neither opens nor changes.
      if (changesValue(event) || opensList(event)) event.preventDefault();
      return;
    }
    if (!changesValue(event)) return;
    event.preventDefault();
    try {
      select.showPicker?.();
    } catch {
      // Not allowed here; the keys that open it natively still do.
    }
  };

  /**
   * The tiles are a listbox: the arrows, Home and End move between them, and Enter, Space or a
   * click picks one. Moving alone never picks, since picking an oven mode resets the settings.
   */
  private readonly onTileKey = (event: KeyboardEvent): void => {
    const tiles = [...this.renderRoot.querySelectorAll<HTMLElement>(".tiles [role=option]")];
    const index = tiles.indexOf(event.target as HTMLElement);
    if (index < 0) return;
    let next = -1;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = Math.min(tiles.length - 1, index + 1);
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = Math.max(0, index - 1);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tiles.length - 1;
    else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const option = this.control?.options[index];
      if (option) this.pick(option.value);
      return;
    }
    if (next < 0) return;
    event.preventDefault();
    for (const [position, tile] of tiles.entries()) tile.tabIndex = position === next ? 0 : -1;
    tiles[next].focus();
  };

  private renderTiles(control: Select, value: string | null) {
    const chosen = control.options.findIndex((option) => option.value === value);
    return this.frame(
      html`<div
        class="tiles ${this.disabled ? "disabled" : ""}"
        role="listbox"
        aria-labelledby="label"
        aria-describedby=${this.describedBy()}
        aria-disabled=${this.locked}
        @keydown=${this.onTileKey}
      >
        ${control.options.map(
          (option, index) => html`<div
            role="option"
            class="tile"
            aria-selected=${option.value === value ? "true" : "false"}
            tabindex=${index === (chosen < 0 ? 0 : chosen) ? "0" : "-1"}
            @click=${() => this.pick(option.value)}
          >
            ${option.label}
          </div>`,
        )}
      </div>`,
      { stacked: true },
    );
  }

  override render() {
    const control = this.control;
    if (!control) return nothing;
    const value = this.value();
    if (control.tiles) return this.renderTiles(control, value);
    const known = control.options.some((option) => option.value === value);
    if (control.options.length <= SEGMENTED_MAX) {
      const wide = control.options.length > 3 || control.options.some((option) => option.label.length > 12);
      // A value outside the choices (a fallback from the entity's sensor) shows under the label;
      // with no value, none of the choices is lit and the lock reason says why.
      const outside = known || value === null ? null : this.t("value.now", { value });
      const hint = [control.hint, outside].filter(Boolean).join("\n") || null;
      return this.frame(
        html`<div class="segmented ${this.disabled ? "disabled" : ""}" role="group" aria-labelledby="label">
          ${control.options.map(
            (option) => html`<button
              type="button"
              aria-pressed=${option.value === value ? "true" : "false"}
              aria-disabled=${this.locked}
              aria-describedby=${this.describedBy(hint)}
              @click=${() => this.pick(option.value)}
            >
              ${option.label}
            </button>`,
          )}
        </div>`,
        { stacked: wide, hint },
      );
    }
    return this.frame(
      html`<span class="dropdown">
        <select
          aria-labelledby="label"
          aria-disabled=${this.locked}
          aria-describedby=${this.describedBy()}
          @keydown=${this.onKey}
          @change=${(event: Event) => this.pick((event.target as HTMLSelectElement).value)}
        >
          ${known ? nothing : html`<option value="" disabled selected>${value === null ? "—" : value}</option>`}
          ${control.options.map(
            (option) => html`<option value=${option.value} ?selected=${option.value === value}>${option.label}</option>`,
          )}
        </select>
        ${icon(icons.chevron)}
      </span>`,
    );
  }

  protected override updated(changed: PropertyValues<this>): void {
    super.updated(changed);
    // A native select keeps the user's pick even when the entity says otherwise; show the entity's.
    const select = this.renderRoot.querySelector("select");
    const value = this.value();
    if (select && value !== null && select.value !== value && this.control?.options.some((option) => option.value === value)) {
      select.value = value;
    }
  }
}

defineOnce("bc-select", BcSelect);
