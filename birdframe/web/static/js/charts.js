import {attr, esc, num, hourLabel, dateLabel, speciesHref} from './core.js';

function timeTip(label, value, composition = null) {
  const lines = [`${label} · ${num(value)} ${value === 1 ? 'detection' : 'detections'}`];
  const voices = composition?.species || [];
  voices.forEach(voice => lines.push(`${voice.common_name} · ${num(voice.count)}`));
  const more = Number(composition?.species_count || 0) - voices.length;
  if (more > 0) lines.push(`+ ${more} more ${more === 1 ? 'species' : 'species'}`);
  return lines.join('\n');
}

function tipTarget(tip) {
  const value = attr(tip);
  return `data-chart-tip="${value}"`;
}

export function initChartTooltips(root = document) {
  root.querySelectorAll('.interactive-chart').forEach(chart => {
    if (chart.dataset.tooltipReady) return;
    chart.dataset.tooltipReady = 'true';
    const tooltip = chart.querySelector(':scope > .chart-tooltip');
    if (!tooltip) return;
    let hideTimer = null;
    const hide = () => tooltip.classList.remove('visible');
    const show = (target, clientX, clientY) => {
      clearTimeout(hideTimer);
      tooltip.textContent = target.dataset.chartTip;
      tooltip.classList.add('visible');
      const x = Math.min(Math.max(clientX, 110), window.innerWidth - 110);
      const y = Math.max(16, clientY - 12);
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${y}px`;
    };
    chart.addEventListener('pointermove', event => {
      const target = event.target.closest?.('[data-chart-tip]');
      if (!target || !chart.contains(target)) { hide(); return; }
      show(target, event.clientX, event.clientY);
    });
    chart.addEventListener('pointerleave', hide);
    chart.addEventListener('click', event => {
      const target = event.target.closest?.('[data-chart-tip]');
      if (!target || !chart.contains(target)) return;
      show(target, event.clientX, event.clientY);
      hideTimer = setTimeout(hide, 2600);
    });
  });
}

// Phones get a narrower drawing, so bars and axis labels keep readable
// proportions instead of a 720-unit sketch shrunk to under half size.
const chartWidth = () => (window.matchMedia('(max-width: 760px)').matches ? 400 : 720);

function points(values, width, height, inset = {l: 34, r: 10, t: 14, b: 25}) {
  const max = Math.max(1, ...values);
  const innerW = width - inset.l - inset.r;
  const innerH = height - inset.t - inset.b;
  return values.map((value, index) => ({
    x: inset.l + (values.length === 1 ? innerW / 2 : index / (values.length - 1) * innerW),
    y: inset.t + innerH - value / max * innerH,
    value,
  }));
}

export function miniSpark(values, label = 'Activity') {
  if (!values?.length) return '';
  const width = 260, height = 54;
  const pts = points(values, width, height, {l: 1, r: 1, t: 5, b: 3});
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const area = `M1 ${height - 1} ${path.replace(/^M/, 'L')} L${width - 1} ${height - 1} Z`;
  return `<div class="chart" style="min-height:54px" role="img" aria-label="${esc(label)}">
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <path class="area" d="${area}"></path><path class="line" d="${path}"></path>
    </svg></div>`;
}

export function areaChart(rows, valueKey = 'detections', {height = 220, label = 'Detections by day'} = {}) {
  if (!rows?.length) return '<div class="empty">No activity in this range.</div>';
  const width = chartWidth();
  const values = rows.map(row => Number(row[valueKey] || 0));
  const pts = points(values, width, height);
  const max = Math.max(1, ...values);
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const area = `M34 ${height - 25} ${path.replace(/^M/, 'L')} L${width - 10} ${height - 25} Z`;
  const labelEvery = Math.max(1, Math.ceil(rows.length / 7));
  const yTicks = [0, .5, 1].map(frac => {
    const y = 14 + (height - 39) * (1 - frac);
    return `<line class="grid" x1="34" x2="${width - 10}" y1="${y}" y2="${y}"></line>
      <text x="29" y="${y + 3}" text-anchor="end">${Math.round(max * frac).toLocaleString()}</text>`;
  }).join('');
  const dots = pts.map((p, i) => `<circle cx="${p.x}" cy="${p.y}" r="3.3" fill="var(--forest)">
    <title>${esc(dateLabel(rows[i].day, 'short'))}: ${num(p.value)} ${esc(valueKey)}</title></circle>`).join('');
  const last = rows.length - 1;
  // Regular ticks, plus the final day; a tick closer than one full interval
  // to the final label is dropped so the two can't overlap on a phone.
  const labels = rows.map((row, i) => (i % labelEvery === 0 && last - i >= labelEvery) || i === last
    ? `<text x="${pts[i].x}" y="${height - 7}" text-anchor="middle">${esc(row.day.slice(5))}</text>` : '').join('');
  return `<div class="chart" role="img" aria-label="${esc(label)}"><svg viewBox="0 0 ${width} ${height}">
    ${yTicks}<path class="area" d="${area}"></path><path class="line" d="${path}"></path>${dots}${labels}
  </svg></div>`;
}

export function hourBars(hours, {height = 210, label = 'Detections around the 24-hour clock', speciesByHour = null} = {}) {
  const width = chartWidth(), left = 30, right = 8, top = 14, bottom = 28;
  const values = hours || Array(24).fill(0);
  const max = Math.max(1, ...values);
  const innerW = width - left - right;
  const innerH = height - top - bottom;
  const gap = width < 720 ? 2 : 4;
  const barW = (innerW - gap * 23) / 24;
  const peak = values.indexOf(Math.max(...values));
  const bars = values.map((value, hour) => {
    const h = Math.max(1.5, value / max * innerH);
    const x = left + hour * (barW + gap), y = top + innerH - h;
    const detail = timeTip(`${hourLabel(hour)}–${hourLabel((hour + 1) % 24)}`, value, speciesByHour?.[hour]);
    return `<rect class="bar ${hour === peak ? 'hot' : ''}" x="${x}" y="${y}" width="${barW}" height="${h}" rx="2" ${tipTarget(detail)}>
      <title>${esc(detail)}</title></rect>`;
  }).join('');
  const labels = values.map((_, hour) => hour % 3 === 0
    ? `<text x="${left + hour * (barW + gap) + barW / 2}" y="${height - 8}" text-anchor="middle">${hour}</text>` : '').join('');
  return `<div class="chart interactive-chart" role="img" aria-label="${esc(label)}"><svg viewBox="0 0 ${width} ${height}">
    <line class="grid" x1="${left}" x2="${width - right}" y1="${top + innerH}" y2="${top + innerH}"></line>
    ${bars}${labels}</svg><div class="chart-tooltip" aria-hidden="true"></div></div>`;
}

export function activityRibbon(quarters, label = 'Bird activity through the day', speciesByQuarter = null) {
  const values = quarters || Array(96).fill(0);
  const width = chartWidth(), height = 135, left = 30, right = 8, top = 12, bottom = 25;
  const max = Math.max(1, ...values);
  const barW = (width - left - right) / values.length;
  const bars = values.map((value, i) => {
    const h = Math.max(1, value / max * (height - top - bottom));
    const hour = Math.floor(i / 4), minute = (i % 4) * 15;
    const next = i === 95 ? 'midnight' : `${String(Math.floor((i + 1) / 4)).padStart(2, '0')}:${String(((i + 1) % 4) * 15).padStart(2, '0')}`;
    const detail = timeTip(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}–${next}`, value, speciesByQuarter?.[i]);
    return `<rect class="bar ${value === max ? 'hot' : ''}" x="${left + i * barW}" y="${height - bottom - h}" width="${Math.max(1, barW - .8)}" height="${h}" rx="1" ${tipTarget(detail)}>
      <title>${esc(detail)}</title></rect>`;
  }).join('');
  const labels = [0, 6, 12, 18, 24].map(hour => `<text x="${left + hour / 24 * (width - left - right)}" y="${height - 7}" text-anchor="${hour === 0 ? 'start' : hour === 24 ? 'end' : 'middle'}">${hour === 24 ? 'midnight' : hourLabel(hour)}</text>`).join('');
  return `<div class="chart interactive-chart" role="img" aria-label="${esc(label)}"><svg viewBox="0 0 ${width} ${height}">${bars}${labels}</svg><div class="chart-tooltip" aria-hidden="true"></div></div>`;
}

