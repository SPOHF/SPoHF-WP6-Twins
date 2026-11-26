// The greenhouse in three.js: geometry built once, then driven by one
// 15-minute step of /greenhouse/api/day at a time. Nothing here computes
// physics — vents, screen, lamps, pipe colour and vapour only *show* what the
// server measured and balanced.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// A glasshouse of 4 m spans, rows running north-south (along z).
const SPAN = 4, NSPAN = 8, W = SPAN * NSPAN, L = 36;
const GUTTER = 6.0, RIDGE = 6.85, SCREEN_Y = 5.75, LAMP_Y = 5.25;
const ROW_PITCH = 1.6, NROW = 20, PLANT_PITCH = 0.62;
const X0 = -W / 2, Z0 = -L / 2;
// Where the climate computer measures: its box hangs in a path, the scale
// carries one gutter section next to it. LetsGrow does not log the spot, so
// it is drawn mid-house; the ring's radius is an illustration, not a measured
// representativeness.
const ZONE = { x: 1.6, z: 0, r: 4.5 };
// Where the row of multi-height sensors is drawn: centred in a path four rows
// from the measuring box (along the rows), or across the rows at MICRO.z. Like
// ZONE, a drawing position: the site has not said where the row hangs. The
// spacing and heights along it are the configured metres.
// ``band`` is how far either side of the row the microclimate is drawn: the two
// crop rows that flank it.
const MICRO = { x: ZONE.x - 4 * ROW_PITCH, z: -6, band: 1.6 };
// The fog around that row: particles per m³ of the band, their size (m) and
// opacity. Dense enough to read as a volume, thin enough to see the crop in it.
const FOG_PER_M3 = 55, FOG_SIZE = 0.85, FOG_OPACITY = 0.9;
// Share of a faded plant's pixels that stay: enough to see where it stands,
// few enough that rows of faded crop between the eye and the subject stay clear.
const GHOST_KEEP = 0.07;


function seeded(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

// Pipe colour: cool steel at air temperature, glowing orange-red when hot.
function pipeColour(tempC, airC) {
  const t = Math.max(0, Math.min(1, ((tempC ?? airC ?? 20) - (airC ?? 20)) / 55));
  const c = new THREE.Color().setHSL(0.6 - 0.6 * t, 0.15 + 0.75 * t, 0.42 + 0.1 * t);
  return { colour: c, glow: t };
}

export class GreenhouseScene {
  // names: the parts' display names in the page's language, by component id
  constructor(container, { names = {}, onPick, onHover } = {}) {
    this.container = container;
    this.names = names;
    this.onPick = onPick || (() => {});
    this.onHover = onHover || (() => {});
    this.pickables = [];
    this.parts = {};          // component -> { materials:[...], objects:[...] }
    this.layers = { vapour: true, labels: true, roof: true, flows: true };
    // Which crop a view is about, shared by every crop material (see _focused):
    // the measuring box's ring (x, z, radius, on while the box is selected) and
    // the multi-height sensors' row (on, axis 0: along z / 1: along x, where it
    // sits across, the band's half-width).
    this.focusU = {
      uGhZone: { value: new THREE.Vector4(ZONE.x, ZONE.z, ZONE.r, 0) },
      uGhMicro: { value: new THREE.Vector4(0, 0, 0, MICRO.band) },
    };
    this.selected = null;
    this.clock = new THREE.Clock();
    this.state = { vent: 0, ventWindSide: 1, ventLee: 0, ventWind: 0, lamps: 0, screen: 0,
                   transpiration: 0.05, airExchange: 0.002, wind: 0, windDir: 270 };

    this._initRenderer();
    this._initWorld();
    this._buildStructure();
    this._buildCrop();
    this._buildSubstrate();
    this._buildPipes();
    this._buildLamps();
    this._buildScreen();
    this._buildVents();
    this._buildSensors();
    this._buildWeather();
    this._buildVapour();
    this._buildFlows();
    this._buildLabels();
    this._bindEvents();
    this._resize();
    this.renderer.setAnimationLoop(() => this._frame());
  }

  // ---------------------------------------------------------------- setup
  _initRenderer() {
    const r = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    r.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 0.55;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(r.domElement);
    this.renderer = r;

    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.className = 'gh-labels';
    this.container.appendChild(this.labelRenderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 4000);
    this.camera.position.set(27, 10.5, 31);
    this.controls = new OrbitControls(this.camera, r.domElement);
    this.controls.target.set(0, 2.6, 3);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.minDistance = 6;
    this.controls.maxDistance = 120;

    const pmrem = new THREE.PMREMGenerator(r);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.35;

    this.composer = new EffectComposer(r);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.5, 0.82);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
  }

  _initWorld() {
    const sky = new Sky();
    sky.scale.setScalar(3500);
    const u = sky.material.uniforms;
    u.turbidity.value = 6; u.rayleigh.value = 1.6; u.mieCoefficient.value = 0.004;
    u.mieDirectionalG.value = 0.8;
    this.sky = sky;
    this.scene.add(sky);

    this.sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const sc = this.sun.shadow.camera;
    sc.left = -30; sc.right = 30; sc.top = 30; sc.bottom = -30; sc.near = 1; sc.far = 220;
    this.sun.shadow.bias = -0.0004;
    this.scene.add(this.sun, this.sun.target);

    this.hemi = new THREE.HemisphereLight(0xbfd7ff, 0x3a4a2a, 0.6);
    this.scene.add(this.hemi);

    // the lamps' own light: a magenta wash from above, scaled by lamp share
    this.lampLight = new THREE.DirectionalLight(0xff6ab8, 0);
    this.lampLight.position.set(0, 30, 0);
    this.scene.add(this.lampLight);

    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(900, 64),
      new THREE.MeshStandardMaterial({ color: 0x4d6a35, roughness: 1 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    ground.receiveShadow = true;
    this.scene.add(ground);
    this.scene.fog = new THREE.Fog(0x9fb4c8, 260, 1200);

    // night sky: stars fade in below the horizon
    const starGeo = new THREE.BufferGeometry();
    const rnd = seeded(7), pos = [];
    for (let i = 0; i < 1400; i++) {
      const th = rnd() * Math.PI * 2, ph = Math.acos(rnd() * 0.95);
      pos.push(1500 * Math.sin(ph) * Math.cos(th), 1500 * Math.cos(ph), 1500 * Math.sin(ph) * Math.sin(th));
    }
    starGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    this.stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
      color: 0xffffff, size: 2.2, sizeAttenuation: false, transparent: true, opacity: 0, fog: false,
    }));
    this.scene.add(this.stars);
  }

  _part(name) {
    if (!this.parts[name]) this.parts[name] = { materials: [], objects: [] };
    return this.parts[name];
  }

  _pickable(obj, name) {
    obj.userData.component = name;
    this.pickables.push(obj);
    this._part(name).objects.push(obj);
    if (obj.material && !this._part(name).materials.includes(obj.material)) {
      this._part(name).materials.push(obj.material);
    }
    return obj;
  }

  // A crop material that fades to a ghost when a view is about other crop: the
  // crop beyond the measuring box's ring while the box is selected, the crop
  // away from the multi-height sensors' row in microclimate mode. Otherwise it
  // is drawn as it is. A fixed share of its pixels is kept rather than blended,
  // which keeps depth right without sorting thousands of instanced leaves.
  _focused(mat) {
    mat.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, this.focusU);
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nvarying vec3 vGhPos;')
        .replace('#include <project_vertex>', `#include <project_vertex>
          vec4 ghP = vec4(transformed, 1.0);
          #ifdef USE_INSTANCING
            ghP = instanceMatrix * ghP;
          #endif
          vGhPos = (modelMatrix * ghP).xyz;`);
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>
          varying vec3 vGhPos;
          uniform vec4 uGhZone;
          uniform vec4 uGhMicro;
