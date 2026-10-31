/* The old name of tests/manual/measure-minecraft-companion.mjs, kept so a
 * path somebody runs (and the devloop guard, which refuses a deleted test
 * file) still finds the measure. It runs the renamed one, which loads
 * bruh-minecraft-server/panel/ (index.html, app.js, style.css).
 *
 *   node tests/manual/measure-minecraft-vesper.mjs
 */
import './measure-minecraft-companion.mjs';