export function heatmap(rows) {
  if (!rows?.length) return '<div class="empty">No day-by-hour data in this range.</div>';
  const max = Math.max(1, ...rows.flatMap(row => row.hours));
  return `<div class="heatmap interactive-chart" role="img" aria-label="Detections by day and hour">
    ${rows.map(row => `<div class="heat-row"><span class="heat-label">${esc(row.day.slice(5))}</span>${row.hours.map((value, hour) => {
      const strength = value ? Math.round(12 + value / max * 88) : 0;
      const detail = timeTip(`${dateLabel(row.day, 'short')} · ${hourLabel(hour)}–${hourLabel((hour + 1) % 24)}`, value, row.species?.[hour]);
      return `<span class="heat-cell" ${tipTarget(detail)} style="${value ? `background:color-mix(in srgb,var(--forest) ${strength}%,var(--surface-strong))` : ''}" title="${attr(detail)}"></span>`;
    }).join('')}</div>`).join('')}
    <div class="heat-axis"><span></span>${Array.from({length: 24}, (_, hour) => `<span>${hour % 3 === 0 ? hour : ''}</span>`).join('')}</div>
    <div class="chart-tooltip" aria-hidden="true"></div>
  </div>`;
}

export function soundscapeScore(rows) {
  if (!rows?.length) return '<div class="empty">No species in this view.</div>';
  const axis = `<div class="score-axis"><span></span>${Array.from({length: 24}, (_, hour) => `<span>${hour % 3 === 0 ? hourLabel(hour) : ''}</span>`).join('')}<span></span></div>`;
  const body = rows.map(row => {
    const values = row.hours || Array(24).fill(0);
    const max = Math.max(1, ...values);
    const peak = values.indexOf(Math.max(...values));
    return `<div class="score-row">
      <a href="${speciesHref(row.common_name)}" title="Open ${attr(row.common_name)} dossier">${esc(row.common_name)}<small>peak ${hourLabel(peak)}</small></a>
      ${values.map((value, hour) => {
        const strength = value ? Math.round(12 + value / max * 88) : 0;
        const share = row.detections ? Math.round(value / row.detections * 100) : 0;
        const detail = `${row.common_name}\n${hourLabel(hour)}–${hourLabel((hour + 1) % 24)} · ${num(value)} ${value === 1 ? 'detection' : 'detections'}\n${share}% of this species’ activity in view`;
        return `<span class="score-cell ${hour === peak ? 'peak' : ''}" aria-hidden="true" ${tipTarget(detail)} style="--strength:${strength}%" title="${attr(detail)}"></span>`;
      }).join('')}
      <b>${num(row.detections)}</b>
    </div>`;
  }).join('');
  return `<div class="soundscape-score interactive-chart" role="group" aria-label="Species activity through the 24-hour day">${axis}<div class="score-body">${body}</div><div class="chart-tooltip" aria-hidden="true"></div></div>`;
}

