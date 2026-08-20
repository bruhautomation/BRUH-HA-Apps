/* BRight panel. Relative URLs only — this page is served under the ingress
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

  function put(path, payload) {
    return api(path, {
      method: "PUT",
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
  // Light Map
  // ------------------------------------------------------------------
  const ROLE_GLYPH = {
    candle: "🕯", downlight: "▽", lamp: "◉", strip: "▬", party: "✦", laser: "✧",
  };
  let mapData = { fixtures: [], roles: [] };

  // Which light is selected. A dot used to carry a role glyph and a `title`,
  // which is no name at all on a phone — you dragged an anonymous circle and
  // found out afterwards what you had moved. Selection is what ties the dot,
  // its name, and the row below it together.
  let selectedFixture = null;

  // A dot is 44px wide and hangs half outside its own coordinate, so a light
  // at x=0 rendered half off the floor — clipped, and hard to grab, which is
  // the corner of a room somebody is most likely to have put a light in. The
  // clamp moves the *drawing* inward and never the stored position.
  function placeDot(dot, x, y) {
    dot.style.left = "clamp(24px, " + (x * 100) + "%, calc(100% - 24px))";
    dot.style.top = "clamp(24px, " + (y * 100) + "%, calc(100% - 42px))";
  }

  function fixtureById(id) {
    return mapData.fixtures.find((f) => f.id === id) || null;
  }

  function selectFixture(id) {
    selectedFixture = id;
    renderSelection();
    for (const dot of $("mapFloor").querySelectorAll(".map-dot")) {
      dot.classList.toggle("selected", dot.dataset.id === id);
    }
    for (const row of $("mapList").querySelectorAll(".row")) {
      row.classList.toggle("selected", row.dataset.id === id);
    }
  }

  function renderSelection() {
    const bar = $("mapSelection");
    const fixture = selectedFixture ? fixtureById(selectedFixture) : null;
    bar.innerHTML = "";
    if (!fixture) {
      const hint = document.createElement("span");
      hint.className = "muted small";
      hint.textContent = mapData.fixtures.length
        ? "Tap a light to select it, then drag it into place."
        : "No lights yet — add discovered bulbs or a switch light.";
      bar.appendChild(hint);
      return;
    }
    const name = document.createElement("strong");
    name.textContent = fixture.label;
    const where = document.createElement("span");
    where.className = "muted small";
    where.textContent = fixture.id +
      (fixture.reachable === false ? " · unreachable" : "");
    const pick = document.createElement("select");
    pick.className = "role-pick";
    for (const role of mapData.roles) {
      const option = document.createElement("option");
      option.value = role;
      option.textContent = role;
      option.selected = role === fixture.role;
      pick.appendChild(option);
    }
    pick.addEventListener("change", () => {
      fixture.role = pick.value;
      saveFixture(fixture);
    });
    const remove = document.createElement("button");
    remove.className = "btn small";
    remove.textContent = "Remove this light";
    remove.addEventListener("click", () => removeFixture(fixture.id));
    bar.appendChild(name);
    bar.appendChild(where);
    bar.appendChild(pick);
    bar.appendChild(remove);
  }

  function renderMap() {
    const floor = $("mapFloor");
    floor.innerHTML = "";
    if (selectedFixture && !fixtureById(selectedFixture)) selectedFixture = null;
    for (const fixture of mapData.fixtures) {
      const dot = document.createElement("div");
      // The name hangs under the dot and is wider than it. Near an edge it
      // would hang off the floor, which clips — so at the edges it hangs
      // inward instead. A clipped name is a name nobody can read.
      const edge = fixture.x > 0.85 ? " edge-right"
        : fixture.x < 0.15 ? " edge-left" : "";
      dot.className = "map-dot" + edge +
        (fixture.reachable === false ? " unreachable" : "") +
        (fixture.id === selectedFixture ? " selected" : "");
      placeDot(dot, fixture.x, fixture.y);
      dot.dataset.id = fixture.id;
      const glyph = document.createElement("span");
      glyph.className = "dot-glyph";
      glyph.textContent = ROLE_GLYPH[fixture.role] || "?";
      // The name rides ON the map, not in a tooltip: a tooltip is nothing
      // at all on the device most likely to be doing the dragging.
      const name = document.createElement("span");
      name.className = "dot-name";
      name.textContent = fixture.label;
      dot.appendChild(glyph);
      dot.appendChild(name);
      floor.appendChild(dot);
    }
    const list = $("mapList");
    list.innerHTML = "";
    for (const fixture of mapData.fixtures) {
      const row = document.createElement("div");
      row.className = "row" + (fixture.id === selectedFixture ? " selected" : "");
      row.dataset.id = fixture.id;
      row.innerHTML = '<div class="row-main"><strong></strong>' +
        '<span class="muted small"></span></div>' +
        '<div class="row-actions"><select class="role-pick"></select>' +
        '<button class="btn small" data-act="remove">Remove</button></div>';
      row.querySelector("strong").textContent = fixture.label;
      row.querySelector(".muted").textContent = fixture.id +
        (fixture.reachable === false ? " · unreachable" : "");
      const pick = row.querySelector(".role-pick");
      for (const role of mapData.roles) {
        const option = document.createElement("option");
        option.value = role;
        option.textContent = role;
        option.selected = role === fixture.role;
        pick.appendChild(option);
      }
      list.appendChild(row);
    }
    renderSelection();
  }

  async function removeFixture(id) {
    try {
      const response = await fetch("api/map/fixture/" + encodeURIComponent(id),
                                   { method: "DELETE" });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || ("HTTP " + response.status));
      }
      if (selectedFixture === id) selectedFixture = null;
      loadMap();
    } catch (error) {
      $("mapStatus").textContent = "could not remove it: " + error.message;
    }
  }

  async function loadMap() {
    try {
      mapData = await api("api/map");
      renderMap();
    } catch (error) {
      $("mapStatus").textContent = "failed: " + error.message;
    }
  }

  function saveFixture(fixture) {
    return post("api/map/fixture", fixture).then(loadMap)
      .catch((error) => { $("mapStatus").textContent = error.message; });
  }

  // Dragging dots around the floor — and selecting one, which is the same
  // gesture until it moves. A press that never travels is a tap: it selects
  // and saves nothing, so tapping a light to see what it is cannot nudge it
  // half a pixel and rewrite the map.
  (function () {
    const MOVED_PX = 4;
    let dragging = null;
    let startedAt = null;
    let travelled = false;
    const floor = $("mapFloor");

    function positionIn(event) {
      const rect = floor.getBoundingClientRect();
      return {
        x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
      };
    }

    floor.addEventListener("pointerdown", (event) => {
      const dot = event.target.closest(".map-dot");
      if (!dot) return;
      dragging = dot;
      startedAt = { x: event.clientX, y: event.clientY };
      travelled = false;
      selectFixture(dot.dataset.id);
      dot.setPointerCapture(event.pointerId);
    });
    floor.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      if (Math.abs(event.clientX - startedAt.x) > MOVED_PX ||
          Math.abs(event.clientY - startedAt.y) > MOVED_PX) {
        travelled = true;
      }
      if (!travelled) return;
      const at = positionIn(event);
      placeDot(dragging, at.x, at.y);
    });
    floor.addEventListener("pointerup", (event) => {
      if (!dragging) return;
      const fixture = fixtureById(dragging.dataset.id);
      const moved = travelled;
      dragging = null;
      travelled = false;
      if (!fixture || !moved) return;
      const at = positionIn(event);
      fixture.x = at.x;
      fixture.y = at.y;
      saveFixture(fixture);
    });
  })();

  // Selecting from the list selects on the map, because they are one thing
  // seen twice — a list disconnected from the picture is what made removing
  // the right light a guess.
  $("mapList").addEventListener("click", (event) => {
    if (event.target.closest("button, select")) return;
    const row = event.target.closest(".row");
    if (row) selectFixture(row.dataset.id);
  });

  $("mapList").addEventListener("change", (event) => {
    const pick = event.target.closest(".role-pick");
    if (!pick) return;
    const fixture = mapData.fixtures.find(
      (f) => f.id === pick.closest(".row").dataset.id);
    if (fixture) {
      fixture.role = pick.value;
      saveFixture(fixture);
    }
  });

  $("mapList").addEventListener("click", (event) => {
    const button = event.target.closest('button[data-act="remove"]');
    if (!button) return;
    removeFixture(button.closest(".row").dataset.id);
  });

  $("btnImportLifx").addEventListener("click", async () => {
    try {
      const result = await post("api/map/import-lifx", {});
      $("mapStatus").textContent = result.added
        ? result.added + " bulb(s) added — drag them into place and set roles"
        : "nothing new (discover bulbs in the Lab first?)";
      loadMap();
    } catch (error) {
      $("mapStatus").textContent = error.message;
    }
  });

  $("btnAddAux").addEventListener("click", async () => {
    const form = $("auxForm");
    form.hidden = !form.hidden;
    if (form.hidden) return;
    const select = $("auxEntity");
    select.innerHTML = "<option value=''>loading…</option>";
    try {
      const [switches, lights] = await Promise.all([
        api("api/ha/entities?domain=switch"),
        api("api/ha/entities?domain=light"),
      ]);
      select.innerHTML = "<option value=''>— switch/light entity —</option>";
      for (const entity of [].concat(switches.entities || [],
                                     lights.entities || [])) {
        const option = document.createElement("option");
        option.value = entity.entity_id;
        option.textContent = entity.name + " (" + entity.entity_id + ")";
        select.appendChild(option);
      }
    } catch (error) {
      select.innerHTML = "<option value=''>failed</option>";
    }
  });

  $("btnAuxSave").addEventListener("click", () => {
    const entityId = $("auxEntity").value;
    if (!entityId) return;
    saveFixture({
      kind: "ha", entity_id: entityId, role: $("auxRole").value,
      label: entityId.split(".")[1], x: 0.5, y: 0.9,
    });
  });

  // Load the map when its tab first opens.
  tabs.addEventListener("click", (event) => {
    const button = event.target.closest(".tab");
    if (button && button.dataset.tab === "map") loadMap();
    if (button && button.dataset.tab === "shows") loadShows();
  });

  // ------------------------------------------------------------------
  // Shows
  // ------------------------------------------------------------------
  async function loadShows() {
    const list = $("showList");
    try {
      const [lib, profiles] = await Promise.all([
        api("api/library"), api("api/calibrate/profiles"),
      ]);
      const playerSelect = $("showPlayer");
      const previous = playerSelect.value;
      playerSelect.innerHTML = '<option value="">— calibrated player —</option>';
      for (const profile of profiles.profiles || []) {
        const option = document.createElement("option");
        option.value = profile.entity_id;
        option.textContent = profile.entity_id;
        option.selected = profile.entity_id === previous;
        playerSelect.appendChild(option);
      }
      const tracks = (lib.tracks || []).filter((t) => t.analyzed);
      if (!tracks.length) {
        list.innerHTML = '<p class="muted">No analyzed tracks — Library first.</p>';
        return;
      }
      list.innerHTML = "";
      for (const track of tracks) {
        const row = document.createElement("div");
        row.className = "row";
        row.dataset.hash = track.hash;
        const show = track.show;
        row.innerHTML = '<div class="row-main"><strong></strong>' +
          '<span class="rtt small"></span></div>' +
          '<div class="row-actions">' +
          '<button class="btn small" data-act="compile">Compile</button>' +
          '<button class="btn small" data-act="play">▶ Play</button></div>';
        row.querySelector("strong").textContent = track.name;
        row.querySelector(".rtt").textContent = show
          ? "compiled: " + show.tier + " · " + show.palette + " · " +
            show.cues + " cues"
          : "not compiled (▶ plays the plain beat pulse)";
        list.appendChild(row);
      }
    } catch (error) {
      list.innerHTML = '<p class="muted">failed: ' + error.message + "</p>";
    }
  }

  $("btnShowsRefresh").addEventListener("click", loadShows);

  $("showList").addEventListener("click", (event) => {
    // Anywhere but the buttons opens that track's show file. The list and
    // the editor are one thing seen twice, the same way the light map and
    // its rows are.
    if (event.target.closest("button")) return;
    const row = event.target.closest(".row");
    if (row) {
      for (const other of $("showList").querySelectorAll(".row")) {
        other.classList.toggle("selected", other === row);
      }
      openScript(row.dataset.hash, row.querySelector("strong").textContent);
    }
  });

  $("showList").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const row = button.closest(".row");
    const out = row.querySelector(".rtt");
    const status = $("showStatus");
    button.disabled = true;
    try {
      if (button.dataset.act === "compile") {
        out.textContent = "compiling…";
        const result = await post("api/show/compile",
                                  { track_hash: row.dataset.hash });
        out.textContent = "compiled: " + result.tier + " · " +
          result.palette + " · " + result.stats.cues + " cues (peak " +
          result.stats.peak_per_device_hz + "/s per bulb)";
        openScript(row.dataset.hash, row.querySelector("strong").textContent);
      } else if (button.dataset.act === "play") {
        const player = $("showPlayer").value;
        if (!player) {
          status.textContent = "Pick a calibrated player first.";
          return;
        }
        const result = await post("api/show/start_show", {
          track_hash: row.dataset.hash, media_player: player,
        });
        status.textContent = "Playing (" + result.cues + " cues, anchored " +
          Math.round(result.offset_ms) + "ms after play).";
        pollRunState();
      }
    } catch (error) {
      out.textContent = "failed: " + error.message;
    } finally {
      button.disabled = false;
    }
  });

  $("btnShowStop").addEventListener("click", async () => {
    try {
      const stopped = await post("api/show/stop_show", {});
      pollRunState();
      $("showStatus").textContent = "Stopped; lights restored.";
      if (stopped.scene) {
        $("showStatus").textContent =
          "Stopped; " + stopped.scene + " called.";
      }
    } catch (error) {
      $("showStatus").textContent = "stop failed: " + error.message;
    }
  });

  // ------------------------------------------------------------------
  // Party
  // ------------------------------------------------------------------
  $("btnPartyLoad").addEventListener("click", async () => {
    try {
      const profiles = await api("api/calibrate/profiles");
      const select = $("partyPlayer");
      select.innerHTML = '<option value="">— calibrated player —</option>';
      for (const profile of profiles.profiles || []) {
        const option = document.createElement("option");
        option.value = profile.entity_id;
        option.textContent = profile.entity_id;
        select.appendChild(option);
      }
    } catch (error) {
      $("partyStatus").textContent = "failed: " + error.message;
    }
  });

  $("btnPartyStart").addEventListener("click", async () => {
    const status = $("partyStatus");
    try {
      // A saved party carries its own speaker, folder, vibe, lights and
      // end scene; anything typed here still wins over it, which is what
      // "the usual thing, but on the kitchen speaker" means.
      const result = await post("api/show/party_mode", {
        party: $("partySaved").value || undefined,
        media_player: $("partyPlayer").value || undefined,
        vibe: $("partyVibe").value || undefined,
      });
      status.textContent = "Party on: " + result.queue +
        " tracks queued, anchored " + Math.round(result.offset_ms) +
        "ms after each play.";
      pollRunState();
    } catch (error) {
      status.textContent = "failed: " + error.message;
    }
  });

  $("btnPartyStop").addEventListener("click", async () => {
    try {
      const stopped = await post("api/show/stop_show", {});
      pollRunState();
      $("partyStatus").textContent = "Party over; lights restored.";
      if (stopped.scene) {
        $("partyStatus").textContent =
          "Stopped; " + stopped.scene + " called.";
      }
    } catch (error) {
      $("partyStatus").textContent = "stop failed: " + error.message;
    }
  });

  // ------------------------------------------------------------------
  // Lab: sync proof (metronome show)
  // ------------------------------------------------------------------
  $("btnLoadSync").addEventListener("click", async () => {
    try {
      const [lib, profiles] = await Promise.all([
        api("api/library"),
        api("api/calibrate/profiles"),
      ]);
      const trackSelect = $("syncTrack");
      trackSelect.innerHTML = '<option value="">— analyzed track —</option>';
      for (const track of (lib.tracks || []).filter((t) => t.analyzed)) {
        const option = document.createElement("option");
        option.value = track.hash;
        option.textContent = track.name;
        trackSelect.appendChild(option);
      }
      const playerSelect = $("syncPlayer");
      playerSelect.innerHTML = '<option value="">— calibrated player —</option>';
      for (const profile of profiles.profiles || []) {
        const option = document.createElement("option");
        option.value = profile.entity_id;
        option.textContent = profile.entity_id + " (" +
          profile.effective_offset_ms + "ms)";
        playerSelect.appendChild(option);
      }
    } catch (error) {
      $("syncStatus").textContent = "failed: " + error.message;
    }
  });

  $("btnSyncStart").addEventListener("click", async () => {
    const status = $("syncStatus");
    const hash = $("syncTrack").value;
    const player = $("syncPlayer").value;
    if (!hash || !player) {
      status.textContent = "Pick an analyzed track and a calibrated player.";
      return;
    }
    try {
      const result = await post("api/show/metronome", {
        track_hash: hash, media_player: player,
      });
      status.textContent = "Running: " + result.cues + " cues, anchored " +
        Math.round(result.offset_ms) + "ms after the play command. " +
        "Watch the bulbs against the beat.";
      pollRunState();
    } catch (error) {
      status.textContent = "failed: " + error.message;
    }
  });

  $("btnSyncStop").addEventListener("click", async () => {
    try {
      const stopped = await post("api/show/stop_show", {});
      pollRunState();
      $("syncStatus").textContent = "Stopped; lights restored.";
      if (stopped.scene) {
        $("syncStatus").textContent =
          "Stopped; " + stopped.scene + " called.";
      }
    } catch (error) {
      $("syncStatus").textContent = "stop failed: " + error.message;
    }
  });

  // ------------------------------------------------------------------
  // Library
  // ------------------------------------------------------------------
  function trackSummary(track) {
    if (!track.analyzed) return "not analyzed";
    const s = track.summary || {};
    return (s.bpm ? s.bpm + " BPM" : "?") +
      " · " + (s.sections || 0) + " sections · " + (s.drops || 0) + " drops" +
      (s.lyrics ? " · lyrics ✓" : "");
  }

  async function scanLibrary() {
    const list = $("trackList");
    list.innerHTML = '<p class="muted">Scanning…</p>';
    try {
      const body = await api("api/library");
      // `folders` is the whole list; `folder` is the main one, kept so a
      // page cached from before the option existed still says something.
      const folders = body.folders ||
        [{ path: body.folder, exists: body.exists }];
      const box = $("libraryFolders");
      box.innerHTML = "";
      for (const folder of folders) {
        const line = document.createElement("div");
        // textContent: a folder name is whatever someone typed into the
        // add-on's options, and it is not markup.
        line.textContent = folder.path + (folder.exists ? "" : " — missing");
        box.appendChild(line);
      }
      const tracks = body.tracks || [];
      if (!tracks.length) {
        list.innerHTML = '<p class="muted">No audio files found.</p>';
        return;
      }
      list.innerHTML = "";
      for (const track of tracks) {
        const row = document.createElement("div");
        row.className = "row";
        row.innerHTML = '<div class="row-main"><strong></strong>' +
          '<span class="rtt small"></span></div>';
        row.querySelector("strong").textContent = track.name;
        row.querySelector(".rtt").textContent = trackSummary(track);
        list.appendChild(row);
      }
    } catch (error) {
      list.innerHTML = '<p class="muted">scan failed: ' + error.message + "</p>";
    }
  }

  // The folder browser. /media as the filesystem, because these have to be
  // folders BRight can read — what Home Assistant will serve out of them is a
  // different question, and Test playback is the one that asks it.
  async function loadTree(path) {
    const tree = $("mediaTree");
    const crumb = $("mediaCrumb");
    tree.innerHTML = '<p class="muted">Reading…</p>';
    try {
      const body = await api("api/media/tree?path=" + encodeURIComponent(path || ""));
      crumb.textContent = body.root + (body.path ? "/" + body.path : "");
      tree.innerHTML = "";
      if (body.parent !== null && body.parent !== undefined) {
        const up = document.createElement("button");
        up.className = "btn small";
        up.textContent = "↑ up a folder";
        up.addEventListener("click", () => loadTree(body.parent));
        tree.appendChild(up);
      }
      if (!body.folders.length) {
        const none = document.createElement("p");
        none.className = "muted";
        none.textContent = "No folders in here.";
        tree.appendChild(none);
      }
      for (const folder of body.folders) {
        const row = document.createElement("div");
        row.className = "row";
        const main = document.createElement("div");
        main.className = "row-main";
        const name = document.createElement("strong");
        name.textContent = folder.name;
        const note = document.createElement("div");
        note.className = "small muted";
        note.textContent = folder.audio_files
          ? folder.audio_files + " track(s) directly inside"
          : "no tracks directly inside";
        if (folder.scanned && !folder.picked) {
          note.textContent += " · already covered by a folder above";
        }
        main.appendChild(name);
        main.appendChild(note);
        const actions = document.createElement("div");
        actions.className = "row-actions";
        const open = document.createElement("button");
        open.className = "btn small";
        open.textContent = "Open";
        open.addEventListener("click", () => loadTree(folder.path));
        const pick = document.createElement("button");
        pick.className = "btn small";
        pick.textContent = folder.picked ? "Stop scanning" : "Scan this";
        pick.addEventListener("click", async () => {
          pick.disabled = true;
          try {
            await post("api/media/folder",
                       { path: folder.path, add: !folder.picked });
            await loadTree(body.path);
            scanLibrary();
          } catch (error) {
            $("mediaCrumb").textContent = "failed: " + error.message;
          }
        });
        actions.appendChild(open);
        actions.appendChild(pick);
        row.appendChild(main);
        row.appendChild(actions);
        tree.appendChild(row);
      }
    } catch (error) {
      tree.innerHTML = '<p class="muted">could not read the media folder: ' +
        error.message + "</p>";
    }
  }

  $("btnBrowseMedia").addEventListener("click", () => loadTree(""));

  $("btnScanLibrary").addEventListener("click", scanLibrary);

  $("btnAnalyzeAll").addEventListener("click", async () => {
    const status = $("analyzeStatus");
    try {
      const started = await post("api/library/analyze", {});
      const job = await awaitJob(started.job, (running) => {
        const p = running.progress;
        if (p) {
          status.textContent = "Analyzing " + (p.current || "…") + " (" +
            p.done + "/" + p.total + (p.failed ? ", " + p.failed + " failed" : "") + ")";
        }
      });
      if (job.status === "done") {
        const r = job.result;
        status.textContent = "Done: " + r.analyzed + " analyzed, " +
          r.skipped + " already had analysis" +
          (r.failed.length ? ", " + r.failed.length + " failed (" +
            r.failed.map((f) => f.file.split("/").pop()).join(", ") + ")" : "");
      } else {
        status.textContent = "Analysis failed: " + job.error;
      }
      scanLibrary();
    } catch (error) {
      status.textContent = "failed: " + error.message;
    }
  });

  // ------------------------------------------------------------------
  // Calibrate: the phone is the measurement instrument
  // ------------------------------------------------------------------
  const RECORD_SECONDS = 14;

  // "Nothing plays" has half a dozen causes and they live in different
  // machines. The server walks them in order; this renders what it found,
  // marking the one that broke rather than making somebody read six lines
  // to find it.
  const STEP_MARK = { true: "✓", false: "✕", null: "!" };

  function renderPlaybackCheck(report) {
    const box = $("playbackCheck");
    box.innerHTML = "";
    for (const step of report.steps || []) {
      const row = document.createElement("div");
      row.className = "row check-step" +
        (step.ok === false ? " bad" : step.ok === null ? " warn" : " good");
      const mark = document.createElement("span");
      mark.className = "check-mark";
      mark.textContent = STEP_MARK[String(step.ok)];
      const text = document.createElement("div");
      text.className = "row-main";
      const name = document.createElement("strong");
      name.textContent = step.name;
      const detail = document.createElement("div");
      detail.className = "small";
      detail.textContent = step.detail;
      text.appendChild(name);
      text.appendChild(detail);
      if (step.fix) {
        const fix = document.createElement("div");
        fix.className = "small check-fix";
        fix.textContent = step.fix;
        text.appendChild(fix);
      }
      row.appendChild(mark);
      row.appendChild(text);
      box.appendChild(row);
    }
    const verdict = document.createElement("p");
    verdict.className = report.ok ? "muted" : "check-verdict";
    verdict.textContent = report.summary || "";
    box.appendChild(verdict);
  }

  $("btnManualOffset").addEventListener("click", async () => {
    const status = $("manualStatus");
    const entityId = $("calPlayer").value;
    if (!entityId) {
      status.textContent = "Pick a media player first.";
      return;
    }
    try {
      const body = await post("api/calibrate/manual", {
        media_player: entityId,
        offset_ms: Number($("manualOffset").value),
      });
      status.textContent = "Saved: " + entityId + " at " +
        body.profile.effective_offset_ms + "ms (manual). Shows can run now.";
      loadProfiles();
    } catch (error) {
      status.textContent = "failed: " + error.message;
    }
  });

  $("btnTestPlayback").addEventListener("click", async () => {
    const entityId = $("calPlayer").value;
    const box = $("playbackCheck");
    if (!entityId) {
      box.innerHTML = '<p class="muted">Pick a media player first.</p>';
      return;
    }
    box.innerHTML = '<p class="muted">Testing — this plays a few seconds of ' +
      'clicks and watches what the speaker does…</p>';
    try {
      renderPlaybackCheck(await post("api/playback/check",
                                     { media_player: entityId }));
    } catch (error) {
      box.innerHTML = "";
      const failed = document.createElement("p");
      failed.className = "check-verdict";
      failed.textContent = "could not run the test: " + error.message;
      box.appendChild(failed);
    }
  });

  $("btnLoadPlayers").addEventListener("click", async () => {
    const select = $("calPlayer");
    select.innerHTML = '<option value="">loading…</option>';
    try {
      const body = await api("api/ha/entities?domain=media_player");
      const found = body.entities || [];
      // An empty picker used to be the answer to both "you have no
      // speakers" and "I could not ask" — the server tells those apart now,
      // and this says the first one out loud rather than showing a list
      // with nothing in it.
      select.innerHTML = found.length
        ? '<option value="">— pick a media player —</option>'
        : '<option value="">no media players in Home Assistant</option>';
      for (const entity of found) {
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

  // ------------------------------------------------------------------
  // What the lights are doing right now.
  //
  // One poller for the whole panel, because "is a show running" has one
  // answer and three buttons used to guess at it separately. A Stop
  // button that is always there is a button nobody trusts: it renders
  // only while the add-on says a run is actually in progress, which is
  // `active` in the state file — the conductor's own answer, not a
  // string comparison against the words that happen to mean running.
  // ------------------------------------------------------------------
  const showState = { data: { status: "idle", active: false }, timer: null };
  const stopButtons = ["btnShowStop", "btnPartyStop", "btnSyncStop"];

  function renderRunState() {
    const state = showState.data || {};
    const running = Boolean(state.active);
    for (const id of stopButtons) {
      const button = $(id);
      if (button) button.hidden = !running;
    }
    const now = $("partyNow");
    if (now) {
      if (!running) {
        now.textContent = "";
      } else {
        const bits = [];
        if (state.party) bits.push("Party: " + state.party);
        if (state.track) bits.push("Playing: " + state.track);
        if (state.queue_left) bits.push(state.queue_left + " tracks left");
        if (state.cues_total) {
          bits.push((state.lights_busy ? "cue " : "cues done — ") +
            (state.lights_busy
              ? (state.cues_sent || 0) + " of " + state.cues_total
              : state.cues_total + " sent"));
        }
        if (state.playback_warning) bits.push("⚠ " + state.playback_warning);
        now.textContent = bits.join(" · ");
      }
    }
    const pre = $("partyState");
    if (pre) {
      pre.hidden = !running;
      if (running) pre.textContent = JSON.stringify(state, null, 2);
    }
  }

  async function pollRunState() {
    try {
      showState.data = await api("api/show/state");
    } catch (error) {
      // A transient failure is not news, and blanking the buttons on one
      // missed poll would make Stop flicker mid-party.
      return;
    }
    renderRunState();
  }

  function watchRunState() {
    if (showState.timer) return;
    pollRunState();
    showState.timer = setInterval(() => {
      if (!document.hidden) pollRunState();
    }, 2500);
  }
  watchRunState();

  // ------------------------------------------------------------------
  // Light Map: add one discovered bulb at a time
  // ------------------------------------------------------------------
  async function loadBulbCandidates() {
    const select = $("bulbCandidate");
    const roles = $("bulbRole");
    try {
      const body = await api("api/map/candidates");
      select.innerHTML = "";
      if (!(body.candidates || []).length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = body.discovered
          ? "— every discovered bulb is already on the map —"
          : "— no bulbs discovered yet (Lab → Discover) —";
        select.appendChild(option);
      } else {
        const first = document.createElement("option");
        first.value = "";
        first.textContent = "— pick a bulb —";
        select.appendChild(first);
        for (const bulb of body.candidates) {
          const option = document.createElement("option");
          option.value = bulb.serial;
          option.textContent = bulb.label + " (" + bulb.serial + ")";
          select.appendChild(option);
        }
      }
      if (!roles.options.length) {
        for (const role of body.roles || []) {
          const option = document.createElement("option");
          option.value = role;
          option.textContent = role;
          option.selected = role === "lamp";
          roles.appendChild(option);
        }
      }
    } catch (error) {
      select.innerHTML = '<option value="">failed: ' + error.message +
        "</option>";
    }
  }

  $("btnRefreshBulbs").addEventListener("click", loadBulbCandidates);

  $("btnAddBulb").addEventListener("click", async () => {
    const serial = $("bulbCandidate").value;
    if (!serial) {
      $("mapStatus").textContent = "Pick a bulb from the list first.";
      return;
    }
    const label = $("bulbCandidate").selectedOptions[0].textContent
      .replace(/\s*\([0-9a-f]{12}\)$/, "");
    try {
      await post("api/map/add-lifx", {
        serial,
        role: $("bulbRole").value,
        zone: $("bulbZone").value,
        label,
        // Dropped near the middle but not ON it, so two bulbs added in a
        // row do not land on top of each other and look like one light.
        x: 0.35 + Math.random() * 0.3,
        y: 0.35 + Math.random() * 0.3,
      });
      $("mapStatus").textContent = label +
        " added — drag it to where it actually is.";
      $("bulbZone").value = "";
      await Promise.all([loadMap(), loadBulbCandidates()]);
    } catch (error) {
      $("mapStatus").textContent = error.message;
    }
  });

  // ------------------------------------------------------------------
  // Effects: the builder
  // ------------------------------------------------------------------
  const fxState = {
    catalog: [], byType: {}, fixtures: [], palettes: [], presets: [],
    selection: new Set(), params: {}, preview: null, playing: false,
    frame: 0, raf: null, lastTick: 0,
  };

  // HSV (what a bulb takes) to a CSS colour (what a screen takes). The
  // conversion is here rather than server-side because the preview frames
  // ARE bulb colours — turning them into CSS on the way out would mean
  // the picture and the packets stopped being the same numbers.
  function hsvCss(hue, sat, val) {
    const l = val * (1 - sat / 2);
    const s = (l === 0 || l === 1) ? 0 : (val - l) / Math.min(l, 1 - l);
    return "hsl(" + Math.round(hue) + " " + Math.round(s * 100) + "% " +
      Math.round(l * 100) + "%)";
  }

  function fxSpec() {
    return fxState.byType[$("fxType").value] || null;
  }

  function renderFxParams() {
    const spec = fxSpec();
    const box = $("fxParams");
    box.innerHTML = "";
    if (!spec) return;
    $("fxBlurb").textContent = spec.blurb;
    for (const param of spec.params) {
      const label = document.createElement("label");
      label.className = "fx-param";
      const name = document.createElement("span");
      name.textContent = param.name.replace(/_/g, " ");
      label.appendChild(name);
      let input;
      if (param.kind === "bool") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.checked = Boolean(fxState.params[param.name] ?? param.default);
      } else if (param.kind === "choice") {
        input = document.createElement("select");
        for (const option of param.options) {
          const el = document.createElement("option");
          el.value = option;
          el.textContent = option;
          el.selected = option === (fxState.params[param.name] ?? param.default);
          input.appendChild(el);
        }
      } else {
        input = document.createElement("input");
        input.type = "number";
        input.min = param.min;
        input.max = param.max;
        input.step = param.kind === "int" ? 1 : 0.05;
        input.value = fxState.params[param.name] ?? param.default;
        const range = document.createElement("span");
        range.className = "muted small";
        range.textContent = param.min + "–" + param.max;
        label.appendChild(range);
      }
      input.dataset.param = param.name;
      input.dataset.kind = param.kind;
      label.appendChild(input);
      box.appendChild(label);
    }
  }

  function readFxParams() {
    const params = {};
    for (const input of $("fxParams").querySelectorAll("[data-param]")) {
      if (input.dataset.kind === "bool") {
        params[input.dataset.param] = input.checked;
      } else if (input.dataset.kind === "choice") {
        params[input.dataset.param] = input.value;
      } else {
        params[input.dataset.param] = Number(input.value);
      }
    }
    return params;
  }

  function currentEffect() {
    const spec = fxSpec();
    return {
      type: $("fxType").value,
      name: $("fxName").value || (spec ? spec.label.toLowerCase() : "effect"),
      order: $("fxOrder").value,
      align: $("fxAlign").value,
      respect_roles: $("fxRespectRoles").checked,
      select: { ids: Array.from(fxState.selection) },
      params: readFxParams(),
    };
  }

  function renderFxFixtures() {
    const box = $("fxFixtures");
    box.innerHTML = "";
    if (!fxState.fixtures.length) {
      box.innerHTML = '<p class="muted">No lights on the map yet — the ' +
        "Light Map tab is where an effect gets something to drive.</p>";
      return;
    }
    for (const fixture of fxState.fixtures) {
      const label = document.createElement("label");
      label.className = "fx-fixture" +
        (fixture.reachable === false ? " unreachable" : "");
      const box2 = document.createElement("input");
      box2.type = "checkbox";
      box2.dataset.id = fixture.id;
      box2.checked = fxState.selection.has(fixture.id);
      const text = document.createElement("span");
      text.textContent = fixture.label + " · " + fixture.role +
        (fixture.zone ? " · " + fixture.zone : "") +
        (fixture.reachable === false ? " · unreachable" : "");
      label.appendChild(box2);
      label.appendChild(text);
      box.appendChild(label);
    }
  }

  function renderFxQuick() {
    const box = $("fxRoleQuick");
    box.innerHTML = "";
    const groups = new Map();
    for (const fixture of fxState.fixtures) {
      groups.set(fixture.role, (groups.get(fixture.role) || 0) + 1);
    }
    for (const [role, count] of groups) {
      const button = document.createElement("button");
      button.className = "btn small";
      button.textContent = role + " (" + count + ")";
      button.dataset.role = role;
      box.appendChild(button);
    }
  }

  $("fxRoleQuick").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-role]");
    if (!button) return;
    const role = button.dataset.role;
    const ids = fxState.fixtures.filter((f) => f.role === role).map((f) => f.id);
    const allOn = ids.every((id) => fxState.selection.has(id));
    for (const id of ids) {
      if (allOn) fxState.selection.delete(id);
      else fxState.selection.add(id);
    }
    renderFxFixtures();
  });

  $("fxFixtures").addEventListener("change", (event) => {
    const box = event.target.closest("input[data-id]");
    if (!box) return;
    if (box.checked) fxState.selection.add(box.dataset.id);
    else fxState.selection.delete(box.dataset.id);
  });

  $("btnFxAll").addEventListener("click", () => {
    for (const fixture of fxState.fixtures) fxState.selection.add(fixture.id);
    renderFxFixtures();
  });
  $("btnFxNone").addEventListener("click", () => {
    fxState.selection.clear();
    renderFxFixtures();
  });

  $("fxType").addEventListener("change", () => {
    fxState.params = {};
    renderFxParams();
  });

  async function loadEffects() {
    if (fxState.catalog.length) {
      // Fixtures can change while the tab is open (somebody adds a bulb),
      // and a builder listing lights that are gone is a builder that
      // silently drives nothing.
      await refreshFxFixtures();
      return;
    }
    try {
      const body = await api("api/effects/catalog");
      fxState.catalog = body.catalog || [];
      fxState.byType = {};
      for (const spec of fxState.catalog) fxState.byType[spec.type] = spec;
      fxState.fixtures = body.fixtures || [];
      fxState.palettes = body.palettes || [];
      fxState.presets = body.presets || [];

      const type = $("fxType");
      type.innerHTML = "";
      for (const spec of fxState.catalog) {
        const option = document.createElement("option");
        option.value = spec.type;
        option.textContent = spec.label + " — " + spec.channel;
        type.appendChild(option);
      }
      fillOptions($("fxOrder"), body.orders || []);
      fillOptions($("fxAlign"), body.alignments || []);
      const palette = $("fxPalette");
      palette.innerHTML = "";
      for (const entry of fxState.palettes) {
        const option = document.createElement("option");
        option.value = entry.name;
        option.textContent = entry.name;
        palette.appendChild(option);
      }
      palette.value = "club";
      type.value = "chase";
      renderFxParams();
      renderFxQuick();
      renderFxFixtures();
      renderPresets();
    } catch (error) {
      $("fxStatus").textContent = "could not load the effect list: " +
        error.message;
    }
  }

  async function refreshFxFixtures() {
    try {
      const body = await api("api/effects/catalog");
      fxState.fixtures = body.fixtures || [];
      for (const id of Array.from(fxState.selection)) {
        if (!fxState.fixtures.some((f) => f.id === id)) {
          fxState.selection.delete(id);
        }
      }
      renderFxQuick();
      renderFxFixtures();
    } catch (error) { /* the builder keeps what it has */ }
  }

  function fillOptions(select, values) {
    select.innerHTML = "";
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value.replace(/_/g, " ");
      select.appendChild(option);
    }
  }

  function previewBody() {
    return {
      effects: [currentEffect()],
      bpm: Number($("fxBpm").value) || 120,
      duration_s: Number($("fxSeconds").value) || 12,
      palette_name: $("fxPalette").value,
    };
  }

  $("btnFxPreview").addEventListener("click", async () => {
    const status = $("fxStatus");
    status.textContent = "rendering…";
    try {
      const body = await post("api/effects/preview", previewBody());
      fxState.preview = body.preview;
      fxState.frame = 0;
      drawTimeline();
      drawFrame(0);
      $("fxScrub").max = String(Math.max(0, body.preview.frames.length - 1));
      $("fxScrub").value = "0";
      const cost = $("fxCost");
      cost.textContent = body.cues + " cues · peak " +
        body.peak_per_device_hz + "/s at one bulb (budget " +
        body.budget_hz + "/s)" +
        (body.effects[0] ? " · " + body.effects[0].fixtures + " lights driven"
          : "");
      cost.className = "cal-status" + (body.over_budget ? " warn" : "");
      status.textContent = body.over_budget
        ? "Over the per-bulb message budget — it will not compile into a " +
          "show until it is slowed down or narrowed."
        : "";
      playPreview(true);
    } catch (error) {
      status.textContent = "preview failed: " + error.message;
    }
  });

  function drawFrame(index) {
    const preview = fxState.preview;
    if (!preview) return;
    const floor = $("fxFloor");
    const frame = preview.frames[Math.min(index, preview.frames.length - 1)];
    if (!floor.dataset.built) {
      floor.innerHTML = "";
      preview.fixtures.forEach((fixture, i) => {
        const dot = document.createElement("div");
        dot.className = "map-dot preview-dot";
        dot.style.left = "clamp(24px, " + (fixture.x * 100) +
          "%, calc(100% - 24px))";
        dot.style.top = "clamp(24px, " + (fixture.y * 100) +
          "%, calc(100% - 42px))";
        dot.dataset.slot = String(i);
        const name = document.createElement("span");
        name.className = "dot-name";
        name.textContent = fixture.label;
        dot.appendChild(name);
        floor.appendChild(dot);
      });
      floor.dataset.built = "1";
    }
    for (const dot of floor.querySelectorAll(".preview-dot")) {
      const colour = frame[Number(dot.dataset.slot)];
      if (!colour) continue;
      dot.style.background = hsvCss(colour[0], colour[1], colour[2]);
      // A bulb at 2% is off, and an unlit dot on a dark floor plan is
      // invisible — the ring is what keeps a dark light legible as a
      // light rather than as nothing.
      dot.style.boxShadow = "0 0 " + Math.round(4 + colour[2] * 26) +
        "px " + hsvCss(colour[0], colour[1], colour[2]);
    }
  }

  function drawTimeline() {
    const preview = fxState.preview;
    const canvas = $("fxTimeline");
    if (!preview || !canvas.getContext) return;
    const rows = preview.fixtures.length || 1;
    const width = canvas.clientWidth || 800;
    const rowHeight = Math.max(10, Math.min(28, 220 / rows));
    canvas.width = width;
    canvas.height = Math.round(rows * rowHeight);
    const ctx = canvas.getContext("2d");
    const frames = preview.frames.length;
    const columnWidth = width / frames;
    for (let f = 0; f < frames; f += 1) {
      for (let r = 0; r < rows; r += 1) {
        const colour = preview.frames[f][r];
        ctx.fillStyle = hsvCss(colour[0], colour[1], colour[2]);
        ctx.fillRect(f * columnWidth, r * rowHeight,
                     Math.ceil(columnWidth), rowHeight - 1);
      }
    }
    canvas.dataset.rowHeight = String(rowHeight);
  }

  function drawPlayhead(index) {
    const canvas = $("fxTimeline");
    const preview = fxState.preview;
    if (!preview || !canvas.getContext) return;
    // Redrawing the whole strip every frame is cheap at these sizes and
    // means the playhead never leaves a trail behind it.
    drawTimeline();
    const ctx = canvas.getContext("2d");
    const x = (index / preview.frames.length) * canvas.width;
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.fillRect(x, 0, 2, canvas.height);
  }

  function playPreview(start) {
    fxState.playing = Boolean(start);
    $("btnFxPlay").textContent = fxState.playing ? "⏸ Pause" : "▶ Play";
    if (fxState.raf) cancelAnimationFrame(fxState.raf);
    if (!fxState.playing || !fxState.preview) return;
    const fps = fxState.preview.fps || 15;
    fxState.lastTick = performance.now();
    const step = (now) => {
      if (!fxState.playing || !fxState.preview) return;
      const advance = Math.floor((now - fxState.lastTick) / (1000 / fps));
      if (advance > 0) {
        fxState.lastTick = now;
        fxState.frame = (fxState.frame + advance) %
          fxState.preview.frames.length;
        drawFrame(fxState.frame);
        drawPlayhead(fxState.frame);
        $("fxScrub").value = String(fxState.frame);
      }
      fxState.raf = requestAnimationFrame(step);
    };
    fxState.raf = requestAnimationFrame(step);
  }

  $("btnFxPlay").addEventListener("click", () => playPreview(!fxState.playing));

  $("fxScrub").addEventListener("input", () => {
    if (!fxState.preview) return;
    playPreview(false);
    fxState.frame = Number($("fxScrub").value);
    drawFrame(fxState.frame);
    drawPlayhead(fxState.frame);
  });

  $("btnFxLive").addEventListener("click", async () => {
    const status = $("fxStatus");
    status.textContent = "running it on the lights…";
    try {
      const result = await post("api/effects/preview-live", {
        ...previewBody(), label: currentEffect().name,
      });
      status.textContent = "Running on " + result.cues + " cues — the " +
        "lights go back to how they were when it ends.";
      pollRunState();
    } catch (error) {
      status.textContent = "could not run it: " + error.message;
    }
  });

  // -- presets ---------------------------------------------------------
  function renderPresets() {
    const list = $("fxPresets");
    list.innerHTML = "";
    if (!fxState.presets.length) {
      list.innerHTML = '<p class="muted">Nothing saved yet.</p>';
      return;
    }
    for (const preset of fxState.presets) {
      const row = document.createElement("div");
      row.className = "row";
      row.dataset.name = preset.name;
      row.innerHTML = '<div class="row-main"><strong></strong>' +
        '<span class="muted small"></span></div>' +
        '<div class="row-actions">' +
        '<button class="btn small" data-act="load">Load</button>' +
        '<button class="btn small" data-act="drop">Delete</button></div>';
      row.querySelector("strong").textContent = preset.name;
      const effect = preset.effect || {};
      row.querySelector(".muted").textContent = effect.type + " · " +
        ((effect.select && effect.select.ids || []).length || "all") +
        " lights · travels " + effect.order;
      list.appendChild(row);
    }
  }

  $("btnFxSave").addEventListener("click", async () => {
    const name = $("fxPresetName").value.trim() || $("fxName").value.trim();
    if (!name) {
      $("fxStatus").textContent = "Give it a name first.";
      return;
    }
    try {
      const body = await post("api/effects/presets",
                              { name, effect: currentEffect() });
      fxState.presets = body.presets || [];
      renderPresets();
      $("fxStatus").textContent = "Saved as " + name + ".";
    } catch (error) {
      $("fxStatus").textContent = "could not save it: " + error.message;
    }
  });

  $("fxPresets").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const name = button.closest(".row").dataset.name;
    if (button.dataset.act === "drop") {
      try {
        const response = await fetch("api/effects/presets/" +
          encodeURIComponent(name), { method: "DELETE" });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.error || response.status);
        fxState.presets = body.presets || [];
        renderPresets();
      } catch (error) {
        $("fxStatus").textContent = error.message;
      }
      return;
    }
    const preset = fxState.presets.find((p) => p.name === name);
    if (!preset) return;
    const effect = preset.effect || {};
    $("fxType").value = effect.type;
    fxState.params = effect.params || {};
    renderFxParams();
    $("fxName").value = effect.name || preset.name;
    $("fxOrder").value = effect.order || "x";
    $("fxAlign").value = effect.align || "beat";
    $("fxRespectRoles").checked = effect.respect_roles !== false;
    fxState.selection = new Set((effect.select && effect.select.ids) || []);
    renderFxFixtures();
    $("fxPresetName").value = preset.name;
    $("fxStatus").textContent = "Loaded " + preset.name + ".";
  });

  // -- putting an effect into a show -----------------------------------
  async function loadFxShowTracks() {
    try {
      const lib = await api("api/library");
      const select = $("fxShowTrack");
      const previous = select.value;
      select.innerHTML = '<option value="">— compiled track —</option>';
      for (const track of (lib.tracks || []).filter((t) => t.show)) {
        const option = document.createElement("option");
        option.value = track.hash;
        option.textContent = track.name;
        option.selected = track.hash === previous;
        select.appendChild(option);
      }
    } catch (error) { /* the picker stays as it was */ }
  }

  $("fxShowTrack").addEventListener("change", async () => {
    const select = $("fxShowScene");
    select.innerHTML = '<option value="">— scene —</option>';
    const hash = $("fxShowTrack").value;
    if (!hash) return;
    try {
      const body = await api("api/show/" + hash + "/script");
      const scenes = (body.script && body.script.scenes) || [];
      scenes.forEach((scene, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = index + ": " + (scene.mood || scene.kind) +
          " (" + Math.round(scene.start) + "–" + Math.round(scene.end) + "s)";
        select.appendChild(option);
      });
    } catch (error) {
      $("fxAddStatus").textContent = error.message;
    }
  });

  $("btnFxAddToShow").addEventListener("click", async () => {
    const hash = $("fxShowTrack").value;
    const index = $("fxShowScene").value;
    const status = $("fxAddStatus");
    if (!hash || index === "") {
      status.textContent = "Pick a compiled track and one of its scenes.";
      return;
    }
    try {
      const current = await api("api/show/" + hash + "/script");
      const script = current.script;
      if (!script) throw new Error("that track has no show script yet");
      const scene = script.scenes[Number(index)];
      scene.effects = (scene.effects || []).concat([currentEffect()]);
      const saved = await put("api/show/" + hash + "/script", { script });
      status.textContent = "Added — recompiled to " + saved.stats.cues +
        " cues (peak " + saved.stats.peak_per_device_hz + "/s per bulb).";
      loadShows();
    } catch (error) {
      status.textContent = "could not add it: " + error.message;
    }
  });

  // ------------------------------------------------------------------
  // Shows: the script editor — the whole show, as the file it is
  // ------------------------------------------------------------------
  let scriptTrack = null;

  async function openScript(hash, name) {
    scriptTrack = hash;
    const status = $("scriptStatus");
    status.textContent = "loading…";
    try {
      const body = await api("api/show/" + hash + "/script");
      $("scriptWhich").textContent = body.title +
        (body.file ? " · " + body.file : " · not compiled yet");
      $("scriptText").value = body.script
        ? JSON.stringify(body.script, null, 2)
        : "";
      renderScriptEffects(body);
      status.textContent = body.compiled
        ? "Compiled: " + body.stats.cues + " cues, peak " +
          body.stats.peak_per_device_hz + "/s per bulb."
        : "No show compiled for this track yet — press Compile above first.";
      $("showCues").hidden = true;
    } catch (error) {
      status.textContent = "could not open it: " + error.message;
    }
  }

  function renderScriptEffects(body) {
    const list = $("scriptEffects");
    list.innerHTML = "";
    for (const entry of body.effects || []) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<div class="row-main"><strong></strong>' +
        '<span class="muted small"></span></div>';
      row.querySelector("strong").textContent =
        (entry.name || entry.type) + " (" + entry.type + ")";
      row.querySelector(".muted").textContent = entry.where + " · " +
        entry.fixtures + " lights · " + entry.actions + " moves · busiest " +
        "light gets " + entry.busiest_fixture;
      list.appendChild(row);
    }
  }

  $("btnScriptSave").addEventListener("click", async () => {
    const status = $("scriptStatus");
    if (!scriptTrack) {
      status.textContent = "Open a track's show first.";
      return;
    }
    let script;
    try {
      script = JSON.parse($("scriptText").value);
    } catch (error) {
      status.textContent = "That is not valid JSON — " + error.message;
      return;
    }
    status.textContent = "compiling…";
    try {
      const body = await put("api/show/" + scriptTrack + "/script", { script });
      status.textContent = "Saved and compiled: " + body.stats.cues +
        " cues, peak " + body.stats.peak_per_device_hz + "/s per bulb.";
      renderScriptEffects(body);
      loadShows();
    } catch (error) {
      status.textContent = error.message;
    }
  });

  $("btnScriptReload").addEventListener("click", async () => {
    const status = $("scriptStatus");
    if (!scriptTrack) {
      status.textContent = "Open a track's show first.";
      return;
    }
    status.textContent = "reading the file…";
    try {
      const body = await post("api/show/" + scriptTrack + "/script/import", {});
      $("scriptText").value = JSON.stringify(body.script, null, 2);
      renderScriptEffects(body);
      status.textContent = "Read from " + body.file + " and compiled: " +
        body.stats.cues + " cues.";
      loadShows();
    } catch (error) {
      status.textContent = error.message;
    }
  });

  $("btnShowCues").addEventListener("click", async () => {
    const pre = $("showCues");
    if (!scriptTrack) {
      $("scriptStatus").textContent = "Open a track's show first.";
      return;
    }
    if (!pre.hidden) {
      pre.hidden = true;
      return;
    }
    try {
      const body = await api("api/show/" + scriptTrack + "/cues?limit=400");
      pre.hidden = false;
      pre.textContent = body.cues.map((cue) =>
        cue.t.toFixed(2).padStart(8) + "s  " + cue.ch.padEnd(4) + " " +
        String(cue.target).padEnd(14) + " " + cue.desc).join("\n") +
        (body.total > body.cues.length
          ? "\n… " + (body.total - body.cues.length) + " more"
          : "");
    } catch (error) {
      $("scriptStatus").textContent = error.message;
    }
  });

  // ------------------------------------------------------------------
  // Party: saved evenings
  // ------------------------------------------------------------------
  let partyEditing = null;

  async function loadParties() {
    try {
      const body = await api("api/parties");
      const list = $("partyList");
      const picker = $("partySaved");
      const previous = picker.value;
      picker.innerHTML = '<option value="">— ad-hoc party —</option>';
      list.innerHTML = "";
      if (!(body.parties || []).length) {
        list.innerHTML = '<p class="muted">No saved parties yet.</p>';
      }
      for (const party of body.parties || []) {
        const option = document.createElement("option");
        option.value = party.name;
        option.textContent = party.name;
        option.selected = party.name === previous;
        picker.appendChild(option);

        const row = document.createElement("div");
        row.className = "row";
        row.dataset.name = party.name;
        row.innerHTML = '<div class="row-main"><strong></strong>' +
          '<span class="muted small"></span></div>' +
          '<div class="row-actions">' +
          '<button class="btn small" data-act="start">▶ Start</button>' +
          '<button class="btn small" data-act="edit">Edit</button>' +
          '<button class="btn small" data-act="drop">Delete</button></div>';
        row.querySelector("strong").textContent = party.name;
        const bits = [];
        if (party.media_player) bits.push(party.media_player);
        if (party.folder) bits.push(party.folder);
        if (party.vibe) bits.push('"' + party.vibe + '"');
        const count = (party.fixtures || []).length;
        bits.push(count ? count + (count === 1 ? " light" : " lights")
          : "all lights");
        if (party.end_scene) bits.push("ends with " + party.end_scene);
        row.querySelector(".muted").textContent = bits.join(" · ");
        list.appendChild(row);
      }
    } catch (error) {
      $("partyStatus").textContent = "could not read the parties: " +
        error.message;
    }
  }

  async function fillPartyForm(party) {
    partyEditing = party ? party.name : null;
    $("partyForm").hidden = false;
    $("pfName").value = party ? party.name : "";
    $("pfVibe").value = (party && party.vibe) || "";
    $("pfFolder").value = (party && party.folder) || "";
    $("pfShuffle").checked = !party || party.shuffle !== false;
    try {
      const [profiles, scenes, catalog] = await Promise.all([
        api("api/calibrate/profiles"),
        api("api/ha/entities?domain=scene").catch(() => ({ entities: [] })),
        api("api/effects/catalog"),
      ]);
      const players = $("pfPlayer");
      players.innerHTML = '<option value="">— calibrated player —</option>';
      for (const profile of profiles.profiles || []) {
        const option = document.createElement("option");
        option.value = profile.entity_id;
        option.textContent = profile.entity_id;
        option.selected = party && profile.entity_id === party.media_player;
        players.appendChild(option);
      }
      const sceneSelect = $("pfScene");
      sceneSelect.innerHTML =
        '<option value="">— put the lights back as they were —</option>';
      for (const entity of scenes.entities || []) {
        const option = document.createElement("option");
        option.value = entity.entity_id;
        option.textContent = entity.name;
        option.selected = party && entity.entity_id === party.end_scene;
        sceneSelect.appendChild(option);
      }
      const chosen = new Set((party && party.fixtures) || []);
      const box = $("pfFixtures");
      box.innerHTML = "";
      for (const fixture of catalog.fixtures || []) {
        const label = document.createElement("label");
        label.className = "fx-fixture";
        const check = document.createElement("input");
        check.type = "checkbox";
        check.dataset.id = fixture.id;
        check.checked = chosen.has(fixture.id);
        const text = document.createElement("span");
        text.textContent = fixture.label + " · " + fixture.role;
        label.appendChild(check);
        label.appendChild(text);
        box.appendChild(label);
      }
    } catch (error) {
      $("pfStatus").textContent = error.message;
    }
  }

  $("btnPartyNew").addEventListener("click", () => fillPartyForm(null));
  $("btnPartyCancel").addEventListener("click", () => {
    $("partyForm").hidden = true;
    partyEditing = null;
  });

  $("btnPartySave").addEventListener("click", async () => {
    const fixtures = Array.from(
      $("pfFixtures").querySelectorAll("input[data-id]:checked"))
      .map((input) => input.dataset.id);
    try {
      await post("api/parties", {
        name: $("pfName").value,
        media_player: $("pfPlayer").value,
        folder: $("pfFolder").value,
        vibe: $("pfVibe").value,
        end_scene: $("pfScene").value,
        shuffle: $("pfShuffle").checked,
        fixtures,
      });
      $("partyForm").hidden = true;
      partyEditing = null;
      $("pfStatus").textContent = "";
      loadParties();
    } catch (error) {
      $("pfStatus").textContent = error.message;
    }
  });

  $("partyList").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const name = button.closest(".row").dataset.name;
    const status = $("partyStatus");
    if (button.dataset.act === "start") {
      try {
        const result = await post("api/show/start_party", { party: name });
        status.textContent = "Party on: " + result.queue + " tracks queued.";
        pollRunState();
      } catch (error) {
        status.textContent = error.message;
      }
    } else if (button.dataset.act === "edit") {
      try {
        const body = await api("api/parties");
        fillPartyForm((body.parties || []).find((p) => p.name === name));
      } catch (error) {
        status.textContent = error.message;
      }
    } else if (button.dataset.act === "drop") {
      try {
        const response = await fetch("api/parties/" + encodeURIComponent(name),
                                     { method: "DELETE" });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.error || response.status);
        }
        loadParties();
      } catch (error) {
        status.textContent = error.message;
      }
    }
  });

  // Load each tab's data when it first opens.
  tabs.addEventListener("click", (event) => {
    const button = event.target.closest(".tab");
    if (!button) return;
    if (button.dataset.tab === "map") loadBulbCandidates();
    if (button.dataset.tab === "effects") {
      loadEffects();
      loadFxShowTracks();
    }
    if (button.dataset.tab === "party") loadParties();
  });
})();
