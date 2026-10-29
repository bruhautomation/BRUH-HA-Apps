/**
 * The panel's two routes: `/bruh-cooking` is the overview and `/bruh-cooking/<device_id>` an
 * appliance's full view. Home Assistant hands the panel `route = {prefix, path}`, where `path` is
 * the part after the panel's own URL ("" or "/<device_id>").
 */

export type PanelRoute = { view: "overview" } | { view: "appliance"; deviceId: string };

/** The panel's URL when Home Assistant hasn't passed a route (it always does in practice). */
export const DEFAULT_PREFIX = "/bruh-cooking";

export function parseRoute(path: string | null | undefined): PanelRoute {
  const [first] = (path ?? "").split(/[?#]/)[0].split("/").filter(Boolean);
  if (!first) return { view: "overview" };
  let deviceId = first;
  try {
    deviceId = decodeURIComponent(first);
  } catch {
    // A stray "%" in a hand-typed URL: keep it as typed, so it shows as not found.
  }
  return { view: "appliance", deviceId };
}

export function routePath(prefix: string | null | undefined, route: PanelRoute): string {
  const base = (prefix || DEFAULT_PREFIX).replace(/\/+$/, "");
  return route.view === "overview" ? base : `${base}/${encodeURIComponent(route.deviceId)}`;
}

/**
 * Goes to `path` the way Home Assistant's own `navigate()` does: its router follows the history
 * entry once it hears `location-changed` on the window.
 */
export function navigate(path: string, options: { replace?: boolean } = {}): void {
  const replace = options.replace === true;
  if (replace) history.replaceState(history.state, "", path);
  else history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace } }));
}

/**
 * For links to other Home Assistant pages: a plain click navigates inside the app instead of
 * reloading it, while a modified click (new tab, new window) is left to the browser.
 */
export function followLink(event: MouseEvent): void {
  if (event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const anchor = event.currentTarget;
  if (!(anchor instanceof HTMLAnchorElement)) return;
  event.preventDefault();
  navigate(anchor.getAttribute("href") ?? "/");
}
