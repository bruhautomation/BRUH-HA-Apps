import { LitElement, html, nothing, svg, type PropertyDeclarations, type PropertyValues, type TemplateResult } from "lit";
import type { Control } from "../kinds/types";
import { followLink } from "../data/route";
import { makeTranslate, type Translate } from "../i18n";
import { buttonStyles } from "../styles";
import { controlStyles } from "./styles";

/** The one event every control fires, with the value to apply (none for a button). */
export const VALUE_EVENT = "bc-value";

export interface ValueDetail {
  value: unknown;
}

// After a call succeeds, how long a control keeps showing the value it sent while Home Assistant
// catches up with the entity's new state.
const SETTLE_MS = 2500;

const english = makeTranslate("en");

export const icons = {
  minus: svg`<path d="M5 11h14v2H5z" />`,
  plus: svg`<path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z" />`,
  chevron: svg`<path d="M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z" />`,
  lock: svg`<path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5Zm-3 8V7a3 3 0 0 1 6 0v3H9Z" />`,
};

export function icon(path: TemplateResult): TemplateResult {
  return html`<svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
}

/**
 * What every control shares: the Control it shows, the translator, and the pending and error
 * states the view sets around a call. A control shows the value it sent until the entity reports
 * it, the call fails, or a moment after it succeeds, so a tap never seems to bounce back.
 */
export abstract class ControlElement<C extends Control> extends LitElement {
  static override properties: PropertyDeclarations = {
    control: { attribute: false },
    t: { attribute: false },
    pending: { type: Boolean, reflect: true },
    error: { attribute: false },
    sharedReason: { attribute: false },
    optimistic: { state: true },
  };

  declare control: C | undefined;
  declare t: Translate;
  declare pending: boolean;
  declare error: string | null;
  /**
   * The section shows this control's lock reason once, above several controls; the control keeps
   * it for screen readers only, so it's still read out with the control.
   */
  declare sharedReason: boolean;
  /** The value sent and not yet confirmed; undefined when there's none. */
  declare optimistic: unknown;
  private settleTimer: ReturnType<typeof setTimeout> | undefined;

  static override styles = [buttonStyles, controlStyles];

  constructor() {
    super();
    this.t = english;
    this.pending = false;
    this.error = null;
    this.sharedReason = false;
    this.optimistic = undefined;
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    clearTimeout(this.settleTimer);
  }

  /** The entity's value, to compare with what the control sent. */
  protected current(): unknown {
    return this.control && "value" in this.control ? this.control.value : undefined;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (this.optimistic === undefined) return;
    if ((changed.has("control") && same(this.current(), this.optimistic)) || (changed.has("error") && this.error)) {
      this.clearOptimistic();
    }
  }

  protected override updated(changed: PropertyValues<this>): void {
    if (changed.has("pending") && changed.get("pending") === true && !this.pending && this.optimistic !== undefined) {
      clearTimeout(this.settleTimer);
      this.settleTimer = setTimeout(() => this.clearOptimistic(), SETTLE_MS);
    }
  }

  protected clearOptimistic(): void {
    clearTimeout(this.settleTimer);
    this.settleTimer = undefined;
    this.optimistic = undefined;
  }

  /** Shows `value` at once and asks the view to apply it. */
  protected send(value: unknown): void {
    clearTimeout(this.settleTimer);
    this.optimistic = value;
    this.emit(value);
  }

  protected emit(value: unknown): void {
    this.dispatchEvent(new CustomEvent<ValueDetail>(VALUE_EVENT, { detail: { value }, bubbles: true, composed: true }));
  }

  protected get disabled(): boolean {
    return Boolean(this.control?.disabled);
  }

  /**
   * For a widget's aria-disabled. A locked widget is only marked so, not disabled, which would
   * take it out of the tab order: focused, it's read out with why it's locked.
   */
  protected get locked(): "true" | typeof nothing {
    return this.disabled ? "true" : nothing;
  }

  /** For a widget's aria-describedby: the hint and the lock reason that frame() shows. */
  protected describedBy(hint: string | null = this.control?.hint ?? null): string | typeof nothing {
    const ids = [hint ? "hint" : null, this.reason() ? "reason" : null].filter(Boolean);
    return ids.length ? ids.join(" ") : nothing;
  }

  private reason(): string | null {
    return (this.control?.disabled && this.control.reason) || null;
  }

  /**
   * The label (with `aside`, a short current value, on its right), the hint, and the widget;
   * then why it's disabled and the last error. `stacked` puts a wide widget under the label, and
   * `hint` replaces the control's own.
   */
  protected frame(widget: unknown, options: FrameOptions = {}): TemplateResult {
    return html`${this.head(widget, options)}${this.errorLine()}`;
  }

  /** The frame without the error line, for a control with more below its row. */
  protected head(widget: unknown, options: FrameOptions = {}): TemplateResult {
    const control = this.control;
    if (!control) return html``;
    const hint = options.hint === undefined ? control.hint : options.hint;
    const reason = this.reason();
    return html`
      <div class="row ${options.stacked ? "stacked" : ""}">
        <div class="text">
          <div class="title">
            <span class="label" id="label">${control.label}</span>
            ${options.aside ? html`<span class="aside">${options.aside}</span>` : nothing}
          </div>
          ${hint ? html`<span class="hint" id="hint">${hint}</span>` : nothing}
        </div>
        <div class="widget">
          ${this.pending ? html`<span class="spinner" role="progressbar" aria-label=${this.t("ctl.saving")}></span>` : nothing}
          ${widget}
        </div>
      </div>
      ${reason
        ? html`<div class="reason ${this.sharedReason ? "visually-hidden" : ""}" id="reason">
            ${icon(icons.lock)}<span>${reason}</span>
          </div>`
        : nothing}
      ${control.disabled && control.link
        ? html`<a class="link" href=${control.link.href} @click=${followLink}>${control.link.text}</a>`
        : nothing}
    `;
  }

  /** Home Assistant's message for the last rejected call. */
  protected errorLine(): TemplateResult | typeof nothing {
    return this.error ? html`<div class="error" role="alert">${this.error}</div>` : nothing;
  }
}

export interface FrameOptions {
  stacked?: boolean;
  aside?: string | null;
  hint?: string | null;
}

function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  return typeof a === "object" && typeof b === "object" && a !== null && b !== null && JSON.stringify(a) === JSON.stringify(b);
}

export function defineOnce(name: string, element: CustomElementConstructor): void {
  if (!customElements.get(name)) customElements.define(name, element);
}
