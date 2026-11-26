// WireScout: a concept demo, loaded only on /greenhouse?wirescout (see app.js).
// A sensor unit that rides a rail along one crop row, stops at regular places
// and lowers a camera-and-sensor head on a scissor lift through five heights:
// one moving unit in place of many fixed multi-height sensors. Nothing here is
// measured; it shows what such a unit would do, not what this house has.

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { LAYOUT, seeded } from './scene.js';
import { colourOf, css as rgbCss, drawSection, gradient, nodeXY, ramp } from './microclimate.js';

const { L, GUTTER, ROW_PITCH, ZONE } = LAYOUT;

// The rail hangs in a path with no gutter post, beside the measuring box's,
// under the lamps and above the crop's head. The charging station stands out
// of the path, at the end of the row beside it.
const RAIL_X = ZONE.x + ROW_PITCH, RAIL_Y = 4.75;
const STATION = { x: RAIL_X + ROW_PITCH / 2, z: L / 2 - 0.35 };
// The concept: a 100 m row, a stop every 20 m from the charging station on,
// and at each stop five heights 500 mm apart. Here the row is the house's own,
// so the six stops spread over its length.
const STOPS = 6, Z_DOCK = L / 2 - 1, Z_END = -L / 2 + 2.6;
const LEVELS = [1.0, 1.5, 2.0, 2.5, 3.0];   // head heights (m), the lowest at the ripe truss
// The rows either side of the rail (``side``: -1 / 1 in x), by an illustrative
// site numbering (section, row): the first is inspected on the way out, the
// second on the way back, the head turned round at the far end.
const ROWS = [{ side: -1, section: 'B', id: 130 }, { side: 1, section: 'B', id: 131 }];
const PARK_Y = 3.6;                          // head height while driving
// Time-lapse pace (s, m/s) and the battery (%): a tour costs a few percent
// (DRAIN_PER_S of demo time), and each return to the station tops it up to
// the top of its BATTERY band. It starts a little below that top.
const DRIVE_MPS = 2.4, RETURN_MPS = 4.5, MOVE_S = 0.45, CAPTURE_S = 0.55, TURN_S = 0.7;
const SEND_S = 1.1, CHARGE_S = 3.5, BATTERY = [20, 80], DRAIN_PER_S = 0.05, BATTERY_START = 74;
// The scissor: stages and bar length (m); it reaches from the carriage to the lowest level.
const SCISSOR_N = 10, SCISSOR_BAR = 0.36;
const CARRIAGE_BOTTOM = RAIL_Y - 0.135, HEAD_TOP = 0.115;
// What one capture sees: trusses in the facing row within this far along the
// row and up or down from the head (m). Detections stay ``hold`` seconds, a
// problem's past the rest of its stop, then fade. Fruit and problems have a
// pool each, so passing trusses never take a problem's slot.
const VIEW_Z = 0.9, VIEW_Y = 0.3, FADE_S = 0.8;
const FRUIT_TAGS = { size: 24, hold: 2.6 }, ALERT_TAGS = { size: 4, hold: 12, alert: true };
// Fruit diameter shown (mm) over the crop's range of fruit scales: plausible
// round-tomato sizes, not a measurement.
const MM = [50, 75], SCALE = [0.75, 1.2];
// What the camera finds besides fruit: a pest, a fungus and a disease, put in
// the crop at fixed stops so every tour comes across them. ``side`` is the row
// (as in ROWS), ``level`` an index into LEVELS, ``dz``
// how far along the row from the stop (m). Drawn as specks of ``colour`` and
// ``size`` (m); ``flutter`` (m) makes them fly. Illustrations, at a size that
// shows from the path: real whiteflies are a millimetre or two.
const INCIDENTS = [
  { title: 'Whitefly', detail: (n) => `pest · ${n} counted`, stop: 1, side: -1, level: 3, dz: 0.25,
    n: 26, colour: 0xffffff, size: 0.035, opacity: 1, spread: [0.3, 0.25, 0.35], flutter: 0.03 },
  { title: 'Powdery mildew', detail: () => 'fungus', stop: 2, side: 1, level: 4, dz: -0.3,
    n: 70, colour: 0xeef0ea, size: 0.06, opacity: 0.8, spread: [0.3, 0.3, 0.45], flutter: 0 },
  { title: 'Late blight', detail: () => 'disease', stop: 4, side: -1, level: 2, dz: 0.2,
    n: 30, colour: 0x3d2a14, size: 0.08, opacity: 0.95, spread: [0.3, 0.3, 0.4], flutter: 0 },
];
const CLASS_COLOUR = { ripe: '#ff5a4a', breaking: '#f2b705', green: '#8fd65a', flag: '#f47230' };
// The card's readings are SYNTHETIC: plausible vertical profiles, not data.
// Air at the lowest height and its change per metre up (T °C, RH %, CO₂ ppm),
// a drift per stop along the row and from one row to the next, and ± noise;
// PAR (µmol/m²/s) falls from PAR_TOP through the leaves above (Beer-Lambert,
// extinction K, leaf area per metre of canopy below CANOPY_TOP m). T_PATCH: a
// warm patch in the air of the house, so at the same place along both rows:
// centred at stop ``at``, ``width`` stops wide, ``dT`` °C at the top height in
// each row (per ROWS; a little weaker one row further on).
const SYNTH = {
  T: { base: 20.6, perM: 0.45, perStop: 0.12, perRow: -0.25, noise: 0.15 },
  T_PATCH: { at: 3.3, width: 1.1, dT: [0.9, 0.75] },
  RH: { base: 84, perM: -3, perStop: -0.4, perRow: 1.2, noise: 0.8 },
  CO2: { base: 735, perM: -22, perStop: -4, perRow: 5, noise: 6 },
  PAR_TOP: 540, K: 0.7, LAI_PER_M: 1.2, CANOPY_TOP: 4.1, PAR_NOISE: 0.05,
};
const STAGE = { charging: 'Charging', driving: 'Driving', measuring: 'Measuring', sending: 'Sending',
                returning: 'Returning' };

