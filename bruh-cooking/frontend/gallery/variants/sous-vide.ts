import type { SousVideState } from "../../src/drawings/types";
import type { GalleryVariant } from "../types";

const idle: SousVideState = {
  kind: "sous_vide",
  available: true,
  running: false,
  heating: false,
  food: false,
  waterC: 21.2,
  readout: "21.2°",
  targetReadout: null,
  error: null,
};

function joule(id: string, title: string, state: Partial<SousVideState>, model: "CSJ100" | "BSV600" = "CSJ100"): GalleryVariant {
  return {
    id: `${model === "CSJ100" ? "joule" : "turbo"}-${id}`,
    title,
    input: { model, finish: "white_polished", state: { ...idle, ...state } },
    reference: model === "CSJ100" ? "damp_pdp.jpg" : "BSV600_BSV600PSS1BNA1_pdp2.png",
  };
}

export const variants: GalleryVariant[] = [
  joule("idle", "Idle, cold water", {}),
  joule("preheating", "Preheating to 56°", { running: true, heating: true, waterC: 38.4, readout: "38.4°", targetReadout: "56°" }),
  joule("ready", "Ready for food", { running: true, waterC: 56, readout: "56.0°" }),
  joule("cooking", "Cooking, food in", { running: true, food: true, waterC: 55.8, readout: "55.8°" }),
  joule("hot", "Vegetables at 85°", { running: true, food: true, waterC: 85, readout: "85.0°" }),
  joule("done", "Done", { running: true, food: true, waterC: 56, readout: "56.0°" }),
  joule("low-water", "Low water", { error: "low_water", waterC: 50.2, readout: "50.2°" }),
  joule("tipped", "Tipped over", { error: "tipped", waterC: 40, readout: "40.0°" }),
  joule("offline", "Offline", { available: false, readout: null }),
  joule("idle", "Idle", {}, "BSV600"),
  joule("cooking", "Cooking", { running: true, food: true, waterC: 57, readout: "57.0°" }, "BSV600"),
];
