import { LitElement, css, html, nothing, type PropertyValues } from "lit";
import { applianceName, relevantChange } from "../data/appliances";
import { translatorFor } from "../data/locale";
import { NO_SHARED, type Shared } from "../kinds/index";
import type { HomeAssistant } from "../hass";
import { syncTheme, tokens, toneStyles } from "../styles";
import type { PanelAppliance } from "../types";
import { DrawingSize } from "./drawing-size";
import { partStyles, renderDisplay, renderInfoPanel, renderPill } from "./parts";
import { cardView, drawingInput, safeDrawing, type CardView } from "./view";

/** Fired (bubbling, composed) when a card is chosen; the panel opens the appliance's full view. */
export const OPEN_APPLIANCE = "bc-open-appliance";

export interface OpenApplianceDetail {
  deviceId: string;
}

let cards = 0;

/**
 * One appliance on the overview, in the GE appliance card's style: the name and a status pill,
 * the live drawing, the display where the appliance has one, and a few label and value rows.
 * The name is the button that opens the full view, and it stretches over the whole card, so
 * a click anywhere opens it while a screen reader still reads the drawing and rows on their own.
 */
export class ApplianceCard extends LitElement {
  static override shadowRootOptions = { ...LitElement.shadowRootOptions, delegatesFocus: true };

  static override properties = {
    hass: { attribute: false },
    appliance: { attribute: false },
    shared: { attribute: false },
    now: { attribute: false },
  };

  declare hass: HomeAssistant | undefined;
  declare appliance: PanelAppliance | undefined;
  declare shared: Shared;
  /** The panel's clock, in ms; it ticks every second so countdowns move. */
  declare now: number;

  // Drawings prefix their SVG ids with it, which the drawing contract asks to be unique.
  private readonly uid = `bcc${++cards}`;
  private readonly size = new DrawingSize(this, ".drawing > svg");
  private view: CardView | undefined;
  private name = "";

  constructor() {
    super();
    this.now = Date.now();
    this.shared = NO_SHARED;
  }

  protected override shouldUpdate(changed: PropertyValues<this>): boolean {
    if (!this.hass || !this.appliance) return false;
    if (changed.size === 1 && changed.has("hass")) {
      return relevantChange(changed.get("hass"), this.hass, this.appliance);
    }
    return true;
  }

  protected override willUpdate(): void {
    const { hass, appliance } = this;
    if (!hass || !appliance) return;
    syncTheme(this, hass);
    this.toggleAttribute("offline", !appliance.available);
    this.name = applianceName(appliance, hass);
    this.view = cardView(appliance, hass, translatorFor(hass), this.now, this.shared);
  }

  protected override render() {
    const { hass, appliance, view } = this;
    if (!hass || !appliance || !view) return nothing;
    const t = translatorFor(hass);
    return html`
      <div class="head">
        <h3 class="name">
          <button type="button" class="open" aria-describedby="status hint" @click=${() => this.open()}>
            ${this.name}
          </button>
        </h3>
        <span id="status">${renderPill(view.status)}</span>
        <span id="hint" class="visually-hidden">${t("card.open_hint")}</span>
      </div>
      <div class="stage ${view.display ? "has-display" : ""}">
        ${renderDisplay(view.display, view.display?.dim)}
        <div class="drawing" role="img" aria-label=${view.description}>
          ${safeDrawing(drawingInput(appliance, view.state, hass, this.uid, this.size.height))}
        </div>
      </div>
      ${renderInfoPanel(view.rows.slice(0, 3))}
    `;
  }

  private open(): void {
    if (!this.appliance) return;
    this.dispatchEvent(
      new CustomEvent<OpenApplianceDetail>(OPEN_APPLIANCE, {
        detail: { deviceId: this.appliance.device_id },
        bubbles: true,
        composed: true,
      }),
    );
  }

  static override styles = [
    tokens,
    toneStyles,
    partStyles,
    css`
      :host {
        position: relative;
        display: flex;
        flex-direction: column;
        box-sizing: border-box;
        min-width: 0;
        padding: 12px 14px 14px;
        border: var(--bc-border-width) solid var(--bc-border);
        border-radius: var(--bc-radius);
        background: var(--bc-card-bg);
        box-shadow: var(--ha-card-box-shadow, none);
        color: var(--bc-text);
        cursor: pointer;
        container-type: inline-size;
        -webkit-tap-highlight-color: transparent;
        transition:
          box-shadow 0.2s ease,
          border-color 0.2s ease,
          transform 0.2s ease;
      }
      /* Only where there's a pointer to hover with: on touch, the lift would stay after a tap. */
      @media (hover: hover) {
        :host(:hover) {
          border-color: color-mix(in srgb, var(--bc-text) 20%, transparent);
          box-shadow: var(--bc-lift);
        }
      }
      :host(:active) {
        transform: scale(0.98);
      }
      :host(:focus-within) {
        outline: 2px solid var(--bc-accent);
        outline-offset: 2px;
      }
      @media (prefers-reduced-motion: reduce) {
        :host {
          transition: none;
        }
        :host(:active) {
          transform: none;
        }
      }
      .head {
        display: flex;
        align-items: center;
        gap: 10px;
        min-height: 28px;
        margin-bottom: 8px;
      }
      .name {
        flex: 1;
        min-width: 0;
        margin: 0;
        overflow: hidden;
        font-size: 17px;
        font-weight: 600;
        line-height: 1.3;
        white-space: nowrap;
        text-overflow: ellipsis;
      }
      /* The name opens the full view, and its hit area covers the whole card. */
      .open {
        max-width: 100%;
        padding: 0;
        border: none;
        background: none;
        color: inherit;
        font: inherit;
        text-align: start;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
        cursor: pointer;
        outline: none;
      }
      .open::after {
        content: "";
        position: absolute;
        inset: 0;
        z-index: 1;
        border-radius: var(--bc-radius);
      }
      :host([offline]) .name {
        color: var(--bc-muted);
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
      /* Every card's stage is the same height and sits right under the title, so the appliances
         in a grid row stand on one floor line; the info panel takes up any slack below. A display
         sits above the drawing, and the drawing in that card starts below it. */
      .stage {
        --drawing-height: clamp(220px, 74cqw, 320px);
        height: var(--drawing-height);
        margin: 0 0 12px;
        padding-bottom: 2px;
      }
      @media (max-width: 600px) {
        .stage {
          --drawing-height: clamp(200px, 62cqw, 280px);
        }
      }
      .stage.has-display .drawing {
        box-sizing: border-box;
        padding-top: 52px;
      }
      .stage .lcd {
        position: absolute;
        top: 0;
        left: 50%;
        z-index: 1;
        height: 50px;
        transform: translateX(-50%);
      }
      /* Three rows' height whatever it holds, the rows centered, as on the GE card. */
      .info {
        min-height: 75px;
        box-sizing: border-box;
        align-content: center;
        margin: auto 4% 0;
      }
    `,
  ];
}

if (!customElements.get("bc-appliance-card")) customElements.define("bc-appliance-card", ApplianceCard);

declare global {
  interface HTMLElementTagNameMap {
    "bc-appliance-card": ApplianceCard;
  }
}
