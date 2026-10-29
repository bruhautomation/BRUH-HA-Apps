import { LitElement, css, html, nothing } from "lit";
import { repeat } from "lit/directives/repeat.js";
import "../card/appliance-card";
import { groupByArea, type AreaGroup } from "../data/appliances";
import { translatorFor } from "../data/locale";
import { followLink } from "../data/route";
import { NO_SHARED, type Shared } from "../kinds/index";
import type { HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import { buttonStyles, syncTheme, tokens } from "../styles";
import type { PanelAppliance } from "../types";

const INTEGRATION_PAGE = "/config/integrations/integration/bruh_cooking";
// A pot with steam, like the panel's sidebar icon (Material Design Icons' pot-steam-outline).
const POT =
  "M19,19A2,2 0 0,1 17,21H7A2,2 0 0,1 5,19V13H3V11H21V13H19V19M7,13V19H17V13H7M13,5.5C13,6.2 12.6,6.7 12.1,7.1" +
  "C11.6,7.6 11,8.1 11,9H9.5C9.5,7.8 10.3,7.1 10.9,6.6C11.4,6.2 11.5,5.9 11.5,5.5C11.5,5.1 11.3,4.7 10.8,4.3" +
  "L11.8,3.2C12.6,3.9 13,4.6 13,5.5M16.5,5.5C16.5,6.2 16.1,6.7 15.6,7.1C15.1,7.6 14.5,8.1 14.5,9H13" +
  "C13,7.8 13.8,7.1 14.4,6.6C14.9,6.2 15,5.9 15,5.5C15,5.1 14.8,4.7 14.3,4.3L15.3,3.2C16.1,3.9 16.5,4.6 16.5,5.5Z";

/** Every appliance as a card, in sections by area. */
export class Overview extends LitElement {
  static override properties = {
    hass: { attribute: false },
    appliances: { attribute: false },
    shared: { attribute: false },
    now: { attribute: false },
  };

  declare hass: HomeAssistant | undefined;
  declare appliances: PanelAppliance[];
  declare shared: Shared;
  declare now: number;

  // Grouping sorts on every render, and the clock renders every second; the inputs rarely change.
  private grouped: { key: unknown[]; groups: AreaGroup[] } | undefined;

  constructor() {
    super();
    this.appliances = [];
    this.shared = NO_SHARED;
    this.now = Date.now();
  }

  protected override willUpdate(): void {
    syncTheme(this, this.hass);
  }

  protected override render() {
    const t = translatorFor(this.hass);
    if (!this.appliances.length) return this.renderEmpty(t);
    const groups = this.groups();
    // A heading for a lone "No area" section would only say what's missing.
    const headings = groups.length > 1 || groups[0]?.areaId !== null;
    return groups.map(
      (group) => html`
        <section class="area" aria-label=${group.name ?? t("overview.no_area")}>
          ${headings ? html`<h2>${group.name ?? t("overview.no_area")}</h2>` : nothing}
          <div class="grid">
            ${repeat(
              group.appliances,
              (entry) => entry.appliance.device_id,
              (entry) => html`<bc-appliance-card
                .hass=${this.hass}
                .appliance=${entry.appliance}
                .shared=${this.shared}
                .now=${this.now}
              ></bc-appliance-card>`,
            )}
          </div>
        </section>
      `,
    );
  }

  private groups(): AreaGroup[] {
    const hass = this.hass;
    const key = [this.appliances, hass?.devices, hass?.areas, hass?.language, hass?.locale];
    if (!this.grouped || key.some((part, index) => part !== this.grouped!.key[index])) {
      this.grouped = { key, groups: groupByArea(this.appliances, hass) };
    }
    return this.grouped.groups;
  }

  private renderEmpty(t: Translate) {
    const admin = this.hass?.user?.is_admin === true;
    return html`<div class="empty">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${POT}></path></svg>
      <h2>${t("overview.empty_title")}</h2>
      <p>${t(admin ? "overview.empty_text" : "overview.empty_text_user")}</p>
      ${admin
        ? html`<a class="bc-button primary" href=${INTEGRATION_PAGE} @click=${followLink}>
            ${t("overview.empty_link")}
          </a>`
        : nothing}
    </div>`;
  }

  static override styles = [
    tokens,
    buttonStyles,
    css`
      :host {
        display: block;
        color: var(--bc-text);
      }
      .area + .area {
        margin-top: 28px;
      }
      /* A section title over the cards, not a caption: as strong as the card names under it. */
      h2 {
        margin: 0 4px 10px;
        font-size: 18px;
        font-weight: 500;
        line-height: 1.4;
        color: var(--bc-text);
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
        gap: 16px;
        align-items: stretch;
      }
      .empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        max-width: 420px;
        margin: 10vh auto 0;
        padding: 0 16px;
        text-align: center;
      }
      .empty svg {
        width: 56px;
        height: 56px;
        fill: var(--bc-muted);
        opacity: 0.6;
      }
      .empty h2 {
        margin: 16px 0 4px;
        font-size: 20px;
        color: var(--bc-text);
      }
      .empty p {
        margin: 0 0 20px;
        color: var(--bc-muted);
        line-height: 1.5;
      }
    `,
  ];
}

if (!customElements.get("bc-overview")) customElements.define("bc-overview", Overview);

declare global {
  interface HTMLElementTagNameMap {
    "bc-overview": Overview;
  }
}