export function confidenceBars(values) {
  const max = Math.max(1, ...(values || []));
  return `<div class="confidence-bars" role="img" aria-label="Detection confidence distribution">
    ${(values || []).map((value, index) => `<i style="height:${Math.max(2, value / max * 100)}%"><title>${index * 10}–${index * 10 + 9}% confidence: ${num(value)} detections</title></i>`).join('')}
  </div><div class="chart-caption"><span>0%</span><span>confidence</span><span>100%</span></div>`;
}

export function dailySpeciesBars(rows) {
  if (!rows?.length) return '';
  // Drawn in SVG so bars always share the width: fixed CSS-grid gaps
  // outgrew a phone card after ~60 days and left every bar zero-wide.
  const width = chartWidth(), height = 130, top = 8;
  const max = Math.max(1, ...rows.map(row => row.species || 0));
  const slot = width / rows.length;
  const bars = rows.map((row, i) => {
    const h = Math.max(2, (row.species || 0) / max * (height - top));
    const detail = `${dateLabel(row.day, 'short')} · ${num(row.species)} species`;
    return `<rect class="bar" x="${(i * slot).toFixed(2)}" y="${(height - h).toFixed(2)}" width="${Math.max(.8, slot * .74).toFixed(2)}" height="${h.toFixed(2)}" rx="1" ${tipTarget(detail)}>
      <title>${esc(detail)}</title></rect>`;
  }).join('');
  return `<div class="chart interactive-chart" role="img" aria-label="Species richness by day"><svg viewBox="0 0 ${width} ${height}">${bars}</svg><div class="chart-tooltip" aria-hidden="true"></div></div>
    <div class="chart-caption"><span>${esc(rows[0].day.slice(5))}</span><span>species per day</span><span>${esc(rows.at(-1).day.slice(5))}</span></div>`;
}

