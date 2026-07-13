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
  const width = 720;
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
  const labels = rows.map((row, i) => i % labelEvery === 0 || i === rows.length - 1
    ? `<text x="${pts[i].x}" y="${height - 7}" text-anchor="middle">${esc(row.day.slice(5))}</text>` : '').join('');
  return `<div class="chart" role="img" aria-label="${esc(label)}"><svg viewBox="0 0 ${width} ${height}">
    ${yTicks}<path class="area" d="${area}"></path><path class="line" d="${path}"></path>${dots}${labels}
  </svg></div>`;
}

export function hourBars(hours, {height = 210, label = 'Detections around the 24-hour clock', speciesByHour = null} = {}) {
  const width = 720, left = 30, right = 8, top = 14, bottom = 28;
  const values = hours || Array(24).fill(0);
  const max = Math.max(1, ...values);
  const innerW = width - left - right;
  const innerH = height - top - bottom;
  const gap = 4;
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
  const width = 720, height = 135, left = 30, right = 8, top = 12, bottom = 25;
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
  const max = Math.max(1, ...rows.map(row => row.species || 0));
  return `<div class="confidence-bars" style="grid-template-columns:repeat(${rows.length},1fr)" role="img" aria-label="Species richness by day">
    ${rows.map(row => `<i style="height:${Math.max(2, row.species / max * 100)}%"><title>${esc(dateLabel(row.day, 'short'))}: ${row.species} species</title></i>`).join('')}
  </div><div class="chart-caption"><span>${esc(rows[0].day.slice(5))}</span><span>species per day</span><span>${esc(rows.at(-1).day.slice(5))}</span></div>`;
}
