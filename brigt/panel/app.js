/* BRigt panel shell. Relative URLs only — this page is served under the
   ingress prefix and must never anchor a request at "/". */
(function () {
  "use strict";

  // Tab switching. Delegated: the strip is static markup.
  const tabs = document.getElementById("tabs");
  tabs.addEventListener("click", (event) => {
    const button = event.target.closest(".tab");
    if (!button) return;
    for (const tab of tabs.querySelectorAll(".tab")) {
      tab.classList.toggle("active", tab === button);
    }
    const name = button.dataset.tab;
    for (const pane of document.querySelectorAll(".pane")) {
      pane.classList.toggle("active", pane.id === "pane-" + name);
    }
  });

  // Version + options snapshot for the footer.
  fetch("api/status")
    .then((response) => (response.ok ? response.json() : null))
    .then((status) => {
      if (!status) return;
      const el = document.getElementById("version");
      if (el && status.version) el.textContent = "v" + status.version;
    })
    .catch(() => {});
})();
