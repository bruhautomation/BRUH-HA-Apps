/* BRigt panel. Relative URLs only — this page is served under the ingress
   prefix and must never anchor a request at "/". */
(function () {
  "use strict";

  // ------------------------------------------------------------------
  // Tab switching. Delegated: the strip is static markup.
  // ------------------------------------------------------------------
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

  const $ = (id) => document.getElementById(id);

  async function api(path, options) {
    const response = await fetch(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok && !body.job) {
      throw new Error(body.error || ("HTTP " + response.status));
    }
    return body;
  }

  function post(path, payload) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
  }

  // Fire-and-poll: a POST answers {job: id}; poll until it settles.
  async function awaitJob(jobId, onTick) {
    for (;;) {
      const job = await api("api/job/" + jobId);
      if (job.status !== "running") return job;
      if (onTick) onTick(job);
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
  }

  function fmtRtt(rtt) {
    if (!rtt || rtt.p50_ms === undefined) return "not probed";
    return "p50 " + rtt.p50_ms + "ms · p95 " + rtt.p95_ms + "ms · loss " +
      Math.round(rtt.loss * 100) + "%";
  }

  // ------------------------------------------------------------------
  // Version footer
  // ------------------------------------------------------------------
  api("api/status").then((status) => {
    const el = $("version");
    if (el && status.version) el.textContent = "v" + status.version;
  }).catch(() => {});

  // ------------------------------------------------------------------
  // Lab: LIFX
  // ------------------------------------------------------------------
  function renderDevices(devices) {
    const list = $("lifxList");
    if (!devices.length) {
      list.innerHTML = '<p class="muted">No bulbs answered the broadcast. ' +
        "Are they on this network?</p>";
      return;
    }
    list.innerHTML = "";
    for (const device of devices) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML =
        '<div class="row-main"><strong></strong>' +
        '<span class="muted small"></span>' +
        '<span class="rtt small"></span></div>' +
        '<div class="row-actions">' +
        '<button class="btn small" data-act="probe">Probe RTT</button>' +
        '<button class="btn small" data-act="rate">Rate test</button>' +
        '<button class="btn small" data-act="demo">Waveform demo</button>' +
        "</div>";
      row.querySelector("strong").textContent = device.label || device.serial;
      row.querySelector(".muted").textContent =
        device.ip + " · " + device.serial;
      row.querySelector(".rtt").textContent = fmtRtt(device.rtt);
      row.dataset.serial = device.serial;
      list.appendChild(row);
    }
  }

  $("btnDiscover").addEventListener("click", async () => {
    const button = $("btnDiscover");
    button.disabled = true;
    button.textContent = "Discovering…";
    try {
      const body = await post("api/lifx/discover");
      renderDevices(body.devices || []);
    } catch (error) {
      $("lifxList").innerHTML =
        '<p class="muted">Discovery failed: ' + error.message + "</p>";
    } finally {
      button.disabled = false;
      button.textContent = "Discover bulbs";
    }
  });

  // Per-row actions, delegated (rows are rebuilt on every discover).
  $("lifxList").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const row = button.closest(".row");
    const serial = row.dataset.serial;
    const out = row.querySelector(".rtt");
    button.disabled = true;
    try {
      if (button.dataset.act === "probe") {
        out.textContent = "probing…";
        const stats = await post("api/lifx/probe", { serial });
        out.textContent = fmtRtt(stats);
      } else if (button.dataset.act === "rate") {
        out.textContent = "rate ramp running (~12s)…";
        const started = await post("api/lifx/rate-test", { serial });
        const job = await awaitJob(started.job);
        if (job.status === "done") {
          out.textContent = job.result
            .map((r) => r.rate_hz + "/s: " + Math.round(r.loss * 100) + "% loss")
            .join(" · ");
        } else {
          out.textContent = "rate test failed: " + job.error;
        }
      } else if (button.dataset.act === "demo") {
        const bpm = Number($("demoBpm").value) || 120;
        const seconds = Number($("demoSecs").value) || 10;
        await post("api/lifx/waveform-demo", { serial, bpm, seconds });
        out.textContent = "pulsing at " + bpm + " BPM for " + seconds +
          "s — one packet, the bulb keeps time itself";
      }
    } catch (error) {
      out.textContent = "failed: " + error.message;
    } finally {
      button.disabled = false;
    }
  });

  // Show anything already known (persisted discovery) on load.
  api("api/lifx/devices").then((body) => {
    if ((body.devices || []).length) renderDevices(body.devices);
  }).catch(() => {});

  // ------------------------------------------------------------------
  // Lab: HA service-call latency
  // ------------------------------------------------------------------
  $("btnLoadEntities").addEventListener("click", async () => {
    const select = $("haEntity");
    select.innerHTML = '<option value="">loading…</option>';
    try {
      const [switches, lights, booleans] = await Promise.all([
        api("api/ha/entities?domain=switch"),
        api("api/ha/entities?domain=light"),
        api("api/ha/entities?domain=input_boolean"),
      ]);
      const entities = [].concat(
        switches.entities || [], lights.entities || [], booleans.entities || []);
      select.innerHTML = '<option value="">— pick an entity —</option>';
      for (const entity of entities) {
        const option = document.createElement("option");
        option.value = entity.entity_id;
        option.textContent = entity.name + " (" + entity.entity_id + ")";
        select.appendChild(option);
      }
    } catch (error) {
      select.innerHTML = '<option value="">failed: ' + error.message + "</option>";
    }
  });

  $("btnHaProbe").addEventListener("click", async () => {
    const entityId = $("haEntity").value;
    const out = $("haProbeResult");
    if (!entityId) {
      out.textContent = "Pick an entity first.";
      return;
    }
    out.textContent = "Toggling " + entityId +
      " a few times and measuring (it ends where it started)…";
    try {
      const started = await post("api/ha/latency-probe", { entity_id: entityId });
      const job = await awaitJob(started.job);
      if (job.status === "done" && !job.result.error) {
        const r = job.result;
        out.textContent = r.entity_id + ": p50 " + r.p50_ms + "ms · max " +
          r.max_ms + "ms · " + r.timeouts + " timeouts (" +
          r.samples_ms.join(", ") + ")";
      } else {
        out.textContent = "probe failed: " +
          (job.error || (job.result && job.result.error));
      }
    } catch (error) {
      out.textContent = "probe failed: " + error.message;
    }
  });

  // ------------------------------------------------------------------
  // Lab: the report
  // ------------------------------------------------------------------
  $("btnReport").addEventListener("click", async () => {
    try {
      const report = await api("api/lab/report");
      $("labReport").textContent = JSON.stringify(report, null, 2);
    } catch (error) {
      $("labReport").textContent = "failed: " + error.message;
    }
  });
})();
