import type { ControlAction } from "./kinds/types";
import type { HomeAssistant } from "./hass";

/**
 * Applies a control's new value through the entity's own Home Assistant action, with the entity
 * as the target, so the integration validates it exactly as it would from a dashboard. A
 * rejected call throws Home Assistant's error, for the view to show under the control.
 */
export async function applyAction(hass: HomeAssistant, action: ControlAction, value?: unknown): Promise<void> {
  const target = { entity_id: action.entity_id };
  switch (action.type) {
    case "number":
      await hass.callService("number", "set_value", { value: Number(value) }, target);
      return;
    case "select":
      await hass.callService("select", "select_option", { option: String(value) }, target);
      return;
    case "switch":
      await hass.callService("switch", value ? "turn_on" : "turn_off", {}, target);
      return;
    case "switch_on":
      await hass.callService("switch", "turn_on", {}, target);
      return;
    case "switch_off":
      await hass.callService("switch", "turn_off", {}, target);
      return;
    case "button":
      await hass.callService("button", "press", {}, target);
      return;
  }
}
