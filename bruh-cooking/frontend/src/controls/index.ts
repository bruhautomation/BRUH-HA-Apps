/**
 * The full view's controls, in the GE card's style. Each shows one Control from a kind model and
 * fires `bc-value` with the value to apply; the view applies it and sets `pending` and `error`
 * around the call.
 */
import { html, type TemplateResult } from "lit";
import type { Control } from "../kinds/types";
import type { Translate } from "../i18n";
import type { ValueDetail } from "./base";
import type { NumberFormatter } from "./setpoint";
import "./action";
import "./countdown";
import "./duration";
import "./reading";
import "./select";
import "./setpoint";
import "./toggle";

export { VALUE_EVENT, type ValueDetail } from "./base";

export interface ControlBinding {
  t: Translate;
  pending: boolean;
  error: string | null;
  onValue: (event: CustomEvent<ValueDetail>) => void;
  /** Hides the label when the widget goes under it, for a lone control named like its section. */
  quiet?: boolean;
  /** Numbers in the user's format, for the setpoint's decimals; plain digits if unset. */
  formatNumber?: NumberFormatter;
  /** The section shows the control's lock reason once for several controls (see ControlElement). */
  sharedReason?: boolean;
}

/** The element for a control's kind. */
export function renderControl(control: Control, binding: ControlBinding): TemplateResult {
  const { t, pending, error, onValue } = binding;
  const quiet = binding.quiet === true;
  const shared = binding.sharedReason === true;
  switch (control.kind) {
    case "setpoint":
      return html`<bc-setpoint
        .control=${control}
        .t=${t}
        .pending=${pending}
        .error=${error}
        .sharedReason=${shared}
        .formatNumber=${binding.formatNumber}
        ?quiet=${quiet}
        @bc-value=${onValue}
      ></bc-setpoint>`;
    case "select":
      return html`<bc-select .control=${control} .t=${t} .pending=${pending} .error=${error} .sharedReason=${shared} ?quiet=${quiet} @bc-value=${onValue}></bc-select>`;
    case "toggle":
      return html`<bc-toggle .control=${control} .t=${t} .pending=${pending} .error=${error} .sharedReason=${shared} ?quiet=${quiet} @bc-value=${onValue}></bc-toggle>`;
    case "action":
      return html`<bc-action .control=${control} .t=${t} .pending=${pending} .error=${error} .sharedReason=${shared} ?quiet=${quiet} @bc-value=${onValue}></bc-action>`;
    case "duration":
      return html`<bc-duration .control=${control} .t=${t} .pending=${pending} .error=${error} .sharedReason=${shared} ?quiet=${quiet} @bc-value=${onValue}></bc-duration>`;
    case "reading":
      return html`<bc-reading .control=${control} .t=${t} ?quiet=${quiet}></bc-reading>`;
    case "countdown":
      return html`<bc-countdown .control=${control} .t=${t} ?quiet=${quiet}></bc-countdown>`;
  }
}
