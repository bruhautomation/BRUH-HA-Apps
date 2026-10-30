import { html, render } from "lit";
import { renderDrawing } from "../src/drawings/index";
import type { GalleryVariant } from "./types";
import { variants as oven } from "./variants/oven";
import { variants as sousVide } from "./variants/sous-vide";

// Query: module (a variants file name, or "all"), filter (substring of ids, comma-separated
// for several), theme (light or dark), width (default stage width), height (a fixed stage
// height the drawing fits into, as on an overview card), refs (folder URL of reference photos).
const MODULES: Record<string, GalleryVariant[]> = { "sous-vide": sousVide, oven };

const params = new URLSearchParams(location.search);
const moduleName = params.get("module") ?? "all";
const filters = (params.get("filter") ?? "").split(",").filter(Boolean);
const theme = params.get("theme") === "dark" ? "dark" : "light";
const width = Number(params.get("width") ?? 480);
const height = Number(params.get("height") ?? 0);
const refs = params.get("refs");
const reducedMotion = params.get("motion") !== "on";

document.documentElement.dataset.theme = theme;
const list = (moduleName === "all" ? Object.values(MODULES).flat() : (MODULES[moduleName] ?? [])).filter(
  (variant) => !filters.length || filters.some((filter) => variant.id.includes(filter)),
);

function draw(shown: ReadonlyArray<number | undefined> = []): void {
  render(
    html`${list.map(
      (variant, index) => html`
        <figure data-variant=${variant.id}>
          <div class="row">
            ${refs && variant.reference ? html`<img class="ref" src=${`${refs}/${variant.reference}`} alt="reference" />` : null}
            <div class="stage ${height > 0 ? "fixed" : ""}" style=${`width:${variant.width ?? width}px${height > 0 ? `;height:${height}px` : ""}`}>
              ${renderDrawing({
                ...variant.input,
                uid: `g${index}`,
                theme,
                reducedMotion,
                pixelHeight: variant.input.pixelHeight ?? shown[index],
              })}
            </div>
          </div>
          <figcaption>${variant.id} · ${variant.title}</figcaption>
        </figure>
      `,
    )}`,
    document.body,
  );
}

// Drawn a second time with each drawing's shown height, as the panel passes it, so labels come
// out at the size they have on screen there.
draw();
draw(
  [...document.querySelectorAll<HTMLElement>(".stage")].map((stage) => {
    const shown = stage.querySelector("svg")?.getBoundingClientRect().height ?? 0;
    return shown > 0 ? Math.round(shown) : undefined;
  }),
);

// Show each reference at the drawing's height, so proportions compare directly.
async function sizeReferences(): Promise<void> {
  const images = [...document.querySelectorAll<HTMLImageElement>("img.ref")];
  await Promise.all(
    images.map((image) =>
      image.complete
        ? undefined
        : new Promise((resolve) => {
            image.addEventListener("load", resolve, { once: true });
            image.addEventListener("error", resolve, { once: true });
          }),
    ),
  );
  for (const image of images) {
    const stage = image.parentElement?.querySelector<HTMLElement>(".stage");
    if (stage) image.style.height = `${stage.getBoundingClientRect().height}px`;
  }
}

void sizeReferences().then(() => {
  (window as unknown as { __galleryReady: boolean }).__galleryReady = true;
});
