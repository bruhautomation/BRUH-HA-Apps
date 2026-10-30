import type { TemplateResult } from "lit";
import { renderOven } from "./oven";
import { renderSousVide } from "./sous-vide";
import type { DrawingInput } from "./types";

/** The appliance's drawing. */
export function renderDrawing(input: DrawingInput): TemplateResult {
  return input.state.kind === "oven" ? renderOven(input) : renderSousVide(input);
}
