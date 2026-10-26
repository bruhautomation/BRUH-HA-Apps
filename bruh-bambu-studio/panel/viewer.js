// The Design tab's 3D view. An ES module on top of three.js, which the
// image vendors (see the Dockerfile) so nothing is fetched from the
// internet at runtime. Parts are modelled Z-up, as they print; three.js is
// Y-up, so the camera is told Z is up and every number shown is the part's
// own millimetres in its own axes.
//
// The camera moves the way Fusion 360's does (FusionCamera below): a
// turntable about a fixed Z-up axis, so it never flips over the top; a turn
// about the point under the pointer; a slide; and a zoom toward the point
// under the pointer, never toward the middle. Named views and Home move
// there rather than jumping, and frame the whole part.
import * as THREE from "three";
import { STLLoader } from "./vendor/STLLoader.js";

const PALETTE = [0x1e9fe0, 0xf2a33a, 0x4cc38a, 0xe0569b, 0x9b7bf2, 0xd6d6d6];
const PLATE = 256;

// Filament names CSS has no word for. Anything else a person might say
// ("white", "matte black", "#ff8800", "Bambu PLA Basic Jade White") is
// read by the browser's own colour parser, last word first.
const FILAMENT_WORDS = {
  natural: "#efe6cf", clear: "#d8e6ee", transparent: "#d8e6ee", translucent: "#d8e6ee",
  jade: "#e8f0e6", cream: "#f3ead3", charcoal: "#3a3d40", graphite: "#4a4d50",
  "space gray": "#5b5f63", "space grey": "#5b5f63", "bambu green": "#00ae42",
};
const SEE_THROUGH = /\b(clear|transparent|translucent)\b/i;
const NOISE = /\b(matte|matt|silk|basic|glossy|metallic|pla|petg|abs|asa|tpu|pa|pc|cf|hf|bambu|filament)\b/gi;
const probe = document.createElement("canvas").getContext("2d");

// A fresh style object takes a colour the browser can read and stays empty
// for one it cannot; the canvas then turns what it took into #rrggbb.
function cssColour(word) {
  const text = String(word || "").trim();
  if (!text) return null;
  const style = document.createElement("i").style;
  style.color = text;
  if (!style.color) return null;
  probe.fillStyle = style.color;
  return probe.fillStyle;
}

/** "#rrggbb"-ish for a colour as a person or brAIn wrote it, or null. */
export function filamentColour(text) {
  const raw = String(text || "").trim().toLowerCase();
  if (!raw) return null;
  if (FILAMENT_WORDS[raw]) return FILAMENT_WORDS[raw];
  const direct = cssColour(raw);
  if (direct) return direct;
  const words = raw.replace(NOISE, " ").split(/[\s,/_-]+/).filter(Boolean);
  for (let n = words.length; n >= 1; n--) {
    for (let i = words.length - n; i >= 0; i--) {
      const phrase = words.slice(i, i + n).join(" ");
      const hit = FILAMENT_WORDS[phrase] || cssColour(phrase.replace(/ /g, ""));
      if (hit) return hit;
    }
  }
  return null;
}

const EL_MAX = Math.PI / 2 - 0.009;  // just short of straight down: no flip
const VIEWS = {  // azimuth about Z from +X, elevation from the bed
  iso: [-50, 30], home: [-50, 30], top: [-90, 90], front: [-90, 0], right: [0, 0],
  back: [90, 0], left: [180, 0], bottom: [-90, -90],
};
const TURN_PER_PX = 0.0085;
const ZOOM_PER_WHEEL = 0.0015;

