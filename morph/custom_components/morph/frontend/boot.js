// Loads Morph's panel. Morph's own modules can be replaced by this house's
// copies (/config/morph/frontend/, served in their place), and a copy can
// break: when the panel does not load, this loads Morph's own instead, from
// shipped/, and leaves the reason where the panel reads it, so the page
// says what happened rather than going blank. This file is never replaced.
const here = new URL('.', import.meta.url).href;
try {
  await import(here + 'morph-panel.js');
} catch (err) {
  window.__morphFallback = String((err && err.message) || err);
  console.error('Morph: a changed file did not load, so Morph is running its own copy.', err);
  await import(here + 'shipped/morph-panel.js');
}
