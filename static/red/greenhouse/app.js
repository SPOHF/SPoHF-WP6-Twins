// The /greenhouse page: fetches a day from the API, drives the 3D scene, and
// renders the timeline, the day-length dial, the component panel, the advice
// and tomorrow's light. All numbers arrive computed and in local time; what
// each one means arrives with the page (#gh-explain) and opens in a balloon.
// Every word on the page comes from the language bundle (#gh-i18n); numbers
// and dates are written the language's way (Intl).

import { GreenhouseScene } from './scene.js';

const root = document.getElementById('gh-app');
const API = root.dataset.api;
const LANG = root.dataset.lang || 'en';
const $ = (id) => document.getElementById(id);
const NOTES = JSON.parse($('gh-explain').textContent);
const I18N = JSON.parse($('gh-i18n').textContent);
const REFS = JSON.parse($('gh-refs').textContent);  // [^id] → literature (not translated)
// the values behind every "configured", and the LetsGrow ids behind plain names
const CONFIG = JSON.parse($('gh-config').textContent);

// A string from the bundle, {placeholders} filled (values are formatted by the caller).
const T = (key, p = {}) => (I18N[key] ?? key).replace(/\{(\w+)\}/g, (m, k) => (k in p ? p[k] : m));

const COMPONENT_IDS = ['lamps', 'pipes', 'vents', 'screen', 'crop', 'substrate', 'weather', 'cover', 'sensors'];
const NAMES = Object.fromEntries(COMPONENT_IDS.map((k) => [k, T(`comp.${k}`)]));

// One colour per flow, the same in the panel and in the 3D arrows.
const FLOW = {
  sun: { colour: '#f2a600', note: 'sun' },
  lamps: { colour: '#ee7fac', note: 'lamp_power' },
  pipes: { colour: '#f47230', note: 'pipe_heat' },
  cover: { colour: '#257de0', note: 'cover' },
  ventilation: { colour: '#00b894', note: 'ventilation' },
  evaporation: { colour: '#9887ef', note: 'evaporation' },
  residual: { colour: '#9c9c9c', note: 'residual' },
};
const C = { blue: '#257de0', orange: '#f47230', aqua: '#00b894', yellow: '#f2a600', magenta: '#ee7fac',
            violet: '#9887ef', grey: '#9c9c9c', night: '#1b2436' };

const ui = { day: null, i: 0, playing: false, timer: null, selected: null, whatif: null };

// ------------------------------------------------------------------ format
const NF = {};
const num = (x, d = 0) => {
  if (x == null || Number.isNaN(Number(x))) return '–';
  NF[d] ||= new Intl.NumberFormat(LANG, { minimumFractionDigits: d, maximumFractionDigits: d });
  return NF[d].format(Number(x));
};
const pct = (x) => (x == null ? '–' : `${num(x * 100)}%`);
const signed = (x, d = 0) => `${x > 0 ? '+' : ''}${num(x, d)}`;
const DF = new Intl.DateTimeFormat(LANG, { day: 'numeric', month: 'short', year: 'numeric' });
const fmtDate = (iso) => (iso ? DF.format(new Date(`${iso}T12:00:00`)) : '');
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const code = (s) => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>');
// [word](cfg:group), (tag:…), (mod:…), (term:…) in escaped prose → a word with a
// popup behind it: the configured values, a LetsGrow series or module, a term.
const terms = (html) => html.replace(/\[([^\]]+)\]\((cfg|tag|mod|term):([a-z0-9_]+)\)/g,
  (m, text, kind, id) => `<button type="button" class="gh-term" data-kind="${kind}" data-id="${id}">${text}</button>`);
// Catalogue prose as the page shows it: terms and numbered citations.
const prose = (text) => citer().mark(terms(code(text)));

// ------------------------------------------------------------------ notes
// Literature markers [^id] become small numbers, in order of first use within
// one balloon or card; each opens a tip with the reference (see tipHtml), so
// the text stays short and no source list trails it.
function citer() {
  const order = [];
  const mark = (html) => html.replace(/\[\^([a-z0-9_]+)\]/g, (m, id) => {
    if (!REFS[id]) return '';
    if (!order.includes(id)) order.push(id);
    return `<sup class="gh-fn"><button type="button" class="gh-term gh-fn-btn" data-kind="ref" data-id="${id}"`
      + ` aria-label="${esc(REFS[id].label)}">${order.indexOf(id) + 1}</button></sup>`;
  });
  return { mark };
}

// An explanation's three parts, with its citations listed under them.
function noteHtml(n, heading = 'h5') {
  const c = citer();
  const part = (field) => `<${heading}>${T(`balloon.${field}`)}</${heading}><p class="gh-note">${c.mark(terms(code(n[field])))}</p>`;
  return part('how') + part('source') + part('read');
}

// ------------------------------------------------------------------ balloon
// One balloon at a time, anchored under (or over) whatever was clicked.
const balloon = document.createElement('div');
balloon.className = 'gh-balloon';
balloon.hidden = true;
balloon.setAttribute('role', 'dialog');
document.body.appendChild(balloon);

function openNote(anchor, key, value) {
  const n = NOTES[key];
  if (!n) return;
  if (!balloon.hidden && balloon.dataset.key === key && balloon._anchor === anchor) { closeNote(); return; }
  balloon.dataset.key = key;
  balloon._anchor = anchor;
  balloon.innerHTML = `
    <div class="gh-balloon-head"><strong>${esc(n.title)}</strong>
      <span class="gh-scope scope-${n.scope}">${T(`scope.${n.scope}`)}</span>
      <button type="button" class="gh-close" aria-label="${T('close')}">×</button></div>
    ${value ? `<div class="gh-balloon-value">${esc(value)}</div>` : ''}
    ${noteHtml(n)}`;
  balloon.setAttribute('aria-label', n.title);
  balloon.hidden = false;
  balloon.querySelector('.gh-close').addEventListener('click', closeNote);
  // place it: under the anchor if it fits, else over it; arrow on the anchor
  const r = anchor.getBoundingClientRect();
  const bw = Math.min(380, window.innerWidth - 16);
  balloon.style.width = `${bw}px`;
  const left = Math.max(8, Math.min(window.innerWidth - bw - 8, r.left + r.width / 2 - bw / 2));
  const bh = balloon.offsetHeight;
  const below = r.bottom + 10 + bh < window.innerHeight || r.top < bh + 10;
  balloon.classList.toggle('is-above', !below);
  balloon.style.left = `${left + window.scrollX}px`;
  balloon.style.top = `${(below ? r.bottom + 10 : r.top - 10 - bh) + window.scrollY}px`;
  balloon.style.setProperty('--arrow', `${Math.max(14, Math.min(bw - 14, r.left + r.width / 2 - left))}px`);
}

function closeNote() { balloon.hidden = true; balloon._anchor = null; hideTip(); }

// ------------------------------------------------------------------ tips
// A small popup behind a "configured" word, a LetsGrow series or module, or a
// term: on hover, on keyboard focus, and on tap or click (which pins it open).
const tip = document.createElement('div');
tip.className = 'gh-tip';
tip.hidden = true;
tip.setAttribute('role', 'tooltip');
document.body.appendChild(tip);
const tipState = { el: null, pinned: false, timer: null };

