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
  let mapData = { fixtures: [], roles: [], zones: [] };

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
    // A zone is a name you give a group of lights — usually a room. It was
    // settable only while ADDING a bulb, which meant the answer to "these
    // four are the kitchen" was to remove them and add them again. It is a
    // free-text field with a datalist rather than a picker because the
    // first light in a new zone has to be able to invent the name, and a
    // picker of existing zones can only ever offer the ones already there.
    const zone = document.createElement("input");
    zone.className = "zone-pick";
    zone.type = "text";
    zone.placeholder = "room / zone";
    zone.value = fixture.zone || "";
    zone.setAttribute("list", "mapZoneNames");
    zone.setAttribute("aria-label", "Room or zone for " + fixture.label);
    const commitZone = () => {
      const wanted = zone.value.trim();
      if (wanted === (fixture.zone || "")) return;
      fixture.zone = wanted;
      saveFixture(fixture);
    };
    zone.addEventListener("change", commitZone);
    zone.addEventListener("blur", commitZone);
    const names = document.createElement("datalist");
    names.id = "mapZoneNames";
    for (const existing of mapData.zones || []) {
      const option = document.createElement("option");
      option.value = existing;
      names.appendChild(option);
    }
    const remove = document.createElement("button");
    remove.className = "btn small";
    remove.textContent = "Remove this light";
    remove.addEventListener("click", () => removeFixture(fixture.id));
    bar.appendChild(name);
    bar.appendChild(where);
    bar.appendChild(pick);
    bar.appendChild(zone);
    bar.appendChild(names);
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
          '<button class="btn small" data-act="claude">✨ Claude</button>' +
          (show ? '<button class="btn small" data-act="play">▶ Show</button>'
                : "") +
          '<button class="btn small" data-act="sync">♪ Beat sync</button>' +
          "</div>";
        row.querySelector("strong").textContent = track.name;
        row.querySelector(".rtt").textContent = show
          ? "compiled: " + show.tier + " · " + show.palette + " · " +
            show.cues + " cues"
          : "not compiled — Beat sync plays plain pulses; Compile builds "
            + "the show";
        list.appendChild(row);
      }
    } catch (error) {
      list.innerHTML = '<p class="muted">failed: ' + error.message + "</p>";
    }
  }

  // Who wrote this show, in a sentence.
  //
  // A show tagged `algorithmic` with nothing beside it is indistinguishable
  // from one nobody asked Claude for — which is how a fortnight of silent
  // fallbacks went unnoticed on a real install. The distinction that
  // matters is not "which tier" but "did the one you asked for actually
  // run", so a fallback always carries its reason.
  function describeDirector(report) {
    if (!report) return "";
    if (report.used === "claude") {
      return "written by Claude" +
        (report.seconds ? " in " + report.seconds + "s" : "");
    }
    if (report.fell_back) {
      return "Claude was asked and could not: " + report.reason +
        " — the algorithmic director wrote this one instead";
    }
    if (report.asked !== "algorithmic" && report.reason) {
      return "algorithmic — " + report.reason;
    }
    return "written by the algorithmic director";
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
      if (button.dataset.act === "compile" ||
          button.dataset.act === "claude") {
        const wantsClaude = button.dataset.act === "claude";
        out.textContent = wantsClaude
          // Named, and with the wait declared: a Claude show is one long
          // considered answer and can take minutes. A spinner that says
          // nothing about how long is a spinner people press twice.
          ? "asking Claude to write this show — this can take a minute or two…"
          : "compiling…";
        const result = await post("api/show/compile", {
          track_hash: row.dataset.hash,
          director: wantsClaude ? "claude" : undefined,
        });
        const who = describeDirector(result.director);
        out.textContent = "compiled: " + result.tier + " · " +
          result.palette + " · " + result.stats.cues + " cues (peak " +
          result.stats.peak_per_device_hz + "/s per bulb)" +
          (who ? " — " + who : "");
        openScript(row.dataset.hash, row.querySelector("strong").textContent);
      } else if (button.dataset.act === "play"
                 || button.dataset.act === "sync") {
        const player = $("showPlayer").value;
        if (!player) {
          status.textContent = "Pick a calibrated player first.";
          return;
        }
        const route = button.dataset.act === "sync"
          ? "api/show/metronome" : "api/show/start_show";
        const result = await post(route, {
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
  async function loadPartyPlayers() {
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
  }

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
        "ms after each play." +
        ((result.skipped_tracks || []).length
          ? " Skipped (no longer analyzed): " +
            result.skipped_tracks.join(", ") + " — re-analyze from the " +
            "Library tab."
          : "");
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
  async function loadSyncChoices() {
    try {
      const [lib, profiles, devices] = await Promise.all([
        api("api/library"),
        api("api/calibrate/profiles"),
        api("api/lifx/devices").catch(() => ({ devices: [] })),
      ]);
      const bulbs = $("syncBulbs");
      bulbs.innerHTML = "";
      for (const device of devices.devices || []) {
        const label = document.createElement("label");
        label.className = "fx-fixture";
        const check = document.createElement("input");
        check.type = "checkbox";
        check.checked = true;
        check.dataset.serial = device.serial;
        const text = document.createElement("span");
        text.textContent = (device.label || device.serial);
        label.appendChild(check);
        label.appendChild(text);
        bulbs.appendChild(label);
      }
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
  }

  $("btnSyncStart").addEventListener("click", async () => {
    const status = $("syncStatus");
    const hash = $("syncTrack").value;
    const player = $("syncPlayer").value;
    if (!hash || !player) {
      status.textContent = "Pick an analyzed track and a calibrated player.";
      return;
    }
    try {
      const serials = Array.from(
        $("syncBulbs").querySelectorAll("input[data-serial]:checked"))
        .map((input) => input.dataset.serial);
      const result = await post("api/show/metronome", {
        track_hash: hash, media_player: player,
        serials: serials.length ? serials : undefined,
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
      try {
        renderMediaSource(await api("api/media/source"));
      } catch (error) {
        // The chain report is the answer; this line is a footnote to it.
      }
    } catch (error) {
      box.innerHTML = "";
      const failed = document.createElement("p");
      failed.className = "check-verdict";
      failed.textContent = "could not run the test: " + error.message;
      box.appendChild(failed);
    }
  });

  // Which media source BRight builds ids with. Rendered only when it is
  // NOT the default: on the install where `local` is right, saying so is a
  // line nobody needs, and discovery working is discovery you never see.
  function renderMediaSource(state) {
    const box = $("mediaSource");
    box.innerHTML = "";
    if (!state) return;
    const bits = [];
    if (state.error) {
      const bad = document.createElement("p");
      bad.className = "ms-bad";
      bad.textContent = state.error;
      bits.push(bad);
    } else if (state.discovered && state.source_id !== "local") {
      const note = document.createElement("p");
      note.className = "muted";
      note.textContent = "Home Assistant calls this add-on's " +
        state.media_root + ' folder "' + state.source_id + '", not the ' +
        'usual "local" — BRight found that and is using it.';
      bits.push(note);
    }
    if (!bits.length) return;
    const again = document.createElement("button");
    again.className = "btn small";
    again.textContent = "Look again";
    again.addEventListener("click", async () => {
      again.disabled = true;
      again.textContent = "looking…";
      try {
        renderMediaSource(await post("api/media/source/rediscover", {}));
      } catch (error) {
        again.disabled = false;
        again.textContent = "Look again — " + error.message;
      }
    });
    for (const bit of bits) box.appendChild(bit);
    box.appendChild(again);
  }

  async function loadCalPlayers() {
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
  }

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
          '<button class="btn small" data-act="nudge">Save</button>' +
          '<button class="btn small" data-act="forget" ' +
          'aria-label="Delete this calibration">✕</button></div>';
        row.querySelector(".row-main span").textContent = describeProfile(profile);
        row.querySelector(".nudge").value = profile.adjust_ms || 0;
        row.dataset.entity = profile.entity_id;
        list.appendChild(row);
      }
    } catch (error) {
      list.innerHTML = '<p class="muted">failed: ' + error.message + "</p>";
    }
  }

  $("calProfiles").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const row = button.closest(".row");
    try {
      if (button.dataset.act === "nudge") {
        await post("api/calibrate/adjust", {
          media_player: row.dataset.entity,
          adjust_ms: Number(row.querySelector(".nudge").value) || 0,
        });
      } else if (button.dataset.act === "forget") {
        // One press, no confirm dialog: a calibration is a measurement,
        // and re-taking it is a minute in the wizard — cheaper than the
        // dialog everyone clicks through would ever be worth.
        const response = await fetch("api/calibrate/profile/" +
          encodeURIComponent(row.dataset.entity), { method: "DELETE" });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.error || response.status);
      }
      loadProfiles();
    } catch (error) {
      row.querySelector(".row-main span").textContent = "failed: " + error.message;
    }
  });

  $("btnCalStop").addEventListener("click", async () => {
    const entityId = $("calPlayer").value;
    const status = $("calStatus") || $("playbackCheck");
    if (!entityId) return;
    try {
      await post("api/calibrate/stop", { media_player: entityId });
    } catch (error) {
      if (status) status.textContent = "could not stop it: " + error.message;
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
    const live = $("partyLive");
    if (live) live.hidden = !running;
    // The Shows tab gets the same trim while anything runs — sync is
    // judged wherever you happen to be standing when you notice it.
    for (const id of ["btnShowNudgeLater", "btnShowNudgeEarlier"]) {
      const button = $(id);
      if (button) button.hidden = !running;
    }
    const showReadout = $("showNudgeReadout");
    if (showReadout) {
      const trim = Number((state.nudge_ms) || 0);
      showReadout.textContent = running && trim
        ? "trim " + (trim > 0 ? "+" : "") + trim + "ms" : "";
    }
    if (!running) {
      partyView.hash = null;
      return;
    }
    const bits = [];
    if (state.party) bits.push(state.party);
    if (state.track) bits.push("♪ " + state.track);
    if (state.queue_left > 1) {
      bits.push((state.queue_left - 1) + " more after this");
    }
    if (state.playback_warning) bits.push("⚠ " + state.playback_warning);
    $("partyNow").textContent = bits.join(" · ");
    const upNext = state.up_next || [];
    $("partyUpNext").textContent = upNext.length
      ? "Up next: " + upNext.join(" · ")
      : "";
    const trimmed = Number(state.nudge_ms || 0);
    $("nudgeReadout").textContent = trimmed
      ? "trimmed " + (trimmed > 0 ? "+" : "") + trimmed + "ms"
      : "";
    $("btnNudgeKeep").hidden = !trimmed;
    // Transport is a queue's, not a show's: a single show has nothing to
    // skip to, so the buttons render only while a party is running.
    const isParty = state.status === "party";
    for (const id of ["btnPartyPrev", "btnPartyNext"]) {
      const button = $(id);
      if (button) button.hidden = !isParty;
    }
    partyFollowLive(state);
  }

  // -- the party's live picture -----------------------------------------
  //
  // The same three ingredients the show editor uses, pointed at whatever
  // is playing right now: the waveform (with the analyser's sections and
  // drops), the floor of dots, and the conductor's own position stamps,
  // advanced locally between polls so the playhead moves through quiet
  // stretches instead of lurching cue to cue. The frames come from the
  // show outline — the compiler's own walk — so the dots on screen are
  // the colours the room is being sent, not a second opinion about them.
  const partyView = { hash: null, wave: null, outline: null, anchor: null,
                      lastStamp: null };

  async function partyFollowLive(state) {
    const hash = state.track_hash;
    if (!hash) return;
    // Re-anchor only when the stamp MOVED. The conductor stamps position
    // as it dispatches cues and not otherwise, so through a quiet stretch
    // or the outro the same number arrives on every poll — re-anchoring
    // to it snaps the playhead backwards to where the last cue was, over
    // and over, which is the exact lurch the local advance exists to
    // avoid.
    if (typeof state.position_s === "number" &&
        state.position_s !== partyView.lastStamp) {
      partyView.lastStamp = state.position_s;
      partyView.anchor = { at: performance.now(), position: state.position_s };
    }
    if (partyView.hash !== hash) {
      partyView.hash = hash;
      partyView.wave = null;
      partyView.outline = null;
      partyView.lastStamp = null;
      // Fetched once per track, not per poll: the song does not change
      // mid-song, and the outline simulates the whole show.
      try {
        partyView.wave = await api("api/track/" + hash + "/waveform");
      } catch (ignored) { /* the floor still works without the song */ }
      try {
        partyView.outline = await post("api/show/" + hash + "/outline", {});
      } catch (ignored) { /* the song still works without the floor */ }
    }
    partyPaint();
  }

  function partyPosition() {
    if (!partyView.anchor) return 0;
    return partyView.anchor.position +
      (performance.now() - partyView.anchor.at) / 1000;
  }

  function partyPaint() {
    const state = showState.data || {};
    if (!state.active || partyView.hash !== state.track_hash) return;
    const position = partyPosition();
    const wave = partyView.wave;
    if (wave && wave.duration_s) {
      paintWave($("partyWave"), wave,
                Math.min(1, Math.max(0, position / wave.duration_s)));
    }
    const outline = partyView.outline;
    if (outline && outline.columns && outline.columns.length) {
      const column = Math.min(outline.columns.length - 1, Math.max(0,
        Math.floor(position / (outline.seconds_per_column || 1))));
      // The outline simulates the WHOLE compiled show; a party may only
      // be driving some of the room (conductor.filter_cues, at dispatch).
      // Excluded lights are dropped from the picture, because a dot
      // dancing on screen while its bulb sits still in the room is a
      // second opinion — the one thing this view promises not to be.
      const allow = state.allow || [];
      let fixtures = outline.fixtures;
      let frame = outline.columns[column];
      let key = "party:" + partyView.hash;
      if (allow.length) {
        const keep = outline.fixtures
          .map((fixture, i) => [fixture, i])
          .filter(([fixture]) => allow.includes(fixture.id));
        fixtures = keep.map(([fixture]) => fixture);
        frame = keep.map(([, i]) => frame[i]);
        key += ":" + allow.length;
      }
      paintFloor($("partyFloor"), fixtures, frame, key);
    }
  }

  // Between polls the playhead keeps moving from the last anchor — same
  // interpolation the editor's live follow does, for the same reason.
  setInterval(() => {
    if (document.hidden) return;
    // The element being un-hidden is not the tab being in front: pane
    // visibility is a class on the pane, and a canvas repaint five times
    // a second behind another tab is heat with no audience.
    if (!document.getElementById("pane-party").classList.contains("active")) {
      return;
    }
    const state = showState.data || {};
    if (state.active && !$("partyLive").hidden) partyPaint();
  }, 200);

  $("btnPartyPrev").addEventListener("click", () => partySkip(-1));
  $("btnPartyNext").addEventListener("click", () => partySkip(1));

  async function partySkip(step) {
    try {
      await post("api/party/skip", { step });
      $("partyStatus").textContent = step > 0
        ? "Skipping to the next track…" : "Going back a track…";
    } catch (error) {
      $("partyStatus").textContent = error.message;
    }
  }

  $("btnNudgeLater").addEventListener("click", () => partyNudge(-25));
  $("btnNudgeEarlier").addEventListener("click", () => partyNudge(25));
  $("btnShowNudgeLater").addEventListener("click", () => partyNudge(-25));
  $("btnShowNudgeEarlier").addEventListener("click", () => partyNudge(25));

  async function partyNudge(ms) {
    try {
      const result = await post("api/show/nudge", { ms });
      $("nudgeReadout").textContent = result.nudge_ms
        ? "trimmed " + (result.nudge_ms > 0 ? "+" : "") + result.nudge_ms + "ms"
        : "";
      $("btnNudgeKeep").hidden = !result.nudge_ms;
    } catch (error) {
      $("partyStatus").textContent = error.message;
    }
  }

  // The nudge, measured instead of guessed. Same recording plumbing as
  // the calibration wizard — clocks mapped via ping, raw mic (no echo
  // cancellation: the music IS the signal), 16-bit wav up — but the
  // reference it is matched against is the playing song itself, so the
  // answer comes back as "the room is Xms off" and is applied whole.
  $("btnAutoSync").addEventListener("click", async () => {
    const status = $("autoSyncStatus");
    const button = $("btnAutoSync");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      status.textContent = "This browser won't share the microphone here " +
        "(it usually needs HTTPS) — use the nudge buttons instead.";
      return;
    }
    button.disabled = true;
    try {
      const offset = await clockOffset();
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
          recordStartClient = Date.now() -
            (event.inputBuffer.length / context.sampleRate) * 1000;
        }
        chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(context.destination);
      for (let s = 4; s > 0; s--) {
        status.textContent = "Listening to the room… " + s + "s";
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      context.close();
      status.textContent = "Matching against the song…";
      const wav = floatTo16BitWav(chunks, context.sampleRate);
      const result = await post("api/show/autosync", {
        wav_b64: bufferToBase64(wav),
        record_start_epoch_ms: recordStartClient + offset,
      });
      const ms = Math.round(result.delta_ms);
      status.textContent = Math.abs(ms) < 25
        ? "In tune — the room was only " + Math.abs(ms) + "ms off."
        : "Heard the room " + Math.abs(ms) + "ms " +
          (ms > 0 ? "ahead of" : "behind") + " the lights — shifted them " +
          "to match. Keep this trim saves it for every show.";
      $("nudgeReadout").textContent = result.nudge_ms
        ? "trimmed " + (result.nudge_ms > 0 ? "+" : "") +
          result.nudge_ms + "ms"
        : "";
      $("btnNudgeKeep").hidden = !result.nudge_ms;
    } catch (error) {
      status.textContent = "Failed: " + error.message;
    } finally {
      button.disabled = false;
    }
  });

  $("btnNudgeKeep").addEventListener("click", async () => {
    try {
      const result = await post("api/show/nudge/keep", {});
      $("partyStatus").textContent = "Kept: " + result.entity_id +
        " now plays lights at " + result.effective_offset_ms +
        "ms — every future show starts in tune.";
      $("nudgeReadout").textContent = "";
      $("btnNudgeKeep").hidden = true;
    } catch (error) {
      $("partyStatus").textContent = error.message;
    }
  });

  async function pollRunState() {
    try {
      showState.data = await api("api/show/state");
    } catch (error) {
      // A transient failure is not news, and blanking the buttons on one
      // missed poll would make Stop flicker mid-party.
      return;
    }
    renderRunState();
    edFollowLiveShow();
  }

  // While a show is actually playing, the editor's playhead follows the
  // room rather than the preview.
  //
  // The conductor stamps `position_s` as it dispatches, so the value is
  // exact but arrives in steps — every cue during a busy scene, and not at
  // all through a quiet one. Sitting on it would make the playhead lurch
  // and then freeze, so it is treated as an anchor and advanced locally
  // between polls: the same trick the show clock itself uses, for the same
  // reason. A poll that moves the anchor backwards (a restart, a different
  // track) re-anchors instead of interpolating toward it.
  function edFollowLiveShow() {
    const state = showState.data || {};
    const live = state.active && typeof state.position_s === "number" &&
      ed.hash && state.track_hash === ed.hash;
    if (!live) {
      if (ed.following) {
        ed.following = false;
        edPlay(false);
      }
      return;
    }
    if (!ed.following) {
      ed.following = true;
      edPlay(false);  // the room is the clock now, not the animation loop
    }
    ed.liveAnchor = { at: performance.now(), position: state.position_s };
    edSeek(state.position_s);
  }

  // Between polls, keep the playhead moving from the last anchor.
  setInterval(() => {
    if (!ed.following || !ed.liveAnchor) return;
    const elapsed = (performance.now() - ed.liveAnchor.at) / 1000;
    edSeek(ed.liveAnchor.position + elapsed, false);
  }, 100);

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
    select: null,
    orders: [], alignments: [], roles: [], zones: [], defaultOrder: "",
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

  // The parameter form, from the catalog. Shared by the Effects tab and
  // the show editor's effect dialog: two places build this form, and a
  // second implementation of "what a strobe's controls are" would drift
  // from the catalog the moment a parameter's range changed.
  function renderParamControls(box, spec, values) {
    box.innerHTML = "";
    if (!spec) return;
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
        input.checked = Boolean(values[param.name] ?? param.default);
      } else if (param.kind === "choice") {
        input = document.createElement("select");
        for (const option of param.options) {
          const el = document.createElement("option");
          el.value = option;
          el.textContent = option;
          el.selected = option === (values[param.name] ?? param.default);
          input.appendChild(el);
        }
      } else {
        input = document.createElement("input");
        input.type = "number";
        input.min = param.min;
        input.max = param.max;
        input.step = param.kind === "int" ? 1 : 0.05;
        input.value = values[param.name] ?? param.default;
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

  function readParamControls(box) {
    const params = {};
    for (const input of box.querySelectorAll("[data-param]")) {
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

  function renderFxParams() {
    const spec = fxSpec();
    if (spec) $("fxBlurb").textContent = spec.blurb;
    renderParamControls($("fxParams"), spec, fxState.params);
  }

  function readFxParams() {
    return readParamControls($("fxParams"));
  }

  function currentEffect() {
    const spec = fxSpec();
    return {
      type: $("fxType").value,
      name: $("fxName").value || (spec ? spec.label.toLowerCase() : "effect"),
      order: $("fxOrder").value,
      align: $("fxAlign").value,
      respect_roles: $("fxRespectRoles").checked,
      // The tick boxes are ids, but an effect's select is not only ids.
      // A generated effect (or a preset) that says "every candle" has to
      // STAY "every candle" — flattening it to the four candles that exist
      // today is wrong the moment a fifth is added, and it is the same
      // quiet rewrite the show editor's dialog was fixed for. Ticking any
      // box is what hands the selection back to the ids.
      select: fxState.select || { ids: Array.from(fxState.selection) },
      params: readFxParams(),
    };
  }

  // A kept select (roles, zones) stops being the answer the moment somebody
  // uses the tick boxes: from then on the ticks ARE the selection, which is
  // what they look like they are.
  function fxTakeSelection() {
    fxState.select = null;
    renderFxFixtures();
    renderFxSelectNote();
  }

  function renderFxSelectNote() {
    const box = $("fxSelectNote");
    if (!box) return;
    if (!fxState.select) {
      box.textContent = "";
      return;
    }
    box.textContent = "This effect selects: " +
      edDescribeSelect(fxState.select) +
      " — the ticks below show which lights that is right now. Tick anything " +
      "to replace it with a fixed list.";
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
    fxTakeSelection();
  });

  $("fxFixtures").addEventListener("change", (event) => {
    const box = event.target.closest("input[data-id]");
    if (!box) return;
    if (box.checked) fxState.selection.add(box.dataset.id);
    else fxState.selection.delete(box.dataset.id);
    fxTakeSelection();
  });

  $("btnFxAll").addEventListener("click", () => {
    for (const fixture of fxState.fixtures) fxState.selection.add(fixture.id);
    fxTakeSelection();
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
      fxState.orders = body.orders || [];
      fxState.roles = body.roles || [];
      fxState.defaultOrder = body.default_order || "x";
      fxState.zones = body.zones || [];
      fxState.alignments = body.alignments || [];
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

  // The room, lit. Shared by the Effects bench and the show editor, because
  // they are the same picture of the same house — and because the dots have
  // three fiddly details (the clamp, the ring on a dark bulb, the name) that
  // a second copy would get subtly different.
  //
  // `key` is what tells the painter its dots are stale: the two surfaces
  // hold different casts, and a floor rebuilt only when it is empty would
  // keep the first tab's bulbs forever.
  function paintFloor(floor, fixtures, frame, key) {
    if (floor.dataset.built !== key) {
      floor.innerHTML = "";
      fixtures.forEach((fixture, i) => {
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
      floor.dataset.built = key;
    }
    if (!frame) return;
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

  function drawFrame(index) {
    const preview = fxState.preview;
    if (!preview) return;
    paintFloor($("fxFloor"), preview.fixtures,
               preview.frames[Math.min(index, preview.frames.length - 1)],
               "bench:" + preview.fixtures.length);
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
    putEffectInForm(preset.effect || {});
    $("fxPresetName").value = preset.name;
    $("fxStatus").textContent = "Loaded " + preset.name + ".";
  });

  $("btnFxAsk").addEventListener("click", async () => {
    const description = $("fxAsk").value.trim();
    const status = $("fxAskStatus");
    const button = $("btnFxAsk");
    if (!description) {
      status.textContent = "Say what you want the lights to do first.";
      return;
    }
    button.disabled = true;
    status.textContent = "Claude is writing it — this takes a few seconds…";
    try {
      const body = await post("api/effects/describe", { description });
      putEffectInForm(body.effect || {});
      status.textContent = "Written. Preview it, change anything, then save " +
        "it or drop it into a show — nothing has been saved yet.";
      // Straight to the preview: the whole question about a generated
      // effect is what it looks like, and making somebody find the button
      // is making them ask twice.
      $("btnFxPreview").click();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  $("fxAsk").addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("btnFxAsk").click();
  });

  // The one route from an effect object into the builder's form. Two
  // callers — a saved preset, and one Claude has just written — and a
  // second copy of "which control holds which key" is the drift that put
  // three quiet rewrites into the show editor's dialog.
  function putEffectInForm(effect) {
    const select = effect.select || {};
    $("fxType").value = effect.type;
    fxState.params = effect.params || {};
    renderFxParams();
    $("fxName").value = effect.name || "";
    $("fxOrder").value = effect.order || fxState.defaultOrder || "x";
    $("fxAlign").value = effect.align || "beat";
    $("fxRespectRoles").checked = effect.respect_roles !== false;
    // Ticks follow the ids the select resolves to; the select itself is
    // kept whole when it says anything the ticks cannot (a role, a zone,
    // an exclude), so previewing or saving does not quietly narrow it.
    const byRole = (f) => (select.roles || []).includes(f.role);
    const byZone = (f) => (select.zones || []).includes((f.zone || "").trim());
    const byId = (f) => (select.ids || []).includes(f.id);
    const named = (select.ids || []).length || (select.roles || []).length ||
      (select.zones || []).length;
    fxState.selection = new Set(
      fxState.fixtures
        .filter((f) => (named ? (byId(f) || byRole(f) || byZone(f)) : true))
        .filter((f) => !(select.exclude || []).includes(f.id))
        .map((f) => f.id));
    const idsOnly = !(select.roles || []).length &&
      !(select.zones || []).length && !(select.exclude || []).length;
    fxState.select = idsOnly ? null : select;
    renderFxFixtures();
    renderFxSelectNote();
  }

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
  // The show editor: the picture IS the interface
  //
  // One document, three views of it. `ed.script` is the show; the scene
  // blocks, the form rows and the Code textarea are all renderings of that
  // one object, and every edit goes through `edTouch()` so none of them can
  // drift from the other two. The preview is a fourth view, and it is the
  // honest one: it comes back from the server's own compiler walking the
  // script currently in hand, unsaved edits and all.
  // ------------------------------------------------------------------
  const ed = {
    hash: null, script: null, outline: null, timeline: null,
    window: null, fixtures: [], duration: 0, t: 0,
    playing: false, raf: null, lastTick: 0,
    fetching: false, wanted: null, outlineTimer: null,
    selected: null, editing: null, editingSelect: {}, editingOrder: false,
  };

  // How close to the end of the loaded window the playhead may get before
  // the next one is asked for. A second of slack is about six frames at
  // preview rate — enough for the request to land before the animation
  // reaches ground it has no frames for.
  const ED_WINDOW_SLACK_S = 1.0;

  // What an effect that names no travel order actually does. It comes off
  // the catalog rather than being written here: a second copy of the
  // compiler's default is a copy that silently rewrites shows once the two
  // disagree. The literal is only the value used before the catalog lands.
  function edDefaultOrder() {
    return fxState.defaultOrder || "x";
  }

  function edClock(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    return Math.floor(whole / 60) + ":" + String(whole % 60).padStart(2, "0");
  }

  function edHasWindow(t) {
    const w = ed.window;
    return Boolean(w) && t >= w.start_s &&
      t <= w.start_s + w.span_s - ED_WINDOW_SLACK_S;
  }

  function edFrameAt(t) {
    const w = ed.window;
    if (!w || !w.frames.length) return null;
    const index = Math.round((t - w.start_s) * w.fps);
    return w.frames[Math.max(0, Math.min(w.frames.length - 1, index))];
  }

  // The preview body. The script rides along on every request, which is
  // what makes this live: the server previews what is in the editor, not
  // what is on disk. Nothing here writes.
  function edBody(extra) {
    return Object.assign({ script: ed.script }, extra || {});
  }

  async function edFetchWindow(t) {
    if (!ed.hash || !ed.script) return;
    if (ed.fetching) { ed.wanted = t; return; }
    ed.fetching = true;
    try {
      const start = Math.max(0, t - 1);
      ed.window = await post("api/show/" + ed.hash + "/preview",
                             edBody({ start_s: start }));
      edStatus("");
    } catch (error) {
      // A script the compiler refuses is the most useful thing this can
      // say, and it says it here rather than at save — while you are still
      // looking at the effect you just changed.
      ed.window = null;
      edStatus(error.message, true);
    } finally {
      ed.fetching = false;
      const next = ed.wanted;
      ed.wanted = null;
      if (next !== null) await edFetchWindow(next);
      else edPaint();
    }
  }

  function edStatus(text, warn) {
    const box = $("edStatus");
    box.textContent = text || "";
    box.classList.toggle("warn", Boolean(warn));
  }

  function edPaint() {
    const frame = edFrameAt(ed.t);
    paintFloor($("edFloor"), ed.fixtures, frame, "show:" + ed.hash);
    $("edClock").textContent = edClock(ed.t) + " / " + edClock(ed.duration);
    const head = $("edHead");
    if (ed.duration > 0) {
      head.hidden = false;
      head.style.left = (ed.t / ed.duration * 100) + "%";
    } else {
      head.hidden = true;
    }
    const scrub = $("edScrub");
    if (document.activeElement !== scrub) {
      scrub.value = String(Math.round(
        ed.duration ? (ed.t / ed.duration) * 1000 : 0));
    }
  }

  function edSeek(t, fetchIfNeeded) {
    ed.t = Math.max(0, Math.min(t, ed.duration));
    edPaint();
    if (fetchIfNeeded !== false && !edHasWindow(ed.t)) edFetchWindow(ed.t);
  }

  function edPlay(on) {
    ed.playing = Boolean(on) && Boolean(ed.script);
    $("btnEdPlay").textContent = ed.playing ? "⏸ Pause" : "▶ Play";
    if (ed.raf) cancelAnimationFrame(ed.raf);
    if (!ed.playing) return;
    ed.lastTick = performance.now();
    const step = (now) => {
      if (!ed.playing) return;
      const delta = (now - ed.lastTick) / 1000;
      ed.lastTick = now;
      let t = ed.t + delta;
      if (t >= ed.duration) { t = 0; }
      ed.t = t;
      edPaint();
      // Ask for the next window a beat before running out of frames, so
      // the animation crosses the seam without stopping on it.
      if (!edHasWindow(ed.t) && !ed.fetching) edFetchWindow(ed.t);
      ed.raf = requestAnimationFrame(step);
    };
    ed.raf = requestAnimationFrame(step);
  }

  // -- the song: what the show is hung off ------------------------------
  //
  // Nothing in the panel used to show the music at all. A show is a list
  // of times, and the only way to know whether a drop landed on the drop
  // was to play it in a dark room and watch. The waveform is the missing
  // half of the picture: the shape of the track, the sections the analyser
  // found, the drops it marked, and the bar lines — so "why does nothing
  // happen for thirty seconds" is answerable by looking.
  //
  // Downbeats rather than every beat, deliberately. At 120bpm a four
  // minute track has 480 beats; drawn on a 900px canvas that is a grey
  // wash, not a grid. Bar lines are the ones a person can count against.
  async function edLoadWave(hash) {
    ed.wave = null;
    $("edWaveNote").textContent = "";
    edDrawWave();
    try {
      const body = await api("api/track/" + hash + "/waveform");
      ed.wave = body;
      const bits = [];
      if (body.bpm) bits.push(Math.round(body.bpm) + " bpm");
      if (body.sections.length) bits.push(body.sections.length + " sections");
      bits.push(body.drops.length
        ? body.drops.length + (body.drops.length === 1 ? " drop" : " drops")
        : "no drops found");
      $("edWaveNote").textContent = bits.join(" · ");
      edDrawWave();
    } catch (error) {
      // A track analysed before envelopes existed, whose file has since
      // moved, is the honest 409 here — say it rather than drawing a flat
      // line that reads as silence.
      $("edWaveNote").textContent = error.message;
    }
  }

  const SECTION_TINT = {
    intro: "rgba(120,160,255,0.13)", verse: "rgba(120,160,255,0.10)",
    build: "rgba(255,190,90,0.16)", chorus: "rgba(255,140,90,0.16)",
    peak: "rgba(255,110,90,0.20)", break: "rgba(140,140,160,0.10)",
    outro: "rgba(120,160,255,0.10)",
  };

  function edDrawWave() {
    paintWave($("edWave"), ed.wave, null, ed.duration);
  }

  // One painter for every picture of a song. The editor's playhead is a
  // DOM element riding over the canvas (it survives repaints); the party
  // has no overlay, so its playhead is drawn in when `playhead` is given.
  function paintWave(canvas, wave, playhead, fallbackDuration) {
    if (!canvas || !canvas.getContext) return;
    const width = canvas.clientWidth || 800;
    const height = canvas.clientHeight || 72;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!wave || !wave.envelope || !wave.envelope.length) return;
    const duration = wave.duration_s || fallbackDuration || 1;
    const at = (seconds) => (seconds / duration) * width;

    // Sections first: they are the ground everything else sits on.
    for (const section of wave.sections) {
      ctx.fillStyle = SECTION_TINT[section.kind] || "rgba(140,140,160,0.10)";
      ctx.fillRect(at(section.start), 0,
                   Math.max(1, at(section.end) - at(section.start)), height);
    }

    // Bar lines, under the audio so they never obscure its shape.
    ctx.strokeStyle = "rgba(160,160,180,0.22)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const beat of wave.downbeats) {
      const x = Math.round(at(beat)) + 0.5;
      ctx.moveTo(x, height - 10);
      ctx.lineTo(x, height);
    }
    ctx.stroke();

    // The audio, mirrored about the middle — the shape people recognise.
    const middle = height / 2;
    const columns = wave.envelope.length;
    const columnWidth = width / columns;
    ctx.fillStyle = "rgba(90,170,255,0.75)";
    for (let i = 0; i < columns; i += 1) {
      const peak = wave.envelope[i] * (height * 0.45);
      ctx.fillRect(i * columnWidth, middle - peak,
                   Math.max(1, columnWidth - 0.3), peak * 2);
    }

    // Drops last, over everything, because they are the thing you are
    // looking for when you look at this at all.
    for (const drop of wave.drops) {
      const x = Math.round(at(drop.t)) + 0.5;
      ctx.strokeStyle = "rgba(255,90,90,0.95)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }

    if (typeof playhead === "number") {
      const x = Math.round(playhead * width) + 0.5;
      ctx.strokeStyle = "rgba(255,255,255,0.9)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
  }

  // Clicking or dragging the song scrubs it, because a picture of a track
  // that you cannot put the playhead on is a picture and not a control.
  (function bindWaveScrub() {
    const canvas = $("edWave");
    if (!canvas) return;
    let dragging = false;
    const seekTo = (event) => {
      const box = canvas.getBoundingClientRect();
      if (!box.width || !ed.duration) return;
      const ratio = Math.min(1, Math.max(0,
        (event.clientX - box.left) / box.width));
      edSeek(ratio * ed.duration);
    };
    canvas.addEventListener("pointerdown", (event) => {
      dragging = true;
      canvas.setPointerCapture(event.pointerId);
      seekTo(event);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (dragging) seekTo(event);
    });
    const release = (event) => {
      if (!dragging) return;
      dragging = false;
      try { canvas.releasePointerCapture(event.pointerId); } catch (ignored) {}
    };
    canvas.addEventListener("pointerup", release);
    canvas.addEventListener("pointercancel", release);
  })();

  // -- the strip: the whole show, one row per light --------------------
  function edDrawStrip() {
    const canvas = $("edStrip");
    const outline = ed.outline;
    if (!canvas.getContext) return;
    const width = canvas.clientWidth || 800;
    const rows = (outline && outline.fixtures.length) || 1;
    const rowHeight = Math.max(6, Math.min(22, 132 / rows));
    // The backing store is scaled for the device's pixel ratio, and every
    // measurement of TIME reads the wrapper's CSS width instead — a canvas
    // twice as wide in device pixels is not twice as long a song.
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(rows * rowHeight * ratio);
    canvas.style.height = (rows * rowHeight) + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, rows * rowHeight);
    if (!outline || !outline.columns.length) return;
    const columnWidth = width / outline.columns.length;
    outline.columns.forEach((column, c) => {
      for (let r = 0; r < rows; r += 1) {
        const colour = column[r];
        if (!colour) continue;
        ctx.fillStyle = hsvCss(colour[0], colour[1], colour[2]);
        ctx.fillRect(c * columnWidth, r * rowHeight,
                     Math.ceil(columnWidth), rowHeight - 0.5);
      }
    });
  }

  function edRenderScenes() {
    const box = $("edScenes");
    box.innerHTML = "";
    const timeline = ed.timeline;
    if (!timeline || !ed.duration) return;
    for (const scene of timeline.scenes) {
      const block = document.createElement("button");
      block.type = "button";
      block.className = "ed-scene" +
        (ed.selected === scene.index ? " selected" : "");
      block.style.left = (scene.start / ed.duration * 100) + "%";
      block.style.width = Math.max(
        1, (scene.end - scene.start) / ed.duration * 100) + "%";
      block.textContent = scene.label;
      block.dataset.scene = String(scene.index);
      block.title = scene.label + " · " + edClock(scene.start) + "–" +
        edClock(scene.end);
      box.appendChild(block);
    }
    for (const moment of timeline.moments) {
      const mark = document.createElement("button");
      mark.type = "button";
      mark.className = "ed-moment";
      mark.style.left = (moment.t / ed.duration * 100) + "%";
      mark.textContent = "◆";
      mark.dataset.moment = String(moment.t);
      mark.title = moment.name + " at " + edClock(moment.t);
      box.appendChild(mark);
    }
  }

  // -- the script, as controls -----------------------------------------

  // What an effect owns, in words. The choreographer selects by ROLE for
  // almost everything it writes, so "all lights" was wrong on nearly every
  // row — and a row that misreads a selection is a row you edit by mistake.
  function edDescribeSelect(select) {
    const parts = [];
    const ids = (select || {}).ids || [];
    const roles = (select || {}).roles || [];
    const zones = (select || {}).zones || [];
    const exclude = (select || {}).exclude || [];
    if (ids.length) parts.push(ids.length + (ids.length === 1 ? " light" : " lights"));
    if (roles.length) parts.push(roles.join(", "));
    if (zones.length) parts.push(zones.join(", "));
    if (!parts.length) parts.push("all lights");
    if (exclude.length) parts.push("except " + exclude.length);
    return parts.join(" · ");
  }

  function edEffectsOf(scene) {
    if (!Array.isArray(scene.effects)) scene.effects = [];
    return scene.effects;
  }

  function edRenderScript() {
    const box = $("edScript");
    box.innerHTML = "";
    if (!ed.script) {
      box.innerHTML = '<p class="muted">Pick a track above to open its show.</p>';
      return;
    }
    const scenes = ed.script.scenes || [];
    scenes.forEach((scene, index) => {
      const block = document.createElement("div");
      block.className = "ed-block" + (ed.selected === index ? " selected" : "");
      block.dataset.scene = String(index);

      const head = document.createElement("div");
      head.className = "ed-block-head";
      const name = document.createElement("strong");
      name.textContent = scene.mood || scene.kind || ("scene " + index);
      const when = document.createElement("span");
      when.className = "ed-when";
      when.textContent = edClock(scene.start) + "–" + edClock(scene.end);
      const swatches = document.createElement("span");
      swatches.className = "ed-swatches";
      for (const entry of (scene.palette || []).slice(0, 6)) {
        const chip = document.createElement("span");
        chip.className = "ed-swatch";
        chip.style.background = hsvCss(entry[0], entry[1],
                                       scene.brightness || 0.6);
        swatches.appendChild(chip);
      }
      const jump = document.createElement("button");
      jump.className = "btn small";
      jump.dataset.act = "jump";
      jump.textContent = "Go to";
      const add = document.createElement("button");
      add.className = "btn small";
      add.dataset.act = "add";
      add.textContent = "+ Effect";
      head.append(name, when, swatches, jump, add);
      block.appendChild(head);

      const list = document.createElement("div");
      list.className = "ed-fx";
      const effects = edEffectsOf(scene);
      if (!effects.length) {
        const empty = document.createElement("div");
        empty.className = "ed-fx-row muted";
        empty.textContent = "No effects — this scene is the base wash only.";
        list.appendChild(empty);
      }
      effects.forEach((effect, position) => {
        const row = document.createElement("div");
        row.className = "ed-fx-row";
        row.dataset.fx = String(position);
        const label = document.createElement("span");
        label.textContent = (effect.name || effect.type) + " · " +
          effect.type + " · " + edDescribeSelect(effect.select) +
          (effect.order ? " · " + effect.order : "");
        const edit = document.createElement("button");
        edit.className = "btn small";
        edit.dataset.act = "edit";
        edit.textContent = "Edit";
        // Keeping an effect is how the library grows. An effect that
        // turned out well in one show is worth having in the next one,
        // and without this the only way back to it was to find the show
        // it was in and copy the JSON out by hand.
        const keep = document.createElement("button");
        keep.className = "btn small";
        keep.dataset.act = "keep";
        keep.textContent = "＋ Library";
        keep.setAttribute("aria-label", "Save this effect to the library");
        const drop = document.createElement("button");
        drop.className = "btn small";
        drop.dataset.act = "drop";
        drop.textContent = "✕";
        drop.setAttribute("aria-label", "Remove this effect");
        row.append(label, edit, keep, drop);
        list.appendChild(row);
      });
      block.appendChild(list);
      box.appendChild(block);
    });
  }

  // Every edit lands here: it refreshes the Code view, redraws the forms,
  // and asks the server what the show now looks like. One door, so the
  // three views cannot disagree and the preview is never of a show that
  // has been edited since.
  function edTouch() {
    $("scriptText").value = JSON.stringify(ed.script, null, 2);
    edRenderScript();
    edPaint();
    if (ed.outlineTimer) clearTimeout(ed.outlineTimer);
    ed.outlineTimer = setTimeout(() => {
      ed.outlineTimer = null;
      edRefreshOutline();
      edFetchWindow(ed.t);
    }, 250);
  }

  async function edRefreshOutline() {
    if (!ed.hash || !ed.script) return;
    try {
      const body = await post("api/show/" + ed.hash + "/outline", edBody({}));
      ed.outline = body;
      ed.timeline = body.timeline;
      ed.fixtures = body.fixtures || [];
      ed.duration = body.duration_s || 0;
      edDrawStrip();
      edDrawWave();
      edRenderScenes();
      edStatus("");
    } catch (error) {
      edStatus(error.message, true);
    }
  }

  // -- the effect dialog ------------------------------------------------
  async function edOpenEffect(where, effect) {
    await loadEffects();
    ed.editing = where;
    const spec = fxState.byType[effect.type] || fxState.catalog[0];
    $("edFxTitle").textContent = effect.name || effect.type || "Effect";
    const form = $("edFxForm");
    form.innerHTML = "";

    const grid = document.createElement("div");
    grid.className = "fx-params";
    grid.appendChild(edField("Name", edInput("text", effect.name || "")));
    const type = document.createElement("select");
    for (const entry of fxState.catalog) {
      const option = document.createElement("option");
      option.value = entry.type;
      option.textContent = entry.label;
      option.selected = entry.type === effect.type;
      type.appendChild(option);
    }
    type.id = "edFxType";
    grid.appendChild(edField("Type", type));
    const order = document.createElement("select");
    fillOptions(order, fxState.orders || []);
    // The compiler's own default, not a nice-looking one: an effect with no
    // `order` travels by x, so offering "listed" here would have turned
    // "across the room" into "in map order" on any edit that touched
    // nothing at all.
    order.value = effect.order || edDefaultOrder();
    order.id = "edFxOrder";
    grid.appendChild(edField("Travels", order));
    form.appendChild(grid);

    const blurb = document.createElement("p");
    blurb.className = "muted small";
    blurb.id = "edFxBlurb";
    blurb.textContent = spec ? spec.blurb : "";
    form.appendChild(blurb);

    const lights = document.createElement("div");
    lights.className = "fx-fixtures";
    lights.id = "edFxLights";
    form.appendChild(edLabelled("Lights this effect owns", lights));
    const chosen = new Set((effect.select || {}).ids || []);
    for (const fixture of fxState.fixtures) {
      const label = document.createElement("label");
      label.className = "fx-fixture";
      const tick = document.createElement("input");
      tick.type = "checkbox";
      tick.dataset.id = fixture.id;
      tick.checked = chosen.has(fixture.id);
      const text = document.createElement("span");
      text.textContent = fixture.label + " · " + fixture.role;
      label.append(tick, text);
      lights.appendChild(label);
    }
    const none = document.createElement("p");
    none.className = "muted small";
    none.textContent = "Nothing ticked anywhere means every light on the " +
      "map. Whatever this effect does not name is left exactly as it is.";
    form.appendChild(none);

    // Roles and zones, because that is how the automatic director selects
    // and an editor that could only tick individual bulbs would rewrite
    // "every candle" as "these four bulbs" the first time you opened it —
    // silently, and wrongly the moment a candle is added to the house.
    form.appendChild(edTickList("Or by role", "edFxRoles", fxState.roles,
                                (effect.select || {}).roles || []));
    form.appendChild(edTickList("Or by room", "edFxZones", fxState.zones,
                                (effect.select || {}).zones || []));
    ed.editingSelect = effect.select || {};
    ed.editingOrder = Boolean(effect.order);

    const params = document.createElement("div");
    params.className = "fx-params";
    params.id = "edFxParams";
    form.appendChild(params);
    renderParamControls(params, spec, effect.params || {});

    type.addEventListener("change", () => {
      const next = fxState.byType[type.value];
      $("edFxBlurb").textContent = next ? next.blurb : "";
      renderParamControls(params, next, {});
    });

    $("edFxModal").hidden = false;
  }

  function edField(name, control) {
    const label = document.createElement("label");
    label.className = "fx-param";
    const span = document.createElement("span");
    span.textContent = name;
    label.append(span, control);
    return label;
  }

  function edLabelled(name, node) {
    const wrap = document.createElement("div");
    const heading = document.createElement("p");
    heading.className = "muted small";
    heading.textContent = name;
    wrap.append(heading, node);
    return wrap;
  }

  function edInput(type, value) {
    const input = document.createElement("input");
    input.type = type;
    input.value = value;
    input.id = "edFxName";
    return input;
  }

  function edTicked(id) {
    return Array.from($(id).querySelectorAll("input:checked"))
      .map((input) => input.dataset.id);
  }

  function edTickList(title, id, values, chosen) {
    const box = document.createElement("div");
    box.className = "fx-fixtures";
    box.id = id;
    const picked = new Set(chosen);
    for (const value of values) {
      const label = document.createElement("label");
      label.className = "fx-fixture";
      const tick = document.createElement("input");
      tick.type = "checkbox";
      tick.dataset.id = value;
      tick.checked = picked.has(value);
      const text = document.createElement("span");
      text.textContent = value;
      label.append(tick, text);
      box.appendChild(label);
    }
    return edLabelled(title, box);
  }

  function edReadEffect() {
    const select = {};
    const ids = edTicked("edFxLights");
    const roles = edTicked("edFxRoles");
    const zones = edTicked("edFxZones");
    if (ids.length) select.ids = ids;
    if (roles.length) select.roles = roles;
    if (zones.length) select.zones = zones;
    // `exclude` has no control yet, so it is carried rather than dropped —
    // an editor may not quietly delete the half of a selection it cannot
    // draw.
    const exclude = (ed.editingSelect || {}).exclude;
    if (exclude && exclude.length) select.exclude = exclude;
    const effect = {
      type: $("edFxType").value,
      name: $("edFxName").value || $("edFxType").value,
      select,
      params: readParamControls($("edFxParams")),
    };
    // Only write `order` when it says something. Opening an effect and
    // pressing Apply must leave the file byte-identical — an editor that
    // sprinkles defaults through a document turns every visit into a diff.
    const order = $("edFxOrder").value;
    if (order !== edDefaultOrder() || ed.editingOrder) effect.order = order;
    return effect;
  }

  function edCloseModal() {
    $("edFxModal").hidden = true;
    ed.editing = null;
  }

  $("btnEdFxClose").addEventListener("click", edCloseModal);
  $("btnEdFxCancel").addEventListener("click", edCloseModal);
  $("edFxModal").addEventListener("click", (event) => {
    if (event.target === $("edFxModal")) edCloseModal();
  });

  $("btnEdFxApply").addEventListener("click", () => {
    const where = ed.editing;
    if (!where || !ed.script) return;
    const effect = edReadEffect();
    const scene = (ed.script.scenes || [])[where.scene];
    if (!scene) { edCloseModal(); return; }
    const effects = edEffectsOf(scene);
    if (where.index === null) effects.push(effect);
    else effects[where.index] = effect;
    edCloseModal();
    edTouch();
  });

  // -- wiring ------------------------------------------------------------
  $("btnEdPlay").addEventListener("click", () => edPlay(!ed.playing));

  $("edScrub").addEventListener("input", () => {
    if (!ed.duration) return;
    edPlay(false);
    edSeek(Number($("edScrub").value) / 1000 * ed.duration);
  });

  $("edScenes").addEventListener("click", (event) => {
    const scene = event.target.closest("[data-scene]");
    if (scene) {
      ed.selected = Number(scene.dataset.scene);
      const found = (ed.timeline.scenes || [])
        .find((s) => s.index === ed.selected);
      edRenderScenes();
      edRenderScript();
      if (found) { edPlay(false); edSeek(found.start); }
      return;
    }
    const moment = event.target.closest("[data-moment]");
    if (moment) { edPlay(false); edSeek(Number(moment.dataset.moment)); }
  });

  $("edScript").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button || !ed.script) return;
    const block = button.closest("[data-scene]");
    if (!block) return;
    const index = Number(block.dataset.scene);
    const scene = (ed.script.scenes || [])[index];
    if (!scene) return;
    const act = button.dataset.act;
    if (act === "jump") { edPlay(false); edSeek(Number(scene.start) || 0); return; }
    if (act === "add") {
      // No `order` on a new effect: it opens at whatever the compiler
      // would do with one that names none, and only carries the key if
      // you pick something else.
      edOpenEffect({ scene: index, index: null },
                   { type: "chase", name: "", params: {} });
      return;
    }
    const row = button.closest("[data-fx]");
    if (!row) return;
    const position = Number(row.dataset.fx);
    if (act === "edit") {
      edOpenEffect({ scene: index, index: position },
                   edEffectsOf(scene)[position] || {});
    } else if (act === "drop") {
      edEffectsOf(scene).splice(position, 1);
      edTouch();
    } else if (act === "keep") {
      edKeepEffect(edEffectsOf(scene)[position] || {});
    }
  });

  // Save one of a show's effects into the library.
  //
  // The name is asked for rather than taken from the effect, because an
  // effect's name is a cue label ("scene chorus") and a library entry is
  // something you will go looking for by name a month later. Saving over
  // an existing name is how you edit one — the same contract the builder's
  // Save has, so the two cannot disagree about what a name means.
  async function edKeepEffect(effect) {
    if (!effect || !effect.type) return;
    const suggested = effect.name || effect.type;
    const name = window.prompt(
      "Save this effect to the library as:", suggested);
    if (name === null) return;
    const status = $("scriptStatus");
    try {
      const body = await post("api/effects/preset", {
        name: name,
        effect: effect,
        note: "kept from " + ($("scriptWhich").textContent || "a show"),
      });
      status.textContent = 'Saved "' + body.preset.name +
        '" to the library — Claude can use it by name in the next show.';
      // The Effects tab's preset list is now out of date, so refresh it.
      // Called directly: it is a function declaration in this same scope,
      // so a `typeof` guard around it can never be false — and a guard
      // that cannot fail reads as "this might not exist", which sends the
      // next person looking for a case there isn't one of.
      loadEffects();
    } catch (error) {
      status.textContent = "could not save it: " + error.message;
    }
  }

  // The Code view is an editor, not a mirror: what is typed there is the
  // show as soon as it parses, and the forms above redraw from it. A
  // half-typed brace leaves the last good script alone and says so, rather
  // than blanking the editor somebody is in the middle of using.
  $("scriptText").addEventListener("change", () => {
    let parsed;
    try {
      parsed = JSON.parse($("scriptText").value);
    } catch (error) {
      edStatus("That is not valid JSON yet — " + error.message, true);
      return;
    }
    ed.script = parsed;
    edStatus("");
    edTouch();
  });

  // The strip is drawn from measured width, so it has to be redrawn when
  // the width changes — including when the tab it lives on is shown, since
  // a hidden pane measures zero.
  window.addEventListener("resize", () => {
    edDrawStrip();
    edDrawWave();
    edRenderScenes();
  });

  // ------------------------------------------------------------------
  // Shows: the script editor — the whole show, as the file it is
  // ------------------------------------------------------------------
  let scriptTrack = null;

  // Who wrote the show that is open, and what the writer was told.
  //
  // Both are fetched rather than remembered, because the editor opens
  // shows it did not compile — including ones from before any of this
  // existed, which is why a missing record is a sentence and not an error.
  async function loadDirectorReport(hash) {
    const line = $("scriptWho");
    line.textContent = "";
    try {
      line.textContent = describeDirector(await api(
        "api/show/" + hash + "/director"));
    } catch (error) {
      // A 404 here is the ordinary case for an older show, not a fault.
      line.textContent = "";
    }
  }

  async function loadDirectorPrompt(hash) {
    const box = $("promptText");
    box.textContent = "reading the brief…";
    try {
      const body = await api("api/show/" + hash + "/prompt");
      box.textContent = body.prompt;
      const summary = $("promptBox").querySelector("summary");
      summary.textContent = "What Claude is told about this track and your " +
        "room (" + body.fixtures + " lights, " +
        Math.round(body.chars / 1000) + "k characters)" +
        (body.available ? "" : " — brAIn is not installed, so nothing can " +
         "be sent");
    } catch (error) {
      box.textContent = error.message;
    }
  }

  async function openScript(hash, name) {
    scriptTrack = hash;
    const status = $("scriptStatus");
    status.textContent = "loading…";
    try {
      const body = await api("api/show/" + hash + "/script");
      $("scriptWhich").textContent = body.title +
        (body.file ? " · " + body.file : " · not compiled yet");
      loadDirectorReport(hash);
      loadDirectorPrompt(hash);
      edLoadWave(hash);
      $("scriptText").value = body.script
        ? JSON.stringify(body.script, null, 2)
        : "";
      renderScriptEffects(body);
      edPlay(false);
      ed.hash = hash;
      ed.script = body.script || null;
      ed.window = null;
      ed.selected = null;
      ed.t = 0;
      ed.duration = Number(body.duration_s) || 0;
      $("edFloor").dataset.built = "";
      edRenderScript();
      if (ed.script) {
        await edRefreshOutline();
        await edFetchWindow(0);
        edSeek(0, false);
      } else {
        ed.outline = null;
        ed.timeline = null;
        ed.fixtures = [];
        edDrawStrip();
      edDrawWave();
        edRenderScenes();
        edPaint();
      }
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
    // The Code view and the forms are the same document, and `change` has
    // already fired on the textarea by the time a click lands here — so
    // parsing it is both a validity check and the current script.
    ed.script = script;
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
      ed.script = body.script || null;
      edTouch();
      status.textContent = "Read from " + body.file + " and compiled: " +
        body.stats.cues + " cues.";
      loadShows();
    } catch (error) {
      status.textContent = error.message;
    }
  });

  // Notes to the director. The revised show comes back through openScript
  // so the strip, the forms and the Code view are all the new script —
  // a revision that only updated one of them would be three editors
  // disagreeing about which show is open.
  $("btnRevise").addEventListener("click", async () => {
    const status = $("reviseStatus");
    const button = $("btnRevise");
    if (!scriptTrack) {
      status.textContent = "Open a track's show first.";
      return;
    }
    const feedback = $("reviseText").value.trim();
    if (!feedback) {
      status.textContent = "Say what you want changed first.";
      return;
    }
    button.disabled = true;
    status.textContent = "Claude is revising the show — this can take a " +
      "couple of minutes…";
    try {
      const body = await post("api/show/" + scriptTrack + "/revise",
        { feedback });
      const took = body.director && body.director.seconds
        ? " in " + Math.round(body.director.seconds) + "s" : "";
      $("reviseText").value = "";
      await openScript(scriptTrack);
      status.textContent = "Revised" + took + " — " + body.stats.cues +
        " cues. The preview above is the new show.";
      loadShows();
    } catch (error) {
      status.textContent = "Not revised — " + error.message;
    } finally {
      button.disabled = false;
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
    // Synchronously, BEFORE any await: the playlist belongs to the party
    // being opened, and a Save pressed while the library fetch is still
    // in flight must write this party's tracks — not whatever the last
    // edited party left in the array. Names patch in when the fetch
    // lands; a track that has left the library keeps its hash prefix
    // rather than vanishing from the playlist it is in.
    pfPlaylist = ((party && party.tracks) || []).map((hash) => ({
      hash, name: hash.slice(0, 8) + "…",
    }));
    renderPfTracks();
    loadPfTrackPick().then(() => {
      const names = {};
      for (const option of $("pfTrackPick").options) {
        if (option.value) names[option.value] = option.dataset.name;
      }
      for (const track of pfPlaylist) {
        if (names[track.hash]) track.name = names[track.hash];
      }
      renderPfTracks();
    });
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

  // The playlist under construction: [{hash, name}], in play order.
  // Lives beside the form rather than in the DOM so reordering is an
  // array move and the list is simply repainted.
  let pfPlaylist = [];

  function renderPfTracks() {
    const box = $("pfTracks");
    box.innerHTML = "";
    if (!pfPlaylist.length) {
      box.innerHTML = '<p class="muted small">No playlist — the whole ' +
        "folder plays.</p>";
      return;
    }
    pfPlaylist.forEach((track, index) => {
      const row = document.createElement("div");
      row.className = "row";
      row.dataset.index = String(index);
      row.innerHTML = '<div class="row-main"><strong></strong></div>' +
        '<div class="row-actions">' +
        '<button class="btn small" data-act="up" aria-label="Earlier">↑</button>' +
        '<button class="btn small" data-act="down" aria-label="Later">↓</button>' +
        '<button class="btn small" data-act="out" aria-label="Remove">✕</button>' +
        "</div>";
      row.querySelector("strong").textContent =
        (index + 1) + ". " + track.name;
      box.appendChild(row);
    });
  }

  async function loadPfTrackPick() {
    const pick = $("pfTrackPick");
    try {
      const lib = await api("api/library");
      pick.innerHTML = '<option value="">— analyzed track —</option>';
      for (const track of (lib.tracks || []).filter((t) => t.analyzed)) {
        const option = document.createElement("option");
        option.value = track.hash;
        option.textContent = track.name;
        option.dataset.name = track.name;
        pick.appendChild(option);
      }
    } catch (error) {
      pick.innerHTML = '<option value="">failed: ' + error.message +
        "</option>";
    }
  }

  $("btnPfAddTrack").addEventListener("click", () => {
    const pick = $("pfTrackPick");
    if (!pick.value) return;
    // Building a playlist is choosing an order, so the first song added
    // turns Shuffle off where the person can SEE it happen — a default
    // that silently randomizes what they just ordered is the feature
    // contradicting itself. Re-ticking it afterwards is still honoured.
    if (!pfPlaylist.length) $("pfShuffle").checked = false;
    // The same song twice in a playlist is a choice, not a mistake.
    pfPlaylist.push({
      hash: pick.value,
      name: pick.selectedOptions[0].dataset.name || pick.value.slice(0, 8),
    });
    renderPfTracks();
  });

  $("pfTracks").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const index = Number(button.closest(".row").dataset.index);
    const act = button.dataset.act;
    if (act === "out") pfPlaylist.splice(index, 1);
    if (act === "up" && index > 0) {
      [pfPlaylist[index - 1], pfPlaylist[index]] =
        [pfPlaylist[index], pfPlaylist[index - 1]];
    }
    if (act === "down" && index < pfPlaylist.length - 1) {
      [pfPlaylist[index + 1], pfPlaylist[index]] =
        [pfPlaylist[index], pfPlaylist[index + 1]];
    }
    renderPfTracks();
  });

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
        tracks: pfPlaylist.map((track) => track.hash),
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
        status.textContent = "Party on: " + result.queue + " tracks queued." +
          ((result.skipped_tracks || []).length
            ? " Skipped (no longer analyzed): " +
              result.skipped_tracks.join(", ") + " — re-analyze from the " +
              "Library tab."
            : "");
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

  // The Lab is the tab the page opens on, so its choices load with it.
  loadSyncChoices();

  // Load each tab's data when it first opens.
  tabs.addEventListener("click", (event) => {
    const button = event.target.closest(".tab");
    if (!button) return;
    // The Library tab used to open empty and wait to be told to scan, so
    // every visit began by pressing a button to be shown the music that
    // was already there — which reads as "it forgot my library again",
    // and after an add-on restart that is exactly what it looks like.
    // Nothing was ever lost: the analysis has always been in /data. It
    // just was not asked for. Affordable to do on every open now that a
    // rescan is a stat per file rather than a megabyte read per file.
    if (button.dataset.tab === "library") scanLibrary();
    if (button.dataset.tab === "map") loadBulbCandidates();
    if (button.dataset.tab === "calibrate") {
      loadCalPlayers();
      loadProfiles();
    }
    if (button.dataset.tab === "lab") loadSyncChoices();
    if (button.dataset.tab === "effects") {
      loadEffects();
      loadFxShowTracks();
    }
    if (button.dataset.tab === "party") {
      loadParties();
      loadPartyPlayers();
    }
  });
})();