// ---- The long view (Seasons) ---------------------------------------------

const DAY_MS = 86_400_000;
const dayNumber = day => Math.round(Date.parse(`${day}T00:00:00Z`) / DAY_MS);
const monthShort = day => new Intl.DateTimeFormat('en-GB', {month: 'short', timeZone: 'UTC'}).format(new Date(`${day}T12:00:00Z`));

export function clockTime(minutes) {
  if (minutes == null) return '—';
  const whole = Math.round(minutes);
  return `${String(Math.floor(((whole % 1440) + 1440) % 1440 / 60)).padStart(2, '0')}:${String(((whole % 60) + 60) % 60).padStart(2, '0')}`;
}

// "1 h 25 min" / "40 min", for offsets from sunrise or sunset.
export function span(minutes) {
  const whole = Math.round(Math.abs(minutes));
  const hours = Math.floor(whole / 60), mins = whole % 60;
  if (!hours) return `${mins} min`;
  return mins ? `${hours} h ${mins} min` : `${hours} h`;
}

function linePath(points) {
  let path = '', open = false;
  points.forEach(point => {
    if (!point) { open = false; return; }
    path += `${open ? 'L' : 'M'}${point[0].toFixed(1)} ${point[1].toFixed(1)}`;
    open = true;
  });
  return path;
}

// The smallest 1, 2, 2.5 or 5 × 10^k at or above a value: round axis ticks.
function niceCeil(value) {
  if (value <= 0) return 1;
  const scale = 10 ** Math.floor(Math.log10(value));
  return scale * [1, 2, 2.5, 5, 10].find(step => step * scale >= value);
}

// A column with a softly rounded data end and a square foot on the baseline.
function columnPath(x, y, w, h, r = 4) {
  if (h <= 0) return '';
  const radius = Math.min(r, w / 2, h);
  return `M${x} ${y + h}V${y + radius}Q${x} ${y} ${x + radius} ${y}H${x + w - radius}` +
    `Q${x + w} ${y} ${x + w} ${y + radius}V${y + h}Z`;
}

// Hover for charts drawn as one SVG: `resolve(x, y)` gets the pointer in the
// drawing's own units and returns {text, focus: {x, y, width, height}} or null.
export function wirePointerTooltip(chart, resolve) {
  const svg = chart?.querySelector('svg');
  const tooltip = chart?.querySelector(':scope > .chart-tooltip');
  const focus = svg?.querySelector('.focus-mark');
  if (!svg || !tooltip) return;
  let hideTimer = null;
  const hide = () => { tooltip.classList.remove('visible'); focus?.setAttribute('visibility', 'hidden'); };
  const show = event => {
    clearTimeout(hideTimer);
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const found = resolve(point.x, point.y);
    if (!found) { hide(); return; }
    tooltip.textContent = found.text;
    tooltip.classList.add('visible');
    tooltip.style.left = `${Math.min(Math.max(event.clientX, 120), window.innerWidth - 120)}px`;
    tooltip.style.top = `${Math.max(16, event.clientY - 12)}px`;
    if (focus && found.focus) {
      Object.entries(found.focus).forEach(([key, value]) => focus.setAttribute(key, value));
      focus.setAttribute('visibility', 'visible');
    }
  };
  svg.addEventListener('pointermove', show);
  svg.addEventListener('pointerdown', show);
  // A lifted finger leaves at once; give the reader a moment, as the other charts do.
  svg.addEventListener('pointerleave', event => {
    if (event.pointerType === 'touch') hideTimer = setTimeout(hide, 2600);
    else hide();
  });
}

