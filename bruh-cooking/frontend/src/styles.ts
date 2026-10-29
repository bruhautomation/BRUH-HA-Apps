import { css } from "lit";
import type { HomeAssistant } from "./hass";

/**
 * Shared CSS: colors derived from Home Assistant's theme variables, so the panel follows light
 * and dark themes and any custom theme. An element that uses them reflects `dark` from
 * `hass.themes.darkMode` (see `syncTheme`); each element sets its own tokens rather than
 * inheriting the panel's, so it also looks right on its own (the gallery, tests).
 */
export const tokens = css`
  :host {
    --bc-text: var(--primary-text-color, #1f2328);
    --bc-muted: var(--secondary-text-color, #6b7178);
    /* Secondary text on an inset or a control's fill, where the plain muted color falls a little
       short of 4.5:1: a quarter of the way to the text color. */
    --bc-muted-inset: color-mix(in srgb, var(--bc-muted) 75%, var(--bc-text));
    --bc-card-bg: var(--ha-card-background, var(--card-background-color, #ffffff));
    --bc-page-bg: var(--primary-background-color, #f4f5f6);
    --bc-radius: var(--ha-card-border-radius, 12px);
    --bc-border-width: var(--ha-card-border-width, 1px);
    --bc-border: var(--ha-card-border-color, var(--divider-color, rgba(0, 0, 0, 0.12)));
    --bc-divider: var(--divider-color, rgba(0, 0, 0, 0.12));
    --bc-accent: var(--primary-color, #03a9f4);
    --bc-on-accent: var(--text-primary-color, #ffffff);
    --bc-error: var(--error-color, #db4437);
    /* Tone text is the tone mixed toward the ink: darker on light themes, lighter on dark ones,
       so a status reads clearly on its tinted pill either way. */
    --bc-ink: #000000;
    --bc-tone-strength: 66%;
    --bc-tone-neutral: var(--primary-text-color, #1f2328);
    --bc-tone-accent: var(--primary-color, #03a9f4);
    --bc-tone-warm: #e8590c;
    --bc-tone-amber: #e69500;
    --bc-tone-green: var(--success-color, #43a047);
    --bc-tone-red: var(--error-color, #db4437);
    --bc-tone-gray: var(--secondary-text-color, #6b7178);
    /* Warning and error text, mixed toward the ink like the tones so it reaches 4.5:1 on the card;
       borders and fills keep the raw colors. */
    --bc-warning-text: color-mix(in srgb, var(--bc-tone-amber) var(--bc-tone-strength), var(--bc-ink));
    --bc-error-text: color-mix(in srgb, var(--bc-error) 80%, var(--bc-ink));
    /* Insets such as the info panel, and the fill of buttons and segmented controls. */
    --bc-inset-bg: rgba(0, 0, 0, 0.04);
    --bc-inset-edge: rgba(0, 0, 0, 0.08);
    --bc-control-bg: rgba(0, 0, 0, 0.06);
    --bc-control-hover: rgba(0, 0, 0, 0.1);
    --bc-lift: 0 8px 24px rgba(0, 0, 0, 0.12);
    /* A switch's off track, at 3:1 against the card so an off switch still reads as one. */
    --bc-switch-off: color-mix(in srgb, var(--bc-text) 50%, transparent);
    /* Fills behind white text (chosen segments, primary and danger buttons), darkened from the
       theme's colors so the text reaches 4.5:1. */
    --bc-accent-fill: color-mix(in srgb, var(--bc-accent) 68%, #000000);
    --bc-danger-fill: color-mix(in srgb, var(--bc-error) 88%, #000000);
  }
  :host([dark]) {
    --bc-ink: #ffffff;
    --bc-tone-strength: 76%;
    --bc-tone-warm: #ff8a4c;
    --bc-tone-amber: #ffb83d;
    --bc-inset-bg: rgba(8, 10, 12, 0.5);
    --bc-inset-edge: rgba(255, 255, 255, 0.08);
    --bc-control-bg: rgba(255, 255, 255, 0.09);
    --bc-control-hover: rgba(255, 255, 255, 0.14);
    --bc-lift: 0 8px 28px rgba(0, 0, 0, 0.45);
    --bc-switch-off: color-mix(in srgb, var(--bc-text) 40%, transparent);
  }
`;

/** `data-tone` sets `--tone`, which pills and other status marks color themselves with. */
export const toneStyles = css`
  [data-tone="neutral"] {
    --tone: var(--bc-tone-neutral);
  }
  [data-tone="accent"] {
    --tone: var(--bc-tone-accent);
  }
  [data-tone="warm"] {
    --tone: var(--bc-tone-warm);
  }
  [data-tone="amber"] {
    --tone: var(--bc-tone-amber);
  }
  /* Amber is so light that its text needs more ink on a light theme to reach 4.5:1. */
  :host(:not([dark])) [data-tone="amber"] {
    --bc-tone-strength: 60%;
  }
  [data-tone="green"] {
    --tone: var(--bc-tone-green);
  }
  [data-tone="red"] {
    --tone: var(--bc-tone-red);
  }
  [data-tone="gray"] {
    --tone: var(--bc-tone-gray);
  }
`;

/** Pill buttons as on the GE appliance card: neutral, primary (the accent) and danger. */
export const buttonStyles = css`
  .bc-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 40px;
    padding: 8px 16px;
    border: none;
    border-radius: 999px;
    background: var(--bc-control-bg);
    color: var(--bc-text);
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.2;
    text-decoration: none;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.15s, opacity 0.15s;
  }
  .bc-button:hover {
    background: var(--bc-control-hover);
  }
  .bc-button.primary {
    background: var(--bc-accent-fill, var(--bc-accent));
    color: var(--bc-on-accent);
  }
  .bc-button.danger {
    background: var(--bc-danger-fill, var(--bc-error));
    color: #ffffff;
  }
  .bc-button:is(.primary, .danger):hover:not(:disabled, [aria-disabled="true"]) {
    opacity: 0.9;
  }
  .bc-button:disabled,
  .bc-button[aria-disabled="true"] {
    opacity: 0.45;
    cursor: default;
  }
  /* A button that can't be pressed doesn't answer the pointer. */
  .bc-button:not(.primary, .danger):is(:disabled, [aria-disabled="true"]):hover {
    background: var(--bc-control-bg);
  }
  .bc-button:focus-visible {
    outline: 2px solid var(--bc-accent);
    outline-offset: 2px;
  }
  /* Touch laptops report a mouse as their main pointer, so any finger gets the bigger target. */
  @media (any-pointer: coarse) {
    .bc-button {
      min-height: 44px;
    }
  }
`;

/** Reflects the Home Assistant theme as the `dark` attribute the tokens switch on. */
export function syncTheme(element: HTMLElement, hass: Pick<HomeAssistant, "themes"> | undefined): void {
  element.toggleAttribute("dark", hass?.themes?.darkMode === true);
}
