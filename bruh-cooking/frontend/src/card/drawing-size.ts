import type { ReactiveController, ReactiveControllerHost } from "lit";

type Host = ReactiveControllerHost & { readonly renderRoot: HTMLElement | DocumentFragment };

/**
 * The height a drawing is shown at, in CSS pixels, for `DrawingInput.pixelHeight`: drawings size
 * their labels from it, so a readout is the same size on screen on a small card and in the large
 * full view. It watches the drawing's svg, which a redraw may replace, and asks the host to draw
 * again when the height, in whole pixels, changes. Labels change neither the viewBox nor the
 * svg's box, so the second draw doesn't resize anything.
 */
export class DrawingSize implements ReactiveController {
  /** Undefined until the svg has been laid out. */
  height: number | undefined;
  private observer: ResizeObserver | undefined;
  private observed: Element | null = null;

  constructor(
    private readonly host: Host,
    /** Finds the drawing's svg in the host's shadow root. */
    private readonly selector: string,
  ) {
    host.addController(this);
  }

  hostConnected(): void {
    this.hostUpdated();
  }

  hostUpdated(): void {
    const svg = this.host.renderRoot?.querySelector(this.selector) ?? null;
    if (svg === this.observed) return;
    this.observer?.disconnect();
    this.observed = svg;
    if (!svg || typeof ResizeObserver !== "function") return;
    this.observer ??= new ResizeObserver((entries) => this.measured(entries));
    this.observer.observe(svg);
  }

  hostDisconnected(): void {
    this.observer?.disconnect();
    this.observed = null;
  }

  private measured(entries: ResizeObserverEntry[]): void {
    const height = Math.round(entries[entries.length - 1]?.contentRect.height ?? 0);
    if (height <= 0 || height === this.height) return;
    this.height = height;
    this.host.requestUpdate();
  }
}