// ------------------------------------------------------------------ motion
// A move is a generator fed the frame's dt; ``yield*`` chains them into a script.
function* tween(dur, fn) {
  let t = 0;
  fn(0);
  while (t < dur) { t += yield; fn(Math.min(1, t / dur)); }
}
const ease = (k) => (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2);
const stopZ = (s) => Z_DOCK + ((Z_END - Z_DOCK) * s) / (STOPS - 1);

function* drive(u, z1, mps) {
  const z0 = u.z;
  yield* tween(Math.abs(z1 - z0) / mps + 0.5, (k) => { u.z = z0 + (z1 - z0) * ease(k); });
}
function* lift(u, y1) {
  const y0 = u.headY;
  if (Math.abs(y1 - y0) < 1e-3) return;
  yield* tween(MOVE_S * Math.max(1, Math.abs(y1 - y0) / 0.5), (k) => { u.headY = y0 + (y1 - y0) * ease(k); });
}
function* turn(u, side) {
  const r0 = u.yaw, r1 = side > 0 ? 0 : Math.PI;
  if (r0 !== r1) yield* tween(TURN_S, (k) => { u.yaw = r0 + (r1 - r0) * ease(k); });
}
function* capture(u, ev, level, side) {
  ev.capture?.(u, level, side);
  yield* tween(CAPTURE_S, (k) => { u.flash = 1 - k; });
}

// The cycle on the concept sheet: drive to a stop, measure its five heights
// from the top down, send, drive on. Out along the row with the camera on the first row, then the
// head turns round and the unit comes back stop by stop along the second; at
// the station it charges and starts again.
function* cycle(u, ev) {
  const out = Array.from({ length: STOPS }, (_, s) => s);
  for (;;) {
    u.stage = 'charging';
    u.row = null;
    ev.tour?.(u);
    const b0 = u.battery;
    yield* tween(CHARGE_S, (k) => { u.battery = b0 + (BATTERY[1] - b0) * k; });
    for (const [ri, order] of [[0, out], [1, [...out].reverse()]]) {
      u.row = ri;
      for (const s of order) {
        u.stop = s;
        u.stage = 'driving';
        yield* drive(u, stopZ(s), DRIVE_MPS);
        yield* turn(u, ROWS[ri].side);
        u.stage = 'measuring';
        for (const lv of [4, 3, 2, 1, 0]) {
          yield* lift(u, LEVELS[lv]);
          u.level = lv;
          yield* capture(u, ev, lv, ROWS[ri].side);
        }
        u.level = null;
        yield* lift(u, PARK_Y);
        u.stage = 'sending';
        ev.send?.(u, s);
        yield* tween(SEND_S, (k) => { u.pulse = k; });
        u.pulse = null;
      }
    }
    u.row = null;
    u.stop = null;
    if (u.z !== Z_DOCK) { u.stage = 'returning'; yield* drive(u, Z_DOCK, RETURN_MPS); }
  }
}

// ------------------------------------------------------------------ model
function materials(scene) {
  const std = (o) => scene._hazed(new THREE.MeshStandardMaterial(o));
  const glow = (color) => new THREE.MeshBasicMaterial({ color, toneMapped: false });
  return {
    white: std({ color: 0xe9ecef, roughness: 0.4, metalness: 0.1 }),
    grey: std({ color: 0x3b424b, roughness: 0.5, metalness: 0.4 }),
    orange: std({ color: 0xf47230, roughness: 0.5 }),
    steel: std({ color: 0xa9b2bb, roughness: 0.35, metalness: 0.7 }),
    lens: std({ color: 0x101418, roughness: 0.15, metalness: 0.8 }),
    led: glow(0x4dff7a),
    ring: glow(0xfff1d6),
  };
}

const place = (m, x, y, z) => { m.position.set(x, y, z); return m; };
const box = (w, h, d, mat, x = 0, y = 0, z = 0) => place(new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat), x, y, z);
const rbox = (w, h, d, r, mat, x = 0, y = 0, z = 0) => place(new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 3, r), mat), x, y, z);
const rod = (r, y0, y1, mat, x, z) => place(new THREE.Mesh(new THREE.CylinderGeometry(r, r, y1 - y0, 8), mat), x, (y0 + y1) / 2, z);

