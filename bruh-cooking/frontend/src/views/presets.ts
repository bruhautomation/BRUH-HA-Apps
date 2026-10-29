/**
 * The full view's presets: built-in ones, then those saved in Home Assistant. Choosing one fills
 * in the cook settings (bruh_cooking/panel/apply_preset) and moves focus to Start; nothing
 * starts by itself. Admins save the current settings as a preset, and rename, update and delete
 * saved ones.
 */
import { LitElement, css, html, nothing, svg, type PropertyValues } from "lit";
import { repeat } from "lit/directives/repeat.js";
import { partStyles, renderConfirmBar } from "../card/parts";
import { localizedError, translatorFor } from "../data/locale";
import { presetFits, presetName, presetSummary } from "../data/presets";
import type { HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import { buttonStyles, syncTheme, tokens } from "../styles";
import type { OvenModeSpec, PanelAppliance, Preset } from "../types";

/** Fired (bubbling, composed) once a preset filled in the settings; the view focuses Start. */
export const PRESET_APPLIED = "bc-preset-applied";

const PENCIL = svg`<path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83a.996.996 0 0 0 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" />`;
const UPDATE = svg`<path d="M17.7 6.3A8 8 0 1 0 19.7 14h-2.1A6 6 0 1 1 12 6c1.7 0 3.1.7 4.2 1.8L13 11h7V4l-2.3 2.3Z" />`;
const TRASH = svg`<path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12M8 9h8v10H8V9m7.5-5-1-1h-5l-1 1H5v2h14V4h-3.5z" />`;

type Editing = { kind: "new" } | { kind: "rename"; id: string } | { kind: "delete"; id: string } | { kind: "update"; id: string };

export class Presets extends LitElement {
  static override properties = {
    hass: { attribute: false },
    appliance: { attribute: false },
    presets: { attribute: false },
    modes: { attribute: false },
    cooking: { type: Boolean },
    busy: { state: true },
    editing: { state: true },
    message: { state: true },
    error: { state: true },
  };

  declare hass: HomeAssistant | undefined;
  declare appliance: PanelAppliance | undefined;
  declare presets: readonly Preset[];
  declare modes: ReadonlyMap<string, OvenModeSpec>;
  /** A cook is open: presets fill in the next cook, so they wait. */
  declare cooking: boolean;
  declare busy: boolean;
  declare editing: Editing | null;
  /** The last outcome, announced politely. */
  declare message: string | null;
  declare error: string | null;

  constructor() {
    super();
    this.presets = [];
    this.modes = new Map();
    this.cooking = false;
    this.busy = false;
    this.editing = null;
    this.message = null;
    this.error = null;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    syncTheme(this, this.hass);
    const before = changed.get("appliance") as PanelAppliance | undefined;
    if (changed.has("appliance") && before && before.device_id !== this.appliance?.device_id) {
      this.editing = null;
      this.message = null;
      this.error = null;
    }
  }

  private t(): Translate {
    return translatorFor(this.hass);
  }

  private async failure(error: unknown): Promise<string> {
    const t = this.t();
    const code = error && typeof error === "object" && "code" in error ? String((error as { code: unknown }).code) : "";
    const key = `presets.error.${code}`;
    const text = t(key);
    return text === key ? (await localizedError(this.hass, error)) || t("full.failed") : text;
  }

  private async call(message: Record<string, unknown>, done: (result: any) => string | null): Promise<boolean> {
    const hass = this.hass;
    if (!hass || this.busy) return false;
    this.busy = true;
    this.error = null;
    this.message = null;
    try {
      const result = await hass.callWS<unknown>(message);
      this.message = done(result);
      return true;
    } catch (error) {
      this.error = await this.failure(error);
      return false;
    } finally {
      this.busy = false;
    }
  }

  private async apply(preset: Preset): Promise<void> {
    const t = this.t();
    const name = presetName(t, preset);
    const applied = await this.call(
      { type: "bruh_cooking/panel/apply_preset", device_id: this.appliance?.device_id, preset_id: preset.id },
      () => t("presets.applied", { name }),
    );
    if (applied) this.dispatchEvent(new CustomEvent(PRESET_APPLIED, { bubbles: true, composed: true }));
  }

  private async save(event: Event, id?: string): Promise<void> {
    event.preventDefault();
    const input = (event.currentTarget as HTMLFormElement).querySelector<HTMLInputElement>("input[name=name]");
    const name = input?.value.trim() ?? "";
    if (!name) {
      input?.reportValidity();
      return;
    }
    const t = this.t();
    const saved = await this.call(
      id
        ? { type: "bruh_cooking/panel/save_preset", preset_id: id, name }
        : { type: "bruh_cooking/panel/save_preset", device_id: this.appliance?.device_id, name },
      () => t(id ? "presets.renamed" : "presets.saved", { name }),
    );
    if (saved) this.editing = null;
  }

  private async replaceSettings(preset: Preset): Promise<void> {
    const t = this.t();
    const updated = await this.call(
      { type: "bruh_cooking/panel/save_preset", preset_id: preset.id, device_id: this.appliance?.device_id },
      () => t("presets.updated", { name: presetName(t, preset) }),
    );
    if (updated) this.editing = null;
  }

  private async deletePreset(preset: Preset): Promise<void> {
    const t = this.t();
    const deleted = await this.call({ type: "bruh_cooking/panel/delete_preset", preset_id: preset.id }, () =>
      t("presets.deleted", { name: presetName(t, preset) }),
    );
    if (deleted) this.editing = null;
  }

  protected override render() {
    const { hass, appliance } = this;
    if (!hass || !appliance) return nothing;
    const t = this.t();
    const admin = hass.user?.is_admin === true;
    const fitting = this.presets.filter((preset) => presetFits(preset, appliance, this.modes));
    const builtin = fitting.filter((preset) => preset.builtin);
    const custom = fitting.filter((preset) => !preset.builtin);
    const blocked = !appliance.available ? t("reason.offline") : this.cooking ? t("presets.disabled_cooking") : null;
    return html`
      ${blocked ? html`<p class="note">${blocked}</p>` : nothing}
      <h3 id="builtin">${t("presets.builtin")}</h3>
      <ul class="list" aria-labelledby="builtin">
        ${repeat(
          builtin,
          (preset) => preset.id,
          (preset) => this.renderRow(t, preset, blocked, false),
        )}
      </ul>
      <h3 id="custom">${t("presets.custom")}</h3>
      ${custom.length
        ? html`<ul class="list" aria-labelledby="custom">
            ${repeat(
              custom,
              (preset) => preset.id,
              (preset) => this.renderRow(t, preset, blocked, admin),
            )}
          </ul>`
        : html`<p class="note">${t(admin ? "presets.none_admin" : "presets.none")}</p>`}
      ${admin ? this.renderNew(t) : nothing}
      <p class="status" role="status">${this.message ?? ""}</p>
      ${this.error ? html`<p class="error" role="alert">${this.error}</p>` : nothing}
      <p class="disclaimer">${t("presets.disclaimer")}</p>
    `;
  }

  private renderRow(t: Translate, preset: Preset, blocked: string | null, editable: boolean) {
    const hass = this.hass!;
    const name = presetName(t, preset);
    const summary = presetSummary(hass, t, preset, this.modes);
    const editing = this.editing && "id" in this.editing && this.editing.id === preset.id ? this.editing : null;
    if (editing?.kind === "rename") {
      return html`<li class="row">
        <form class="rename" @submit=${(event: Event) => void this.save(event, preset.id)}>
          <input name="name" maxlength="40" required .value=${name} aria-label=${t("presets.name")} />
          <button type="submit" class="bc-button primary" ?disabled=${this.busy}>${t("presets.save")}</button>
          <button type="button" class="bc-button" @click=${() => (this.editing = null)}>${t("presets.cancel")}</button>
        </form>
      </li>`;
    }
    const id = `p-${preset.id}`;
    return html`<li class="row">
      <button
        type="button"
        class="apply"
        aria-describedby=${`${id}-summary${preset.note ? ` ${id}-note` : ""}${blocked ? ` ${id}-blocked` : ""}`}
        aria-disabled=${blocked || this.busy ? "true" : nothing}
        @click=${() => {
          if (!blocked && !this.busy) void this.apply(preset);
        }}
      >
        <span class="name">${name}</span>
        <span class="summary" id=${`${id}-summary`}>${summary}</span>
        ${preset.note ? html`<span class="warning" id=${`${id}-note`}>${t(`presets.note.${preset.note}`)}</span>` : nothing}
        ${blocked ? html`<span class="visually-hidden" id=${`${id}-blocked`}>${blocked}</span>` : nothing}
      </button>
      ${editable
        ? html`<span class="tools">
            ${this.tool(PENCIL, t("presets.rename_named", { name }), () => (this.editing = { kind: "rename", id: preset.id }))}
            ${this.tool(UPDATE, t("presets.update_named", { name }), () => (this.editing = { kind: "update", id: preset.id }), Boolean(blocked))}
            ${this.tool(TRASH, t("presets.delete_named", { name }), () => (this.editing = { kind: "delete", id: preset.id }))}
          </span>`
        : nothing}
      ${editing?.kind === "delete"
        ? html`<div class="ask">
            ${renderConfirmBar({
              text: t("presets.delete_confirm", { name }),
              confirm: t("presets.delete"),
              cancel: t("presets.cancel"),
              tone: "danger",
              busy: this.busy,
              onConfirm: () => void this.deletePreset(preset),
              onCancel: () => (this.editing = null),
            })}
          </div>`
        : nothing}
      ${editing?.kind === "update"
        ? html`<div class="ask">
            ${renderConfirmBar({
              text: t("presets.update_confirm", { name }),
              confirm: t("presets.update"),
              cancel: t("presets.cancel"),
              busy: this.busy,
              onConfirm: () => void this.replaceSettings(preset),
              onCancel: () => (this.editing = null),
            })}
          </div>`
        : nothing}
    </li>`;
  }

  private tool(path: unknown, label: string, action: () => void, disabled = false) {
    return html`<button
      type="button"
      class="tool"
      aria-label=${label}
      title=${label}
      aria-disabled=${disabled ? "true" : nothing}
      @click=${() => {
        if (!disabled) {
          action();
          void this.updateComplete.then(() => this.renderRoot.querySelector<HTMLElement>(".ask .bc-button, .rename input")?.focus());
        }
      }}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg>
    </button>`;
  }

  private renderNew(t: Translate) {
    if (this.editing?.kind !== "new") {
      return html`<button
        type="button"
        class="bc-button save"
        ?disabled=${!this.appliance?.available}
        @click=${() => {
          this.editing = { kind: "new" };
          void this.updateComplete.then(() => this.renderRoot.querySelector<HTMLInputElement>("form.new input")?.focus());
        }}
      >
        ${t("presets.save_current")}
      </button>`;
    }
    return html`<form class="new" @submit=${(event: Event) => void this.save(event)}>
      <label for="new-name">${t("presets.name")}</label>
      <div class="fields">
        <input id="new-name" name="name" maxlength="40" required autocomplete="off" />
        <button type="submit" class="bc-button primary" ?disabled=${this.busy}>${t("presets.save")}</button>
        <button type="button" class="bc-button" @click=${() => (this.editing = null)}>${t("presets.cancel")}</button>
      </div>
      <p class="hint">${t("presets.save_hint")}</p>
    </form>`;
  }

  static override styles = [
    tokens,
    buttonStyles,
    partStyles,
    css`
      :host {
        display: block;
        color: var(--bc-text);
        font-size: 14px;
      }
      h3 {
        margin: 4px 0 6px;
        font-size: 13px;
        font-weight: 600;
        color: var(--bc-muted);
        text-transform: none;
      }
      h3:not(:first-of-type) {
        margin-top: 14px;
      }
      .list {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 230px), 1fr));
        gap: 6px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .row {
        position: relative;
        display: flex;
        flex-wrap: wrap;
        align-items: stretch;
        gap: 4px;
        min-width: 0;
      }
      .apply {
        display: flex;
        flex: 1 1 auto;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        min-width: 0;
        min-height: 52px;
        padding: 8px 12px;
        box-sizing: border-box;
        border: none;
        border-radius: 12px;
        background: var(--bc-control-bg);
        color: inherit;
        font: inherit;
        text-align: start;
        cursor: pointer;
        -webkit-tap-highlight-color: transparent;
        transition: background-color 0.15s;
      }
      .apply:hover:not([aria-disabled="true"]) {
        background: var(--bc-control-hover);
      }
      .apply[aria-disabled="true"] {
        opacity: 0.55;
        cursor: default;
      }
      .apply:focus-visible,
      .tool:focus-visible,
      input:focus-visible {
        outline: 2px solid var(--bc-accent);
        outline-offset: 2px;
      }
      .name {
        font-weight: 600;
      }
      .summary {
        color: var(--bc-muted-inset);
        font-size: 12.5px;
        font-variant-numeric: tabular-nums;
      }
      .warning {
        color: var(--bc-warning-text);
        font-size: 12px;
      }
      .tools {
        display: flex;
        align-items: center;
        gap: 2px;
      }
      .tool {
        display: grid;
        place-items: center;
        width: 32px;
        height: 32px;
        padding: 0;
        border: none;
        border-radius: 50%;
        background: none;
        color: var(--bc-muted);
        cursor: pointer;
      }
      .tool:hover:not([aria-disabled="true"]) {
        background: var(--bc-control-bg);
        color: var(--bc-text);
      }
      .tool[aria-disabled="true"] {
        opacity: 0.4;
        cursor: default;
      }
      .tool svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
      }
      .ask {
        flex-basis: 100%;
      }
      .save {
        margin-top: 12px;
      }
      form.new {
        margin-top: 12px;
      }
      form.new label {
        display: block;
        margin-bottom: 4px;
        font-weight: 500;
      }
      .fields,
      .rename {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        width: 100%;
      }
      input {
        flex: 1 1 12em;
        min-height: 40px;
        box-sizing: border-box;
        padding: 6px 12px;
        border: 1px solid var(--bc-divider);
        border-radius: 10px;
        background: transparent;
        color: inherit;
        font: inherit;
      }
      .hint,
      .note,
      .disclaimer {
        margin: 6px 0 0;
        color: var(--bc-muted);
        font-size: 12.5px;
        line-height: 1.45;
      }
      .note {
        margin: 0 0 8px;
        font-size: 13px;
      }
      .status:empty {
        display: none;
      }
      .status {
        margin: 10px 0 0;
        color: var(--bc-text);
        font-size: 13px;
      }
      .error {
        margin: 8px 0 0;
        color: var(--bc-error-text);
        font-size: 13px;
      }
      .disclaimer {
        margin-top: 12px;
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
      @media (any-pointer: coarse) {
        .tool {
          width: 44px;
          height: 44px;
        }
        input {
          min-height: 44px;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .apply {
          transition: none;
        }
      }
    `,
  ];
}

if (!customElements.get("bc-presets")) customElements.define("bc-presets", Presets);

declare global {
  interface HTMLElementTagNameMap {
    "bc-presets": Presets;
  }
}
