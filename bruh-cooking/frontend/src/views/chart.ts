/**
 * The temperature chart: the current cook's temperature against its target, since the cook
 * started, or the last cook until the next one starts. For the oven, a dashed line shows the
 * temperature it holds its own sensor at, below the setpoint, so the gap doesn't read as a fault.
 * Drawn by hand in SVG; a sentence sums it up for screen readers, and a table shows the readings.
 */
import { LitElement, css, html, nothing, svg, type PropertyValues } from "lit";
import { panelHelpers } from "../data/helpers";
import type { CookChart, Point } from "../data/history";
import { translatorFor } from "../data/locale";
import {
  formatClock,
  formatDateTime,
  formatNumber,
  formatTemperature,
  fromCelsius,
  isCelsius,
  temperatureUnit,
} from "../kinds/common";
import type { HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import { buttonStyles, syncTheme, tokens } from "../styles";
import type { PanelAppliance } from "../types";

// Drawn at the size it's shown, so its text stays 11 px whatever the width.
const DEFAULT_WIDTH = 600;
const PAD = { left: 46, right: 14, top: 12, bottom: 26 };
// Table rows at most, sampled evenly.
const TABLE_ROWS = 24;
const TIME_STEPS_MIN = [5, 10, 15, 30, 60, 120, 180, 360, 720];

/** The value of a stepped series at a moment: its last reading at or before it. */
export function valueAt(points: readonly Point[], at: number): number | null {
  let value: number | null = null;
  for (const point of points) {
    if (point.at > at) break;
    value = point.value;
  }
  return value;
}

/**
 * Since when the temperature has stayed within `tolerance` of the target, up to its latest
 * reading; null when it isn't there now.
 */
export function atTemperatureSince(current: readonly Point[], target: readonly Point[], tolerance: number): number | null {
  let since: number | null = null;
  for (let index = current.length - 1; index >= 0; index--) {
    const point = current[index];
    const goal = valueAt(target, point.at);
    if (goal === null || Math.abs(point.value - goal) > tolerance) break;
    since = point.at;
  }
  return since;
}

/** Round tick values covering `min` to `max`, about `count` of them. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  const span = Math.max(max - min, 1e-6);
  const raw = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((factor) => factor * magnitude).find((candidate) => candidate >= raw) ?? raw;
  // From the first tick at or below the lowest value to the first at or above the highest, so
  // the target line always sits inside the axis.
  const ticks: number[] = [];
  const last = Math.ceil(max / step - 1e-9) * step;
  for (let value = Math.floor(min / step + 1e-9) * step; value <= last + step * 1e-6; value += step) ticks.push(Number(value.toFixed(6)));
  return ticks;
}

export class TempChart extends LitElement {
  static override properties = {
    hass: { attribute: false },
    appliance: { attribute: false },
    now: { attribute: false },
    table: { state: true },
    width: { state: true },
  };

  declare hass: HomeAssistant | undefined;
  declare appliance: PanelAppliance | undefined;
  declare now: number;
  declare table: boolean;
  /** The chart's width in CSS pixels. */
  declare width: number;

  private stop: (() => void) | undefined;
  private observer: ResizeObserver | undefined;

  constructor() {
    super();
    this.now = Date.now();
    this.table = false;
    this.width = DEFAULT_WIDTH;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.stop = panelHelpers.onChange(() => this.requestUpdate());
    if (typeof ResizeObserver === "function") {
      this.observer ??= new ResizeObserver((entries) => {
        const width = Math.round(entries[entries.length - 1]?.contentRect.width ?? 0);
        if (width > 0 && width !== this.width) this.width = width;
      });
      this.observer.observe(this);
    }
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.stop?.();
    this.stop = undefined;
    this.observer?.disconnect();
  }

  protected override willUpdate(_changed: PropertyValues<this>): void {
    syncTheme(this, this.hass);
  }

  protected override render() {
    const { hass, appliance } = this;
    if (!hass || !appliance) return nothing;
    const t = translatorFor(hass);
    const chart = panelHelpers.history.chart(hass, appliance);
    if (chart.status === "loading" && !chart.current.length) return html`<p class="note">${t("chart.loading")}</p>`;
    if (chart.status === "failed") return html`<p class="note">${t("chart.failed")}</p>`;
    if (chart.status === "none" || !chart.window) return html`<p class="note">${t("chart.none")}</p>`;
    const unit = temperatureUnit(hass);
    const sensor = appliance.sensor_target_c === null ? null : fromCelsius(hass, appliance.sensor_target_c);
    return html`
      <p class="summary">${this.summary(t, chart, unit, sensor)}</p>
      <figure>
        ${this.renderSvg(chart, unit, sensor)}
        <figcaption class="legend" aria-hidden="true">
          <span><i class="key current"></i>${t("chart.temperature")}</span>
          <span><i class="key target"></i>${t("chart.target")}</span>
          ${sensor !== null ? html`<span><i class="key sensor"></i>${t("chart.sensor_target")}</span>` : nothing}
        </figcaption>
      </figure>
      ${sensor !== null ? html`<p class="note">${t("chart.sensor_caption")}</p>` : nothing}
      <button type="button" class="bc-button" aria-expanded=${this.table ? "true" : "false"} @click=${() => (this.table = !this.table)}>
        ${t(this.table ? "chart.hide_table" : "chart.show_table")}
      </button>
      ${this.table ? this.renderTable(t, chart, unit) : nothing}
    `;
  }

  private summary(t: Translate, chart: CookChart, unit: string, sensor: number | null): string {
    const hass = this.hass!;
    const decimals = this.appliance?.kind === "sous_vide" ? 1 : 0;
    const last = chart.current[chart.current.length - 1];
    const goal = valueAt(chart.target, chart.to);
    const parts: string[] = [];
    if (chart.window?.end != null) {
      parts.push(
        t("chart.last_cook", {
          start: formatDateTime(hass, chart.window.start, this.now),
          end: formatClock(hass, chart.window.end),
        }),
      );
    }
    if (last) {
      const now = formatTemperature(hass, last.value, unit, decimals);
      parts.push(
        goal === null
          ? t(chart.window?.end != null ? "chart.summary_last" : "chart.summary_now", { now })
          : t(chart.window?.end != null ? "chart.summary_last_target" : "chart.summary_now_target", {
              now,
              target: formatTemperature(hass, goal, unit, decimals),
            }),
      );
    }
    if (this.appliance?.kind === "sous_vide" && chart.window?.end == null) {
      const since = atTemperatureSince(chart.current, chart.target, isCelsius(hass) ? 0.5 : 1);
      if (since !== null) parts.push(t("chart.at_temperature_since", { time: formatDateTime(hass, since, this.now) }));
    }
    if (sensor !== null) parts.push(t("chart.sensor_summary", { temp: formatTemperature(hass, sensor, unit) }));
    if (chart.window && chart.from > chart.window.start) parts.push(t("chart.last_day"));
    return parts.join(" ");
  }

  private renderSvg(chart: CookChart, unit: string, sensor: number | null) {
    const hass = this.hass!;
    const WIDTH = Math.max(260, this.width);
    const HEIGHT = Math.round(Math.min(240, Math.max(170, WIDTH * 0.36)));
    const values = [...chart.current, ...chart.target].map((point) => point.value);
    if (sensor !== null) values.push(sensor);
    const pad = this.appliance?.kind === "oven" ? 10 : 1;
    let low = values.length ? Math.min(...values) - pad : 0;
    let high = values.length ? Math.max(...values) + pad : 100;
    if (high - low < 4) {
      low -= 2;
      high += 2;
    }
    const ticks = niceTicks(low, high, 4);
    low = Math.min(low, ticks[0]);
    high = Math.max(high, ticks[ticks.length - 1]);
    const from = chart.from;
    const to = Math.max(chart.to, from + 60_000);
    const x = (at: number) => PAD.left + ((at - from) / (to - from)) * (WIDTH - PAD.left - PAD.right);
    const y = (value: number) => HEIGHT - PAD.bottom - ((value - low) / (high - low)) * (HEIGHT - PAD.top - PAD.bottom);
    const clipped = (points: readonly Point[]) => points.filter((point) => point.at >= from - 1 && point.at <= to + 1);
    const line = (points: readonly Point[]) =>
      clipped(points)
        .map((point, index) => `${index ? "L" : "M"}${x(point.at).toFixed(1)},${y(point.value).toFixed(1)}`)
        .join("");
    // The target holds each value until the next: a step line, carried to the end.
    const startTarget = valueAt(chart.target, from);
    const steps: Point[] = startTarget === null ? [] : [{ at: from, value: startTarget }];
    for (const point of clipped(chart.target)) {
      const previous = steps[steps.length - 1];
      if (previous) steps.push({ at: point.at, value: previous.value });
      steps.push(point);
    }
    if (steps.length) steps.push({ at: to, value: steps[steps.length - 1].value });
    const minutes = (to - from) / 60_000;
    // About one time label per 90 px.
    const labels = Math.max(2, Math.floor((WIDTH - PAD.left - PAD.right) / 90));
    const stepMin = TIME_STEPS_MIN.find((step) => minutes / step <= labels) ?? 1440;
    const first = Math.ceil(from / (stepMin * 60_000)) * stepMin * 60_000;
    const times: number[] = [];
    for (let at = first; at <= to; at += stepMin * 60_000) times.push(at);
    return html`<svg class="chart" viewBox="0 0 ${WIDTH} ${HEIGHT}" width=${WIDTH} height=${HEIGHT} aria-hidden="true">
      ${ticks.map(
        (tick) => svg`<line class="grid" x1=${PAD.left} x2=${WIDTH - PAD.right} y1=${y(tick)} y2=${y(tick)}></line>
          <text class="axis" x=${PAD.left - 6} y=${y(tick) + 4} text-anchor="end">${formatNumber(hass, tick, 1)}°</text>`,
      )}
      ${times.map(
        (at) => svg`<text class="axis" x=${x(at)} y=${HEIGHT - 8} text-anchor="middle">${formatClock(hass, at)}</text>`,
      )}
      ${sensor !== null
        ? svg`<line class="sensor" x1=${PAD.left} x2=${WIDTH - PAD.right} y1=${y(sensor)} y2=${y(sensor)}></line>`
        : nothing}
      ${steps.length ? svg`<path class="target" d=${line(steps)}></path>` : nothing}
      <path class="current" d=${line(chart.current)}></path>
      <text class="unit" x="4" y="14">${unit}</text>
    </svg>`;
  }

  private renderTable(t: Translate, chart: CookChart, unit: string) {
    const hass = this.hass!;
    const decimals = this.appliance?.kind === "sous_vide" ? 1 : 0;
    const points = chart.current;
    const step = Math.max(1, Math.ceil(points.length / TABLE_ROWS));
    const rows = points.filter((_, index) => index % step === 0 || index === points.length - 1);
    return html`<table>
      <caption class="visually-hidden">${t("chart.table_caption")}</caption>
      <thead>
        <tr>
          <th scope="col">${t("chart.time")}</th>
          <th scope="col">${t("chart.temperature")}</th>
          <th scope="col">${t("chart.target")}</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((point) => {
          const goal = valueAt(chart.target, point.at);
          return html`<tr>
            <th scope="row">${formatDateTime(hass, point.at, this.now)}</th>
            <td>${formatTemperature(hass, point.value, unit, decimals)}</td>
            <td>${goal === null ? "—" : formatTemperature(hass, goal, unit, decimals)}</td>
          </tr>`;
        })}
      </tbody>
    </table>`;
  }

  static override styles = [
    tokens,
    buttonStyles,
    css`
      :host {
        display: block;
        color: var(--bc-text);
        font-size: 14px;
        --bc-chart-current: var(--bc-tone-warm);
        --bc-chart-target: color-mix(in srgb, var(--bc-text) 55%, transparent);
      }
      .summary {
        margin: 0 0 8px;
        line-height: 1.45;
      }
      .note {
        margin: 6px 0 10px;
        color: var(--bc-muted);
        font-size: 13px;
        line-height: 1.45;
      }
      figure {
        margin: 0;
      }
      .chart {
        display: block;
        max-width: 100%;
        height: auto;
        overflow: visible;
      }
      .grid {
        stroke: var(--bc-divider);
        stroke-width: 1;
        vector-effect: non-scaling-stroke;
      }
      .axis,
      .unit {
        fill: var(--bc-muted);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
      }
      .current,
      .target,
      .sensor {
        fill: none;
        vector-effect: non-scaling-stroke;
        stroke-linejoin: round;
        stroke-linecap: round;
      }
      .current {
        stroke: var(--bc-chart-current);
        stroke-width: 2.25;
      }
      .target {
        stroke: var(--bc-chart-target);
        stroke-width: 1.5;
      }
      .sensor {
        stroke: var(--bc-chart-target);
        stroke-width: 1.5;
        stroke-dasharray: 5 4;
      }
      .legend {
        display: flex;
        flex-wrap: wrap;
        gap: 4px 16px;
        margin-top: 6px;
        color: var(--bc-muted);
        font-size: 12.5px;
      }
      .legend span {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .key {
        display: inline-block;
        width: 18px;
        height: 0;
        border-top: 2.5px solid var(--bc-chart-current);
      }
      .key.target {
        border-top: 1.5px solid var(--bc-chart-target);
      }
      .key.sensor {
        border-top: 1.5px dashed var(--bc-chart-target);
      }
      .bc-button {
        margin-top: 10px;
      }
      table {
        width: 100%;
        margin-top: 10px;
        border-collapse: collapse;
        font-variant-numeric: tabular-nums;
      }
      th,
      td {
        padding: 5px 8px;
        border-top: 1px solid var(--bc-divider);
        text-align: start;
        font-weight: 400;
      }
      thead th {
        border-top: none;
        color: var(--bc-muted);
        font-weight: 500;
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
    `,
  ];
}

if (!customElements.get("bc-temp-chart")) customElements.define("bc-temp-chart", TempChart);

declare global {
  interface HTMLElementTagNameMap {
    "bc-temp-chart": TempChart;
  }
}
