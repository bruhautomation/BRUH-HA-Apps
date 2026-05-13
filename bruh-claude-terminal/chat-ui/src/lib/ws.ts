import type { ClientMessage, WireEvent } from "./events";

export type WSStatus = "connecting" | "open" | "closing" | "closed" | "error";

export interface WSClientOpts {
  url: string;
  onEvent: (ev: WireEvent) => void;
  onStatus?: (s: WSStatus) => void;
  /** Auto-reconnect with exponential backoff. Defaults to true. */
  reconnect?: boolean;
}

/**
 * Thin wrapper around WebSocket. Reconnects on close with backoff. Buffers
 * outgoing messages while the socket isn't open so the UI's "send" handler
 * doesn't have to care about timing.
 *
 * One quirk worth knowing: when running inside Home Assistant's ingress
 * iframe, `location.pathname` is rooted at `/api/hassio_ingress/<token>/`
 * with a trailing slash, and we serve `/ws/chat` relative to that. The URL
 * is built by the caller; we just plug it in.
 */
export class WSClient {
  private ws: WebSocket | null = null;
  private opts: WSClientOpts;
  private outbox: ClientMessage[] = [];
  private retry = 0;
  private retryTimer: number | null = null;
  private stopped = false;

  constructor(opts: WSClientOpts) {
    this.opts = opts;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // closing a non-open socket throws; ignore
      }
      this.ws = null;
    }
  }

  send(msg: ClientMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      this.outbox.push(msg);
    }
  }

  private connect(): void {
    this.opts.onStatus?.("connecting");
    const ws = new WebSocket(this.opts.url);
    this.ws = ws;

    ws.addEventListener("open", () => {
      this.retry = 0;
      this.opts.onStatus?.("open");
      const queued = this.outbox;
      this.outbox = [];
      for (const m of queued) ws.send(JSON.stringify(m));
    });

    ws.addEventListener("message", (e) => {
      let ev: WireEvent;
      try {
        ev = JSON.parse(e.data);
      } catch {
        ev = { type: "raw", line: e.data };
      }
      this.opts.onEvent(ev);
    });

    ws.addEventListener("error", () => {
      this.opts.onStatus?.("error");
    });

    ws.addEventListener("close", () => {
      this.ws = null;
      this.opts.onStatus?.("closed");
      if (this.stopped || this.opts.reconnect === false) return;
      const delay = Math.min(30000, 500 * 2 ** this.retry);
      this.retry += 1;
      this.retryTimer = window.setTimeout(() => this.connect(), delay);
    });
  }
}

/** Build a WS URL that works in both direct-port and HA-ingress contexts. */
export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  // location.pathname under HA ingress ends with `/` (the panel root). We
  // strip a leading slash from `path` and then resolve relative to pathname.
  const base = location.pathname.endsWith("/")
    ? location.pathname
    : location.pathname + "/";
  const cleanPath = path.replace(/^\/+/, "");
  return `${proto}//${location.host}${base}${cleanPath}`;
}
