import { html, nothing } from "lit";
import { partStyles, renderConfirmBar } from "../card/parts";
import type { Control } from "../kinds/types";
import { ControlElement, defineOnce } from "./base";

type Action = Extract<Control, { kind: "action" }>;

/**
 * A button. One with a question asks it first in the GE card's inline confirmation bar (the
 * question, Not now, and the action); the others act at once.
 */
export class BcAction extends ControlElement<Action> {
  static override properties = { asking: { state: true } };
  static override styles = [...ControlElement.styles, partStyles];

  declare asking: boolean;

  constructor() {
    super();
    this.asking = false;
  }

  private async press(): Promise<void> {
    if (this.disabled || this.pending) return;
    if (!this.control?.confirm) {
      this.emit(undefined);
      return;
    }
    this.asking = true;
    await this.updateComplete;
    // Focus the safe choice, so Enter or Space doesn't start anything by accident.
    this.renderRoot.querySelector<HTMLButtonElement>(".confirm .bc-button")?.focus();
  }

  private answer(go: boolean): void {
    this.asking = false;
    if (go && !this.disabled) this.emit(undefined);
    void this.updateComplete.then(() => this.renderRoot.querySelector<HTMLButtonElement>(".row .bc-button")?.focus());
  }

  private readonly onKey = (event: KeyboardEvent): void => {
    if (event.key === "Escape" && this.asking) {
      event.stopPropagation();
      this.answer(false);
    }
  };

  override render() {
    const control = this.control;
    if (!control) return nothing;
    const tone = control.tone === "danger" ? "danger" : control.tone === "primary" ? "primary" : "";
    // Locked, or while the call is in flight, the button is only marked unavailable: it stays
    // focusable, so its reason is read out and focus can come back to it from the bar.
    return html`<div @keydown=${this.onKey}>
      ${this.head(html`<button
        type="button"
        class="bc-button ${this.asking ? "" : tone}"
        aria-expanded=${control.confirm ? (this.asking ? "true" : "false") : nothing}
        aria-disabled=${(this.disabled || this.pending) && !this.asking ? "true" : nothing}
        aria-describedby=${this.describedBy()}
        ?disabled=${this.asking}
        @click=${() => this.press()}
      >
        ${control.button}
      </button>`)}
      ${this.asking && control.confirm
        ? html`<div class="ask">
            ${renderConfirmBar({
              text: control.confirm,
              confirm: control.button,
              cancel: this.t("ctl.not_now"),
              tone: control.tone === "danger" ? "danger" : "primary",
              busy: this.pending,
              onConfirm: () => this.answer(true),
              onCancel: () => this.answer(false),
            })}
          </div>`
        : nothing}
      ${this.errorLine()}
    </div>`;
  }
}

defineOnce("bc-action", BcAction);