// Every quarter-hour of every listening day (columns are days, time runs down),
// with sunrise and sunset, and the first and last voices, drawn across it.
export function seasonClock(clock, lightDays = []) {
  if (!clock?.length) return {html: '<div class="empty">No listening days yet.</div>', resolve: () => null};
  const phone = chartWidth() < 720;
  const width = chartWidth(), left = phone ? 42 : 44, right = 6, top = 8, bottom = 26;
  const height = phone ? 330 : 360;
  const innerW = width - left - right, innerH = height - top - bottom;
  const first = dayNumber(clock[0].day);
  const spanDays = dayNumber(clock.at(-1).day) - first + 1;
  const colW = innerW / spanDays, qh = innerH / 96;
  let max = 1;
  clock.forEach(day => day.q.forEach(value => { if (value > max) max = value; }));
  const xOf = day => left + (dayNumber(day) - first) * colW;
  const yOf = minutes => top + minutes / 1440 * innerH;
  const cells = [];
  clock.forEach(day => {
    const x = xOf(day.day).toFixed(2);
    day.q.forEach((value, q) => {
      if (!value) return;
      const step = Math.min(7, Math.floor(Math.sqrt(value / max) * 8));
      cells.push(`<rect class="h${step}" x="${x}" y="${(top + q * qh).toFixed(2)}" width="${(colW + .35).toFixed(2)}" height="${(qh + .35).toFixed(2)}"></rect>`);
    });
  });
  const mid = day => xOf(day) + colW / 2;
  const sunLine = key => linePath(clock.map(day => day[key] == null ? null : [mid(day.day), yOf(day[key])]));
  // A week's median keeps the voices' line honest without chasing every stray day.
  const rolling = key => lightDays.map((day, i) => {
    const near = lightDays.slice(Math.max(0, i - 3), i + 4).map(d => d[key]).filter(v => v != null).sort((a, b) => a - b);
    return near.length >= 3 ? [mid(day.day), yOf(near[Math.floor(near.length / 2)])] : null;
  });
  const voiceLine = key => linePath(rolling(key));
  const hours = (phone ? [0, 6, 12, 18, 24] : [0, 3, 6, 9, 12, 15, 18, 21, 24]);
  const yLabels = hours.map(hour => `<text x="${left - 6}" y="${(yOf(hour * 60) + 3.5).toFixed(1)}" text-anchor="end">${String(hour).padStart(2, '0')}:00</text>
    <line class="tick" x1="${left - 3}" x2="${left}" y1="${yOf(hour * 60).toFixed(1)}" y2="${yOf(hour * 60).toFixed(1)}"></line>`).join('');
  const months = [];
  for (let n = 0; n < spanDays; n++) {
    const day = new Date((first + n) * DAY_MS).toISOString().slice(0, 10);
    if (day.endsWith('-01') || (n === 0 && Number(day.slice(8)) <= 20)) months.push(day);
  }
  const xLabels = months.map(day => `<text x="${(xOf(day) + 2).toFixed(1)}" y="${height - 8}">${esc(monthShort(day))}</text>
    <line class="tick" x1="${xOf(day).toFixed(1)}" x2="${xOf(day).toFixed(1)}" y1="${top + innerH}" y2="${top + innerH + 4}"></line>`).join('');
  const html = `<div class="chart season-clock" role="img" aria-label="Detections through every quarter-hour of the season, with sunrise, sunset and the first and last voices of each day">
    <svg viewBox="0 0 ${width} ${height}">
      <rect class="plot" x="${left}" y="${top}" width="${innerW}" height="${innerH}"></rect>
      <g class="cells">${cells.join('')}</g>
      <g class="sun-lines"><path class="halo" d="${sunLine('sunrise')}"></path><path class="halo" d="${sunLine('sunset')}"></path>
        <path class="sun" d="${sunLine('sunrise')}"></path><path class="sun" d="${sunLine('sunset')}"></path></g>
      <g class="voice-lines"><path class="halo" d="${voiceLine('first')}"></path><path class="halo" d="${voiceLine('last')}"></path>
        <path class="voice" d="${voiceLine('first')}"></path><path class="voice" d="${voiceLine('last')}"></path></g>
      <rect class="focus-mark" visibility="hidden"></rect>
      ${yLabels}${xLabels}
    </svg><div class="chart-tooltip" aria-hidden="true"></div></div>`;

  const byDay = new Map(clock.map(day => [dayNumber(day.day), day]));
  const lightByDay = new Map(lightDays.map(day => [dayNumber(day.day), day]));
  const resolve = (x, y) => {
    if (x < left || x > left + innerW || y < top || y > top + innerH) return null;
    const n = first + Math.min(spanDays - 1, Math.floor((x - left) / colW));
    const q = Math.min(95, Math.floor((y - top) / qh));
    const day = byDay.get(n);
    const date = new Date(n * DAY_MS).toISOString().slice(0, 10);
    const lines = [`${dateLabel(date, 'short')} · ${clockTime(q * 15)}–${clockTime(q * 15 + 15)}`];
    if (!day) lines.push('Not listening that day');
    else {
      const value = day.q[q];
      lines.push(`${num(value)} ${value === 1 ? 'detection' : 'detections'}`);
      if (day.sunrise != null) lines.push(`Sunrise ${clockTime(day.sunrise)} · sunset ${clockTime(day.sunset)}`);
      const light = lightByDay.get(n);
      if (light?.first != null) lines.push(`First voice ${clockTime(light.first)} · ${light.first_species}`);
      if (light?.last != null) lines.push(`Last voice ${clockTime(light.last)} · ${light.last_species}`);
    }
    return {text: lines.join('\n'), focus: {x: (left + (n - first) * colW).toFixed(2), y: (top + q * qh).toFixed(2),
      width: Math.max(colW, 2).toFixed(2), height: Math.max(qh, 2).toFixed(2)}};
  };
  return {html, resolve};
}

