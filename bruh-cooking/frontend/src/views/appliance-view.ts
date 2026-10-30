/**
 * An appliance's full view: the large live drawing with its status, display and preheat ring,
 * then the cook's controls, the settings, presets, the temperature chart and the details. The
 * shell renders <bc-appliance-view .hass .appliance .shared .narrow .now> for
 * /bruh-cooking/<device_id>.
 */
import { LitElement, css, html, nothing, svg, type PropertyValues } from "lit";
import { repeat } from "lit/directives/repeat.js";
import { applyAction } from "../actions";
import { DrawingSize } from "../card/drawing-size";
import { partStyles, renderDisplay, renderPill } from "../card/parts";
import { attempt, drawingInput, fallbackState, safeDrawing } from "../card/view";
import { icon, icons } from "../controls/base";
import { renderControl } from "../controls/index";
import { relevantChange } from "../data/appliances";
import { localizedError, translatorFor } from "../data/locale";
import { formatNumber, numberOf } from "../kinds/common";
import { kindModel, makeContext, NO_SHARED, type Shared } from "../kinds/index";
import type { Control, Section } from "../kinds/types";
import type { HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import { buttonStyles, syncTheme, tokens, toneStyles } from "../styles";
import type { PanelAppliance } from "../types";
import "./chart";
import { PRESET_APPLIED } from "./presets";

const CHEVRON = svg`<path d="M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z" />`;

let views = 0;

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const copy = { ...record };
  delete copy[key];
  return copy;
}

function sameName(a: string, b: string): boolean {
  return a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();
}

export class ApplianceView extends LitElement {
  static override properties = {
    hass: { attribute: false },
    appliance: { attribute: false },
    shared: { attribute: false },
    narrow: { type: Boolean, reflect: true },
    now: { attribute: false },
    pending: { state: true },
    errors: { state: true },
  };

  declare hass: HomeAssistant | undefined;
  declare appliance: PanelAppliance | undefined;
  declare shared: Shared;
  declare narrow: boolean;
  /** The panel's clock in ms; without it the view keeps its own. */
  declare now: number | undefined;
  /** Calls in flight, by section and control id. */
  declare pending: Record<string, boolean>;
  /** Home Assistant's message for the last rejected call, by section and control id. */
  declare errors: Record<string, string>;

