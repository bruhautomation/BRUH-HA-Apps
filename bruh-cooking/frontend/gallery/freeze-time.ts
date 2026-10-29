// Imported first, so every module sees the same clock: the fixtures' moment, plus `?seconds=`.
// Frozen there for screenshots; `?live=1` lets it run on from there, for trying the panel out.
const params = new URLSearchParams(location.search);
const at = Date.parse(params.get("now") ?? "2026-10-25T18:00:00Z") + Number(params.get("seconds") ?? 0) * 1000;
if (Number.isFinite(at)) {
  const started = performance.now();
  Date.now = params.get("live") === "1" ? () => at + (performance.now() - started) : () => at;
}