// Columns for a weekly series (one value per week, nulls left blank).
export function weekBars(weeks, values, {height = 170, width = chartWidth(), label = 'By week', tip = () => ''} = {}) {
  if (!weeks?.length) return '<div class="empty">Nothing yet.</div>';
  const left = 40, right = 6, top = 12, bottom = 24;
  const innerW = width - left - right, innerH = height - top - bottom;
  const max = niceCeil(Math.max(1, ...values.map(v => v || 0)));
  const slot = innerW / weeks.length, barW = Math.min(24, slot - 2);
  const ticks = [0, .5, 1].map(frac => {
    const y = top + innerH * (1 - frac);
    return `<line class="grid" x1="${left}" x2="${width - right}" y1="${y}" y2="${y}"></line>
      <text x="${left - 6}" y="${y + 3.5}" text-anchor="end">${num(Math.round(max * frac))}</text>`;
  }).join('');
  let lastMonth = '';
  const bars = weeks.map((week, i) => {
    const value = values[i];
    const x = left + i * slot + (slot - barW) / 2;
    const h = value ? Math.max(1.5, value / max * innerH) : 0;
    const month = monthShort(new Date(Date.parse(`${week.start}T12:00:00Z`) + 3 * DAY_MS).toISOString().slice(0, 10));
    const monthLabel = month !== lastMonth ? `<text x="${(left + i * slot + slot / 2).toFixed(1)}" y="${height - 8}" text-anchor="middle">${esc(month)}</text>` : '';
    lastMonth = month;
    const detail = tip(week, value, i);
    return `<g ${detail ? `data-chart-tip="${attr(detail)}"` : ''}><rect class="hit" x="${(left + i * slot).toFixed(1)}" y="${top}" width="${slot.toFixed(1)}" height="${innerH}"></rect>
      ${h ? `<path class="bar" d="${columnPath(x, top + innerH - h, barW, h)}"></path>` : ''}</g>${monthLabel}`;
  }).join('');
  return `<div class="chart interactive-chart" role="img" aria-label="${attr(label)}"><svg viewBox="0 0 ${width} ${height}">
    ${ticks}${bars}</svg><div class="chart-tooltip" aria-hidden="true"></div></div>`;
}

