import { css } from "lit";

/**
 * The controls' layout and widgets. Colors come from the `--bc-*` tokens (styles.ts), which the
 * full view defines and the controls inherit; the fallbacks keep a control legible on its own.
 * Targets are 40 px, and 44 px wherever there's a finger to tap with.
 */
export const controlStyles = css`
  :host {
    display: block;
    color: var(--bc-text, var(--primary-text-color, #1f2328));
    font-size: 14px;
    line-height: 1.35;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px 16px;
    min-height: 40px;
  }
  /* One column that never wraps: a wrapping column sizes its height from its content's narrowest
     layout, which for the mode tiles is one tile per row. */
  .row.stacked {
    flex-direction: column;
    flex-wrap: nowrap;
    align-items: stretch;
  }
  /* In a column the flex basis would be a height, so stacked parts take their own. */
  .row.stacked .text,
  .row.stacked .widget {
    flex: none;
  }
  .text {
    display: flex;
    flex: 1 1 9em;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
  }
  .label {
    font-weight: 500;
  }
  /* Still read out: the label of a quiet control, and a reason the section shows once. */
  :host([quiet]) .row.stacked .label,
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  .aside {
    color: var(--bc-muted, #6b7178);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .hint {
    color: var(--bc-muted, #6b7178);
    font-size: 12.5px;
    white-space: pre-line;
  }
  .widget {
    display: flex;
    flex: 0 1 auto;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    max-width: 100%;
  }
  .reason,
  .error {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin-top: 6px;
    font-size: 12.5px;
  }
  .reason {
    color: var(--bc-muted, #6b7178);
  }
  .reason svg {
    flex: none;
    width: 14px;
    height: 14px;
    margin-top: 1px;
    fill: currentColor;
  }
  .error {
    color: var(--bc-error-text, #b3261e);
  }
  .ask {
    margin-top: 8px;
  }
  .link {
    display: inline-block;
    margin-top: 4px;
    font-size: 12.5px;
    font-weight: 500;
    color: var(--bc-accent, #03a9f4);
  }

  /* A small ring while a call is in flight. */
  .spinner {
    flex: none;
    width: 16px;
    height: 16px;
    box-sizing: border-box;
    border: 2px solid var(--bc-control-bg, rgba(127, 127, 127, 0.25));
    border-top-color: var(--bc-accent, #03a9f4);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* Choices as separate chips, the chosen one filled: the same whether they fit beside the label
     or wrap under it, and the same as the timer presets. */
  .segmented {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 6px;
    max-width: 100%;
  }
  .segmented button {
    flex: 0 0 auto;
    min-height: 40px;
    padding: 6px 14px;
    border: none;
    border-radius: 999px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
    color: inherit;
    font: inherit;
    font-size: 13.5px;
    font-weight: 600;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.15s, color 0.15s;
  }
  .segmented button:hover:not([aria-disabled="true"]):not([aria-pressed="true"]) {
    background: var(--bc-control-hover, rgba(127, 127, 127, 0.2));
  }
  .segmented button[aria-pressed="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    color: var(--bc-on-accent, #ffffff);
  }
  .segmented button:disabled,
  .segmented button[aria-disabled="true"] {
    cursor: default;
  }
  .segmented.disabled {
    opacity: 0.55;
  }

  /* The oven's modes: a grid of tiles, the chosen one filled. */
  /* A block, not a flex row, around the grid: a flex row sizes its height from the grid's
     narrowest layout (one tile per row), then centres the real grid in all that height. */
  .widget:has(> .tiles) {
    display: block;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(118px, 1fr));
    gap: 6px;
    width: 100%;
  }
  .tile {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 6px 10px;
    box-sizing: border-box;
    border-radius: 12px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
    font-size: 13.5px;
    font-weight: 600;
    line-height: 1.2;
    text-align: center;
    cursor: pointer;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.15s, color 0.15s;
  }
  .tile:hover:not([aria-selected="true"]) {
    background: var(--bc-control-hover, rgba(127, 127, 127, 0.2));
  }
  .tile[aria-selected="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    color: var(--bc-on-accent, #ffffff);
  }
  .tile:focus-visible {
    outline: 2px solid var(--bc-accent, #03a9f4);
    outline-offset: 2px;
  }
  .tiles.disabled .tile {
    opacity: 0.55;
    cursor: default;
  }
  .tiles.disabled .tile:hover:not([aria-selected="true"]) {
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
  }
  .custom label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--bc-muted, #6b7178);
  }
  .custom input[type="number"] {
    width: 4.5em;
  }

  /* The dropdown for more than five choices. */
  .dropdown {
    position: relative;
    display: inline-flex;
    max-width: 100%;
  }
  .dropdown select {
    max-width: 100%;
    min-height: 40px;
    padding: 7px 36px 7px 14px;
    border: none;
    border-radius: 999px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
    color: inherit;
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    text-overflow: ellipsis;
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
  }
  /* Locked but focusable: it doesn't open, by pointer or key (see BcSelect). */
  .dropdown select[aria-disabled="true"] {
    opacity: 0.55;
    cursor: default;
    pointer-events: none;
  }
  .dropdown svg {
    position: absolute;
    top: 50%;
    right: 12px;
    width: 18px;
    height: 18px;
    margin-top: -9px;
    fill: currentColor;
    pointer-events: none;
  }

  /* An on/off switch, in the same blue as a chosen chip. */
  .switch {
    position: relative;
    flex: none;
    width: 48px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: 999px;
    background: var(--bc-switch-off, rgba(127, 127, 127, 0.5));
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.2s;
  }
  /* A 56 × 44 target for fingers around the smaller switch. */
  .switch::before {
    content: "";
    position: absolute;
    inset: -8px -4px;
  }
  .switch::after {
    content: "";
    position: absolute;
    top: 3px;
    left: 3px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
    transition: transform 0.2s;
  }
  .switch[aria-checked="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
  }
  .switch[aria-checked="true"]::after {
    transform: translateX(20px);
  }
  /* A switch whose entity has no state yet: neither on nor off. */
  .switch.unknown::after {
    transform: translateX(10px);
  }
  .switch:disabled,
  .switch[aria-disabled="true"] {
    opacity: 0.5;
    cursor: default;
  }

  /* Minus, the value, plus. */
  .stepper {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 3px;
    border-radius: 999px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
  }
  .stepper button {
    display: grid;
    place-items: center;
    width: 40px;
    height: 40px;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: inherit;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
  }
  .stepper button:hover:not(:disabled):not([aria-disabled="true"]) {
    background: var(--bc-control-hover, rgba(127, 127, 127, 0.2));
  }
  .stepper button:disabled,
  .stepper button[aria-disabled="true"] {
    opacity: 0.35;
    cursor: default;
  }
  .stepper svg {
    width: 20px;
    height: 20px;
    fill: currentColor;
  }
  .stepper output {
    min-width: 4.2em;
    font-size: 17px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    text-align: center;
  }
  /* On the stepper's grey, the muted color falls short of 4.5:1; the text color, softened, doesn't. */
  .stepper output .unit {
    margin-inline-start: 1px;
    font-size: 13px;
    font-weight: 500;
    color: color-mix(in srgb, var(--bc-text, #1f2328) 72%, transparent);
  }
  /* No setpoint, like a blank display. */
  .stepper output.empty {
    color: var(--bc-muted, #6b7178);
    font-weight: 500;
    letter-spacing: 0.06em;
  }
  .stepper.draft output {
    color: var(--bc-accent, #03a9f4);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chips .bc-button {
    min-height: 40px;
    padding: 6px 14px;
    font-size: 13.5px;
  }
  .chips .bc-button[aria-pressed="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    color: var(--bc-on-accent, #ffffff);
  }

  .reading {
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    text-align: end;
  }
  /* Text tokens, not the raw tones: amber and red text need more ink to reach 4.5:1. */
  .reading[data-tone="warning"] {
    color: var(--bc-warning-text, #8a5a00);
  }
  .reading[data-tone="alert"] {
    color: var(--bc-error-text, #b3261e);
  }

  input[type="number"],
  input[type="time"] {
    min-height: 40px;
    box-sizing: border-box;
    padding: 6px 12px;
    border: 1px solid var(--bc-divider, rgba(127, 127, 127, 0.35));
    border-radius: 10px;
    background: transparent;
    color: inherit;
    font: inherit;
    font-variant-numeric: tabular-nums;
  }
  input[type="number"] {
    width: 6em;
  }

  .slider {
    display: grid;
    grid-template-columns: minmax(6em, auto) 1fr 4.2em;
    align-items: center;
    gap: 12px;
  }
  .slider span {
    color: var(--bc-muted, #6b7178);
    font-size: 13px;
  }
  .slider output {
    font-variant-numeric: tabular-nums;
    text-align: end;
  }
  /* Both sliders share a track and a thumb: brightness fills its track with the accent up to the
     value, white temperature shows its warm-to-cool range. */
  input[type="range"] {
    width: 100%;
    min-width: 0;
    height: 8px;
    margin: 0;
    border-radius: 999px;
    background: linear-gradient(
      90deg,
      var(--bc-accent-fill, var(--bc-accent, #03a9f4)) var(--filled, 0%),
      var(--bc-control-bg, rgba(127, 127, 127, 0.14)) var(--filled, 0%)
    );
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
  }
  input[type="range"].kelvin {
    background: linear-gradient(90deg, #ffb46b, #fff4e6 55%, #d6e6ff);
    box-shadow: inset 0 0 0 1px var(--bc-inset-edge, rgba(0, 0, 0, 0.08));
  }
  input[type="range"]::-moz-range-track {
    background: transparent;
  }
  input[type="range"]::-webkit-slider-thumb {
    width: 20px;
    height: 20px;
    border: 2px solid #ffffff;
    border-radius: 50%;
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
    -webkit-appearance: none;
    appearance: none;
  }
  input[type="range"]::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border: 2px solid #ffffff;
    border-radius: 50%;
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  }
  input[type="range"]:disabled {
    opacity: 0.5;
    cursor: default;
  }

  button:focus-visible,
  select:focus-visible,
  input:focus-visible {
    outline: 2px solid var(--bc-accent, #03a9f4);
    outline-offset: 2px;
  }

  /* Bigger targets wherever there's a finger: touch laptops report a mouse as their main pointer. */
  @media (any-pointer: coarse) {
    .segmented button,
    .tile,
    .chips .bc-button,
    .dropdown select,
    input[type="number"],
    input[type="time"] {
      min-height: 44px;
    }
    .stepper button {
      width: 44px;
      height: 44px;
    }
    input[type="range"]::-webkit-slider-thumb {
      width: 24px;
      height: 24px;
    }
    input[type="range"]::-moz-range-thumb {
      width: 20px;
      height: 20px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .spinner {
      animation-duration: 2.4s;
    }
    .switch,
    .switch::after,
    .segmented button {
      transition: none;
    }
  }
`;