`)
        .replace('#include <clipping_planes_fragment>', `#include <clipping_planes_fragment>
          float ghKeep = 1.0 - uGhZone.w * smoothstep(uGhZone.z, uGhZone.z + 1.4, length(vGhPos.xz - uGhZone.xy));
          // the sensors' two crop rows stay whole along their full length: past
          // the outer sensors, without fog, they show the crop the fog is about
          if (uGhMicro.x > 0.5) {
            float across = uGhMicro.y < 0.5 ? vGhPos.x : vGhPos.z;
            ghKeep = min(ghKeep, 1.0 - smoothstep(uGhMicro.w * 0.6, uGhMicro.w, abs(across - uGhMicro.z)));
          }
          float ghN = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
          if (ghN > mix(${GHOST_KEEP.toFixed(3)}, 1.0, ghKeep)) discard;`);
    };
    mat.customProgramCacheKey = () => 'gh-focus';
    return mat;
  }

  _buildStructure() {
    const g = new THREE.Group();
    const alu = new THREE.MeshStandardMaterial({ color: 0xcfd6de, metalness: 0.85, roughness: 0.35 });
    const glass = new THREE.MeshPhysicalMaterial({
      color: 0xdcecff, metalness: 0, roughness: 0.08, transparent: true, opacity: 0.07,
      clearcoat: 0.35, clearcoatRoughness: 0.1, side: THREE.DoubleSide, depthWrite: false,
      envMapIntensity: 0.6,
    });
    this._part('cover').materials.push(glass);
    const box = (w, h, d, x, y, z, mat = alu) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      m.position.set(x, y, z); m.castShadow = true; g.add(m); return m;
    };
    // gutters and posts
    for (let i = 0; i <= NSPAN; i++) {
      const x = X0 + i * SPAN;
      box(0.22, 0.14, L, x, GUTTER, 0);
      for (let z = Z0; z <= L / 2 + 0.01; z += (i === 0 || i === NSPAN) ? 3 : 6) {
        box(0.09, GUTTER, 0.09, x, GUTTER / 2, z);
      }
    }
    // trusses across every 6 m, ridges along
    for (let z = Z0; z <= L / 2 + 0.01; z += 6) box(W, 0.12, 0.06, 0, GUTTER - 0.35, z);
    for (let i = 0; i < NSPAN; i++) box(0.07, 0.07, L, X0 + i * SPAN + SPAN / 2, RIDGE, 0);
    // roof glass, two slopes per span, as one geometry
    const roof = [];
    const quad = (a, b, c, d) => roof.push(...a, ...b, ...c, ...a, ...c, ...d);
    for (let i = 0; i < NSPAN; i++) {
      const xa = X0 + i * SPAN, xm = xa + SPAN / 2, xb = xa + SPAN;
      quad([xa, GUTTER, Z0], [xm, RIDGE, Z0], [xm, RIDGE, -Z0], [xa, GUTTER, -Z0]);
      quad([xm, RIDGE, Z0], [xb, GUTTER, Z0], [xb, GUTTER, -Z0], [xm, RIDGE, -Z0]);
    }
    const roofGeo = new THREE.BufferGeometry();
    roofGeo.setAttribute('position', new THREE.Float32BufferAttribute(roof, 3));
    roofGeo.computeVertexNormals();
    this.roof = this._pickable(new THREE.Mesh(roofGeo, glass), 'cover');
    this.roof.renderOrder = 2;
    g.add(this.roof);
    // walls: sides and gable ends
    const wall = [];
    const q2 = (a, b, c, d) => wall.push(...a, ...b, ...c, ...a, ...c, ...d);
    q2([X0, 0, Z0], [X0, GUTTER, Z0], [X0, GUTTER, -Z0], [X0, 0, -Z0]);
    q2([-X0, 0, Z0], [-X0, GUTTER, Z0], [-X0, GUTTER, -Z0], [-X0, 0, -Z0]);
    for (const z of [Z0, -Z0]) {
      q2([X0, 0, z], [-X0, 0, z], [-X0, GUTTER, z], [X0, GUTTER, z]);
      for (let i = 0; i < NSPAN; i++) {
        const xa = X0 + i * SPAN;
        wall.push(xa, GUTTER, z, xa + SPAN, GUTTER, z, xa + SPAN / 2, RIDGE, z);
      }
    }
    const wallGeo = new THREE.BufferGeometry();
    wallGeo.setAttribute('position', new THREE.Float32BufferAttribute(wall, 3));
    wallGeo.computeVertexNormals();
    const walls = this._pickable(new THREE.Mesh(wallGeo, glass), 'cover');
    walls.renderOrder = 2;
    g.add(walls);
    this.walls = walls;
    // floor: white ground cloth and a concrete main path
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, L),
      new THREE.MeshStandardMaterial({ color: 0xe6e9e2, roughness: 0.95 }));
    floor.rotation.x = -Math.PI / 2; floor.position.y = 0.01; floor.receiveShadow = true;
    g.add(floor);
    const path = new THREE.Mesh(new THREE.PlaneGeometry(W, 1.6),
      new THREE.MeshStandardMaterial({ color: 0xb9bcbf, roughness: 0.9 }));
    path.rotation.x = -Math.PI / 2; path.position.set(0, 0.015, Z0 + 0.8); path.receiveShadow = true;
    g.add(path);
    this.scene.add(g);
  }

  _rows() {
    const rows = [];
    for (let k = 0; k < NROW; k++) rows.push(X0 + ROW_PITCH / 2 + k * ROW_PITCH);
    return rows;
  }

  // A tomato leaf: a rachis with three pairs of leaflets and a terminal one,
  // drooping along its length. Built flat, then bent; one geometry, instanced.
  _leafGeometry() {
    const shapes = [];
    const ellipse = (cx, cy, rx, ry, rot) => {
      const sh = new THREE.Shape();
      sh.absellipse(cx, cy, rx, ry, 0, Math.PI * 2, false, rot);
      return sh;
    };
    const rachis = new THREE.Shape();
    rachis.moveTo(0, -0.004); rachis.lineTo(0.44, -0.003); rachis.lineTo(0.44, 0.003); rachis.lineTo(0, 0.004);
    shapes.push(rachis);
    for (let i = 0; i < 3; i++) {
      const x = 0.1 + i * 0.11, r = 0.05 + i * 0.006;
      shapes.push(ellipse(x + 0.02, 0.05, r, r * 0.48, 0.55));
      shapes.push(ellipse(x + 0.02, -0.05, r, r * 0.48, -0.55));
    }
    shapes.push(ellipse(0.47, 0, 0.065, 0.034, 0));
    const geo = new THREE.ShapeGeometry(shapes, 5);
    geo.rotateX(-Math.PI / 2);                     // lie flat, pointing along +x
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {           // droop with distance from the stem
      const x = pos.getX(i), z = pos.getZ(i);
      pos.setY(i, pos.getY(i) + 0.18 * x - 0.95 * x * x - 0.25 * z * z);
    }
    geo.computeVertexNormals();
    return geo;
  }

  _buildCrop() {
    // High-wire tomato as grown commercially: the lower stem is de-leafed, so
    // ripening trusses hang free below a head of compound leaves.
    const rows = this._rows();
    const zs = [];
    for (let z = Z0 + 2.2; z < -Z0 - 0.6; z += PLANT_PITCH) zs.push(z);
    const nPlants = rows.length * zs.length;
    const rnd = seeded(42);
    const leafMat = this._focused(new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.7, metalness: 0,
      side: THREE.DoubleSide }));
    const perPlant = 11;
    const leaves = new THREE.InstancedMesh(this._leafGeometry(), leafMat, nPlants * perPlant);
    const stemMat = this._focused(new THREE.MeshStandardMaterial({ color: 0x5f7f33, roughness: 0.8 }));
    const stems = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.011, 0.016, 3.5, 5), stemMat, nPlants);
    const fruitGeo = new THREE.IcosahedronGeometry(0.05, 1);
    const fruitMat = this._focused(new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.28, metalness: 0,
      clearcoat: 0.6, clearcoatRoughness: 0.3 }));
    const trusses = 3, perTruss = 5;
    const fruits = new THREE.InstancedMesh(fruitGeo, fruitMat, nPlants * trusses * perTruss);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
    const e = new THREE.Euler(), c = new THREE.Color();
    let li = 0, fi = 0, si = 0;
    const GOLDEN = 2.39996;
    for (const x of rows) {
      for (const z of zs) {
        const jx = (rnd() - 0.5) * 0.1, jz = (rnd() - 0.5) * 0.1;
        const lean = (rnd() - 0.5) * 0.06;
        p.set(x + jx, 2.45, z + jz); e.set(lean, 0, (rnd() - 0.5) * 0.06); q.setFromEuler(e); s.set(1, 1, 1);
        stems.setMatrixAt(si++, m.compose(p, q, s));
        const phase = rnd() * Math.PI * 2;
        for (let k = 0; k < perPlant; k++) {
          const t = k / (perPlant - 1);                       // 0 low … 1 head
          const y = 1.55 + t * 2.55 + (rnd() - 0.5) * 0.08;
          // phyllotaxis, pulled towards the paths (the crop fans out across them)
          let az = phase + k * GOLDEN;
          az = Math.atan2(Math.sin(az) * 0.55, Math.cos(az));
          p.set(x + jx, y, z + jz + lean * (y - 2.45));
          e.set((rnd() - 0.5) * 0.25, az, -0.15 + (rnd() - 0.5) * 0.35, 'YXZ');
          q.setFromEuler(e);
          const sc = (1.55 - 0.75 * t) * (0.85 + rnd() * 0.3);
          s.set(sc, sc, sc);
          leaves.setMatrixAt(li, m.compose(p, q, s));
          // old leaves darker and bluer, the head a fresh yellow-green
          c.setHSL(0.27 + 0.04 * t + rnd() * 0.02, 0.5 + 0.15 * t, 0.2 + 0.16 * t + rnd() * 0.04);
          leaves.setColorAt(li++, c);
        }
        for (let tr = 0; tr < trusses; tr++) {
          const ty = 0.95 + tr * 0.32;
          const side = tr % 2 ? 1 : -1;
          for (let k = 0; k < perTruss; k++) {
            p.set(x + jx + side * (0.08 + k * 0.035), ty - k * 0.03 + (rnd() - 0.5) * 0.03,
                  z + jz + (rnd() - 0.5) * 0.08);
            q.identity(); const fs = 0.9 + rnd() * 0.3 - k * 0.05; s.set(fs, fs * 0.88, fs);
            fruits.setMatrixAt(fi, m.compose(p, q, s));
            // lowest truss ripe red, the next breaking, the top still green
            if (tr === 0) c.setHSL(0.0 + rnd() * 0.015, 0.85, 0.42);
            else if (tr === 1) c.setHSL(0.05 + rnd() * 0.04, 0.85, 0.47);
            else c.setHSL(0.2 + rnd() * 0.04, 0.6, 0.42);
            fruits.setColorAt(fi++, c);
          }
        }
      }
    }
    for (const im of [leaves, stems, fruits]) {
      im.castShadow = true; im.receiveShadow = true;
      if (im.instanceColor) im.instanceColor.needsUpdate = true;
      this._pickable(im, 'crop');
      this.scene.add(im);
    }
    this.leafMat = leafMat;
    this._part('crop').materials.push(stemMat, fruitMat);
    this.plantZs = zs;
  }

  _buildSubstrate() {
    const rows = this._rows();
    const slabMat = new THREE.MeshStandardMaterial({ color: 0xf4f6f6, roughness: 0.6 });
    const gutterMat = new THREE.MeshStandardMaterial({ color: 0x9aa3ab, metalness: 0.6, roughness: 0.4 });
    const len = -Z0 * 2 - 2.8;
    for (const x of rows) {
      const gut = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.06, len), gutterMat);
      gut.position.set(x, 0.72, 0.8); gut.castShadow = true; gut.receiveShadow = true;
      this._pickable(gut, 'substrate'); this.scene.add(gut);
    }
    const slabs = new THREE.InstancedMesh(new THREE.BoxGeometry(0.2, 0.09, 0.96), slabMat, rows.length * 32);
    const m = new THREE.Matrix4(); let i = 0;
    for (const x of rows) {
      for (let z = Z0 + 2.2, k = 0; k < 32; k++, z += 1.0) {
        m.makeTranslation(x, 0.8, z + 0.5);
        slabs.setMatrixAt(i++, m);
      }
    }
    slabs.castShadow = true; slabs.receiveShadow = true;
    this._pickable(slabs, 'substrate');
    this.scene.add(slabs);
    this.slabMat = slabMat;
    this._part('substrate').materials.push(gutterMat);
  }

  _buildPipes() {
    const rows = this._rows();
    const len = L - 1.6;
    const rail = new THREE.MeshStandardMaterial({ color: 0x8c96a0, metalness: 0.7, roughness: 0.3,
      emissive: 0x000000 });
    const grow = new THREE.MeshStandardMaterial({ color: 0x8c96a0, metalness: 0.7, roughness: 0.3,
      emissive: 0x000000 });
    const railGeo = new THREE.CylinderGeometry(0.05, 0.05, len, 10);
    railGeo.rotateX(Math.PI / 2);
    const growGeo = new THREE.CylinderGeometry(0.032, 0.032, len, 8);
    growGeo.rotateX(Math.PI / 2);
    const nPaths = rows.length - 1;
    const rails = new THREE.InstancedMesh(railGeo, rail, nPaths * 2);
    const grows = new THREE.InstancedMesh(growGeo, grow, rows.length);
    const m = new THREE.Matrix4(); let i = 0;
    for (let k = 0; k < nPaths; k++) {
      const x = (rows[k] + rows[k + 1]) / 2;
      for (const dx of [-0.28, 0.28]) { m.makeTranslation(x + dx, 0.14, 0.8); rails.setMatrixAt(i++, m); }
    }
    rows.forEach((x, k) => { m.makeTranslation(x + 0.18, 1.12, 0.8); grows.setMatrixAt(k, m); });
    for (const im of [rails, grows]) {
      im.castShadow = true;
      this._pickable(im, 'pipes');
      this.scene.add(im);
    }
    this.railMat = rail; this.growMat = grow;
  }

  _buildLamps() {
    const rows = this._rows();
    const housing = new THREE.MeshStandardMaterial({ color: 0x2a2f36, metalness: 0.7, roughness: 0.4 });
    const led = new THREE.MeshStandardMaterial({ color: 0x181818, emissive: 0xff2f8f,
      emissiveIntensity: 0, roughness: 0.4 });
    const per = 13, step = (L - 3) / per;
    const n = rows.length * per;
    const bodies = new THREE.InstancedMesh(new THREE.BoxGeometry(0.14, 0.07, 1.1), housing, n);
    const faces = new THREE.InstancedMesh(new THREE.BoxGeometry(0.11, 0.012, 1.02), led, n);
    const coneGeo = new THREE.ConeGeometry(1.0, 1.7, 20, 1, true);
    coneGeo.translate(0, -0.85, 0);
    const coneMat = new THREE.MeshBasicMaterial({ color: 0xff5fb2, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, fog: false });
    const cones = new THREE.InstancedMesh(coneGeo, coneMat, n);
    const m = new THREE.Matrix4(); let i = 0;
    for (const x of rows) {
      for (let k = 0; k < per; k++) {
        const z = Z0 + 1.5 + step * (k + 0.5);
        m.makeTranslation(x, LAMP_Y, z); bodies.setMatrixAt(i, m);
        m.makeTranslation(x, LAMP_Y - 0.042, z); faces.setMatrixAt(i, m);
        m.makeScale(0.8, 1, 1.25).setPosition(x, LAMP_Y - 0.05, z); cones.setMatrixAt(i, m);
        i++;
      }
    }
    bodies.castShadow = true;
    cones.renderOrder = 3;
    for (const im of [bodies, faces]) { this._pickable(im, 'lamps'); this.scene.add(im); }
    this.scene.add(cones);
    this.ledMat = led; this.coneMat = coneMat;
    this._part('lamps').materials.push(housing);
  }

  _buildScreen() {
    const mat = new THREE.MeshStandardMaterial({ color: 0xf3efe2, roughness: 0.92, transparent: true,
      opacity: 0.5, side: THREE.DoubleSide, emissive: 0x000000, depthWrite: false });
    this.screens = [];
    for (let i = 0; i < NSPAN; i++) {
      const geo = new THREE.PlaneGeometry(SPAN - 0.1, L - 0.2);
      geo.rotateX(-Math.PI / 2);
      geo.translate((SPAN - 0.1) / 2, 0, 0);   // anchored at the span's left gutter
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(X0 + i * SPAN + 0.05, SCREEN_Y, 0);
      mesh.receiveShadow = true;
      this._pickable(mesh, 'screen');
      this.screens.push(mesh);
      this.scene.add(mesh);
    }
    // the screen packs, where a parked screen sits
    const pack = new THREE.MeshStandardMaterial({ color: 0xe8e2d0, roughness: 0.9 });
    for (let i = 0; i < NSPAN; i++) {
      const b = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.1, L - 0.2), pack);
      b.position.set(X0 + i * SPAN + 0.1, SCREEN_Y, 0);
      this._pickable(b, 'screen'); this.scene.add(b);
    }
    this.screenMat = mat;
  }

  _buildVents() {
    // one vent window per 3 m on every ridge, alternately on either slope;
    // hinged at the ridge, the lower edge lifts, pushed up by a rack arm
    const mat = new THREE.MeshPhysicalMaterial({ color: 0xeaf4ff, roughness: 0.05, transparent: true,
      opacity: 0.22, clearcoat: 0.4, side: THREE.DoubleSide, depthWrite: false, emissive: 0x000000 });
    const frame = new THREE.MeshStandardMaterial({ color: 0xd9dee4, metalness: 0.8, roughness: 0.3,
      emissive: 0x000000 });
    const slope = Math.atan2(RIDGE - GUTTER, SPAN / 2);
    const wv = 1.05, lv = 1.7;
    const armGeo = new THREE.CylinderGeometry(0.016, 0.016, 1, 6);
    armGeo.translate(0, 0.5, 0);
    this.vents = [];
    for (let i = 0; i < NSPAN; i++) {
      const xm = X0 + i * SPAN + SPAN / 2;
      for (let k = 0, z = Z0 + 2; z < -Z0 - 1; k++, z += 3) {
        const side = (k + i) % 2 === 0 ? 1 : -1;     // +1: slope facing +x (east)
        const hinge = new THREE.Group();
        hinge.position.set(xm, RIDGE + 0.02, z);
        const pane = new THREE.Mesh(new THREE.BoxGeometry(wv, 0.02, lv), mat);
        pane.position.set(side * wv / 2, 0, 0);
        const bar = (w, d, x, bz) => {
          const b = new THREE.Mesh(new THREE.BoxGeometry(w, 0.045, d), frame);
          b.position.set(x, 0, bz);
          return b;
        };
        // the frame: lower (free) edge along the ridge direction, two sides up to the hinge
        const parts = [pane, bar(0.05, lv, side * wv, 0),
          bar(wv, 0.035, side * wv / 2, lv / 2), bar(wv, 0.035, side * wv / 2, -lv / 2)];
        hinge.add(...parts);
        hinge.rotation.z = -side * slope;
        // the rack arm rises out of the roof under the lower edge
        const arm = new THREE.Mesh(armGeo, frame);
        const anchor = new THREE.Vector3(xm + side * (wv - 0.05) * Math.cos(slope),
          RIDGE + 0.02 - (wv - 0.05) * Math.sin(slope) - 0.06, z);
        hinge.userData = { side, slope, wv, arm, anchor };
        for (const o of [...parts, arm]) this._pickable(o, 'vents');
        this.vents.push(hinge);
        this.scene.add(hinge, arm);
      }
    }
    this.ventMat = mat;
    this._setVent(this.vents, 0, 0, true);
  }

  // Open each vent to its side's percentage and stretch its arm to the lower edge.
  _setVent(vents, lee, wind, fromEast) {
    const maxAngle = THREE.MathUtils.degToRad(42);
    const up = new THREE.Vector3(0, 1, 0), tip = new THREE.Vector3(), d = new THREE.Vector3();
    for (const h of vents) {
      const { side, slope, wv, arm, anchor } = h.userData;
      const windward = (side > 0) === fromEast;
      const pct = (windward ? wind : lee) ?? 0;
      const rot = -side * (slope - (pct / 100) * maxAngle);
      h.rotation.z = rot;
      tip.set(h.position.x + side * (wv - 0.05) * Math.cos(rot),
        h.position.y + side * (wv - 0.05) * Math.sin(rot), h.position.z);
      d.subVectors(tip, anchor);
      const len = d.length();
      arm.position.copy(anchor);
      arm.quaternion.setFromUnitVectors(up, d.normalize());
      arm.scale.set(1, Math.max(0.001, len), 1);
      arm.visible = this.layers.roof && len > 0.09;
    }
  }

  _buildSensors() {
    const g = new THREE.Group();
    // the measuring box: an aspirated white box hanging in the path at head height
    const white = new THREE.MeshStandardMaterial({ color: 0xf5f5f0, roughness: 0.5, emissive: 0x000000 });
    const amber = new THREE.MeshStandardMaterial({ color: 0xf2a600, emissive: 0xf2a600, emissiveIntensity: 0.6 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x30363d, roughness: 0.6, emissive: 0x000000 });
    const box = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.24, 0.55), white);
    box.position.set(ZONE.x, 2.6, ZONE.z); box.castShadow = true;
    const fan = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.1, 16), dark);
    fan.rotation.x = Math.PI / 2; fan.position.set(ZONE.x, 2.6, ZONE.z - 0.32);
    const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.27, 0.04, 0.4), amber);
    stripe.position.set(ZONE.x, 2.74, ZONE.z);
    const wire = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, LAMP_Y - 2.72, 4), dark);
    wire.position.set(ZONE.x, (LAMP_Y + 2.72) / 2, ZONE.z);
    // the scale: a load cell under one gutter section of the next row
    const rowX = ZONE.x + ROW_PITCH / 2;
    const cell = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.12, 0.34), dark);
    cell.position.set(rowX, 0.6, ZONE.z);
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.54, 8), dark);
    post.position.set(rowX, 0.27, ZONE.z);
    const tray = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.03, 2.0), amber);
    tray.position.set(rowX, 0.675, ZONE.z);
    g.add(box, fan, stripe, wire, cell, post, tray);
    for (const o of [box, fan, stripe, cell, post, tray]) this._pickable(o, 'sensors');
    // the ring: how far one spot is taken to speak for (an illustration)
    const ring = new THREE.Mesh(new THREE.RingGeometry(ZONE.r - 0.12, ZONE.r, 120),
      new THREE.MeshBasicMaterial({ color: 0xf2a600, transparent: true, opacity: 0.9, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(ZONE.x, 0.03, ZONE.z);
    // and a halo just over the crop tops, so it reads from above
    const halo = new THREE.Mesh(new THREE.TorusGeometry(ZONE.r, 0.11, 10, 180),
      new THREE.MeshBasicMaterial({ color: 0xffb21a, transparent: true, opacity: 0.95, fog: false }));
    halo.rotation.x = Math.PI / 2; halo.position.set(ZONE.x, 4.6, ZONE.z);
    g.add(ring, halo);
    this.zoneParts = [ring, halo];
    this.scene.add(g);
  }

  _buildWeather() {
    const g = new THREE.Group();
    g.position.set(-X0 + 6, 0, Z0 - 4);
    const metal = new THREE.MeshStandardMaterial({ color: 0xc9cfd5, metalness: 0.8, roughness: 0.3 });
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.06, 9, 10), metal);
    mast.position.y = 4.5; mast.castShadow = true;
    const cupsGroup = new THREE.Group(); cupsGroup.position.y = 9.1;
    for (let k = 0; k < 3; k++) {
      const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.5), metal);
      arm.rotation.z = Math.PI / 2; arm.position.x = 0.25;
      const holder = new THREE.Group(); holder.rotation.y = (k * 2 * Math.PI) / 3;
      const cup = new THREE.Mesh(new THREE.SphereGeometry(0.07, 10, 8, 0, Math.PI), metal);
      cup.position.x = 0.5; cup.rotation.y = Math.PI / 2;
      holder.add(arm, cup); cupsGroup.add(holder);
    }
    const vane = new THREE.Group(); vane.position.y = 8.5;
    const tail = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.22, 0.5), metal);
    tail.position.z = 0.3;
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.04, 0.2, 8), metal);
    nose.rotation.x = -Math.PI / 2; nose.position.z = -0.25;
    vane.add(tail, nose);
    const sensor = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.08, 16),
      new THREE.MeshStandardMaterial({ color: 0xf2f2f2, roughness: 0.3 }));
    sensor.position.y = 9.55;
    g.add(mast, cupsGroup, vane, sensor);
    for (const o of [mast, sensor, tail, nose]) this._pickable(o, 'weather');
    this.anemometer = cupsGroup; this.vane = vane;
    this.scene.add(g);
    this.weatherPos = g.position.clone().setY(9.8);
  }

  _sprite() {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const x = c.getContext('2d');
    const gr = x.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.4, 'rgba(255,255,255,0.35)');
    gr.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = gr; x.fillRect(0, 0, 64, 64);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }

  _buildVapour() {
    const n = 2200, rnd = seeded(11);
    const pos = new Float32Array(n * 3), seed = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = X0 + 0.5 + rnd() * (W - 1);
      pos[i * 3 + 1] = 1.5 + rnd() * 4;
      pos[i * 3 + 2] = Z0 + 1 + rnd() * (L - 2);
      seed[i] = rnd();
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.vapourSeed = seed;
    this.vapour = new THREE.Points(geo, new THREE.PointsMaterial({
      size: 0.32, map: this._sprite(), color: 0xcfe7ff, transparent: true, opacity: 0.35,
      depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    this.vapour.renderOrder = 4;
    this.scene.add(this.vapour);
  }

  _arrow(colour) {
    const g = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 0.6,
      transparent: true, opacity: 0.85, roughness: 0.4 });
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 1, 14), mat);
    shaft.position.y = 0.5;
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.36, 0.8, 18), mat);
    g.add(shaft, head);
    g.userData = { shaft, head, mat };
    this.scene.add(g);
    return g;
  }

  _buildFlows() {
    // heat flow arrows over the roof: in (sun, lamps, pipes) and out (cover, air, vapour)
    this.flowArrows = {
      sun: this._arrow(0xf2a600), cover: this._arrow(0x257de0),
      ventilation: this._arrow(0x00b894), evaporation: this._arrow(0x9887ef),
    };
  }

  _setArrow(a, value, from, dir) {
    const len = Math.min(6, Math.max(0, value) / 55);
    // flows are the overview; a close-up on one part hides them
    a.visible = this.layers.flows && !this.selected && len > 0.25;
    if (!a.visible) return;
    const d = new THREE.Vector3(...dir).normalize();
    a.position.set(...from);
    a.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d);
    a.userData.shaft.scale.set(1, len, 1);
    a.userData.shaft.position.y = len / 2;
    a.userData.head.position.y = len + 0.35;
  }

  _buildLabels() {
    // on the side the default camera looks at (+x, +z), spread so they do not stack
    const spots = {
      lamps: [X0 + 4.8, LAMP_Y + 0.2, 10], screen: [X0 + 21, SCREEN_Y + 0.25, 13],
      vents: [X0 + 26, RIDGE + 0.8, 4], pipes: [X0 + 9.6, 0.45, 16.5],
      crop: [X0 + 13.6, 3.9, 14], substrate: [X0 + 20, 1.0, 16.5],
      weather: this.weatherPos.toArray(), cover: [X0 + 8, RIDGE + 1.2, -2],
      sensors: [ZONE.x, 3.15, ZONE.z],
    };
    this.labels = {};
    for (const [name, p] of Object.entries(spots)) {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'gh-pin';
      el.dataset.component = name;
      el.innerHTML = `<span class="gh-pin-name">${this.names[name] ?? name}</span><span class="gh-pin-val"></span>`;
      el.addEventListener('click', (ev) => { ev.stopPropagation(); this.onPick(name); });
      const obj = new CSS2DObject(el);
      obj.position.set(...p);
      this.scene.add(obj);
      this.labels[name] = { obj, el };
    }
  }

  _bindEvents() {
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    let down = null;
    const el = this.renderer.domElement;
    el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener('pointerup', (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const hit = this._hit(e);
      this.onPick(hit);
    });
    el.addEventListener('pointermove', (e) => {
      const hit = this._hit(e);
      if (hit !== this.hovered) {
        this.hovered = hit;
        el.style.cursor = hit ? 'pointer' : 'grab';
        this._highlight();
        this.onHover(hit);
      }
    });
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(this.container);
  }

  _hit(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const visible = this.pickables.filter((o) => o.visible && (o.parent?.visible ?? true));
    const hits = this.raycaster.intersectObjects(visible, false);
    // the glass is everywhere: prefer anything behind it
    const solid = hits.find((h) => h.object.userData.component !== 'cover');
    return (solid || hits[0])?.object.userData.component || null;
  }

  _highlight() {
    for (const [name, part] of Object.entries(this.parts)) {
      const on = name === this.selected ? 0.32 : name === this.hovered ? 0.18 : 0;
      for (const m of part.materials) {
        if (!m.emissive || m === this.ledMat) continue;
        if (m.userData.baseEmissive === undefined) m.userData.baseEmissive = m.emissive.getHex();
        if (on) m.emissive.setHex(0x3fa7ff).multiplyScalar(on);
        else m.emissive.setHex(m.userData.baseEmissive);
      }
    }
    for (const [name, l] of Object.entries(this.labels)) {
      l.el.classList.toggle('is-active', name === this.selected);
    }
  }

  _resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.labelRenderer.setSize(w, h);
    this.composer.setSize(w, h);
    this.bloom.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  // ---------------------------------------------------------------- public
  select(name) {
    this.selected = name;
    // the measuring box speaks for its surroundings only: the rest fades
    this.focusU.uGhZone.value.w = name === 'sensors' ? 1 : 0;
    this._highlight();
    if (name) for (const a of Object.values(this.flowArrows)) a.visible = false;
    else if (this._last) this.update(this._last);
    const views = {
      lamps: [[14, 8.5, -6], [0, 5, -10]], pipes: [[-6, 2.2, -21], [-9, 0.5, -12]],
      vents: [[10, 13, -28], [0, 6.8, -10]], screen: [[16, 9, -26], [0, 5.8, -6]],
      crop: [[-4, 3.2, -22], [-8, 2.2, -12]], substrate: [[-5, 1.6, -21], [-9, 0.8, -14]],
      weather: [[34, 8, -32], [22, 7, -22]], cover: [[44, 26, 40], [0, 4, 0]],
      sensors: [[ZONE.x + 8, 8.5, ZONE.z + 10], [ZONE.x, 1.2, ZONE.z - 0.5]],
      ...(this.micro ? { microclimate: this.micro.view() } : {}),
    };
    if (name && views[name]) this._fly(...views[name]);
  }

  resetView() { this._fly([27, 10.5, 31], [0, 2.6, 3]); }

  // standing in the main path at the gable end, looking down the rows
  insideView() { this._fly([1.6, 2.0, 16.4], [1.6, 2.3, 2]); }  // x = 1.6: a path with no gutter post

  _fly(pos, target) {
    this._flight = {
      p0: this.camera.position.clone(), p1: new THREE.Vector3(...pos),
      t0: this.controls.target.clone(), t1: new THREE.Vector3(...target), start: performance.now(),
    };
  }

  setLayer(name, on) {
    this.layers[name] = on;
    if (name === 'roof') {
      this.roof.visible = on; this.walls.visible = on;
      for (const v of this.vents) { v.visible = on; v.userData.arm.visible = on; }
      for (const m of this.screens) m.visible = on && (this._last?.state.screen ?? 0) > 0.01;
    }
    if (name === 'labels') {
      for (const l of Object.values(this.labels)) l.obj.visible = on && !this.microOn;
      for (const l of this.micro?.labels ?? []) l.obj.visible = on && this.microOn;
      if (this.micro) this.micro.pin.visible = on && !this.microOn;
    }
    if (name === 'vapour') this.vapour.visible = on;
    if (name === 'flows') for (const a of Object.values(this.flowArrows)) a.visible = on;
  }

  // ---------------------------------------------------------------- microclimate
  // The multi-height sensors' row: a thin post per sensor string, a bead per
  // height (the measured points, drawn over everything so they are never lost),
  // and around the crop a coloured fog. Each fog particle takes the colour of
  // the section (interpolated by microclimate.js) at its own place along the
  // row and height, so the fog is that section spread through the two crop
  // rows that flank the sensors. Where a reading is missing there is no fog.
  buildMicroclimate(section, ax) {
    if (this.micro) {
      this.scene.remove(this.micro.group);
      for (const l of this.micro.labels) l.obj.removeFromParent();
      this.micro.pin.removeFromParent();
      this.micro.fog.geometry.dispose();
      this.pickables = this.pickables.filter((o) => o.userData.component !== 'microclimate');
      delete this.parts.microclimate;
    }
    const along = section.runs === 'along_rows';
    const x0 = ax.xs[0], span = ax.xs[ax.xs.length - 1] - x0;
    const y0 = ax.ys[0], y1 = ax.ys[ax.ys.length - 1];
    const at = (p, y, across = 0) => (along
      ? new THREE.Vector3(MICRO.x + across, y, p - x0 - span / 2)
      : new THREE.Vector3(p - x0 - span / 2, y, MICRO.z + across));
    this.focusU.uGhMicro.value.y = along ? 0 : 1;
    this.focusU.uGhMicro.value.z = along ? MICRO.x : MICRO.z;

    const group = new THREE.Group();
    // the fog: particles spread evenly through the band, each remembering where
    // it is in the section's own terms (metres along the row, metres up)
    const n = Math.round(FOG_PER_M3 * span * (y1 - y0) * 2 * MICRO.band);
    const rnd = seeded(23);
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 4);
    const p = new Float32Array(n), y = new Float32Array(n), across = new Float32Array(n);
    const edge = new Float32Array(n), drift = new Float32Array(n * 2);
    for (let i = 0; i < n; i++) {
      p[i] = x0 + rnd() * span;
      y[i] = y0 + rnd() * (y1 - y0);
      across[i] = (rnd() * 2 - 1) * MICRO.band;
      // thinning towards the band's sides and its top and bottom: no hard surface
      const side = 1 - THREE.MathUtils.smoothstep(Math.abs(across[i]), MICRO.band * 0.55, MICRO.band);
      const yv = Math.min(y[i] - y0, y1 - y[i]);
      edge[i] = side * THREE.MathUtils.smoothstep(yv, 0, 0.35) * 0.5 + side * 0.5;
      drift[i * 2] = (rnd() - 0.5) * 0.12;     // m/s along the row
      drift[i * 2 + 1] = (rnd() - 0.5) * 0.05; // m/s up or down
      at(p[i], y[i], across[i]).toArray(pos, i * 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 4));
    const fog = new THREE.Points(geo, new THREE.PointsMaterial({
      size: FOG_SIZE, map: this._sprite(), vertexColors: true, transparent: true, opacity: FOG_OPACITY,
      depthWrite: false, toneMapped: false,
    }));
    fog.renderOrder = 5;
    fog.frustumCulled = false;
    group.add(fog);

    const postMat = new THREE.MeshStandardMaterial({ color: 0x30363d, roughness: 0.6 });
    const beadGeo = new THREE.SphereGeometry(0.07, 16, 10);
    const beads = [], labels = [];
    section.wires.forEach((w) => {
      const top = at(w.at_m, LAMP_Y), foot = at(w.at_m, 0.3);
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, LAMP_Y - 0.3, 6), postMat);
      post.position.copy(top.clone().add(foot).multiplyScalar(0.5));
      group.add(post);
      beads.push(section.heights.map((h) => {
        const bead = new THREE.Mesh(beadGeo, new THREE.MeshBasicMaterial({
          color: 0x9c9c9c, depthTest: false, depthWrite: false, toneMapped: false, transparent: true,
        }));
        bead.position.copy(at(w.at_m, h.m));
        bead.renderOrder = 12;
        group.add(this._pickable(bead, 'microclimate'));
        return bead;
      }));
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'gh-pin gh-pin-wire';
      el.textContent = w.id;
      el.addEventListener('click', (ev) => { ev.stopPropagation(); this.onPick('microclimate'); });
      const obj = new CSS2DObject(el);
      obj.position.copy(at(w.at_m, y1 + 0.55));
      this.scene.add(obj);
      labels.push({ obj, el });
    });
    // unselected, the row is one pin; selected, it opens into a label per string
    const pinEl = document.createElement('button');
    pinEl.type = 'button';
    pinEl.className = 'gh-pin';
    pinEl.dataset.component = 'microclimate';
    pinEl.innerHTML = `<span class="gh-pin-name">${this.names.microclimate ?? 'microclimate'}</span>`;
    pinEl.addEventListener('click', (ev) => { ev.stopPropagation(); this.onPick('microclimate'); });
    const pin = new CSS2DObject(pinEl);
    pin.position.copy(at(x0 + span / 2, y1 + 0.55));
    this.scene.add(pin);
    fog.visible = false;
    this.scene.add(group);
    // Square on to the row from the side, far enough out to frame all of it:
    // every line of sight then crosses the fog at one place along the row and
    // one height, so it shows the section's colour there instead of averaging
    // 25 m of it. From the side that puts the first sensor string on the left,
    // as the panel's cross-section has it. The crop in between is a ghost.
    const view = () => {
      const hfov = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * this.camera.aspect);
      // a few metres past each end: the row's head and tail, solid and fog-free
      const d = (span / 2 + 3.5) / Math.tan(hfov / 2);
      const mid = at(x0 + span / 2, (y0 + y1) / 2);
      // looking down -x, +z runs to the right; looking down -z, +x runs right
      const side = along ? -d : d;
      return [at(x0 + span / 2, (y0 + y1) / 2 + 0.8, side).toArray(), mid.toArray()];
    };
    this.micro = { group, fog, beads, labels, pin, at, x0, span, y0, y1, p, y, across, edge, drift, colourAt: null, view };
    this.setMicroclimate(this.microOn ?? false);
  }

  setMicroclimate(on) {
    this.microOn = on;
    // the measuring box's ring would compete with the row for the eye
    for (const o of this.zoneParts) o.visible = !on;
    // the other parts' pins would sit on top of the row
    for (const l of Object.values(this.labels)) l.obj.visible = !on && this.layers.labels;
    if (!this.micro) return;
    // the posts are always there; the fog and the colours only while selected
    this.micro.fog.visible = on;
    this.focusU.uGhMicro.value.x = on ? 1 : 0;
    for (const l of this.micro.labels) l.obj.visible = on && this.layers.labels;
    this.micro.pin.visible = !on && this.layers.labels;
    // measured points over everything while selected; in the house otherwise
    for (const col of this.micro.beads) {
      for (const b of col) {
        b.material.depthTest = !on;
        if (!on) b.material.color.setHex(0x9c9c9c);
      }
    }
  }

  // One step: ``colourAt(metres along, metres up)`` gives the section's
  // [r, g, b] there (null: no reading); ``beads[wire][height]`` the measured.
  updateMicroclimate(colourAt, beads) {
    if (!this.micro) return;
    this.micro.colourAt = colourAt;
    this._colourFog();
    this.micro.beads.forEach((col, wi) => col.forEach((bead, k) => {
      const c = beads[wi]?.[k];
      bead.material.color.setRGB(...(c ? c.map((v) => v / 255) : [0.36, 0.38, 0.42]), THREE.SRGBColorSpace);
    }));
  }

  _colourFog() {
    const m = this.micro;
    if (!m?.colourAt) return;
    const col = m.fog.geometry.attributes.color.array, c = new THREE.Color();
    for (let i = 0; i < m.p.length; i++) {
      const rgb = m.colourAt(m.p[i], m.y[i]);
      if (rgb) c.setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace);
      col[i * 4] = c.r; col[i * 4 + 1] = c.g; col[i * 4 + 2] = c.b;
      col[i * 4 + 3] = rgb ? m.edge[i] : 0;
    }
    m.fog.geometry.attributes.color.needsUpdate = true;
  }

  // The fog drifts slowly within its band, taking the colour of where it goes.
  _driftFog(dt) {
    const m = this.micro;
    if (!m || !m.fog.visible || !m.colourAt) return;
    const pos = m.fog.geometry.attributes.position.array, v = new THREE.Vector3();
    for (let i = 0; i < m.p.length; i++) {
      m.p[i] += m.drift[i * 2] * dt;
      m.y[i] += m.drift[i * 2 + 1] * dt;
      if (m.p[i] < m.x0) m.p[i] += m.span; else if (m.p[i] > m.x0 + m.span) m.p[i] -= m.span;
      if (m.y[i] < m.y0 || m.y[i] > m.y1) { m.drift[i * 2 + 1] *= -1; m.y[i] = Math.min(m.y1, Math.max(m.y0, m.y[i])); }
      m.at(m.p[i], m.y[i], m.across[i]).toArray(pos, i * 3);
    }
    m.fog.geometry.attributes.position.needsUpdate = true;
    this._colourFog();
  }

  setLabel(name, text) {
    const l = this.labels[name];
    if (l) l.el.querySelector('.gh-pin-val').textContent = text ?? '';
  }

  // One 15-minute step of the day.
  update(step) {
    this._last = step;
    const s = step.state, f = step.flows;
    const el = step.sun_el ?? -20, az = step.sun_az ?? 180;
    const er = THREE.MathUtils.degToRad(el), ar = THREE.MathUtils.degToRad(az);
    const dir = new THREE.Vector3(Math.sin(ar) * Math.cos(er), Math.sin(er), -Math.cos(ar) * Math.cos(er));
    this.sky.material.uniforms.sunPosition.value.copy(dir);
    const day = THREE.MathUtils.clamp((el + 4) / 14, 0, 1);       // 0 night … 1 day
    const rad = s.radiation ?? 0;
    this.sun.position.copy(dir.clone().multiplyScalar(120));
    this.sun.intensity = el > 0 ? 0.4 + Math.min(3.2, rad / 220) : 0;
    this.hemi.intensity = 0.06 + 0.55 * day;
    this.hemi.color.setHSL(0.6, 0.4, 0.35 + 0.4 * day);
    this.renderer.toneMappingExposure = 0.34 + 0.12 * day;
    this.scene.environmentIntensity = 0.08 + 0.3 * day;
    this.stars.material.opacity = (1 - day) * 0.85;
    this.scene.fog.color.setHSL(0.6, 0.3, 0.04 + 0.5 * day);
    this.sky.visible = day > 0.02;
    if (!this.sky.visible) this.scene.background = new THREE.Color(0x05070d);
    else this.scene.background = null;

    // lamps
    const lamps = s.lamps ?? 0;
    this.state.lamps = lamps;
    this.ledMat.emissiveIntensity = lamps * 5.5;
    this.coneMat.opacity = lamps * (0.09 - 0.06 * day);
    this.lampLight.intensity = lamps * (3.4 - 2.6 * day);
    // bloom is for the lamps' glow at night; by day it would only haze the scene
    this.bloom.strength = 0.08 + 0.55 * (1 - day);
    this.bloom.threshold = 0.82 + 0.15 * day;

    // pipes: colour by temperature above the air
    const tAir = s.t_in;
    const rail = pipeColour(s.lg_pipe_lower, tAir), grow = pipeColour(s.lg_pipe_growth, tAir);
    this.railMat.color.copy(rail.colour); this.railMat.emissive.copy(rail.colour).multiplyScalar(rail.glow * 0.9);
    this.growMat.color.copy(grow.colour); this.growMat.emissive.copy(grow.colour).multiplyScalar(grow.glow * 0.9);
    this.railMat.userData.baseEmissive = this.railMat.emissive.getHex();
    this.growMat.userData.baseEmissive = this.growMat.emissive.getHex();

    // screen: deployed share, from the left gutter of each span
    const screen = s.screen;
    for (const m of this.screens) {
      m.visible = this.layers.roof && screen != null && screen > 0.01;
      m.scale.x = Math.max(0.001, screen ?? 0);
    }

    // vents: lee and wind side by wind direction (wind *from*)
    const fromEast = Math.sin(THREE.MathUtils.degToRad(s.wind_dir ?? 270)) > 0;
    this._setVent(this.vents, s.vent_lee, s.vent_wind, fromEast);
    this.state.airExchange = f.air_exchange ?? 0.002;
    this.state.vent = s.vent ?? 0;
    this.state.transpiration = s.transpiration ?? 0.03;
    this.state.wind = s.wind ?? 0;
    this.vane.rotation.y = -THREE.MathUtils.degToRad(s.wind_dir ?? 0);

    // crop: a touch more saturated when transpiring hard
    const act = THREE.MathUtils.clamp((this.state.transpiration - 0.03) / 0.4, 0, 1);
    this.leafMat.color.setRGB(0.92 + 0.08 * act, 1, 0.9 + 0.05 * act);
    // slab: whiter dry, bluer wet (weight on the scale, ~25-35 kg)
    const wet = THREE.MathUtils.clamp(((s.weight ?? 28) - 24) / 12, 0, 1);
    this.slabMat.color.setHSL(0.55, 0.1 + 0.45 * wet, 0.92 - 0.25 * wet);

    // heat-flow arrows over the roof
    this._setArrow(this.flowArrows.sun, f.sun, [-10, RIDGE + 12, 4], [0.25, -1, 0]);
    this._setArrow(this.flowArrows.cover, f.cover, [-2, RIDGE + 0.8, 4], [0, 1, 0]);
    this._setArrow(this.flowArrows.ventilation, f.ventilation, [5, RIDGE + 0.8, 4], [0.25, 1, 0]);
    this._setArrow(this.flowArrows.evaporation, f.evaporation, [12, RIDGE + 0.8, 4], [0.45, 1, 0]);
  }

  _frame() {
    const dt = Math.min(0.05, this.clock.getDelta());
    if (this._flight) {
      const fl = this._flight;
      fl.k = Math.min(1, (performance.now() - fl.start) / 800);  // by the clock, not the frame
      const e = fl.k < 0.5 ? 2 * fl.k * fl.k : 1 - Math.pow(-2 * fl.k + 2, 2) / 2;
      this.camera.position.lerpVectors(fl.p0, fl.p1, e);
      this.controls.target.lerpVectors(fl.t0, fl.t1, e);
      if (fl.k >= 1) this._flight = null;
    }
    this.controls.update();
    this._driftFog(dt);
    this.anemometer.rotation.y += dt * (0.5 + this.state.wind * 2.5);

    // vapour: rises with transpiration; leaves through the vents when open
    if (this.vapour.visible) {
      const pos = this.vapour.geometry.attributes.position.array;
      const e = this.state.transpiration, open = this.state.vent;
      const up = 0.15 + e * 3.2, out = 0.4 + this.state.airExchange * 260;
      const live = Math.min(1, 0.12 + e * 2.2);
      this.vapour.material.opacity = 0.12 + 0.45 * live;
      const n = pos.length / 3;
      for (let i = 0; i < n; i++) {
        const k = i * 3, sd = this.vapourSeed[i];
        if (sd > live) { pos[k + 1] = -50; continue; }
        if (pos[k + 1] < 0) pos[k + 1] = 1.4 + sd * 2;
        pos[k + 1] += dt * up * (0.6 + sd);
        pos[k] += dt * Math.sin(sd * 40 + pos[k + 1]) * 0.15;
        if (pos[k + 1] > GUTTER - 0.4) {
          if (open > 0.03) {
            // drift to the nearest ridge and out
            const xm = X0 + Math.floor((pos[k] - X0) / SPAN) * SPAN + SPAN / 2;
            pos[k] += (xm - pos[k]) * dt * 1.5;
            pos[k + 1] += dt * out;
            if (pos[k + 1] > RIDGE + 3 + sd * 3) pos[k + 1] = 1.4 + sd * 2;
          } else if (pos[k + 1] > SCREEN_Y - 0.1) {
            pos[k + 1] = 1.4 + sd * 2;            // closed house: it condenses and cycles
          }
        }
      }
      this.vapour.geometry.attributes.position.needsUpdate = true;
    }
    this.composer.render();
    this.labelRenderer.render(this.scene, this.camera);
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this._ro?.disconnect();
    this.renderer.dispose();
  }
}