function cfgTable(group) {
  const rows = CONFIG.groups[group].rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${esc(r.value)}</td>
    <td><span class="gh-src src-${r.source}">${esc(CONFIG.sources[r.source])}</span></td></tr>`).join('');
  return `<table class="gh-cfg"><tbody>${rows}</tbody></table>`;
}

function tipHtml(kind, id, text) {
  if (kind === 'cfg') {
    const groups = id === 'all' ? Object.keys(CONFIG.groups) : [id].filter((g) => CONFIG.groups[g]);
    const title = id === 'all' ? T('tip.all') : `${T('tip.configured')} · ${CONFIG.groups[id]?.title ?? id}`;
    const body = groups.map((g) => `${id === 'all' ? `<h6>${esc(CONFIG.groups[g].title)}</h6>` : ''}${cfgTable(g)}`).join('');
    return `<strong>${esc(title)}</strong>${body}<p class="gh-tip-note">${esc(T('tip.configured_note'))}</p>`;
  }
  if (kind === 'tag') {
    const mod = CONFIG.modules[CONFIG.tags[id]];
    return `<strong>${text}</strong><p>${esc(T('tip.series'))}${mod ? ` · ${esc(mod.name)}` : ''}, ${esc(T('tip.series_note'))}</p><code>${esc(id)}</code>`;
  }
  if (kind === 'ref') {
    const r = REFS[id];
    if (!r) return '';
    const host = r.url.replace(/^https?:\/\/(www\.)?/, '').replace(/\/.*$/, '');
    return `<strong>${esc(r.label)}</strong><p>${esc(r.cite)}</p>`
      + `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(T('tip.open_source', { host }))} ↗</a>`;
  }
  if (kind === 'mod') {
    const mod = CONFIG.modules[id];
    return mod ? `<strong>${esc(T('tip.module'))} · ${esc(mod.name)}</strong><p>${esc(mod.about)}</p><code>${esc(mod.device)}</code>` : '';
  }
  return `<strong>${text}</strong><p>${esc(T(`term.${id}`))}</p>`;
}

function showTip(el) {
  clearTimeout(tipState.timer);
  const html = tipHtml(el.dataset.kind, el.dataset.id, el.innerHTML);
  if (!html) return;
  tipState.el = el;
  tip.innerHTML = html;
  tip.classList.toggle('is-wide', el.dataset.kind === 'cfg');
  tip.hidden = false;
  const r = el.getBoundingClientRect();
  const w = Math.min(el.dataset.kind === 'cfg' ? 420 : 300, window.innerWidth - 16);
  tip.style.width = `${w}px`;
  const left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2));
  const h = tip.offsetHeight;
  const below = r.bottom + 8 + h < window.innerHeight || r.top < h + 8;
  tip.style.left = `${left + window.scrollX}px`;
  tip.style.top = `${(below ? r.bottom + 6 : r.top - 6 - h) + window.scrollY}px`;
}

function hideTip() { clearTimeout(tipState.timer); tip.hidden = true; tipState.el = null; tipState.pinned = false; }
const hideTipSoon = () => { if (!tipState.pinned) tipState.timer = setTimeout(hideTip, 200); };

document.addEventListener('mouseover', (e) => {
  const el = e.target.closest('.gh-term');
  if (el && !tipState.pinned) showTip(el);
});
document.addEventListener('mouseout', (e) => { if (e.target.closest('.gh-term')) hideTipSoon(); });
tip.addEventListener('mouseenter', () => clearTimeout(tipState.timer));
tip.addEventListener('mouseleave', hideTipSoon);
document.addEventListener('focusin', (e) => { const el = e.target.closest?.('.gh-term'); if (el) showTip(el); });
document.addEventListener('focusout', (e) => { if (e.target.closest?.('.gh-term')) hideTipSoon(); });

document.addEventListener('click', (e) => {
  const term = e.target.closest('.gh-term');
  if (term) {
    e.stopPropagation();
    if (tipState.pinned && tipState.el === term) { hideTip(); return; }
    showTip(term);
    tipState.pinned = true;
    return;
  }
  if (!tip.hidden && !e.target.closest('.gh-tip')) hideTip();
  const el = e.target.closest('[data-note]');
  if (el) { e.stopPropagation(); openNote(el, el.dataset.note, el.dataset.value); return; }
  if (!balloon.hidden && !e.target.closest('.gh-balloon')) closeNote();
});
window.addEventListener('resize', closeNote);

// A table row that opens its note: [label, value, key]
const row = ([label, value, key]) => `<tr class="gh-row" data-note="${key}" data-value="${esc(`${label}: ${value}`)}" tabindex="0">
  <td>${esc(label)}<span class="gh-i" aria-hidden="true">i</span></td><td>${esc(value)}</td></tr>`;
const kv = (rows) => `<table class="gh-kv"><tbody>${rows.map(row).join('')}</tbody></table>`;

// ------------------------------------------------------------------ charts
// A small single-unit line chart (one y-axis, never two). series: [{name, values, colour}]
function lineChart({ series, t, marker, unit, height = 120, bands = [], fixed = null }) {
  const W = 340, H = height, pl = 34, pr = 8, pt = 20, pb = 18;
  const all = series.flatMap((s) => s.values).filter((v) => v != null && Number.isFinite(v));
  if (!all.length) return `<p class="gh-muted">${T('no_data')}</p>`;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (fixed) { [lo, hi] = fixed; } else {
    if (lo > 0 && lo / (hi || 1) < 0.35) lo = 0;
    if (hi - lo < 1e-6) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.08; hi += pad; lo = lo === 0 ? 0 : lo - pad;
  }
  const n = t.length;
  const x = (i) => pl + (i / Math.max(1, n - 1)) * (W - pl - pr);
  const y = (v) => pt + (1 - (v - lo) / (hi - lo)) * (H - pt - pb);
  const ticks = [lo, (lo + hi) / 2, hi];
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="gh-chart" role="img" aria-label="${esc(series.map((s) => s.name).join(', '))}">`;
  for (const b of bands) {
    svg += `<rect x="${x(b[0])}" y="${pt}" width="${Math.max(1, x(b[1]) - x(b[0]))}" height="${H - pt - pb}" class="gh-band"/>`;
  }
  for (const v of ticks) {
    svg += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" class="gh-grid"/>`;
    svg += `<text x="${pl - 4}" y="${y(v) + 3}" text-anchor="end" class="gh-axis">${num(v, Math.abs(hi - lo) < 5 ? 1 : 0)}</text>`;
  }
  for (const h of [0, 6, 12, 18, 24]) {
    const i = Math.min(n - 1, Math.round((h / 24) * n));
    svg += `<text x="${x(i)}" y="${H - 4}" text-anchor="middle" class="gh-axis">${String(h).padStart(2, '0')}</text>`;
  }
  series.forEach((s) => {
    let d = '', pen = false;
    s.values.forEach((v, i) => {
      if (v == null || !Number.isFinite(v)) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true;
    });
    svg += `<path d="${d}" fill="none" stroke="${s.colour}" stroke-width="${s.dash ? 1.5 : 2}" ${s.dash ? 'stroke-dasharray="4 3"' : ''} stroke-linejoin="round" stroke-linecap="round"/>`;
  });
  if (marker != null) svg += `<line x1="${x(marker)}" x2="${x(marker)}" y1="${pt}" y2="${H - pb}" class="gh-marker"/>`;
  // header: the unit on the left, then the legend (only for two or more series)
  svg += `<text x="${pl - 30}" y="10" class="gh-unit">${esc(unit)}</text>`;
  if (series.length > 1) {
    let lx = W - pr;
    [...series].reverse().forEach((s) => {
      const w = 18 + s.name.length * 5.4;
      lx -= w;
      svg += `<line x1="${lx}" x2="${lx + 12}" y1="7" y2="7" stroke="${s.colour}" stroke-width="2" ${s.dash ? 'stroke-dasharray="4 3"' : ''}/>`;
      svg += `<text x="${lx + 15}" y="10" class="gh-legend">${esc(s.name)}</text>`;
      lx -= 8;
    });
  }
  return svg + '</svg>';
}

