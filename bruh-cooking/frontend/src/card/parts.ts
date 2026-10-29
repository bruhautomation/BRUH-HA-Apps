/**
 * The GE-style card's parts, for the overview card and anything else that shows an appliance
 * the same way: the status pill, the amber display, the translucent info panel, the inline
 * confirmation bar, and the stage a drawing stands in. Use them with `partStyles` (and
 * `tokens`, `toneStyles` and `buttonStyles` from styles.ts).
 */
import { css, html, nothing, type TemplateResult } from "lit";
import type { DisplayText, InfoRow, StatusPill } from "../kinds/types";

export function renderPill(status: StatusPill | null | undefined): TemplateResult | typeof nothing {
  if (!status?.text) return nothing;
  return html`<span class="pill" data-tone=${status.tone}>${status.text}</span>`;
}

/**
 * Amber digits with a small caption, like the appliance's own display. `dim` greys the digits
 * while it has nothing live to show (an oven that's off), as the GE card does when it's ready.
 */
export function renderDisplay(display: DisplayText | null | undefined, dim = false): TemplateResult | typeof nothing {
  if (!display?.text) return nothing;
  return html`<div class="lcd ${dim ? "dim" : ""}">
    <span class="digits">${display.text}</span>
    ${display.caption ? html`<span class="caption">${display.caption}</span>` : nothing}
  </div>`;
}

export function renderInfoPanel(rows: readonly InfoRow[]): TemplateResult | typeof nothing {
  if (!rows.length) return nothing;
  return html`<dl class="info">
    ${rows.map((row) => html`<div class="row"><dt>${row.label}</dt><dd>${row.value}</dd></div>`)}
  </dl>`;
}

export interface ConfirmBar {
  /** The question, e.g. "Start the oven at Air fry 400 °F for 18 minutes?". */
  text: string;
  confirm: string;
  cancel: string;
  onConfirm: () => void;
  onCancel: () => void;
  tone?: "primary" | "danger";
  /** Both buttons wait while the call is in flight. */
  busy?: boolean;
}

/**
 * The GE card's inline confirmation: the question, then Cancel and the action, which wrap
 * together under the question on a narrow screen. The border takes the action's color.
 */
export function renderConfirmBar(bar: ConfirmBar): TemplateResult {
  const tone = bar.tone ?? "primary";
  return html`<div class="confirm ${tone}" role="group" aria-label=${bar.text}>
    <span class="question">${bar.text}</span>
    <span class="actions">
      <button type="button" class="bc-button" ?disabled=${bar.busy} @click=${bar.onCancel}>
        ${bar.cancel}
      </button>
      <button type="button" class="bc-button ${tone}" ?disabled=${bar.busy} @click=${bar.onConfirm}>
        ${bar.confirm}
      </button>
    </span>
  </div>`;
}

export const partStyles = css`
  .pill {
    flex: none;
    max-width: 60%;
    overflow: hidden;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    line-height: 18px;
    white-space: nowrap;
    text-overflow: ellipsis;
    /* Fallbacks for browsers without color-mix. */
    color: var(--tone);
    background: rgba(127, 127, 127, 0.14);
    color: color-mix(in srgb, var(--tone) var(--bc-tone-strength), var(--bc-ink));
    background: color-mix(in srgb, var(--tone) 15%, transparent);
  }
  .pill[data-tone="neutral"] {
    color: var(--bc-text);
    background: color-mix(in srgb, var(--bc-text) 8%, transparent);
  }
  .pill[data-tone="gray"] {
    color: var(--bc-muted);
    background: color-mix(in srgb, var(--bc-muted) 14%, transparent);
  }

  /* The display is a physical part of the appliance, so it looks the same in both themes. */
  .lcd {
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-width: 7.5em;
    padding: 6px 14px 5px;
    box-sizing: border-box;
    border-radius: 8px;
    /* Dark glass with a faint glare across its upper half. */
    background:
      linear-gradient(168deg, rgba(255, 255, 255, 0.07) 0%, rgba(255, 255, 255, 0.015) 45%, transparent 46%),
      linear-gradient(180deg, #15171b 0%, #0a0b0d 100%);
    box-shadow:
      inset 0 0 0 1px rgba(255, 255, 255, 0.07),
      inset 0 2px 6px rgba(0, 0, 0, 0.8),
      0 1px 2px rgba(0, 0, 0, 0.25);
    line-height: 1;
  }
  /* The theme's sans with even-width digits: a monospace font's slashed zero reads as code. */
  .lcd .digits {
    font-family: inherit;
    font-size: 26px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.03em;
    color: #ffa53a;
    text-shadow: 0 0 10px rgba(255, 140, 30, 0.45);
    white-space: nowrap;
  }
  .lcd.dim .digits {
    color: #6b6e73;
    text-shadow: none;
  }
  .lcd .caption {
    margin-top: 4px;
    font-size: 11px;
    color: #9a9da2;
    white-space: nowrap;
  }

  .info {
    display: grid;
    gap: 3px;
    margin: 0;
    padding: 7px 12px;
    border-radius: 12px;
    background: var(--bc-inset-bg);
    box-shadow: inset 0 0 0 1px var(--bc-inset-edge);
    font-size: 13.5px;
    line-height: 1.35;
  }
  .info .row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    min-width: 0;
  }
  .info dt {
    flex: none;
    max-width: 50%;
    overflow: hidden;
    color: var(--bc-muted-inset, var(--bc-muted));
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  /* A long value (setpoints in German, say) wraps rather than losing its end. */
  .info dd {
    margin: 0;
    min-width: 0;
    font-weight: 500;
    text-align: end;
    overflow-wrap: anywhere;
    text-wrap: balance;
  }

  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 8px 10px 8px 14px;
    border-radius: 12px;
    border: 1px solid var(--bc-accent);
    background: var(--bc-inset-bg);
  }
  .confirm.danger {
    border-color: var(--bc-error);
  }
  .confirm .question {
    flex: 1 1 14em;
    font-size: 14px;
  }
  .confirm .actions {
    display: flex;
    gap: 8px;
    margin-inline-start: auto;
  }
  /* On the bar's inset the neutral fill all but disappears in the dark theme; an edge keeps the
     safe choice looking like the button it is. */
  .confirm .bc-button:not(.primary, .danger) {
    background: var(--bc-control-hover);
    box-shadow: inset 0 0 0 1px var(--bc-inset-edge);
  }

  /* A drawing stands at the bottom of its stage and fits it: tall refrigerators fill the
     height, wide ranges the width. The drawing's svg has a viewBox in true proportions. */
  .stage {
    position: relative;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    box-sizing: border-box;
  }
  .stage .drawing {
    display: flex;
    align-items: flex-end;
    justify-content: center;
    width: 100%;
    height: 100%;
  }
  .stage .drawing > svg {
    display: block;
    width: 100%;
    height: auto;
    max-height: 100%;
  }
`;