function buildRail(M) {
  const g = new THREE.Group();
  const z0 = Z_END - 0.6, z1 = L / 2 - 0.25;
  g.add(box(0.05, 0.08, z1 - z0, M.steel, RAIL_X, RAIL_Y + 0.12, (z0 + z1) / 2));
  for (let z = z1 - 0.2; z > z0; z -= 4) g.add(rod(0.008, RAIL_Y + 0.16, GUTTER, M.grey, RAIL_X, z));
  return g;
}

// A cabinet at the row's end, its face (and bolt) to the path; a post and an
// arm carry the power to the rail's end, where the unit docks.
function buildStation(M) {
  const g = new THREE.Group();
  const h = 1.35, armY = RAIL_Y + 0.3;
  g.add(rbox(0.3, h, 0.5, 0.04, M.white, 0, h / 2, 0));
  g.add(box(0.31, 0.06, 0.51, M.orange, 0, h - 0.12, 0));
  g.add(box(0.01, 0.6, 0.34, M.grey, -0.155, 0.72, 0));
  const s = new THREE.Shape();
  [[0.02, 0.2], [-0.09, -0.02], [-0.01, -0.02], [-0.04, -0.2], [0.09, 0.04], [0.01, 0.04]]
    .forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
  const bolt = new THREE.Mesh(new THREE.ShapeGeometry(s), M.led.clone());
  bolt.position.set(-0.162, 0.72, 0);
  bolt.rotation.y = -Math.PI / 2;
  g.add(bolt);
  const reach = STATION.x - RAIL_X;
  g.add(rod(0.025, h, armY, M.grey, 0.06, 0));
  g.add(box(reach + 0.1, 0.04, 0.04, M.grey, (0.06 - reach) / 2, armY, 0));
  g.add(rod(0.012, RAIL_Y + 0.16, armY, M.grey, -reach, 0));
  g.position.set(STATION.x, 0, STATION.z);
  return { group: g, bolt };
}

function buildUnit(M) {
  const unit = new THREE.Group();
  // carriage: a trolley over the rail and a body under it, long along the rail
  unit.add(rbox(0.24, 0.17, 0.44, 0.06, M.white, 0, RAIL_Y - 0.05, 0));
  for (const z of [-0.215, 0.215]) unit.add(rbox(0.245, 0.175, 0.05, 0.02, M.orange, 0, RAIL_Y - 0.05, z));
  for (const x of [-0.121, 0.121]) unit.add(box(0.004, 0.02, 0.2, M.led, x, RAIL_Y - 0.02, 0));
  for (const z of [-0.15, 0.15]) {
    const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.03, 16), M.grey);
    wheel.rotation.z = Math.PI / 2;
    wheel.position.set(0, RAIL_Y + 0.205, z);
    unit.add(wheel, box(0.016, 0.14, 0.03, M.grey, 0.035, RAIL_Y + 0.12, z));
  }

  // scissor: two crossing bars per stage, set from the head's height each
  // frame. Pins run through both bars' planes at every crossing and at every
  // joint between stages; the bars reach a little past their pins, as real
  // links do. A foot plate carries the lowest pins and the head.
  const barGeo = new THREE.BoxGeometry(0.014, SCISSOR_BAR + 0.03, 0.014);
  const bars = [];
  for (let i = 0; i < SCISSOR_N * 2; i++) {
    const b = new THREE.Mesh(barGeo, M.steel);
    b.position.x = i % 2 ? 0.016 : -0.016;
    bars.push(b);
    unit.add(b);
  }
  const pinGeo = new THREE.CylinderGeometry(0.011, 0.011, 0.056, 10).rotateZ(Math.PI / 2);
  const pins = [];
  for (let i = 0; i < SCISSOR_N + 2 * (SCISSOR_N + 1); i++) {
    const pin = new THREE.Mesh(pinGeo, M.grey);
    pins.push(pin);
    unit.add(pin);
  }
  const foot = box(0.06, 0.02, SCISSOR_BAR + 0.06, M.grey);
  unit.add(foot);
  const scissor = { bars, pins, foot };

  // head: a sensor body long along the camera's line of sight, the camera with
  // its LED ring at its end; it turns to either row. Local +x is where it looks.
  const HEAD_HALF = 0.18;
  const head = new THREE.Group();
  head.add(rbox(2 * HEAD_HALF, 0.15, 0.16, 0.045, M.white));
  head.add(rbox(2 * HEAD_HALF + 0.005, 0.03, 0.165, 0.012, M.orange, 0, -0.05, 0));
  head.add(box(0.06, 0.04, 0.06, M.grey, 0, 0.095, 0));
  const housing = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.04, 24), M.grey);
  housing.rotation.z = Math.PI / 2;
  housing.position.x = HEAD_HALF + 0.01;
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.048, 0.011, 10, 32), M.ring);
  ring.rotation.y = Math.PI / 2;
  ring.position.x = HEAD_HALF + 0.032;
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.034, 0.02, 20), M.lens);
  lens.rotation.z = Math.PI / 2;
  lens.position.x = HEAD_HALF + 0.034;
  // the camera's view: a faint cone out to the facing row, brighter at each shot
  const cone = new THREE.Mesh(new THREE.ConeGeometry(0.42, 0.62, 24, 1, true), new THREE.MeshBasicMaterial({
    color: 0xffe9a8, transparent: true, depthWrite: false, toneMapped: false,
    blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  }));
  cone.rotation.z = Math.PI / 2;      // apex at the lens, opening along +x
  cone.position.x = HEAD_HALF + 0.04 + 0.31;
  cone.visible = false;
  head.add(housing, ring, lens, cone);
  unit.add(head);

  unit.position.x = RAIL_X;
  return { unit, scissor, head, cone };
}