const col = (key) => ui.day.steps.map((s) => {
  const v = typeof key === 'function' ? key(s) : (s.state[key] ?? s.flows[key]);
  return v == null ? null : v;
});
const times = () => ui.day.steps.map((s) => s.t);
const windowsToBands = (windows) => (windows || []).map(([a, b]) => {
  const ts = times();
  const ia = Math.max(0, ts.indexOf(a)), ib = b === '24:00' ? ts.length - 1 : Math.max(0, ts.indexOf(b));
  return [ia, ib];
});
const S = (key) => T(`series.${key}`);

// Light so far today, J/cm² (outdoor-equivalent): sun, and sun plus lamps.
function lightSoFar() {
  const k = ui.day.params.lamp_jcm2_per_h;
  let sun = 0, all = 0;
  const sunC = [], allC = [];
  for (const s of ui.day.steps) {
    const r = Math.max(0, s.state.radiation ?? 0) * 900 / 1e4;
    sun += r; all += r + (s.state.lamps ?? 0) * k / 4;
    sunC.push(sun); allC.push(all);
  }
  return { sunC, allC };
}

// Light, lamps-only or dark, per step (the dial and the timeline agree).
const phase = (s) => {
  const r = s.state.radiation, l = s.state.lamps;
  if (r != null && r > 0) return 'sun';
  if (l != null && l > 0.01) return 'lamps';
  if (r != null && l != null) return 'dark';
  return 'unknown';
};

// ------------------------------------------------------------------ components
const R = (key) => T(`row.${key}`);
const COMPONENT = {
  lamps: {
    values: (s, f, d) => {
      const m = d.summary;
      return [
        [R('lamps_now'), pct(s.lamps), 'lamps'],
        [R('lamp_heat_now'), `${num(f.lamps)} W/m²`, 'lamp_power'],
        [R('day_length'), T('row.day_length_value', { light: num(m.light_h, 1), sun: num(m.sun_h, 1), lamps: num(m.lamp_only_h, 1) }), 'day_length'],
        [R('longest_dark'), `${num(m.longest_dark_h, 1)} h`, 'dark'],
        [R('light_sum_today'), `${num(m.light_jcm2)} J/cm²`, 'light_sum'],
        [R('lamp_h_today'), `${num(m.lamp_h, 1)} h`, 'lamp_h'],
        [R('lamp_h_needed'), `${num(m.lamp_h_needed)} h`, 'lamp_h_needed'],
        [R('lamp_h_longest'), `${num(m.lamp_h_longest_day)} h`, 'lamp_h_longest_day'],
      ];
    },
    charts: () => {
      const { sunC, allC } = lightSoFar();
      const target = ui.day.params.advice.light_target_jcm2;
      return [
        { unit: T('chart.lamps_on'), fixed: [0, 100], series: [{ name: S('lamps'), values: col((s) => (s.state.lamps ?? 0) * 100), colour: C.magenta }] },
        { unit: T('chart.light_so_far'), series: [
          { name: S('sun_lamps'), values: allC, colour: C.magenta },
          { name: S('sun'), values: sunC, colour: C.yellow },
          { name: S('target'), values: allC.map(() => target), colour: C.grey, dash: true }] },
      ];
    },
    whatif: 'lamps',
  },
  pipes: {
    values: (s, f) => [
      [R('pipe_rail'), T('row.pipe_value', { temp: num(s.lg_pipe_lower, 1), asked: num(s.lg_pipe_lower_calc, 0) }), 'pipe_temp'],
      [R('growth_pipe'), T('row.pipe_value', { temp: num(s.lg_pipe_growth, 1), asked: num(s.lg_pipe_growth_calc, 0) }), 'pipe_temp'],
      [R('heat_into'), `${num(f.pipes)} W/m²`, 'pipe_heat'],
      [R('heat_sp'), T('row.heat_sp_value', { sp: num(s.heat_sp, 1), air: num(s.t_in, 1) }), 'heat_sp'],
    ],
    charts: () => [
      { unit: '°C', series: [
        { name: S('pipe_rail'), values: col('lg_pipe_lower'), colour: C.orange },
        { name: S('growth_pipe'), values: col('lg_pipe_growth'), colour: C.yellow },
        { name: S('air'), values: col('t_in'), colour: C.blue }] },
      { unit: T('chart.pipe_heat'), series: [{ name: S('pipes'), values: col((s) => s.flows.pipes), colour: C.orange }] },
    ],
    whatif: 'vents',
  },
  vents: {
    values: (s, f) => [
      [R('lee_wind'), `${num(s.vent_lee)}% / ${num(s.vent_wind)}%`, 'vent_pos'],
      [R('air_exchange'), `${num((f.air_exchange ?? 0) * 3600, 1)} m³/m²/h`, 'air_exchange'],
      [R('heat_out_air'), `${num(f.ventilation)} W/m²`, 'ventilation'],
      [R('vapour_out'), `${num((f.vapour_out ?? 0) * 1000)} ml/m²/h`, 'vapour_out'],
      [R('rh_inside'), `${num(s.rh_in)}%`, 'rh_in'],
    ],
    charts: () => [
      { unit: T('chart.vent'), fixed: [0, 100], series: [
        { name: S('lee'), values: col('vent_lee'), colour: C.aqua },
        { name: S('windward'), values: col('vent_wind'), colour: C.blue }] },
      { unit: T('chart.rh'), fixed: [30, 100], series: [{ name: S('rh_inside'), values: col('rh_in'), colour: C.violet }] },
    ],
    whatif: 'vents',
  },
  screen: {
    values: (s, f) => [
      [R('screen_closed'), s.screen == null ? R('not_logged') : pct(s.screen), 'screen_pos'],
      [R('cover_out'), `${num(f.cover)} W/m²`, 'cover'],
      [R('delta_t'), `${num((s.t_in ?? 0) - (s.t_out ?? 0), 1)} °C`, 'delta_t'],
    ],
    charts: () => [
      { unit: T('chart.screen'), fixed: [0, 100], series: [{ name: S('screen'), values: col((s) => (s.state.screen == null ? null : s.state.screen * 100)), colour: C.grey }] },
      { unit: T('chart.cover_loss'), series: [{ name: S('cover'), values: col((s) => s.flows.cover), colour: C.blue }] },
    ],
    whatif: 'screen',
  },
  crop: {
    values: (s, f, d, st) => [
      [R('transpiration'), `${num((s.transpiration ?? 0) * 1000)} ml/m²/h (${R(st.e_source === 'scale' ? 'measured' : 'modelled')})`, 'transpiration'],
      [R('evap_heat'), `${num(f.evaporation)} W/m²`, 'evaporation'],
      [R('air'), T('row.air_value', { t: num(s.t_in, 1), rh: num(s.rh_in) }), 't_in'],
      [R('co2'), `${num(s.co2)} ppm`, 'co2'],
      [R('woke'), d.activity.wake ? T('row.woke_value', { wake: d.activity.wake, cause: T(`cause.${d.activity.cause}`), trigger: d.activity.trigger, lag: num(d.activity.lag_min) }) : '–', 'wake'],
    ],
    charts: () => [
      { unit: 'ml/m²/h', series: [
        { name: S('measured'), values: col((s) => (s.e_source === 'scale' ? s.state.transpiration * 1000 : null)), colour: C.aqua },
        { name: S('modelled'), values: col((s) => (s.e_source !== 'scale' ? s.state.transpiration * 1000 : null)), colour: C.aqua, dash: true }] },
      { unit: T('chart.co2'), series: [{ name: S('co2'), values: col('co2'), colour: C.grey }] },
    ],
  },
  substrate: {
    values: (s, f, d) => [
      [R('weight'), `${num(s.weight, 2)} kg`, 'weight'],
      [R('irr_today'), `${num(d.summary.irrigation_l, 2)} l/m²`, 'irrigation'],
      [R('drain_today'), `${num(d.summary.drain_l, 2)} l/m² (${d.summary.irrigation_l ? num(100 * d.summary.drain_l / d.summary.irrigation_l) : '–'}%)`, 'drain'],
      [R('crop_water_today'), `${num(d.summary.transpiration_l, 2)} l/m²`, 'crop_water'],
      [R('ec_drain'), `${num(s.ec_drain, 1)} mS/cm`, 'ec_drain'],
    ],
    charts: () => [
      { unit: 'kg', series: [{ name: S('scale_weight'), values: col('weight'), colour: C.blue }] },
    ],
  },
  weather: {
    values: (s) => [
      [R('outside_air'), `${num(s.t_out, 1)} °C`, 't_out'],
      [R('outside_rh'), `${num(s.rh_out)}%`, 'rh_out'],
      [R('radiation'), `${num(s.radiation)} W/m²`, 'radiation'],
      [R('wind'), T('row.wind_value', { speed: num(s.wind, 1), dir: num(s.wind_dir) }), 'wind'],
    ],
    charts: () => [
      { unit: 'W/m²', series: [{ name: S('radiation'), values: col('radiation'), colour: C.yellow }] },
      { unit: '°C', series: [{ name: S('outside'), values: col('t_out'), colour: C.blue }, { name: S('inside'), values: col('t_in'), colour: C.orange }] },
    ],
  },
  cover: {
    values: (s, f) => [
      [R('sun_kept'), `${num(f.sun)} W/m²`, 'sun'],
      [R('cover_out'), `${num(f.cover)} W/m²`, 'cover'],
      [R('delta_t'), `${num((s.t_in ?? 0) - (s.t_out ?? 0), 1)} °C`, 'delta_t'],
    ],
    charts: () => [
      { unit: 'W/m²', series: [{ name: S('sun_in'), values: col((s) => s.flows.sun), colour: C.yellow }, { name: S('cover_loss'), values: col((s) => s.flows.cover), colour: C.blue }] },
    ],
  },
  sensors: {
    values: (s) => [
      [R('box_air'), T('row.air_value', { t: num(s.t_in, 1), rh: num(s.rh_in) }), 't_in'],
      [R('box_co2'), `${num(s.co2)} ppm`, 'co2'],
      [R('scale_weight'), `${num(s.weight, 2)} kg`, 'weight'],
      [R('scale_e'), `${num((s.transpiration ?? 0) * 1000)} ml/m²/h`, 'transpiration'],
      [R('roof_out'), `${num(s.t_out, 1)} °C · ${num(s.radiation)} W/m²`, 't_out'],
      [R('block_lamps'), pct(s.lamps), 'lamps'],
      [R('block_pipes'), `${num(s.lg_pipe_lower)} / ${num(s.lg_pipe_growth)} °C`, 'pipe_temp'],
      [R('block_vents'), `${num(s.vent_lee)}% / ${num(s.vent_wind)}%`, 'vent_pos'],
      [R('block_screen'), s.screen == null ? R('not_logged') : pct(s.screen), 'screen_pos'],
    ],
    charts: () => [],
    extra: () => `<p class="gh-muted"><span class="gh-scope scope-spot">${T('scope.spot')}</span> ${esc(T('sensors.legend_spot'))}
      <span class="gh-scope scope-block">${T('scope.block')}</span> ${esc(T('sensors.legend_block'))}
      ${esc(T('sensors.toggle', { chip: T('layer.zone') }))}</p>
      <p class="gh-muted"><button type="button" class="gh-link" data-note="sensors">${esc(T('sensors.link'))}</button></p>`,
  },
};
const blurb = (name) => (COMPONENT[name].blurb ? COMPONENT[name].blurb() : T(`blurb.${name}`));

