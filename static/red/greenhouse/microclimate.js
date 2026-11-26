// The microclimate section: the multi-height sensors' readings, drawn as one
// vertical cross-section along their row (the panel shows it flat; the scene
// colours the crop along the row with it). The server sends only measurements (per step,
// per sensor, per height); this module fills the space between them for drawing
// and nothing else — the page never states an interpolated number as measured.
//
// Interpolation: straight lines along the row and up the canopy, separately
// (bilinear on the real, unequal metres). In greenhouses the temperature
// difference between two places grows about linearly with distance, and for
// that a straight line between two neighbours is what kriging would give; three
// positions along the row could not support any fitted spatial model. It passes
// through every measurement, never leaves the range of its four corners, and
// draws nothing beyond the outer sensors. A square with a missing corner is
// hatched, not guessed.

// ------------------------------------------------------------------ colour
// One hue per metric, light for high and dark for low: the viewer is a dark
// scene, where the low end recedes. Steps are even in OKLab lightness.
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const gam = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

function hexToOklab(hex) {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => lin(c / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}

function oklabToRgb(L, a, b) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
}

const LUT_SIZE = 256;
const L_LOW = 0.3, L_HIGH = 0.93;

// 256 colours from dark to light in the hue of ``hex``, as [r, g, b] 0-255.
// Chroma peaks mid-ramp and is pulled in wherever it would leave sRGB.
export function ramp(hex) {
  const [, a0, b0] = hexToOklab(hex);
  const c0 = Math.hypot(a0, b0), h = Math.atan2(b0, a0);
  const lut = [];
  for (let i = 0; i < LUT_SIZE; i++) {
    const t = i / (LUT_SIZE - 1);
    const L = L_LOW + (L_HIGH - L_LOW) * t;
    let c = c0 * (0.45 + 0.55 * Math.sin(Math.PI * Math.min(1, t * 1.15)));
    let rgb = oklabToRgb(L, c * Math.cos(h), c * Math.sin(h));
    while (rgb.some((v) => v < 0 || v > 1) && c > 0.001) {
      c *= 0.94;
      rgb = oklabToRgb(L, c * Math.cos(h), c * Math.sin(h));
    }
    lut.push(rgb.map((v) => Math.round(255 * gam(Math.min(1, Math.max(0, v))))));
  }
  return lut;
}

export const css = ([r, g, b]) => `rgb(${r} ${g} ${b})`;

export function colourOf(lut, value, scale) {
  if (value == null || !scale) return null;
  const t = (value - scale[0]) / Math.max(1e-9, scale[1] - scale[0]);
  return lut[Math.round(Math.min(1, Math.max(0, t)) * (LUT_SIZE - 1))];
}

// A CSS gradient of the ramp, low on the left, for the legend.
export const gradient = (lut) => `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1]
  .map((t) => `${css(lut[Math.round(t * (LUT_SIZE - 1))])} ${t * 100}%`).join(', ')})`;

// Hatch for "no reading": the same two greys in the legend and the section.
export const HATCH = { light: [92, 98, 108], dark: [52, 57, 65] };
export const hatchCss = `repeating-linear-gradient(135deg, ${css(HATCH.light)} 0 2px, ${css(HATCH.dark)} 2px 6px)`;

// ------------------------------------------------------------------ geometry
// The section's axes in metres: ``xs`` along the row (wire order), ``ys`` up
// (heights sorted from the floor), with the payload's height index per ``ys``.
export function axes(section) {
  const xs = section.wires.map((w) => w.at_m);
  const up = section.heights.map((h, k) => ({ m: h.m, k })).sort((p, q) => p.m - q.m);
  return { xs, ys: up.map((p) => p.m), k: up.map((p) => p.k) };
}

// The segment ``x`` falls in along ascending ``xs`` and how far along it.
function locate(xs, x) {
  if (x < xs[0] || x > xs[xs.length - 1]) return null;
  let i = 0;
  while (i < xs.length - 2 && x > xs[i + 1]) i++;
  const span = xs[i + 1] - xs[i];
  return [i, span > 0 ? (x - xs[i]) / span : 0];
}

// The value at (``x`` m along the row, ``y`` m high) for one step's grid
// ``values[wire][height]``: bilinear between the four sensors around it, or
// null outside the sensors or when any of the four has no reading.
export function valueAt(ax, values, x, y) {
  const px = locate(ax.xs, x), py = locate(ax.ys, y);
  if (!px || !py || !values) return null;
  const [i, u] = px, [j, w] = py;
  const at = (wi, yj) => values[wi]?.[ax.k[yj]];
  const c00 = at(i, j), c10 = at(i + 1, j), c01 = at(i, j + 1), c11 = at(i + 1, j + 1);
  if (c00 == null || c10 == null || c01 == null || c11 == null) return null;
  return (1 - u) * (1 - w) * c00 + u * (1 - w) * c10 + (1 - u) * w * c01 + u * w * c11;
}

// ------------------------------------------------------------------ drawing
// The section into ``canvas`` (any size): left = first wire, top = highest
// sensor. ``values`` is one step's [wire][height] grid, or null for a step
// with no readings at all. Where a reading is missing the section is hatched,
// or left transparent with ``clear`` (the scene's crop then keeps its colour).
export function drawSection(canvas, ax, values, lut, scale, { clear = false } = {}) {
  const W = canvas.width, H = canvas.height;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(W, H);
  const x0 = ax.xs[0], x1 = ax.xs[ax.xs.length - 1];
  const y0 = ax.ys[0], y1 = ax.ys[ax.ys.length - 1];
  for (let py = 0; py < H; py++) {
    const y = y1 - ((py + 0.5) / H) * (y1 - y0);
    for (let px = 0; px < W; px++) {
      const x = x0 + ((px + 0.5) / W) * (x1 - x0);
      const v = valueAt(ax, values, x, y);
      const c = colourOf(lut, v, scale);
      const rgb = c || ((px + py) % 8 < 3 ? HATCH.light : HATCH.dark);
      const o = (py * W + px) * 4;
      img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2];
      img.data[o + 3] = c || !clear ? 255 : 0;
    }
  }
  ctx.putImageData(img, 0, 0);
}

// Pixel position of sensor (wire ``wi``, payload height ``k``) on a canvas
// drawn by ``drawSection``.
export function nodeXY(ax, section, wi, k, W, H) {
  const x0 = ax.xs[0], x1 = ax.xs[ax.xs.length - 1];
  const y0 = ax.ys[0], y1 = ax.ys[ax.ys.length - 1];
  return [((ax.xs[wi] - x0) / (x1 - x0)) * W, ((y1 - section.heights[k].m) / (y1 - y0)) * H];
}