  // Drawings prefix their SVG ids with it, which the drawing contract asks to be unique.
  private readonly uid = `bcv${++views}`;
  private readonly size = new DrawingSize(this, ".stage .drawing > svg");
  private clock = Date.now();
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    super();
    this.narrow = false;
    this.shared = NO_SHARED;
    this.pending = {};
    this.errors = {};
    // A preset filled in the settings: Start is next, and nothing starts by itself.
    this.addEventListener(PRESET_APPLIED, () => void this.focusStart());
  }

  private async focusStart(): Promise<void> {
    await this.updateComplete;
    const action = this.renderRoot.querySelector<HTMLElement & { updateComplete?: Promise<unknown> }>(
      '.control[data-control="start"] bc-action',
    );
    await action?.updateComplete;
    action?.shadowRoot?.querySelector<HTMLButtonElement>("button")?.focus();
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.tick();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    clearTimeout(this.timer);
    this.timer = undefined;
  }

  // Countdowns move every second, on the panel's clock when it passes one.
  private readonly tick = (): void => {
    this.clock = Date.now();
    if (this.now === undefined) this.requestUpdate();
    this.timer = setTimeout(this.tick, 1000 - (this.clock % 1000) + 5);
  };

  // Home Assistant hands panels a new hass for any state change in the house, many times a
  // second on a busy system; the view redraws only for its own appliance and the user's settings.
  protected override shouldUpdate(changed: PropertyValues<this>): boolean {
    if (changed.size === 1 && changed.has("hass") && this.hass && this.appliance) {
      return relevantChange(changed.get("hass"), this.hass, this.appliance);
    }
    return true;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    syncTheme(this, this.hass);
    const before = changed.get("appliance") as PanelAppliance | undefined;
    if (changed.has("appliance") && before?.device_id !== this.appliance?.device_id) {
      this.pending = {};
      this.errors = {};
    }
  }

  private async apply(key: string, control: Control, value: unknown): Promise<void> {
    const hass = this.hass;
    if (!hass || !("action" in control)) return;
    this.pending = { ...this.pending, [key]: true };
    this.errors = without(this.errors, key);
    try {
      await applyAction(hass, control.action, value);
    } catch (error) {
      const message = await localizedError(hass, error);
      this.errors = { ...this.errors, [key]: message || translatorFor(hass)("full.failed") };
    } finally {
      this.pending = without(this.pending, key);
    }
  }

  protected override render() {
    const { hass, appliance } = this;
    if (!hass || !appliance) return nothing;
    const t = translatorFor(hass);
    const now = this.now ?? this.clock;
    const model = kindModel(appliance);
    const ctx = makeContext(appliance, hass, t, now, this.shared);
    const what = (part: string) => `${appliance.kind} ${part} for ${appliance.device_id}`;
    // A model that trips over an appliance's state shows less, never a broken page.
    const state = attempt(what("drawing state"), () => model.drawingState(ctx), fallbackState(appliance));
    const status = attempt(what("status"), () => model.status(ctx), { text: "", tone: "neutral" as const });
    const display = appliance.available ? attempt(what("display"), () => model.display(ctx), null) : null;
    const sections = attempt(what("sections"), () => model.sections(ctx), [] as Section[]);
    const description = attempt(what("description"), () => model.describe(ctx), appliance.product);
    const phase = attempt(what("phase"), () => model.phase(ctx), "idle" as const);
    const preheat = phase === "preheating" ? numberOf(ctx, "preheat", "sensor") : null;
    const cooking = phase !== "idle" && phase !== "offline" && phase !== "error" && phase !== "updating";
    const [first, ...rest] = sections;
    const details = rest.find((section) => section.id === "details");
    const middle = rest.filter((section) => section !== details);
    return html`<div class="layout">
      <section class="hero" aria-label=${t("full.appliance")}>
        <div class="hero-head">
          <!-- Not a live region: preheat and timer pills change every second; the panel
               announces what matters. -->
          <div class="status">${renderPill(status)} ${preheat !== null ? this.renderRing(t, preheat) : nothing}</div>
          ${renderDisplay(display, display?.dim)}
        </div>
        <div class="stage">
          <div class="drawing" role="img" aria-label=${description}>
            ${safeDrawing(drawingInput(appliance, state, hass, this.uid, this.size.height))}
          </div>
        </div>
      </section>
      <div class="sections">
        ${first ? this.renderSection(first, t) : nothing}
        ${repeat(
          middle,
          (section) => section.id,
          (section) => this.renderSection(section, t),
        )}
        ${this.card(
          "presets",
          t("section.presets"),
          html`<bc-presets
            .hass=${this.hass}
            .appliance=${appliance}
            .presets=${this.shared.presets}
            .modes=${this.shared.modes}
            .cooking=${cooking}
          ></bc-presets>`,
          true,
        )}
        ${this.card(
          "chart",
          t("section.chart"),
          html`<bc-temp-chart .hass=${this.hass} .appliance=${appliance} .now=${now}></bc-temp-chart>`,
          true,
        )}
        ${details ? this.renderSection(details, t) : nothing}
      </div>
    </div>`;
  }

  /** The preheat ring: how far the appliance has got, as the app shows it. */
  private renderRing(t: Translate, percent: number) {
    const value = Math.max(0, Math.min(100, Math.round(percent)));
    const radius = 15.5;
    const length = 2 * Math.PI * radius;
    return html`<span
      class="ring"
      role="progressbar"
      aria-label=${t("full.preheat")}
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow=${value}
      aria-valuetext=${t("full.preheat_value", { n: value })}
    >
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <circle class="track" cx="18" cy="18" r=${radius}></circle>
        <circle
          class="bar"
          cx="18"
          cy="18"
          r=${radius}
          stroke-dasharray=${`${(length * value) / 100} ${length}`}
          transform="rotate(-90 18 18)"
        ></circle>
      </svg>
      <span class="ring-value">${formatNumber(this.hass!, value)}%</span>
    </span>`;
  }

  private card(id: string, title: string, body: unknown, open: boolean) {
    return html`<details class="card" data-section=${id} ?open=${open}>
      <summary>
        <h2>${title}</h2>
        <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true">${CHEVRON}</svg>
      </summary>
      <div class="body">${body}</div>
    </details>`;
  }

  private renderSection(section: Section, t: Translate) {
    const hass = this.hass!;
    // A reason that two or more disabled controls share shows once at the top instead of under
    // each of them; a one-off stays with its control. Each control keeps it for screen readers,
    // so the note at the top is only for the eye.
    const counts = new Map<string, number>();
    for (const control of section.controls) {
      if (control.disabled && control.reason) counts.set(control.reason, (counts.get(control.reason) ?? 0) + 1);
    }
    const shared = new Set([...counts].filter(([, count]) => count > 1).map(([reason]) => reason));
    if (section.note) shared.add(section.note);
    const note = (reason: string, hidden: boolean) =>
      html`<p class="note shared" aria-hidden=${hidden ? "true" : nothing}>${icon(icons.lock)}<span>${reason}</span></p>`;
    // A section's only control, named like the section, doesn't repeat the name on its own line.
    const quiet = section.controls.length === 1 && sameName(section.controls[0].label, section.title);
    const formatter = (value: number, decimals: number) => formatNumber(hass, value, decimals, decimals);
    return this.card(
      section.id,
      section.title,
      html`${[...shared].map((reason) => note(reason, reason !== section.note))}
      ${repeat(
        section.controls,
        (control) => control.id,
        (control) => {
          const key = `${section.id}/${control.id}`;
          return html`<div class="control" data-control=${control.id}>
            ${renderControl(control, {
              t,
              pending: Boolean(this.pending[key]),
              error: this.errors[key] ?? null,
              onValue: (event) => void this.apply(key, control, event.detail.value),
              quiet,
              sharedReason: Boolean(control.disabled && control.reason && shared.has(control.reason)),
              formatNumber: formatter,
            })}
          </div>`;
        },
      )}`,
      !section.collapsed,
    );
  }

  static override styles = [
    tokens,
    toneStyles,
    buttonStyles,
    partStyles,
    css`
      :host {
        display: block;
        color: var(--bc-text);
        container-type: inline-size;
      }
      :host([dark]) {
        color-scheme: dark;
      }
      .layout {
        display: grid;
        grid-template-columns: minmax(300px, 5fr) minmax(0, 7fr);
        align-items: start;
        gap: 20px;
        max-width: 1240px;
        margin: 0 auto;
      }
      .hero,
      .card {
        box-sizing: border-box;
        border: var(--bc-border-width) solid var(--bc-border);
        border-radius: var(--bc-radius);
        background: var(--bc-card-bg);
        box-shadow: var(--ha-card-box-shadow, none);
      }
      /* The page scrolls under the panel's sticky toolbar; the drawing stays in view below it. */
      .hero {
        position: sticky;
        top: calc(var(--bc-toolbar-height, 0px) + 16px);
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 14px 16px 18px;
      }
      .hero-head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-height: 36px;
      }
      .status {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .hero-head .pill {
        max-width: none;
        padding: 4px 12px;
        font-size: 13px;
      }
      .ring {
        position: relative;
        display: inline-grid;
        place-items: center;
        width: 40px;
        height: 40px;
      }
      .ring svg {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
      }
      .ring circle {
        fill: none;
        stroke-width: 3.5;
      }
      .ring .track {
        stroke: var(--bc-control-bg);
      }
      .ring .bar {
        stroke: var(--bc-tone-warm);
        stroke-linecap: round;
        transition: stroke-dasharray 0.6s ease;
      }
      .ring-value {
        font-size: 10.5px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
      }
      /* The drawing takes its own proportions, up to a height that keeps it in view. */
      .stage,
      .stage .drawing {
        height: auto;
      }
      .stage .drawing > svg {
        max-height: min(62vh, 560px);
      }
      .sections {
        display: flex;
        flex-direction: column;
        gap: 12px;
        min-width: 0;
      }
      summary {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-height: 52px;
        padding: 0 16px;
        box-sizing: border-box;
        border-radius: var(--bc-radius);
        cursor: pointer;
        list-style: none;
        -webkit-tap-highlight-color: transparent;
      }
      summary::-webkit-details-marker {
        display: none;
      }
      summary:focus-visible {
        outline: 2px solid var(--bc-accent);
        outline-offset: -2px;
      }
      summary h2 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
      }
      .chevron {
        flex: none;
        width: 22px;
        height: 22px;
        fill: var(--bc-muted);
        transition: transform 0.2s;
      }
      details[open] > summary .chevron {
        transform: rotate(180deg);
      }
      .body {
        padding: 0 16px 12px;
      }
      .control {
        padding: 10px 0;
        border-top: 1px solid var(--bc-divider);
      }
      /* Values to read sit closer than controls to use, like Home Assistant's device info. */
      .control:has(> bc-reading, > bc-countdown) {
        padding: 7px 0;
      }
      .control:first-child,
      .note + .control {
        padding-top: 0;
        border-top: none;
      }
      .note {
        margin: 0 0 6px;
        color: var(--bc-muted);
      }
      .note.shared {
        display: flex;
        align-items: flex-start;
        gap: 6px;
        margin-bottom: 10px;
        font-size: 13px;
      }
      .note.shared svg {
        flex: none;
        width: 14px;
        height: 14px;
        margin-top: 2px;
        fill: currentColor;
      }
      @media (prefers-reduced-motion: reduce) {
        .chevron,
        .ring .bar {
          transition: none;
        }
      }
      /* Narrow: the drawing on top, short enough that the first controls show under it. */
      @container (max-width: 760px) {
        .layout {
          grid-template-columns: minmax(0, 1fr);
          gap: 12px;
        }
        .hero {
          position: static;
        }
        .stage .drawing > svg {
          max-height: min(40vh, 340px);
        }
      }
      :host([narrow]) .layout {
        grid-template-columns: minmax(0, 1fr);
        gap: 12px;
      }
      :host([narrow]) .hero {
        position: static;
      }
      :host([narrow]) .stage .drawing > svg {
        max-height: min(40vh, 340px);
      }
    `,
  ];
}

if (!customElements.get("bc-appliance-view")) customElements.define("bc-appliance-view", ApplianceView);

declare global {
  interface HTMLElementTagNameMap {
    "bc-appliance-view": ApplianceView;
  }
}