// HUD readings open as a day chart in the panel: inside and outside together
// where they share a unit, so the two can be compared on one axis.
const temps = () => ({ unit: '°C', series: [
  { name: S('inside'), values: col('t_in'), colour: C.orange },
  { name: S('outside'), values: col('t_out'), colour: C.blue },
  { name: S('heat_sp'), values: col('heat_sp'), colour: C.grey, dash: true }] });
const humid = () => ({ unit: T('chart.rh'), fixed: [0, 100], series: [
  { name: S('inside'), values: col('rh_in'), colour: C.violet },
  { name: S('outside'), values: col('rh_out'), colour: C.blue }] });
const METRIC = {
  t_out: { charts: () => [temps()], now: (s) => `${num(s.t_out, 1)} °C` },
  t_in: { charts: () => [temps()], now: (s) => `${num(s.t_in, 1)} °C` },
  rh_out: { charts: () => [humid()], now: (s) => `${num(s.rh_out)}%` },
  rh_in: { charts: () => [humid()], now: (s) => `${num(s.rh_in)}%` },
  radiation: { now: (s) => `${num(s.radiation)} W/m²`, charts: () => [
    { unit: 'W/m²', series: [
      { name: S('outside'), values: col('radiation'), colour: C.yellow },
      { name: S('kept_inside'), values: col((s) => s.flows.sun), colour: C.orange, dash: true }] }] },
  wind: { now: (s) => T('row.wind_value', { speed: num(s.wind, 1), dir: num(s.wind_dir) }), charts: () => [
    { unit: T('chart.wind_speed'), series: [{ name: S('wind'), values: col('wind'), colour: C.blue }] },
    { unit: T('chart.wind_from'), fixed: [0, 360], series: [{ name: S('direction'), values: col('wind_dir'), colour: C.grey }] }] },
  co2: { now: (s) => `${num(s.co2)} ppm`, charts: () => [
    { unit: T('chart.co2'), series: [{ name: S('co2'), values: col('co2'), colour: C.grey }] },
    { unit: T('chart.lamps_on'), fixed: [0, 100], series: [{ name: S('lamps'), values: col((s) => (s.state.lamps ?? 0) * 100), colour: C.magenta }] }] },
  transpiration: { now: (s) => `${num((s.transpiration ?? 0) * 1000)} ml/m²/h`, charts: () => COMPONENT.crop.charts().slice(0, 1) },
};

// ------------------------------------------------------------------ scene
const scene = new GreenhouseScene($('gh-viewer'), {
  names: NAMES,
  onPick: (name) => select(name),
  onHover: () => {},
});

function layerButtons() {
  const el = $('gh-layers');
  const defs = ['zone', 'vapour', 'flows', 'labels', 'roof'];
  el.innerHTML = defs.map((k) => `<button type="button" class="gh-chip is-on" data-layer="${k}" aria-pressed="true">${esc(T(`layer.${k}`))}</button>`).join('')
    + `<button type="button" class="gh-chip" id="gh-inside">${esc(T('layer.inside'))}</button>`
    + `<button type="button" class="gh-chip" id="gh-reset">${esc(T('layer.overview'))}</button>`;
  el.querySelectorAll('[data-layer]').forEach((b) => b.addEventListener('click', () => {
    const on = !b.classList.contains('is-on');
    b.classList.toggle('is-on', on); b.setAttribute('aria-pressed', String(on));
    scene.setLayer(b.dataset.layer, on);
  }));
  $('gh-reset').addEventListener('click', () => { select(null); scene.resetView(); });
  $('gh-inside').addEventListener('click', () => { select(null); scene.insideView(); });
}