// The life list accumulating: a step line with a soft wash, labelled at its end.
export function growthChart(points, {height = 190} = {}) {
  if (!points?.length) return '<div class="empty">The life list starts with the first bird.</div>';
  const width = chartWidth(), left = 34, right = 16, top = 14, bottom = 24;
  const innerW = width - left - right, innerH = height - top - bottom;
  const first = dayNumber(points[0].day);
  const spanDays = Math.max(1, dayNumber(points.at(-1).day) - first);
  const max = niceCeil(Math.max(1, points.at(-1).total));
  const xOf = day => left + (dayNumber(day) - first) / spanDays * innerW;
  const yOf = total => top + innerH - total / max * innerH;
  let path = '';
  points.forEach((point, i) => {
    const x = xOf(point.day).toFixed(1), y = yOf(point.total).toFixed(1);
    path += i ? `H${x}V${y}` : `M${x} ${y}`;
  });
  const area = `${path}V${top + innerH}H${xOf(points[0].day).toFixed(1)}Z`;
  const end = points.at(-1);
  const ticks = [0, .5, 1].map(frac => {
    const y = top + innerH * (1 - frac);
    return `<line class="grid" x1="${left}" x2="${width - right}" y1="${y}" y2="${y}"></line>
      <text x="${left - 6}" y="${y + 3.5}" text-anchor="end">${Math.round(max * frac)}</text>`;
  }).join('');
  const strips = points.map((point, i) => {
    const x0 = i ? (xOf(points[i - 1].day) + xOf(point.day)) / 2 : left;
    const x1 = i < points.length - 1 ? (xOf(point.day) + xOf(points[i + 1].day)) / 2 : width - right;
    const added = point.total - (i ? points[i - 1].total : 0);
    const detail = `${dateLabel(point.day, 'short')} · ${point.total} species${added ? ` (+${added})` : ''}`;
    return `<rect class="hit" x="${x0.toFixed(1)}" y="${top}" width="${Math.max(.5, x1 - x0).toFixed(1)}" height="${innerH}" data-chart-tip="${attr(detail)}"></rect>`;
  }).join('');
  const months = [];
  for (let n = 0; n <= spanDays; n++) {
    const day = new Date((first + n) * DAY_MS).toISOString().slice(0, 10);
    if (day.endsWith('-01') || (n === 0 && Number(day.slice(8)) <= 20)) months.push(day);
  }
  const xLabels = months.map(day => `<text x="${(xOf(day) + 2).toFixed(1)}" y="${height - 7}">${esc(monthShort(day))}</text>`).join('');
  return `<div class="chart interactive-chart growth-chart" role="img" aria-label="Well-supported species on the life list, day by day: ${end.total} now">
    <svg viewBox="0 0 ${width} ${height}">${ticks}<path class="area" d="${area}"></path><path class="line" d="${path}"></path>
      <circle class="end-dot" cx="${xOf(end.day).toFixed(1)}" cy="${yOf(end.total).toFixed(1)}" r="4"></circle>
      ${xLabels}${strips}</svg><div class="chart-tooltip" aria-hidden="true"></div></div>`;
}


