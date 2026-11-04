// What brAIn adds to every Home Assistant page (frontend.add_extra_js_url),
// docs/design/morph-on-lovelace.md: Morph's cards as Lovelace cards, the card
// types brAIn builds, and the layer that lets brAIn change a dashboard in
// place. Each part is its own module and fails alone: a dashboard must keep
// drawing whatever happens here.
const PARTS = ['./morph-cards.js', './morph-types.js', './brain-layer.js', './morph-features.js'];
PARTS.forEach((p) => {
  import(p).catch((e) => console.warn(`brAIn: ${p} did not load`, e)); // eslint-disable-line no-console
});