// ------------------------------------------------------------------ timeline
function renderTimeline() {
  const d = ui.day, n = d.steps.length;
  const W = 1000, H = 34;
  const x = (i) => (i / (n - 1)) * W;
  let bands = '';
  d.steps.forEach((s, i) => {
    const p = phase(s);
    if (p === 'dark') bands += `<rect x="${x(i)}" y="0" width="${W / n + 0.5}" height="${H}" fill="${C.night}" opacity="0.9"/>`;
    if ((s.state.lamps ?? 0) > 0.5) bands += `<rect x="${x(i)}" y="0" width="${W / n + 0.5}" height="${H}" fill="${C.magenta}" opacity="0.32"/>`;
  });
  const rad = d.steps.map((s) => s.state.radiation ?? 0), rmax = Math.max(50, ...rad);
  let sun = `M0,${H}`;
  rad.forEach((r, i) => { sun += `L${x(i).toFixed(1)},${(H - (r / rmax) * (H - 4)).toFixed(1)}`; });
  sun += `L${W},${H}Z`;
  const humid = d.steps.map((s, i) => ((s.state.rh_in ?? 0) >= d.params.advice.humid_rh ? `<rect x="${x(i)}" y="${H - 3}" width="${W / n + 0.5}" height="3" fill="${C.violet}"/>` : '')).join('');
  $('gh-timeline').innerHTML = `
    <button type="button" class="gh-play" id="gh-play" aria-label="${esc(T('play'))}">▶</button>
    <div class="gh-track">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="gh-strip" aria-hidden="true">
        ${bands}<path d="${sun}" fill="${C.yellow}" opacity="0.55"/>${humid}
      </svg>
      <input type="range" id="gh-slider" min="0" max="${n - 1}" step="1" value="${ui.i}" aria-label="${esc(T('time_of_day'))}">
      <div class="gh-strip-key"><span><i style="background:${C.yellow}"></i>${esc(T('legend.sun'))}</span><span><i style="background:${C.magenta}"></i>${esc(T('legend.lamps_on'))}</span><span><i style="background:${C.night};outline:1px solid #445"></i>${esc(T('legend.dark'))}</span><span><i style="background:${C.violet}"></i>${esc(T('legend.humid', { rh: num(d.params.advice.humid_rh) }))}</span></div>
    </div>
    <div class="gh-clock" id="gh-clock"></div>`;
  $('gh-slider').addEventListener('input', (e) => setStep(Number(e.target.value)));
  $('gh-play').addEventListener('click', togglePlay);
}

