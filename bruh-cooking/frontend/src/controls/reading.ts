import { css, html, nothing } from "lit";
import type { Control } from "../kinds/types";
import { ControlElement, defineOnce } from "./base";

type Reading = Extract<Control, { kind: "reading" }>;

/** Read-only rows are as tall as their text, not as a control's 40 px target. */
export const readingStyles = css`
  .row {
    min-height: 0;
  }
`;

/** A value to read, already formatted, colored by its tone. */
export class BcReading extends ControlElement<Reading> {
  static override styles = [...ControlElement.styles, readingStyles];

  override render() {
    const control = this.control;
    if (!control) return nothing;
    return this.frame(html`<span class="reading" data-tone=${control.tone ?? "normal"}>${control.value}</span>`);
  }
}

defineOnce("bc-reading", BcReading);
