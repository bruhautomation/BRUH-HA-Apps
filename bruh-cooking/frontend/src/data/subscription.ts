import type { HassConnection } from "../hass";
import type { PanelMessage } from "../types";

type Unsubscribe = () => Promise<void>;

/**
 * The panel's `bruh_cooking/panel/subscribe` subscription: one per connection object. A new
 * connection (Home Assistant hands a new one after some reconnects) gets a fresh subscription,
 * and messages from a connection that has been replaced or disconnected are ignored.
 */
export class PanelSubscription {
  private connection: HassConnection | undefined;
  private unsubscribe: Promise<Unsubscribe | undefined> | undefined;

  constructor(
    private readonly onMessage: (message: PanelMessage) => void,
    private readonly onError: (error: unknown) => void,
  ) {}

  /** Subscribes on `connection` unless already subscribed there; undefined unsubscribes. */
  connect(connection: HassConnection | undefined): void {
    if (connection === this.connection) return;
    this.disconnect();
    if (!connection) return;
    this.connection = connection;
    let subscription: Promise<Unsubscribe>;
    try {
      subscription = connection.subscribeMessage<PanelMessage>(
        (message) => {
          if (this.connection === connection) this.onMessage(message);
        },
        { type: "bruh_cooking/panel/subscribe" },
      );
    } catch (error) {
      subscription = Promise.reject(error);
    }
    this.unsubscribe = subscription.catch((error: unknown) => {
      if (this.connection === connection) this.onError(error);
      return undefined;
    });
  }

  disconnect(): void {
    const pending = this.unsubscribe;
    this.connection = undefined;
    this.unsubscribe = undefined;
    // The socket may already be closed, which rejects the unsubscribe; nothing to do then.
    void pending?.then((unsubscribe) => unsubscribe?.()).catch(() => {});
  }

  /** Subscribes again on the same connection, after an error. */
  retry(): void {
    const connection = this.connection;
    this.disconnect();
    this.connect(connection);
  }
}