// ------------------------------------------------------------------ day-length dial
// 24 hours around a clock, midnight at the top: sun on the outer ring, lamps on
// the inner ring, dark where neither. The hand is the time on the timeline.
function renderDial() {
  const d = ui.day, n = d.steps.length, m = d.summary;
  const cx = 60, cy = 60;
  const arc = (i0, i1, r0, r1) => {
    const a0 = (i0 / n) * 2 * Math.PI - Math.PI / 2, a1 = (i1 / n) * 2 * Math.PI - Math.PI / 2;
    const p = (r, a) => `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    return `M${p(r1, a0)}A${r1},${r1} 0 ${large} 1 ${p(r1, a1)}L${p(r0, a1)}A${r0},${r0} 0 ${large} 0 ${p(r0, a0)}Z`;
  };
  // merge runs of equal state into one arc each
  const runs = (test) => {
    const out = []; let start = null;
    d.steps.forEach((s, i) => {
      if (test(s) && start == null) start = i;
      if (!test(s) && start != null) { out.push([start, i]); start = null; }
    });
    if (start != null) out.push([start, n]);
    return out;
  };
  let svg = `<circle cx="${cx}" cy="${cy}" r="50" fill="${C.night}" stroke="rgba(255,255,255,0.12)"/>`;
  for (const [a, b] of runs((s) => phase(s) === 'sun')) svg += `<path d="${arc(a, b, 43, 50)}" fill="${C.yellow}"/>`;
  for (const [a, b] of runs((s) => (s.state.lamps ?? 0) > 0.01)) svg += `<path d="${arc(a, b, 35, 42)}" fill="${C.magenta}"/>`;
  for (const [a, b] of runs((s) => phase(s) === 'unknown')) svg += `<path d="${arc(a, b, 35, 50)}" fill="#555" opacity="0.6"/>`;
  // sunrise / sunset ticks (astronomical)
  for (const t of [m.sunrise, m.sunset]) {
    if (!t) continue;
    const [hh, mm] = t.split(':').map(Number);
    const a = ((hh + mm / 60) / 24) * 2 * Math.PI - Math.PI / 2;
    svg += `<line x1="${cx + 50 * Math.cos(a)}" y1="${cy + 50 * Math.sin(a)}" x2="${cx + 55 * Math.cos(a)}" y2="${cy + 55 * Math.sin(a)}" stroke="#fff" stroke-width="1.5"/>`;
  }
  for (const [h, lx, ly] of [[0, 60, 7], [6, 114, 63], [12, 60, 119], [18, 6, 63]]) {
    svg += `<text x="${lx}" y="${ly}" text-anchor="middle" class="gh-dial-tick">${h}</text>`;
  }
  const a = (ui.i / n) * 2 * Math.PI - Math.PI / 2 + Math.PI / n;
  svg += `<line x1="${cx + 24 * Math.cos(a)}" y1="${cy + 24 * Math.sin(a)}" x2="${cx + 52 * Math.cos(a)}" y2="${cy + 52 * Math.sin(a)}" stroke="#fff" stroke-width="2" stroke-linecap="round"/>`;
  const value = T('dial.value', { light: num(m.light_h, 1), sun: num(m.sun_h, 1), lamps: num(m.lamp_only_h, 1), dark: num(m.longest_dark_h, 1) });
  $('gh-dial').innerHTML = `<button type="button" class="gh-dial-btn" data-note="day_length" data-value="${esc(value)}" aria-label="${esc(value)}">
    <svg viewBox="0 0 120 120" aria-hidden="true">${svg}</svg>
    <span class="gh-dial-text"><strong>${num(m.light_h, 1)} h</strong><small>${esc(T('dial.day_length'))}</small></span></button>
    <div class="gh-dial-sub"><i style="background:${C.yellow}"></i>${esc(T('dial.sun', { h: num(m.sun_h, 1) }))} <i style="background:${C.magenta}"></i>${esc(T('dial.lamps'))}
      <br>${esc(T('dial.dark', { h: num(m.longest_dark_h, 1), min: num(d.params.advice.dark_min_h) }))}${m.sunrise ? `<br>${esc(T('dial.sunrise', { rise: m.sunrise, set: m.sunset }))}` : ''}</div>`;
}

function togglePlay() {
  ui.playing = !ui.playing;
  $('gh-play').textContent = ui.playing ? '❚❚' : '▶';
  clearInterval(ui.timer);
  if (ui.playing) ui.timer = setInterval(() => setStep((ui.i + 1) % ui.day.steps.length), 260);
}

function setStep(i) {
  ui.i = i;
  const step = ui.day.steps[i];
  scene.update(step);
  $('gh-slider').value = i;
  $('gh-clock').textContent = step.t;
  renderHud(step);
  renderDial();
  renderPanel();
  updateUrl();
}

function renderHud(step) {
  const s = step.state;
  const H = (key) => esc(T(`hud.${key}`));
  const chip = (label, value, key) => `<button type="button" class="gh-hud-chip${ui.selected === `metric:${key}` ? ' is-active' : ''}" data-metric="${key}" aria-pressed="${ui.selected === `metric:${key}`}"><span>${label}</span><strong>${value}</strong></button>`;
  $('gh-hud-out').innerHTML = `<div class="gh-hud-title">${esc(T('hud.outside', { date: fmtDate(ui.day.date), time: step.t }))}</div>`
    + chip(H('air'), `${num(s.t_out, 1)} °C`, 't_out') + chip(H('rh'), `${num(s.rh_out)}%`, 'rh_out')
    + chip(H('sun'), `${num(s.radiation)} W/m²`, 'radiation') + chip(H('wind'), `${num(s.wind, 1)} m/s`, 'wind');
  $('gh-hud-in').innerHTML = `<div class="gh-hud-title">${H('inside')}</div>`
    + chip(H('air'), `${num(s.t_in, 1)} °C`, 't_in') + chip(H('rh'), `${num(s.rh_in)}%`, 'rh_in')
    + chip(H('co2'), `${num(s.co2)} ppm`, 'co2')
    + chip(H('crop'), `${num((s.transpiration ?? 0) * 1000)} ml/h`, 'transpiration');
  scene.setLabel('lamps', (s.lamps ?? 0) > 0.05 ? T('pin.on', { w: num(step.flows.lamps) }) : T('pin.off'));
  scene.setLabel('pipes', `${num(s.lg_pipe_lower)}° / ${num(s.lg_pipe_growth)}°C`);
  scene.setLabel('vents', `${num(s.vent_lee)}% / ${num(s.vent_wind)}%`);
  scene.setLabel('screen', s.screen == null ? R('not_logged') : pct(s.screen));
  scene.setLabel('crop', `${num((s.transpiration ?? 0) * 1000)} ml/m²/h`);
  scene.setLabel('substrate', `${num(s.weight, 1)} kg`);
  scene.setLabel('weather', `${num(s.t_out, 1)} °C · ${num(s.radiation)} W/m²`);
  scene.setLabel('cover', T('pin.cover_out', { w: num(step.flows.cover) }));
  scene.setLabel('sensors', `${num(s.t_in, 1)} °C · ${num(s.rh_in)}% · ${num(s.co2)} ppm`);
}

// ------------------------------------------------------------------ panel
function balanceBars(f) {
  const ins = ['sun', 'lamps', 'pipes'], outs = ['cover', 'ventilation', 'evaporation'];
  const max = Math.max(20, ...[...ins, ...outs].map((k) => Math.abs(f[k] ?? 0)), Math.abs(f.residual ?? 0));
  const bar = (k) => {
    const v = f[k] ?? 0, w = Math.min(100, (Math.abs(v) / max) * 100);
    const label = T(`flow.${k}`);
    return `<button type="button" class="gh-bar" data-note="${FLOW[k].note}" data-value="${esc(`${label}: ${num(v)} W/m²`)}">
      <span class="gh-bar-label"><i style="background:${FLOW[k].colour}"></i>${esc(label)}<span class="gh-i" aria-hidden="true">i</span></span>
      <span class="gh-bar-track"><span class="gh-bar-fill" style="width:${w}%;background:${FLOW[k].colour}"></span></span>
      <span class="gh-bar-val">${num(v)} </span></button>`;
  };
  return `<div class="gh-bars"><div class="gh-bar-head">${esc(T('panel.heat_in'))}</div>${ins.map(bar).join('')}
    <div class="gh-bar-head">${esc(T('panel.heat_out'))}</div>${outs.map(bar).join('')}
    <div class="gh-bar-head">${esc(T('panel.remainder'))}</div>${bar('residual')}</div>`;
}

function renderPanel() {
  const d = ui.day, step = d.steps[ui.i], s = step.state, f = step.flows;
  const name = ui.selected;
  const close = `<button type="button" class="gh-close" aria-label="${esc(T('close'))}">×</button>`;
  if (!name) {
    const t = d.summary.flows_mj;
    const share = num(100 * t.residual / Math.max(1e-6, t.sun + t.lamps + t.pipes));
    const D = (key) => T(`day.${key}`);
    $('gh-panel').innerHTML = `
      <h3>${esc(T('panel.balance_at', { time: step.t }))}</h3>
      ${balanceBars(f)}
      <p class="gh-muted">${esc(T('panel.remainder_note'))}</p>
      <h4>${esc(T('panel.over_day'))}</h4>
      ${kv([
        [D('in_sun'), num(t.sun, 1), 'sun'], [D('in_lamps'), num(t.lamps, 1), 'lamp_power'], [D('in_pipes'), num(t.pipes, 1), 'pipe_heat'],
        [D('out_cover'), num(t.cover, 1), 'cover'], [D('out_air'), num(t.ventilation, 1), 'ventilation'],
        [D('out_water'), num(t.evaporation, 1), 'evaporation'],
        [D('remainder'), T('day.remainder_value', { mj: num(t.residual, 1), share }), 'residual'],
      ])}
      <p class="gh-muted">${esc(T('panel.click_hint'))}</p>`;
    return;
  }
  if (name.startsWith('metric:')) {
    const key = name.slice(7), n = NOTES[key], m = METRIC[key];
    const charts = m.charts().map((c) => lineChart({ ...c, t: times(), marker: ui.i, height: 140 })).join('');
    $('gh-panel').innerHTML = `
      <div class="gh-panel-head"><h3>${esc(n.title)}</h3>${close}</div>
      <p class="gh-metric-now"><strong>${m.now(s)}</strong> ${esc(T('panel.at', { time: step.t }))} <span class="gh-scope scope-${n.scope}">${T(`scope.${n.scope}`)}</span></p>
      ${charts}
      ${noteHtml(n)}`;
    $('gh-panel').querySelector('.gh-close').addEventListener('click', () => select(null));
    return;
  }
  const def = COMPONENT[name];
  const related = d.advice.filter((a) => a.component === name);
  const bands = related.flatMap((a) => windowsToBands(a.windows));
  const charts = def.charts().map((c) => lineChart({ ...c, t: times(), marker: ui.i, bands })).join('');
  $('gh-panel').innerHTML = `
    <div class="gh-panel-head"><h3>${esc(NAMES[name])}</h3>${close}</div>
    <p class="gh-muted">${prose(blurb(name))}</p>
    ${kv(def.values(s, f, d, step))}
    ${def.extra ? def.extra() : ''}
    ${charts}
    ${related.length ? `<h4>${esc(T('panel.advice'))}</h4>${related.map(adviceCard).join('')}` : ''}
    ${def.whatif ? whatIfControls(def.whatif) : ''}
    <div id="gh-whatif-out"></div>`;
  $('gh-panel').querySelector('.gh-close').addEventListener('click', () => select(null));
  bindAdvice($('gh-panel'));
  if (def.whatif) bindWhatIf(def.whatif);
  if (ui.whatif && ui.whatif.kind === def.whatif) renderWhatIf(ui.whatif.result, ui.whatif.label);
}

// ------------------------------------------------------------------ what-if
function whatIfControls(kind) {
  const head = `<h4>${esc(T('wi.title'))}</h4>`;
  if (kind === 'vents') {
    const v = ui.whatif?.kind === 'vents' ? ui.whatif.value : 100;
    return `${head}<label class="gh-whatif">${esc(T('wi.vents_before'))}
      <input type="range" id="gh-wi-vent" min="0" max="150" step="10" value="${v}">
      <output id="gh-wi-vent-out">${num(v)}%</output> ${esc(T('wi.vents_after'))}</label>`;
  }
  if (kind === 'screen') {
    return `${head}<button type="button" class="outline gh-wi-btn" data-q="screen_dark=1">${esc(T('wi.screen'))}</button>`;
  }
  if (kind === 'lamps') {
    return `${head}<button type="button" class="outline gh-wi-btn" data-q="lamps=off">${esc(T('wi.lamps_off'))}</button>`;
  }
  return '';
}

let wiTimer = null;
function bindWhatIf(kind) {
  const slider = $('gh-wi-vent');
  if (slider) {
    slider.addEventListener('input', () => {
      $('gh-wi-vent-out').textContent = `${num(slider.value)}%`;
      clearTimeout(wiTimer);
      wiTimer = setTimeout(() => runWhatIf('vents', `vent_scale=${slider.value / 100}`, T('wi.vents_label', { pct: num(slider.value) }), Number(slider.value)), 250);
    });
  }
  document.querySelectorAll('.gh-wi-btn').forEach((b) => b.addEventListener('click', () => runWhatIf(kind, b.dataset.q, b.textContent)));
}

async function runWhatIf(kind, query, label, value) {
  const out = $('gh-whatif-out');
  out.innerHTML = `<p class="gh-muted">${esc(T('wi.running'))}</p>`;
  try {
    const r = await fetch(`${API}/whatif?date=${ui.day.date}&${query}`);
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const result = await r.json();
    ui.whatif = { kind, result, label, value };
    renderWhatIf(result, label);
  } catch (e) {
    out.innerHTML = `<p class="gh-muted">${esc(T('wi.unavailable', { error: e.message }))}</p>`;
  }
}

function renderWhatIf(r, label) {
  const dMj = r.heat_mj_whatif - r.heat_mj;
  const t = r.series.t;
  const rh = ui.day.params.advice.humid_rh;
  $('gh-whatif-out').innerHTML = `
    <div class="gh-wi-result">
      <div class="gh-wi-title">${esc(label)}</div>
      <table class="gh-kv"><tbody>
        <tr><td>${esc(T('wi.pipe_heat'))}</td><td>${num(r.heat_mj, 1)} → <strong>${num(r.heat_mj_whatif, 1)}</strong> MJ/m² (${signed(dMj, 1)})</td></tr>
        <tr><td>${esc(T('wi.humid_hours', { rh: num(rh) }))}</td><td>${num(r.humid_h, 1)} → <strong>${num(r.humid_h_whatif, 1)}</strong> (${esc(T('wi.max', { rh: num(r.rh_max_whatif) }))})</td></tr>
        ${r.surplus_mj > 0.05 ? `<tr><td>${esc(T('wi.surplus'))}</td><td>${num(r.surplus_mj, 1)} MJ/m²</td></tr>` : ''}
      </tbody></table>
      ${lineChart({ t, unit: T('chart.pipe_heat'), marker: ui.i, series: [{ name: S('as_ran'), values: r.series.pipes, colour: C.orange }, { name: S('what_if'), values: r.series.pipes_whatif, colour: C.orange, dash: true }] })}
      ${lineChart({ t, unit: T('chart.rh'), marker: ui.i, series: [{ name: S('as_ran'), values: r.series.rh, colour: C.violet }, { name: S('what_if'), values: r.series.rh_whatif, colour: C.violet, dash: true }] })}
      <p class="gh-muted">${esc(T('wi.note'))}</p>
    </div>`;
}

// ------------------------------------------------------------------ advice
const ORDER = { act: 0, consider: 1, info: 2, ok: 3 };

function impactText(im) {
  const parts = [];
  if (im.mj != null) parts.push(T('impact.mj', { mj: num(im.mj, 1) }));
  if (im.lamp_h != null) parts.push(T('impact.lamp_h', { h: num(im.lamp_h, 1) }));
  if (im.jcm2 != null) parts.push(T('impact.jcm2', { v: signed(im.jcm2) }));
  if (im.humid_h != null) parts.push(T('impact.humid', { h: num(im.humid_h, 1) }));
  if (im.dark_h != null) parts.push(T('impact.dark', { h: num(im.dark_h, 1) }));
  if (im.lag_h != null) parts.push(T('impact.lag', { h: signed(im.lag_h, 1) }));
  if (im.ppm != null) parts.push(T('impact.ppm', { ppm: num(im.ppm) }));
  return parts.join(' · ');
}

function adviceCard(a) {
  const win = (a.windows || []).map(([x, y]) => `<button type="button" class="gh-win" data-t="${x}">${x}–${y}</button>`).join('');
  const detail = prose(a.detail);
  return `<article class="gh-advice-card lvl-${a.level}">
    <header><span class="gh-level">${esc(T(`level.${a.level}`))}</span>
      <button type="button" class="gh-comp" data-component="${a.component}">${esc(NAMES[a.component] || a.component)}</button></header>
    <strong>${esc(a.title)}</strong>
    <p>${detail}</p>
    ${impactText(a.impact) ? `<p class="gh-impact">${esc(impactText(a.impact))}</p>` : ''}
    ${win ? `<div class="gh-wins">${win}</div>` : ''}
  </article>`;
}

function bindAdvice(el) {
  el.querySelectorAll('.gh-comp').forEach((b) => b.addEventListener('click', () => select(b.dataset.component)));
  el.querySelectorAll('.gh-win').forEach((b) => b.addEventListener('click', () => {
    const i = times().indexOf(b.dataset.t);
    if (i >= 0) setStep(i);
  }));
}

function renderAdvice() {
  const items = [...ui.day.advice].sort((a, b) => ORDER[a.level] - ORDER[b.level]);
  const acts = items.filter((a) => a.level === 'act' || a.level === 'consider').length;
  $('gh-advice-sub').textContent = T(acts === 1 ? 'advice.sub_one' : 'advice.sub_many', { date: fmtDate(ui.day.date), n: num(acts) });
  $('gh-advice').innerHTML = items.map(adviceCard).join('');
  bindAdvice($('gh-advice'));
}

// ------------------------------------------------------------------ tiles
function renderTiles() {
  const s = ui.day.summary, a = ui.day.activity, p = ui.day.params;
  const tile = (key, value, sub, note) => {
    const label = T(`tile.${key}`);
    return `<button type="button" class="gh-tile" data-note="${note}" data-value="${esc(`${label}: ${value} (${sub})`)}"><span>${esc(label)}<span class="gh-i" aria-hidden="true">i</span></span><strong>${esc(value)}</strong><small>${esc(sub)}</small></button>`;
  };
  $('gh-tiles').innerHTML = [
    tile('pipe_heat', `${num(s.heat_mj, 1)} MJ/m²`, T('tile.pipe_heat_sub'), 'heat_mj'),
    tile('day_length', `${num(s.light_h, 1)} h`, T('tile.day_length_sub', { sun: num(s.sun_h, 1), lamps: num(s.lamp_only_h, 1), dark: num(s.longest_dark_h, 1) }), 'day_length'),
    tile('lamps', `${num(s.lamp_h, 1)} h`, T('tile.lamps_sub', { needed: num(s.lamp_h_needed), longest: num(s.lamp_h_longest_day) }), 'lamp_h_needed'),
    tile('light_sum', `${num(s.light_jcm2)} J/cm²`, T('tile.light_sum_sub', { sun: num(s.sun_jcm2), target: num(p.advice.light_target_jcm2) }), 'light_sum'),
    tile('crop_water', `${num(s.transpiration_l, 2)} l/m²`, T('tile.crop_water_sub', { irr: num(s.irrigation_l, 2), drain: num(s.drain_l, 2) }), 'crop_water'),
    tile('humid', `${num(s.humid_h, 1)} h`, T('tile.humid_sub', { rh: num(p.advice.humid_rh), target: num(p.advice.humid_hours_target) }), 'humid_h'),
    tile('woke', a.wake || '–', a.wake ? T('tile.woke_sub', { lag: num(a.lag_min), cause: T(`cause.${a.cause}`), trigger: a.trigger }) : T('tile.no_woke'), 'wake'),
  ].join('');
}

// ------------------------------------------------------------------ tomorrow
async function renderTomorrow() {
  const el = $('gh-tomorrow');
  el.innerHTML = `<p class="gh-muted">${esc(T('tm.fetching'))}</p>`;
  try {
    const r = await (await fetch(`${API}/tomorrow`)).json();
    if (!r.available) { el.innerHTML = `<p class="gh-muted">${esc(fmtDate(r.date))}: ${esc(r.reason)}</p>`; return; }
    const W = 480, H = 150, pl = 34, pb = 18, pt = 24;
    const hi = Math.max(r.sun_max_j * 1.15, ...r.sun_j);
    const bw = (W - pl) / 24;
    const y = (v) => pt + (1 - v / hi) * (H - pt - pb);
    let svg = `<svg viewBox="0 0 ${W} ${H}" class="gh-chart" role="img" aria-label="${esc(T('tm.aria'))}">`;
    for (const v of [0, hi / 2, hi]) {
      svg += `<line x1="${pl}" x2="${W}" y1="${y(v)}" y2="${y(v)}" class="gh-grid"/><text x="${pl - 4}" y="${y(v) + 3}" text-anchor="end" class="gh-axis">${num(v)}</text>`;
    }
    r.sun_j.forEach((v, h) => {
      svg += `<rect x="${pl + h * bw + 1}" y="${y(v)}" width="${bw - 2}" height="${Math.max(0, y(0) - y(v))}" rx="2" fill="${C.yellow}"><title>${esc(T('tm.bar', { hour: String(h).padStart(2, '0'), v: num(v) }))}</title></rect>`;
      if (h % 6 === 0) svg += `<text x="${pl + h * bw + bw / 2}" y="${H - 4}" text-anchor="middle" class="gh-axis">${String(h).padStart(2, '0')}</text>`;
    });
    svg += `<line x1="${pl}" x2="${W}" y1="${y(r.sun_max_j)}" y2="${y(r.sun_max_j)}" class="gh-marker"/>`;
    svg += `<text x="${W - 2}" y="${y(r.sun_max_j) - 4}" text-anchor="end" class="gh-unit">${esc(T('tm.no_lamps_above'))}</text>`;
    svg += `<text x="${pl - 30}" y="10" class="gh-unit">${esc(T('tm.unit'))}</text></svg>`;
    const need = r.lamp_h_needed;
    const p = { target: num(r.target), dark: num(r.dark_min), h: num(need) };
    const needText = need == null ? esc(T('tm.none', p))
      : need === 0 ? esc(T('tm.zero', p))
        : T('tm.need_html', p);
    const longest = T('tm.longest', { h: num(r.lamp_h_longest_day), dark: num(r.dark_min), light: num(r.light_longest_day) })
      + (need ? T('tm.longest_more', { more: num(r.lamp_h_longest_day - need) }) : '');
    el.innerHTML = `
      <p>${esc(T('tm.forecast', { date: fmtDate(r.date), sun: num(r.sun_total), h: num(r.sun_h) }))}
        <button type="button" class="gh-link" data-note="lamp_h_needed">${esc(T('tm.how'))}</button></p>
      <p>${needText}</p>
      <p>${esc(longest)}.</p>
      ${svg}
      <p class="gh-muted">${esc(T('tm.source', { k: num(r.lamp_jcm2, 1) }))}</p>`;
  } catch (e) {
    el.innerHTML = `<p class="gh-muted">${esc(T('tm.unavailable', { error: e.message }))}</p>`;
  }
}

// ------------------------------------------------------------------ flow
function select(name) {
  ui.selected = name || null;
  closeNote();
  const part = ui.selected && !ui.selected.startsWith('metric:') ? ui.selected : null;
  if (part || !ui.selected || scene.selected) scene.select(part);
  if (ui.day) { renderHud(ui.day.steps[ui.i]); renderPanel(); }
}

for (const id of ['gh-hud-out', 'gh-hud-in']) {
  $(id).addEventListener('click', (e) => {
    const b = e.target.closest('[data-metric]');
    if (!b) return;
    const name = `metric:${b.dataset.metric}`;
    select(ui.selected === name ? null : name);
  });
}

function updateUrl() {
  const u = new URL(window.location.href);
  u.searchParams.set('date', ui.day.date);
  u.searchParams.set('t', ui.day.steps[ui.i].t);
  u.searchParams.delete('lang');  // the cookie remembers it
  window.history.replaceState(null, '', u);
}

async function loadDay(date, t) {
  $('gh-loading').hidden = false;
  $('gh-loading').textContent = T('load.loading');
  closeNote();
  try {
    const r = await fetch(`${API}/day${date ? `?date=${date}` : ''}`);
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const d = await r.json();
    if (d.empty) {
      $('gh-loading').textContent = (d.notes || [T('load.no_data')]).join(' ');
      $('gh-date').value = d.date;
      return;
    }
    ui.day = d; ui.whatif = null;
    const input = $('gh-date');
    input.value = d.date;
    if (d.range.first) input.min = d.range.first;
    input.max = d.range.latest;
    renderTimeline();
    renderAdvice();
    renderTiles();
    const at = t ? d.steps.findIndex((s) => s.t === t) : -1;
    setStep(at >= 0 ? at : Math.min(d.steps.length - 1, 44));
    $('gh-loading').hidden = true;
  } catch (e) {
    $('gh-loading').textContent = T('load.failed', { error: e.message });
  }
}

function shiftDay(delta) {
  const dt = new Date(`${ui.day?.date || $('gh-date').value}T12:00:00`);
  dt.setDate(dt.getDate() + delta);
  const iso = dt.toISOString().slice(0, 10);
  if (ui.day?.range?.latest && iso > ui.day.range.latest) return;
  loadDay(iso, ui.day?.steps[ui.i]?.t);
}

document.querySelectorAll('[data-day]').forEach((b) => b.addEventListener('click', () => shiftDay(Number(b.dataset.day))));
$('gh-date').addEventListener('change', (e) => loadDay(e.target.value, ui.day?.steps[ui.i]?.t));
$('gh-latest').addEventListener('click', () => loadDay(null));
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (!tip.hidden) { hideTip(); return; }
    if (!balloon.hidden) { closeNote(); return; }
    select(null);
  }
  if (e.target.closest('input, textarea')) return;
  if (e.key === 'Enter' && e.target.matches('.gh-row')) { openNote(e.target, e.target.dataset.note, e.target.dataset.value); return; }
  if (e.key === ' ' && !e.target.closest('button')) { e.preventDefault(); togglePlay(); }
  if (e.key === 'ArrowRight' && ui.day) setStep(Math.min(ui.day.steps.length - 1, ui.i + 1));
  if (e.key === 'ArrowLeft' && ui.day) setStep(Math.max(0, ui.i - 1));
});

layerButtons();
const params = new URLSearchParams(window.location.search);
loadDay(params.get('date'), params.get('t'));
renderTomorrow();
