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
  // Calibrate: the phone is the measurement instrument
  // ------------------------------------------------------------------
  const RECORD_SECONDS = 14;

  $("btnLoadPlayers").addEventListener("click", async () => {
    const select = $("calPlayer");
    select.innerHTML = '<option value="">loading…</option>';
    try {
      const body = await api("api/ha/entities?domain=media_player");
      select.innerHTML = '<option value="">— pick a media player —</option>';
      for (const entity of body.entities || []) {
        const option = document.createElement("option");
        option.value = entity.entity_id;
        option.textContent = entity.name + " (" + entity.entity_id + ")";
        select.appendChild(option);
      }
    } catch (error) {
      select.innerHTML = '<option value="">failed: ' + error.message + "</option>";
    }
  });

  // Several ping exchanges; the lowest-RTT one carries the least clock
  // ambiguity. Returns (server_epoch - client_epoch) in ms.
  async function clockOffset() {
    let best = { rtt: Infinity, offset: 0 };
    for (let i = 0; i < 5; i++) {
      const t0 = Date.now();
      const body = await post("api/calibrate/ping", {});
      const t1 = Date.now();
      const rtt = t1 - t0;
      if (rtt < best.rtt) {
        best = { rtt, offset: body.server_epoch_ms - (t0 + t1) / 2 };
      }
    }
    return best.offset;
  }

  function floatTo16BitWav(chunks, sampleRate) {
    let length = 0;
    for (const chunk of chunks) length += chunk.length;
    const buffer = new ArrayBuffer(44 + length * 2);
    const view = new DataView(buffer);
    const writeString = (at, s) => {
      for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i));
    };
    writeString(0, "RIFF");
    view.setUint32(4, 36 + length * 2, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);       // PCM
    view.setUint16(22, 1, true);       // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, length * 2, true);
    let at = 44;
    for (const chunk of chunks) {
      for (let i = 0; i < chunk.length; i++) {
        const s = Math.max(-1, Math.min(1, chunk[i]));
        view.setInt16(at, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        at += 2;
      }
    }
    return buffer;
  }

  function bufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const STEP = 0x8000;
    for (let i = 0; i < bytes.length; i += STEP) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + STEP));
    }
    return btoa(binary);
  }

  function describeProfile(profile) {
    const runs = (profile.runs || []).length;
    return profile.entity_id + ": " + profile.effective_offset_ms + "ms" +
      (profile.adjust_ms ? " (measured " + profile.offset_ms +
        " + nudge " + profile.adjust_ms + ")" : "") +
      " · " + runs + " run" + (runs === 1 ? "" : "s") +
      " · spread " + (profile.spread_ms || 0) + "ms" +
      (profile.position_attr && profile.position_attr.reliable
        ? " · position reporting OK" : "");
  }

  $("btnMicWizard").addEventListener("click", async () => {
    const entityId = $("calPlayer").value;
    const status = $("micStatus");
    if (!entityId) { status.textContent = "Pick a media player first."; return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      status.textContent = "This browser won't share the microphone here " +
        "(it usually needs HTTPS). Use the tap method below instead.";
      return;
    }
    const button = $("btnMicWizard");
    button.disabled = true;
    try {
      status.textContent = "Syncing clocks…";
      const offset = await clockOffset();

      status.textContent = "Asking for the microphone…";
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      const context = new (window.AudioContext || window.webkitAudioContext)();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const chunks = [];
      let recordStartClient = null;
      processor.onaudioprocess = (event) => {
        if (recordStartClient === null) {
          // First delivered buffer: its audio began one buffer ago.
          recordStartClient = Date.now() -
            (event.inputBuffer.length / context.sampleRate) * 1000;
        }
        chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(context.destination);

      status.textContent = "Recording — starting playback on " + entityId + "…";
      const play = await post("api/calibrate/play", { media_player: entityId });

      for (let s = RECORD_SECONDS; s > 0; s--) {
        status.textContent = "Listening for clicks… " + s + "s";
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      context.close();

      status.textContent = "Analyzing…";
      const wav = floatTo16BitWav(chunks, context.sampleRate);
      const result = await post("api/calibrate/analyze", {
        media_player: entityId,
        wav_b64: bufferToBase64(wav),
        record_start_epoch_ms: recordStartClient + offset,
        play_epoch_ms: play.play_epoch_ms,
      });
      status.textContent = "Measured: this speaker starts making sound " +
        Math.round(result.measured_offset_ms) + "ms after the play command. " +
        describeProfile(result.profile);
      loadProfiles();
    } catch (error) {
      status.textContent = "Failed: " + error.message;
    } finally {
      button.disabled = false;
    }
  });

  $("btnTapWizard").addEventListener("click", async () => {
    const entityId = $("calPlayer").value;
    const status = $("tapStatus");
    if (!entityId) { status.textContent = "Pick a media player first."; return; }
    const wizard = $("btnTapWizard");
    const tap = $("btnTap");
    wizard.disabled = true;
    try {
      const offset = await clockOffset();
      const taps = [];
      const onTap = () => taps.push(Date.now() + offset);
      tap.hidden = false;
      tap.addEventListener("pointerdown", onTap);
      status.textContent = "Starting playback — tap on every click you hear.";
      const play = await post("api/calibrate/play", { media_player: entityId });
      for (let s = RECORD_SECONDS; s > 0; s--) {
        status.textContent = "Tap each click… " + s + "s (" + taps.length + " taps)";
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      tap.hidden = true;
      tap.removeEventListener("pointerdown", onTap);
      status.textContent = "Computing…";
      const result = await post("api/calibrate/taps", {
        media_player: entityId,
        play_epoch_ms: play.play_epoch_ms,
        taps_epoch_ms: taps,
      });
      status.textContent = "Measured (taps): " +
        Math.round(result.measured_offset_ms) + "ms. " +
        describeProfile(result.profile);
      loadProfiles();
    } catch (error) {
      status.textContent = "Failed: " + error.message;
      tap.hidden = true;
    } finally {
      wizard.disabled = false;
    }
  });

  async function loadProfiles() {
    const list = $("calProfiles");
    try {
      const body = await api("api/calibrate/profiles");
      const profiles = body.profiles || [];
      if (!profiles.length) {
        list.innerHTML = '<p class="muted">Nothing calibrated yet.</p>';
        return;
      }
      list.innerHTML = "";
      for (const profile of profiles) {
        const row = document.createElement("div");
        row.className = "row";
        row.innerHTML = '<div class="row-main"><span class="small"></span></div>' +
          '<div class="row-actions"><label class="small">Nudge ms ' +
          '<input type="number" step="10" class="nudge"></label>' +
          '<button class="btn small" data-act="nudge">Save</button></div>';
        row.querySelector(".row-main span").textContent = describeProfile(profile);
        row.querySelector(".nudge").value = profile.adjust_ms || 0;
        row.dataset.entity = profile.entity_id;
        list.appendChild(row);
      }
    } catch (error) {
      list.innerHTML = '<p class="muted">failed: ' + error.message + "</p>";
    }
  }

  $("btnProfiles").addEventListener("click", loadProfiles);
  $("calProfiles").addEventListener("click", async (event) => {
    const button = event.target.closest('button[data-act="nudge"]');
    if (!button) return;
    const row = button.closest(".row");
    try {
      await post("api/calibrate/adjust", {
        media_player: row.dataset.entity,
        adjust_ms: Number(row.querySelector(".nudge").value) || 0,
      });
      loadProfiles();
    } catch (error) {
      row.querySelector(".row-main span").textContent = "failed: " + error.message;
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