/** A turntable camera with Fusion 360's mouse map and touch gestures. */
class FusionCamera {
  constructor(camera, dom, pick) {
    this.camera = camera;
    this.dom = dom;
    this.pick = pick;  // (clientX, clientY) -> a point on the part, or null
    this.goal = { target: new THREE.Vector3(), dist: 200, az: -0.87, el: 0.52 };
    this.cur = { target: new THREE.Vector3(), dist: 200, az: -0.87, el: 0.52 };
    this.rate = 22;  // how fast the camera catches up: smooth, not floaty
    this.limits = [1, 5000];
    this.pointers = new Map();
    this.mode = null;
    const on = (type, fn, opts) => dom.addEventListener(type, fn, opts);
    on("pointerdown", (e) => this._down(e));
    on("pointermove", (e) => this._move(e));
    on("pointerup", (e) => this._up(e));
    on("pointercancel", (e) => this._up(e));
    on("wheel", (e) => this._wheel(e), { passive: false });
    on("contextmenu", (e) => e.preventDefault());
    // A middle press would start the browser's autoscroll.
    on("mousedown", (e) => { if (e.button === 1) e.preventDefault(); });
  }

  _dir(az, el) {
    return new THREE.Vector3(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el));
  }

  _basis(state = this.goal) {
    const back = this._dir(state.az, state.el);
    const right = new THREE.Vector3(-Math.sin(state.az), Math.cos(state.az), 0);
    const up = new THREE.Vector3().crossVectors(back, right).negate();
    return { back, right, up };
  }

  /** World millimetres per screen pixel at the target's depth. */
  _perPixel() {
    const h = this.dom.clientHeight || 300;
    return (2 * this.goal.dist * Math.tan((this.camera.fov * Math.PI) / 360)) / h;
  }

  _ray(clientX, clientY) {
    const rect = this.dom.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    return ray;
  }

  /** The point under the pointer: on the part if it is there, else on the
   * plane through the target facing the camera. */
  pointAt(clientX, clientY) {
    const hit = this.pick(clientX, clientY);
    if (hit) return hit;
    const ray = this._ray(clientX, clientY).ray;
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(
      this.camera.getWorldDirection(new THREE.Vector3()), this.cur.target);
    return ray.intersectPlane(plane, new THREE.Vector3()) || this.cur.target.clone();
  }

  /** Turn by (dAz, dEl) about a pivot, keeping the turntable's Z up. */
  turn(dAz, dEl, pivot) {
    const g = this.goal;
    const el = Math.max(-EL_MAX, Math.min(EL_MAX, g.el + dEl));
    dEl = el - g.el;
    if (pivot) {
      const { right } = this._basis(g);
      const offset = g.target.clone().sub(pivot);
      offset.applyAxisAngle(right, -dEl);
      offset.applyAxisAngle(new THREE.Vector3(0, 0, 1), dAz);
      g.target.copy(pivot).add(offset);
    }
    g.az += dAz;
    g.el = el;
  }

  slide(dx, dy) {
    const { right, up } = this._basis(this.goal);
    const k = this._perPixel();
    this.goal.target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
  }

  /** Zoom by `factor` (under 1 is closer) toward a world point. */
  zoom(factor, toward) {
    const g = this.goal;
    const dist = Math.max(this.limits[0], Math.min(this.limits[1], g.dist * factor));
    const f = dist / g.dist;
    if (toward) g.target.sub(toward).multiplyScalar(f).add(toward);
    g.dist = dist;
  }

  /** Move to these angles (radians) and frame a box. */
  frame(box, az, el, instant = false) {
    const centre = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 5);
    const aspect = this.camera.aspect || 1;
    const vfov = (this.camera.fov * Math.PI) / 180;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
    const dist = (radius / Math.sin(Math.min(vfov, hfov) / 2)) * 1.05;
    this.limits = [radius * 0.05, radius * 60];
    const g = this.goal;
    g.target.copy(centre);
    g.dist = dist;
    // The shorter way round to the new azimuth.
    const twoPi = Math.PI * 2;
    g.az = this.cur.az + ((((az - this.cur.az) % twoPi) + twoPi + Math.PI) % twoPi) - Math.PI;
    g.el = Math.max(-EL_MAX, Math.min(EL_MAX, el));
    if (instant) this._snap();
  }

  _snap() {
    this.cur.target.copy(this.goal.target);
    Object.assign(this.cur, { dist: this.goal.dist, az: this.goal.az, el: this.goal.el });
  }

  get settled() {
    const c = this.cur, g = this.goal;
    return Math.abs(c.az - g.az) < 1e-4 && Math.abs(c.el - g.el) < 1e-4
      && Math.abs(c.dist - g.dist) < g.dist * 1e-4 && c.target.distanceTo(g.target) < g.dist * 1e-4;
  }

  update(dt) {
    const k = 1 - Math.exp(-dt * this.rate);
    const c = this.cur, g = this.goal;
    if (this.settled) this._snap();
    else {
      c.az += (g.az - c.az) * k;
      c.el += (g.el - c.el) * k;
      c.dist *= Math.pow(g.dist / c.dist, k);
      c.target.lerp(g.target, k);
    }
    const pos = c.target.clone().addScaledVector(this._dir(c.az, c.el), c.dist);
    this.camera.position.copy(pos);
    this.camera.up.set(0, 0, 1);
    this.camera.lookAt(c.target);
    this.camera.near = Math.max(0.01, c.dist / 200);
    this.camera.far = c.dist * 50 + 2000;
    this.camera.updateProjectionMatrix();
  }

  // -- pointers: Fusion's map --------------------------------------------
  _down(e) {
    this.dom.setPointerCapture?.(e.pointerId);
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, button: e.button });
    this.rate = 30;
    if (this.pointers.size === 2) { this.mode = "pinch"; this._pinch = this._twoFinger(); return; }
    if (e.pointerType === "touch") { this.mode = "turn"; }
    else if (e.button === 2 || (e.button === 1 && !e.shiftKey)) this.mode = "slide";
    else this.mode = "turn";  // left drag, or Shift + middle drag
    // A turn goes about the point under the pointer when it is on the part,
    // else about the part's own centre.
    this.pivot = this.mode === "turn" ? (this.pick(e.clientX, e.clientY) || this.goal.target.clone()) : null;
  }

  _twoFinger() {
    const [a, b] = [...this.pointers.values()];
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, span: Math.hypot(a.x - b.x, a.y - b.y) || 1 };
  }

  _move(e) {
    const p = this.pointers.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    if (this.mode === "pinch") {
      if (this.pointers.size < 2) return;
      const now = this._twoFinger();
      this.slide(now.x - this._pinch.x, now.y - this._pinch.y);
      if (Math.abs(now.span - this._pinch.span) > 0.5) {
        this.zoom(this._pinch.span / now.span, this.pointAt(now.x, now.y));
      }
      this._pinch = now;
    } else if (this.mode === "turn") {
      this.turn(-dx * TURN_PER_PX, dy * TURN_PER_PX, this.pivot);
    } else if (this.mode === "slide") {
      this.slide(dx, dy);
    }
  }

  _up(e) {
    this.pointers.delete(e.pointerId);
    if (this.pointers.size === 0) { this.mode = null; this.rate = 22; }
    else if (this.mode === "pinch") this.mode = "settle";  // one finger left: not a turn
  }

  _wheel(e) {
    e.preventDefault();
    const step = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
    this.zoom(Math.exp(step * ZOOM_PER_WHEEL), this.pointAt(e.clientX, e.clientY));
  }
}

