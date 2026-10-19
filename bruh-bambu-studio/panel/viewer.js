// The Design tab's 3D view. An ES module on top of three.js, which the
// image vendors (see the Dockerfile) so nothing is fetched from the
// internet at runtime. Parts are modelled Z-up, as they print; three.js is
// Y-up, so the model is turned once and every number shown is the part's
// own millimetres in its own axes.
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
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

export class Viewer {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 5000);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    container.append(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    // Z-up: the part's bed is the XY plane, as it prints.
    this.camera.up.set(0, 0, 1);
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
    const grid = new THREE.GridHelper(PLATE, PLATE / 10, 0x6f7e8a, 0x2c3a46);
    grid.rotation.x = Math.PI / 2;
    grid.material.transparent = true;
    grid.material.opacity = 0.5;
    this.scene.add(grid);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.marks = new THREE.Group();
    this.scene.add(this.marks);
    this.measuring = false;
    this.points = [];
    this.raycaster = new THREE.Raycaster();
    this.onMeasure = null;
    this.renderer.domElement.addEventListener("pointerdown", (e) => { this._down = [e.clientX, e.clientY]; });
    // `click`, not `pointerup`: OrbitControls captures the pointer, and a
    // captured pointerup never reaches a second listener.
    this.renderer.domElement.addEventListener("click", (e) => this._click(e));
    this._resize = new ResizeObserver(() => this.resize());
    this._resize.observe(container);
    this.resize();
    const loop = () => {
      this._frame = requestAnimationFrame(loop);
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    loop();
  }

  resize() {
    const w = this.container.clientWidth || 300;
    const h = this.container.clientHeight || 300;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
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
    this.view("iso");
    return loaded.map((m) => m.name);
  }

  size() {
    if (!this.box || this.box.isEmpty()) return null;
    const s = this.box.getSize(new THREE.Vector3());
    return [s.x, s.y, s.z];
  }

  view(which) {
    if (!this.box || this.box.isEmpty()) return;
    const centre = this.box.getCenter(new THREE.Vector3());
    const radius = Math.max(this.box.getSize(new THREE.Vector3()).length() / 2, 5);
    const d = radius / Math.sin((this.camera.fov * Math.PI) / 360) * 1.1;
    const dirs = { iso: [1, -1.2, 0.9], top: [0, -0.0001, 1], front: [0, -1, 0], right: [1, 0, 0] };
    const v = new THREE.Vector3(...(dirs[which] || dirs.iso)).normalize().multiplyScalar(d);
    this.camera.position.copy(centre.clone().add(v));
    this.camera.near = d / 100;
    this.camera.far = d * 20;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(centre);
    this.controls.update();
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
    this.controls.enableRotate = true;
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
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.group.children.filter((m) => m.visible), false)[0];
    if (!hit) return;
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