// The scissor spans the carriage's bottom to the head's top in equal stages:
// each stage is two bars of fixed length crossing, so it narrows as it extends.
function setScissor({ bars, pins, foot }, headY) {
  const H = CARRIAGE_BOTTOM - (headY + HEAD_TOP);
  const h = Math.min(H / SCISSOR_N, SCISSOR_BAR * 0.98);
  const w = Math.sqrt(SCISSOR_BAR ** 2 - h ** 2);
  const phi = Math.atan2(w, h);
  let k = 0;
  for (let i = 0; i < SCISSOR_N; i++) {
    const y = CARRIAGE_BOTTOM - h * (i + 0.5);
    bars[2 * i].position.y = y; bars[2 * i].rotation.x = -phi;
    bars[2 * i + 1].position.y = y; bars[2 * i + 1].rotation.x = phi;
    pins[k++].position.set(0, y, 0);                  // where the two bars cross
  }
  for (let i = 0; i <= SCISSOR_N; i++) {              // where the stages join
    const y = CARRIAGE_BOTTOM - h * i;
    pins[k++].position.set(0, y, -w / 2);
    pins[k++].position.set(0, y, w / 2);
  }
  foot.position.y = CARRIAGE_BOTTOM - H - 0.01;
}

function buildPulse() {
  const m = new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 48), new THREE.MeshBasicMaterial({
    color: 0x6ee07a, transparent: true, depthWrite: false, toneMapped: false,
    blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  }));
  m.rotation.x = -Math.PI / 2;
  m.visible = false;
  return m;
}

// ------------------------------------------------------------------ camera
// The trusses of the two rows either side of the rail, read once from the
// scene's own fruit: a box around each truss, its ripeness from its colour.
function indexTrusses(fruits) {
  const per = fruits.userData.perTruss, R = fruits.geometry.parameters.radius;
  const rows = [RAIL_X - ROW_PITCH / 2, RAIL_X + ROW_PITCH / 2];
  const m = new THREE.Matrix4(), p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
  const c = new THREE.Color(), hsl = {}, out = [];
  for (let t = 0; t < Math.floor(fruits.count / per); t++) {
    fruits.getMatrixAt(t * per, m);
    p.setFromMatrixPosition(m);
    const row = rows.findIndex((x) => Math.abs(p.x - x) < ROW_PITCH / 4);
    if (row < 0) continue;
    const bb = new THREE.Box3();
    let hue = 0, scale = 0;
    for (let k = 0; k < per; k++) {
      fruits.getMatrixAt(t * per + k, m);
      m.decompose(p, q, s);
      bb.expandByPoint(p.clone().addScalar(R * s.x)).expandByPoint(p.clone().subScalar(R * s.x));
      fruits.getColorAt(t * per + k, c);
      hue += c.getHSL(hsl).h / per;
      scale += s.x / per;
    }
    const cls = hue < 0.03 ? 'ripe' : hue < 0.14 ? 'breaking' : 'green';
    const f = THREE.MathUtils.clamp((scale - SCALE[0]) / (SCALE[1] - SCALE[0]), 0, 1);
    out.push({ id: t, side: row ? 1 : -1, box: bb, centre: bb.getCenter(new THREE.Vector3()),
               size: bb.getSize(new THREE.Vector3()), cls, mm: Math.round(MM[0] + f * (MM[1] - MM[0])) });
  }
  return out;
}

// A pool of wireframe boxes, each with its tag; reused round-robin. An alert
// pool's boxes pulse and its tags shout (⚠, title over detail).
function buildDetections({ size, hold, alert = false }) {
  const group = new THREE.Group();
  const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1));
  const pool = [];
  for (let i = 0; i < size; i++) {
    const lines = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({
      transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    }));
    lines.renderOrder = 13;
    lines.visible = false;
    const el = document.createElement('span');
    el.className = alert ? 'ws-tag ws-alert' : 'ws-tag';
    const tag = new CSS2DObject(el);
    tag.visible = false;
    group.add(lines, tag);
    pool.push({ lines, tag, el, age: Infinity });
  }
  let next = 0;
  return {
    group,
    // text: a string, or for an alert [title, detail]
    show(centre, extent, colour, text) {
      const d = pool[next];
      next = (next + 1) % size;
      d.lines.position.copy(centre);
      d.lines.scale.set(extent.x + 0.04, extent.y + 0.04, extent.z + 0.04);
      d.lines.material.color.set(colour);
      d.tag.position.set(centre.x, centre.y + extent.y / 2 + (alert ? 0.14 : 0.06), centre.z);
      if (alert) {
        const title = document.createElement('strong'), detail = document.createElement('span');
        title.textContent = `⚠ ${text[0]}`;
        detail.textContent = text[1];
        d.el.replaceChildren(title, detail);
      } else d.el.textContent = text;
      d.el.style.setProperty('--ws-c', colour);
      d.age = 0;
    },
    tick(dt, labels) {
      for (const d of pool) {
        d.age += dt;
        const a = d.age < hold ? 1 : 1 - (d.age - hold) / FADE_S;
        d.lines.visible = a > 0;
        d.tag.visible = a > 0 && labels;
        if (a <= 0) continue;
        d.lines.material.opacity = alert ? a * (0.55 + 0.45 * Math.sin(d.age * 6)) : a;
        d.el.style.opacity = String(a);
      }
    },
  };
}