// Who wakes first: each species' median start against sunrise, with the
// middle half of its mornings as a bar.
export function dawnRoster(rows) {
  if (!rows?.length) return '<div class="empty">Not enough mornings yet to say who wakes first.</div>';
  const floor30 = value => Math.floor(value / 30) * 30, ceil30 = value => Math.ceil(value / 30) * 30;
  const lo = Math.max(-150, Math.min(-60, floor30(Math.min(...rows.map(r => r.q1)))));
  const hi = Math.min(240, Math.max(60, ceil30(Math.max(...rows.map(r => r.q3)))));
  const at = minutes => `${((Math.min(hi, Math.max(lo, minutes)) - lo) / (hi - lo) * 100).toFixed(2)}%`;
  const when = minutes => minutes === 0 ? 'at sunrise' : `${span(minutes)} ${minutes < 0 ? 'before' : 'after'}`;
  const signed = minutes => minutes === 0 ? '0 min' : `${minutes < 0 ? '−' : '+'}${Math.abs(minutes)} min`;
  const ticks = [];
  for (let m = Math.ceil(lo / 60) * 60; m <= hi; m += 60) ticks.push(m);
  const axis = `<div class="roster-axis"><span></span><div>${ticks.map(m => `<span style="left:${at(m)}">${m === 0 ? 'sunrise' : `${m > 0 ? '+' : '−'}${Math.abs(m / 60)} h`}</span>`).join('')}</div><span></span></div>`;
  const body = rows.map(row => {
    const detail = `${row.common_name}\nUsually gets going ${when(row.median)}\nMiddle half of mornings: ${when(row.q1)} to ${when(row.q3)}\n${row.mornings} mornings`;
    return `<div class="roster-row" role="listitem" data-chart-tip="${attr(detail)}">
      <a href="${speciesHref(row.common_name)}">${esc(row.common_name)}</a>
      <div class="roster-track" style="--zero:${at(0)}"><i style="left:${at(row.q1)};width:calc(${at(row.q3)} - ${at(row.q1)})"></i><b style="left:${at(row.median)}"></b></div>
      <span><span class="long">${Math.abs(row.median)} min ${row.median < 0 ? 'before' : 'after'}</span><span class="short">${signed(row.median)}</span></span>
    </div>`;
  }).join('');
  return `<div class="roster interactive-chart" role="list" aria-label="Species in the order they start singing, against sunrise">${axis}${body}<div class="chart-tooltip" aria-hidden="true"></div></div>`;
}

// The season chart: one row per species, one cell per week, darker where it
// was heard on more of that week's listening days.
export function seasonChart(rows, weeks, groups) {
  if (!rows?.length) return '<div class="empty">No well-supported species yet.</div>';
  const columns = `--weeks:${weeks.length}`;
  let lastMonth = '';
  const axis = `<div class="pheno-axis" style="${columns}"><span></span>${weeks.map(week => {
    const month = monthShort(new Date(Date.parse(`${week.start}T12:00:00Z`) + 3 * DAY_MS).toISOString().slice(0, 10));
    const label = month !== lastMonth ? month : '';
    lastMonth = month;
    return `<span>${esc(label)}</span>`;
  }).join('')}<span>days</span></div>`;
  const body = groups.map(group => {
    const members = rows.filter(row => row.status === group.status);
    if (!members.length) return '';
    const fold = members.length > 8;
    return `<div class="pheno-group"><h3>${esc(group.title)} <small>${members.length}</small></h3><p>${esc(group.note)}</p></div>
      <div class="pheno-members" data-collapsed="${fold}">${members.map(row => `<div class="pheno-row" style="${columns}">
        <a href="${speciesHref(row.common_name)}" title="Open ${attr(row.common_name)} dossier">${esc(row.common_name)}<small>${esc(group.detail(row))}</small></a>
        ${weeks.map((week, i) => {
          const heard = row.presence[i], days = week.days;
          const share = days ? heard / days : 0;
          const detail = `${row.common_name}\nWeek of ${dateLabel(week.start, 'short')}\n` + (days
            ? `Heard on ${heard} of ${days} listening ${days === 1 ? 'day' : 'days'} · ${num(row.volume[i])} ${row.volume[i] === 1 ? 'detection' : 'detections'}`
            : 'Not listening that week');
          return `<span class="pheno-cell${days ? '' : ' off'}" aria-hidden="true" style="--strength:${heard ? Math.round(18 + share * 82) : 0}%" data-chart-tip="${attr(detail)}"></span>`;
        }).join('')}
        <b>${row.days}</b>
      </div>`).join('')}</div>
      ${fold ? `<button type="button" class="text-link pheno-more" data-more="${members.length}">Show all ${members.length}</button>` : ''}`;
  }).join('');
  return `<div class="season-chart interactive-chart" role="group" aria-label="Each species, week by week across the season">${axis}<div>${body}</div><div class="chart-tooltip" aria-hidden="true"></div></div>`;
}