export class Viewer {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 5000);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    container.append(this.renderer.domElement);
    // Z-up: the part's bed is the XY plane, as it prints.
    this.camera.up.set(0, 0, 1);
    this.raycaster = new THREE.Raycaster();
    this.controls = new FusionCamera(this.camera, this.renderer.domElement, (x, y) => this._hit(x, y));
    // A white part has to read as white: its lit face near full white,
    // its other faces a step down each, so the shape still shows. A key
    // light from the front-top and a weaker fill from behind, over a sky.
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a96a2, 1.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.9);
    sun.position.set(120, -160, 260);
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xffffff, 0.7);
    fill.position.set(-160, 140, 90);
    this.scene.add(fill);
    this.bed = this._bed();
    this.scene.add(this.bed);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.marks = new THREE.Group();
    this.scene.add(this.marks);
    this.measuring = false;
    this.points = [];
    this.onMeasure = null;
    this.renderer.domElement.addEventListener("pointerdown", (e) => { this._down = [e.clientX, e.clientY]; });
    this.renderer.domElement.addEventListener("click", (e) => this._click(e));
    this.renderer.domElement.addEventListener("dblclick", (e) => this._recentre(e));
    this._resize = new ResizeObserver(() => this.resize());
    this._resize.observe(container);
    this.resize();
    let last = performance.now();
    const loop = (now) => {
      this._frame = requestAnimationFrame(loop);
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      this.controls.update(dt);
      this.renderer.render(this.scene, this.camera);
    };
    loop(last);
  }

  // The printer's bed: a dark plate with a 10 mm grid and a lighter rim,
  // under the part, so "how big is it" has something to read against.
  _bed() {
    const bed = new THREE.Group();
    bed.name = "bed";
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(PLATE, PLATE),
      new THREE.MeshStandardMaterial({ color: 0x27313b, roughness: 0.9, metalness: 0,
        transparent: true, opacity: 0.92, side: THREE.DoubleSide }));
    plate.position.z = -0.05;
    plate.name = "plate";
    bed.add(plate);
    const grid = new THREE.GridHelper(PLATE, PLATE / 10, 0x8193a2, 0x3b4955);
    grid.rotation.x = Math.PI / 2;
    grid.material.transparent = true;
    grid.material.opacity = 0.55;
    bed.add(grid);
    const half = PLATE / 2;
    const rim = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-half, -half, 0), new THREE.Vector3(half, -half, 0),
      new THREE.Vector3(half, half, 0), new THREE.Vector3(-half, half, 0)]),
    new THREE.LineBasicMaterial({ color: 0xb9c7d3 }));
    bed.add(rim);
    return bed;
  }

  resize() {
    const w = this.container.clientWidth || 300;
    const h = this.container.clientHeight || 300;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _hit(clientX, clientY) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.group.children.filter((m) => m.visible), false)[0];
    return hit ? hit.point.clone() : null;
  }

  // A double click (or tap) on the part makes that point the middle.
  _recentre(e) {
    if (this.measuring) return;
    const hit = this._hit(e.clientX, e.clientY);
    if (hit) this.controls.goal.target.copy(hit);
  }

  // -- read back, for the measure and for anybody debugging a view --------
  cameraState() {
    const g = this.controls.cur;
    const round = (v) => Math.round(v * 1e4) / 1e4;
    return { az: round(g.az), el: round(g.el), distance: round(g.dist),
      target: g.target.toArray().map(round), up: this.camera.up.toArray().map(round),
      position: this.camera.position.toArray().map(round) };
  }

  pointAt(clientX, clientY) { return this.controls.pointAt(clientX, clientY).toArray(); }

  screenOf(point) {
    this.camera.updateMatrixWorld();
    const v = new THREE.Vector3(...point).project(this.camera);
    const rect = this.renderer.domElement.getBoundingClientRect();
    return [rect.left + ((v.x + 1) / 2) * rect.width, rect.top + ((1 - v.y) / 2) * rect.height];
  }

  /** How far the part's box reaches toward the view's edges (1 = the edge). */
  boxOnScreen() {
    if (!this.box || this.box.isEmpty()) return { max: 0 };
    this.camera.updateMatrixWorld();
    let max = 0;
    const { min, max: hi } = this.box;
    for (const x of [min.x, hi.x]) for (const y of [min.y, hi.y]) for (const z of [min.z, hi.z]) {
      const v = new THREE.Vector3(x, y, z).project(this.camera);
      max = Math.max(max, Math.abs(v.x), Math.abs(v.y));
    }
    return { max };
  }

  /** Resolves once the camera has caught up with where it was sent. */
  settled() {
    return new Promise((resolve) => {
      const check = () => (this.controls.settled && !this.controls.mode ? resolve(true) : requestAnimationFrame(check));
      requestAnimationFrame(() => requestAnimationFrame(check));
    });
  }

  async load(bodies) {
    this.clearMeasure();
    this.group.clear();
    const loader = new STLLoader();
    const loaded = await Promise.all(bodies.map(async (body, i) => {
      const geometry = await loader.loadAsync(body.url);
      geometry.computeVertexNormals();
      const hex = filamentColour(body.color);
      const colour = new THREE.Color(hex || PALETTE[i % PALETTE.length]);
      const clear = SEE_THROUGH.test(String(body.color || ""));
      const material = new THREE.MeshStandardMaterial({
        color: colour, metalness: 0, roughness: 0.6,
        transparent: clear, opacity: clear ? 0.55 : 1 });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.name = body.name;
      // Creases drawn faintly in a contrasting shade, so a white part on a
      // light screen and a black one on a dark screen both keep an outline.
      const light = colour.r * 0.3 + colour.g * 0.59 + colour.b * 0.11 > 0.5;
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 28),
        new THREE.LineBasicMaterial({ color: light ? 0x2b3640 : 0xc9d4dd, transparent: true, opacity: 0.35 }));
      edges.name = "edges";
      mesh.add(edges);
      this.group.add(mesh);
      return mesh;
    }));
    this.box = new THREE.Box3().setFromObject(this.group);
    // The bed sits under the part, centred on it.
    const centre = this.box.getCenter(new THREE.Vector3());
    this.bed.position.set(centre.x, centre.y, this.box.min.z);
    this.view("home", true);
    return loaded.map((m) => m.name);
  }

  size() {
    if (!this.box || this.box.isEmpty()) return null;
    const s = this.box.getSize(new THREE.Vector3());
    return [s.x, s.y, s.z];
  }

  /** Home, Fit or a named view; each moves there and frames the whole part. */
  view(which, instant = false) {
    if (!this.box || this.box.isEmpty()) return;
    const c = this.controls.goal;
    const [az, el] = which === "fit" ? [c.az, c.el]
      : (VIEWS[which] || VIEWS.iso).map((deg) => (deg * Math.PI) / 180);
    this.controls.frame(this.box, az, el, instant);
  }

  setWireframe(on) {
    this.group.children.forEach((m) => {
      m.material.wireframe = on;
      const edges = m.getObjectByName("edges");
      if (edges) edges.visible = !on;
    });
  }

  setVisible(name, on) {
    const mesh = this.group.getObjectByName(name);
    if (mesh) mesh.visible = on;
  }

  setMeasuring(on) {
    this.measuring = on;
    if (!on) this.clearMeasure();
  }

  clearMeasure() {
    this.points = [];
    this.marks.clear();
    if (this.onMeasure) this.onMeasure(null);
  }

  _click(e) {
    if (!this.measuring || !this._down) return;
    // A drag is the camera moving, not a point being picked.
    if (Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) > 4) return;
    const point = this._hit(e.clientX, e.clientY);
    if (!point) return;
    const hit = { point };
    if (this.points.length === 2) this.clearMeasure();
    this.points.push(hit.point.clone());
    const r = Math.max((this.size() || [10])[0] / 120, 0.4);
    const dot = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0xffd23f, depthTest: false }));
    dot.position.copy(hit.point);
    dot.renderOrder = 10;
    this.marks.add(dot);
    if (this.points.length === 2) {
      const [a, b] = this.points;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]),
        new THREE.LineBasicMaterial({ color: 0xffd23f, depthTest: false }));
      line.renderOrder = 10;
      this.marks.add(line);
      if (this.onMeasure) {
        this.onMeasure({ distance: a.distanceTo(b), dx: Math.abs(b.x - a.x),
          dy: Math.abs(b.y - a.y), dz: Math.abs(b.z - a.z) });
      }
    } else if (this.onMeasure) {
      this.onMeasure({ first: true });
    }
  }

  snapshot() {
    this.renderer.render(this.scene, this.camera);
    return new Promise((resolve) => this.renderer.domElement.toBlob(resolve, "image/png"));
  }

  dispose() {
    cancelAnimationFrame(this._frame);
    this._resize.disconnect();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

window.BambuViewer = Viewer;
window.bambuFilamentColour = filamentColour;
window.dispatchEvent(new Event("bambu-viewer-ready"));