// The incidents in the crop: specks on the path side of their row, around the
// height and place the camera will look; the whiteflies hover about theirs.
function buildIncidents(scene) {
  const group = new THREE.Group(), sprite = scene._sprite(), list = [];
  INCIDENTS.forEach((inc, k) => {
    const rnd = seeded(500 + k);
    const rowX = RAIL_X + (inc.side * ROW_PITCH) / 2;
    const c = new THREE.Vector3(rowX - inc.side * 0.12, LEVELS[inc.level], stopZ(inc.stop) + inc.dz);
    const base = new Float32Array(inc.n * 3), phase = new Float32Array(inc.n);
    for (let i = 0; i < inc.n; i++) {
      base[3 * i] = c.x + (rnd() - 0.5) * inc.spread[0];
      base[3 * i + 1] = c.y + (rnd() - 0.5) * inc.spread[1];
      base[3 * i + 2] = c.z + (rnd() - 0.5) * inc.spread[2];
      phase[i] = rnd() * Math.PI * 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(base.slice(), 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({
      color: inc.colour, size: inc.size, map: sprite, transparent: true, opacity: inc.opacity, depthWrite: false,
    }));
    pts.frustumCulled = false;
    group.add(pts);
    geo.computeBoundingBox();
    const box = geo.boundingBox.clone().expandByScalar(inc.flutter + 0.03);
    list.push({ ...inc, pts, base, phase, centre: box.getCenter(new THREE.Vector3()), extent: box.getSize(new THREE.Vector3()) });
  });
  return {
    group, list,
    tick(t) {
      for (const inc of list) {
        if (!inc.flutter) continue;
        const pos = inc.pts.geometry.attributes.position;
        for (let i = 0; i < inc.n; i++) {
          const ph = inc.phase[i];
          pos.setXYZ(i, inc.base[3 * i] + inc.flutter * Math.sin(t * 5.3 + ph),
            inc.base[3 * i + 1] + inc.flutter * Math.sin(t * 7.1 + 2 * ph),
            inc.base[3 * i + 2] + inc.flutter * Math.cos(t * 6.2 + ph));
        }
        pos.needsUpdate = true;
      }
    },
  };
}

// ------------------------------------------------------------------ card
// One synthetic reading in a row at a stop and height (the same every tour).
function synthReading(ri, stop, level) {
  const rnd = seeded(7000 + 100 * ri + 10 * stop + level), n = () => rnd() * 2 - 1;
  const up = LEVELS[level] - LEVELS[0];
  const air = (q) => q.base + q.perM * up + q.perStop * stop + q.perRow * ri + q.noise * n();
  const above = Math.max(0, SYNTH.CANOPY_TOP - LEVELS[level]) * SYNTH.LAI_PER_M;
  const P = SYNTH.T_PATCH, top = LEVELS.at(-1) - LEVELS[0];
  const patch = P.dT[ri] * Math.exp(-(((stop - P.at) / P.width) ** 2)) * (0.4 + 0.6 * (up / top));
  return { t: air(SYNTH.T) + patch, rh: air(SYNTH.RH), co2: air(SYNTH.CO2),
           par: SYNTH.PAR_TOP * Math.exp(-SYNTH.K * above) * (1 + SYNTH.PAR_NOISE * n()) };
}

const fx = (x, d = 0) => (x == null ? '–' : x.toFixed(d));
const rowName = (ri) => `section ${ROWS[ri].section}, row ${ROWS[ri].id}`;

function statusText(u) {
  if (u.stage === 'charging') return 'at the station';
  if (u.stage === 'returning') return 'back to the station';
  const row = rowName(u.row), stop = `stop ${u.stop + 1}/${STOPS}`;
  if (u.stage === 'driving') return `${row} · to ${stop}`;
  const at = `${row} · ${stop} · ${fx(Z_DOCK - u.z, 1)} m`;
  if (u.stage === 'sending') return `${at} · LoRaWAN`;
  return u.level == null ? at : `${at} · head at ${fx(LEVELS[u.level], 1)} m`;
}

function cardHtml(u, problems, follow) {
  const pct = Math.round(u.battery);
  const dot = (cls) => `<span><i style="background:${CLASS_COLOUR[cls]}"></i>${u.tally[cls]} ${cls}</span>`;
  const found = problems.length
    ? problems.map((p) => `<li>⚠ <strong>${p.title}</strong> · ${p.detail} · ${rowName(p.row)}, stop ${p.stop + 1}, ${fx(p.y, 1)} m</li>`).join('')
    : '<li class="ws-none">none found yet</li>';
  return `
    <div class="ws-head"><strong>WireScout</strong><span>concept demo</span>
      <button type="button" class="ws-x" data-ws="close" aria-label="Close the WireScout demo">×</button></div>
    <p class="ws-note">A 100 m row, a stop every 20 m, five heights 500 mm apart: drawn here over this house's rows.</p>
    <div class="ws-status"><span class="ws-stage" data-stage="${u.stage}">${STAGE[u.stage]}</span>${statusText(u)}</div>
    <div class="ws-batt"><span>Battery</span><i><b style="width:${pct}%"></b></i><span>${pct} %</span></div>
    <div class="ws-sub">Problems this tour</div>
    <ul class="ws-problems">${found}</ul>
    <div class="ws-sub">Trusses this tour</div>
    <div class="ws-tally">${dot('ripe')}${dot('breaking')}${dot('green')}</div>
    <div class="ws-foot">
      <button type="button" class="ws-chip${follow ? ' is-on' : ''}" data-ws="follow" aria-pressed="${follow}">Follow</button>
      <span>synthetic demo values</span>
    </div>`;
}

// ------------------------------------------------------------------ panel
// A temperature section per row, filled in live as the unit inspects it: a
// column at each stop, a row at each height. Drawn by the same code as the
// multi-height sensors' section (microclimate.js), on the unit's own grid, and
// in temperature's hue on this page.
const T_HUE = '#f47230';
const SECTION_AX = { xs: Array.from({ length: STOPS }, (_, s) => Z_DOCK - stopZ(s)), ys: LEVELS,
                     k: LEVELS.map((_, i) => i) };
const SECTION_HEIGHTS = { heights: LEVELS.map((m) => ({ m })) };

// One colour scale for the whole tour (all its synthetic readings, both rows),
// so the rows compare and a column keeps its colour as the others arrive.
function tourScale() {
  const ts = ROWS.flatMap((_, ri) => SECTION_AX.xs.flatMap((_, s) => LEVELS.map((_, lv) => synthReading(ri, s, lv).t)));
  return [Math.floor(Math.min(...ts) * 10) / 10, Math.ceil(Math.max(...ts) * 10) / 10];
}

// The fixed multi-height row on this page, for comparison: strings × heights.
function fixedGrid() {
  try {
    const g = JSON.parse(document.getElementById('gh-micro-geom').textContent);
    return { wires: g.wires.length, heights: g.heights.length };
  } catch { return null; }
}

function panelHtml(scale, lut) {
  const x1 = SECTION_AX.xs.at(-1), y0 = LEVELS[0], y1 = LEVELS.at(-1);
  const yl = LEVELS.map((m) => `<span style="top:${((y1 - m) / (y1 - y0)) * 100}%">${fx(m, 1)} m</span>`).join('');
  const xl = SECTION_AX.xs.map((x) => `<span style="left:${(x / x1) * 100}%">${fx(x)} m</span>`).join('');
  const fixed = fixedGrid(), n = STOPS * LEVELS.length;
  const compare = fixed
    ? ` The fixed multi-height sensors on this page: <strong>${fixed.wires * fixed.heights}</strong> (${fixed.wires} strings × ${fixed.heights} heights).`
    : '';
  const plot = (ri) => `
    <div class="ws-row" data-row="${ri}">
      <h4>Section ${ROWS[ri].section} · row ${ROWS[ri].id} <span class="ws-live">● live</span></h4>
      <div class="gh-xs ws-xs">
        <div class="gh-xs-y">${yl}</div>
        <div class="gh-xs-plot"><canvas aria-label="WireScout temperature section, ${rowName(ri)}"></canvas></div>
        <div></div><div class="gh-xs-x">${xl}</div>
      </div>
    </div>`;
  return `
    <div class="gh-panel-head"><h3>WireScout · temperature</h3></div>
    <p class="gh-muted">Each row's section fills in as the unit inspects it: ${rowName(0)} on the way out, ${rowName(1)} on the way back. Hatched: not measured yet this tour.</p>
    ${ROWS.map((_, ri) => plot(ri)).join('')}
    <p class="gh-xs-key"><span class="gh-micro-legend"><span>${fx(scale[0], 1)} °C</span>
      <span class="gh-micro-ramp" style="background:${gradient(lut)}"></span><span>${fx(scale[1], 1)} °C</span></span></p>
    <p class="ws-res">Points per row and tour: <strong>${n}</strong> (${STOPS} stops × ${LEVELS.length} heights).${compare}</p>
    <h4 class="ws-read-title"></h4>
    <table class="gh-kv gh-xs-table ws-read-table"></table>
    <p class="gh-muted"><em>synthetic demo values</em></p>`;
}

function readTableHtml(u, reads) {
  const now = reads.row === u.row && reads.stop === u.stop && u.stage === 'measuring';
  const rows = LEVELS.map((y, lv) => {
    const r = reads.rows[lv];
    return `<tr class="${now && u.level === lv ? 'is-now' : ''}">`
      + `<td>${fx(y, 1)} m</td><td>${fx(r?.t, 1)}</td><td>${fx(r?.rh)}</td><td>${fx(r?.co2)}</td><td>${fx(r?.par)}</td></tr>`;
  }).reverse().join('');
  return `<thead><tr><th>Height</th><th>T °C</th><th>RH %</th><th>CO₂ ppm</th><th>PAR</th></tr></thead><tbody>${rows}</tbody>`;
}

// Paints a row's section: the colours (cached, redrawn only when a reading
// arrives or the canvas resizes), then the measuring points and, on the row
// being inspected, the unit.
function sectionPainter(canvas, lut, scale) {
  const base = document.createElement('canvas');
  let baseKey = '';
  const x1 = SECTION_AX.xs.at(-1), y0 = LEVELS[0], y1 = LEVELS.at(-1);
  return (values, unit) => {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = Math.round(canvas.clientWidth * dpr), H = Math.round(canvas.clientHeight * dpr);
    if (!W || !H) return;
    const key = `${W}x${H}|${JSON.stringify(values)}`;
    if (key !== baseKey) {
      base.width = W; base.height = H;
      drawSection(base, SECTION_AX, values, lut, scale);
      baseKey = key;
    }
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(base, 0, 0);
    const clampX = (x) => Math.min(W - 5 * dpr, Math.max(5 * dpr, x));
    const clampY = (y) => Math.min(H - 5 * dpr, Math.max(5 * dpr, y));
    SECTION_AX.xs.forEach((_, s) => LEVELS.forEach((_, lv) => {
      const [x, y] = nodeXY(SECTION_AX, SECTION_HEIGHTS, s, lv, W, H);
      const v = values[s]?.[lv];
      ctx.beginPath();
      ctx.arc(clampX(x), clampY(y), (v == null ? 2.5 : 3.5) * dpr, 0, 2 * Math.PI);
      if (v != null) { ctx.fillStyle = rgbCss(colourOf(lut, v, scale)); ctx.fill(); }
      ctx.lineWidth = 1.2 * dpr;
      ctx.strokeStyle = v == null ? 'rgba(255, 255, 255, 0.45)' : '#fff';
      ctx.stroke();
    }));
    if (!unit) return;
    // where the unit is along the row, and its head
    const mx = clampX((Math.min(x1, Math.max(0, unit.along)) / x1) * W);
    ctx.setLineDash([4 * dpr, 3 * dpr]);
    ctx.lineWidth = 1.2 * dpr;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.beginPath(); ctx.moveTo(mx, 0); ctx.lineTo(mx, H); ctx.stroke();
    ctx.setLineDash([]);
    if (unit.headY >= y0 - 0.05 && unit.headY <= y1 + 0.05) {
      ctx.beginPath();
      ctx.arc(mx, clampY(((y1 - unit.headY) / (y1 - y0)) * H), 7 * dpr, 0, 2 * Math.PI);
      ctx.lineWidth = 2 * dpr; ctx.strokeStyle = '#ffe9a8'; ctx.stroke();
    }
  };
}

// ------------------------------------------------------------------ start
export function start(scene) {
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = new URL('./wirescout.css', import.meta.url).href;
  document.head.append(css);

  const M = materials(scene);
  const group = new THREE.Group();
  const station = buildStation(M);
  const { unit, scissor, head, cone } = buildUnit(M);
  const pulse = buildPulse();
  const det = buildDetections(FRUIT_TAGS), alerts = buildDetections(ALERT_TAGS);
  const incidents = buildIncidents(scene);
  group.add(buildRail(M), station.group, unit, pulse, det.group, alerts.group, incidents.group);
  scene.scene.add(group);

  const u = { z: Z_DOCK, headY: PARK_Y, yaw: 0, flash: 0, pulse: null, battery: BATTERY_START,
              stage: 'charging', row: null, stop: null, level: null,
              tally: { ripe: 0, breaking: 0, green: 0, flags: 0 } };
  const trusses = indexTrusses(scene.fruits);
  // per tour: trusses seen, problems found, and each row's section [stop][level]
  let seen = new Set(), problems = [], sections = ROWS.map(() => []);
  let reads = { row: null, stop: null, rows: [] };   // the readings at the latest stop
  const ev = {
    tour() {
      seen = new Set(); problems = []; sections = ROWS.map(() => []);
      u.tally = { ripe: 0, breaking: 0, green: 0, flags: 0 };
    },
    capture(_, level, side) {
      const y = LEVELS[level];
      if (reads.row !== u.row || reads.stop !== u.stop) reads = { row: u.row, stop: u.stop, rows: [] };
      reads.rows[level] = synthReading(u.row, u.stop, level);
      (sections[u.row][u.stop] ??= [])[level] = reads.rows[level].t;
      for (const t of trusses) {
        if (t.side !== side || Math.abs(t.centre.z - u.z) > VIEW_Z || Math.abs(t.centre.y - y) > VIEW_Y) continue;
        det.show(t.centre, t.size, CLASS_COLOUR[t.cls], `${t.cls} · ${t.mm} mm`);
        if (!seen.has(t.id)) { seen.add(t.id); u.tally[t.cls] += 1; }
      }
      for (const inc of incidents.list) {
        if (inc.stop !== u.stop || inc.side !== side || inc.level !== level) continue;
        alerts.show(inc.centre, inc.extent, CLASS_COLOUR.flag, [inc.title, inc.detail(inc.n)]);
        u.tally.flags += 1;
        problems.push({ title: inc.title, detail: inc.detail(inc.n), row: u.row, stop: u.stop, y });
      }
    },
  };
  const script = cycle(u, ev);
  script.next();                       // run to the first yield; later calls carry dt

  // Follow: the camera moves with the head, along the rail and up and down,
  // keeping whatever angle the viewer orbits to. Any other flight (a part, the
  // overview) ends it.
  scene._fly([RAIL_X, PARK_Y - 0.3, Z_DOCK - 3.6], [RAIL_X, PARK_Y - 0.2, Z_DOCK], true);
  const ownFlight = scene._flight;
  let follow = true, lastZ = u.z, lastY = u.headY;

  // the card, in place of the outdoor readouts while the demo runs; drawn
  // again only when what it shows has changed
  const viewer = scene.container;
  viewer.classList.add('ws-on');
  const card = document.createElement('section');
  card.className = 'ws-card';
  card.setAttribute('aria-label', 'WireScout concept demo');
  viewer.append(card);
  let cardKey = '';
  const drawCard = () => {
    const key = JSON.stringify([u.stage, u.row, u.stop, u.level, Math.round(u.battery), u.tally, problems.length, follow]);
    if (key === cardKey) return;
    cardKey = key;
    card.innerHTML = cardHtml(u, problems, follow);
  };
  let handle = null;
  card.addEventListener('click', (e) => {
    const what = e.target.closest('[data-ws]')?.dataset.ws;
    if (what === 'close') handle.stop();
    if (what === 'follow') { follow = !follow; drawCard(); }
  });

  // the panel beside the view, in place of the page's own while the demo runs
  const stageEl = viewer.parentElement;
  stageEl.classList.add('ws-on');
  const lut = ramp(T_HUE), scale = tourScale();
  const panel = document.createElement('aside');
  panel.className = 'gh-panel ws-panel';
  panel.setAttribute('aria-live', 'polite');
  panel.innerHTML = panelHtml(scale, lut);
  viewer.after(panel);
  const rowEls = [...panel.querySelectorAll('.ws-row')];
  const painters = rowEls.map((el) => sectionPainter(el.querySelector('canvas'), lut, scale));
  const readTitle = panel.querySelector('.ws-read-title'), readTable = panel.querySelector('.ws-read-table');
  const paintKeys = ROWS.map(() => '');
  let tableKey = '';
  const drawPanel = () => {
    const along = Z_DOCK - u.z;
    ROWS.forEach((_, ri) => {
      const live = u.row === ri;
      const k = JSON.stringify([sections[ri], live && [Math.round(along * 20), Math.round(u.headY * 40)], panel.clientWidth]);
      if (k === paintKeys[ri]) return;
      paintKeys[ri] = k;
      rowEls[ri].classList.toggle('is-live', live);
      painters[ri](sections[ri], live ? { along, headY: u.headY } : null);
    });
    const tk = JSON.stringify([reads, u.row, u.level, u.stage, u.stop]);
    if (tk === tableKey) return;
    tableKey = tk;
    readTitle.textContent = reads.row == null ? 'Readings'
      : `Readings · ${rowName(reads.row)}, stop ${reads.stop + 1}`;
    readTable.innerHTML = readTableHtml(u, reads);
  };

  const tick = (dt) => {
    script.next(dt);
    if (u.stage !== 'charging') u.battery = Math.max(BATTERY[0], u.battery - DRAIN_PER_S * dt);
    unit.position.z = u.z;
    head.position.y = u.headY;
    head.rotation.y = u.yaw;
    setScissor(scissor, u.headY);
    M.ring.color.setScalar(0.85 + 1.6 * u.flash);
    cone.visible = u.level != null;
    cone.material.opacity = 0.05 + 0.2 * u.flash;
    station.bolt.material.color.setScalar(u.stage === 'charging' ? 0.6 + 0.4 * Math.sin(performance.now() / 180) : 0.35);
    pulse.visible = u.pulse != null;
    if (pulse.visible) {
      pulse.position.set(RAIL_X, RAIL_Y, u.z);
      pulse.scale.setScalar(0.2 + 3.2 * u.pulse);
      pulse.material.opacity = 0.85 * (1 - u.pulse);
    }
    det.tick(dt, scene.layers.labels);
    alerts.tick(dt, scene.layers.labels);
    incidents.tick(performance.now() / 1000);
    if (scene._flight && scene._flight !== ownFlight) follow = false;
    if (follow && !scene._flight) {
      const d = new THREE.Vector3(0, u.headY - lastY, u.z - lastZ);
      scene.camera.position.add(d);
      scene.controls.target.add(d);
    }
    lastZ = u.z;
    lastY = u.headY;
    drawCard();
    drawPanel();
    return true;
  };
  scene.addTicker(tick);

  handle = {
    stop() {
      scene.removeTicker(tick);
      scene.scene.remove(group);       // a removed CSS2DObject takes its element with it
      group.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
      card.remove();
      panel.remove();
      viewer.classList.remove('ws-on');
      stageEl.classList.remove('ws-on');
      css.remove();
    },
  };
  return handle;
}
