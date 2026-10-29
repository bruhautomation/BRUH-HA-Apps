/**
 * The parts of Home Assistant's frontend `hass` object the panel uses. Only these documented
 * members: no internal `ha-*` elements, which a custom panel can't count on being loaded.
 */

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
  last_changed: string;
  last_updated: string;
}

export interface HassDevice {
  id: string;
  name: string | null;
  name_by_user: string | null;
  area_id: string | null;
  model?: string | null;
  model_id?: string | null;
  manufacturer?: string | null;
  sw_version?: string | null;
}

export interface HassArea {
  area_id: string;
  name: string;
  floor_id?: string | null;
}

export interface HassConnection {
  subscribeMessage<T>(
    callback: (message: T) => void,
    message: Record<string, unknown>,
  ): Promise<() => Promise<void>>;
}

export interface HomeAssistant {
  states: Record<string, HassEntity>;
  devices: Record<string, HassDevice>;
  areas: Record<string, HassArea>;
  language: string;
  /** time_zone "server" asks for times in the server's zone rather than the browser's. */
  locale: { language: string; number_format?: string; time_format?: string; time_zone?: string };
  themes: { darkMode: boolean };
  /** "always_hidden" when the user hid the sidebar, so a panel shows its own menu button. */
  dockedSidebar?: "docked" | "always_hidden" | "auto";
  user?: { id?: string; name?: string; is_admin: boolean };
  config: { unit_system: { temperature: string }; time_zone: string };
  connection: HassConnection;
  callService(
    domain: string,
    service: string,
    data?: Record<string, unknown>,
    target?: Record<string, unknown>,
  ): Promise<unknown>;
  callWS<T>(message: Record<string, unknown>): Promise<T>;
  /** Translated state with units, as the frontend shows it; absent on very old versions. */
  formatEntityState?(stateObj: HassEntity, state?: string): string;
  /**
   * Loads a category of an integration's backend translations in the user's language, and
   * returns a localize function that has them: how the frontend translates the errors a service
   * call returns.
   */
  loadBackendTranslation?(
    category: string,
    integration?: string,
  ): Promise<(key: string, values?: Record<string, unknown>) => string>;
}
