import {
  api, app, esc, num, dateLabel, hourLabel, speciesHref, tierBadge,
  pageHeader, routeIsCurrent,
} from '../core.js';
import {
  areaChart, dailySpeciesBars, heatmap, hourBars, initChartTooltips, soundscapeScore,
} from '../charts.js';
import {stats} from '../components.js';

function patternUrl(days, tiers) {
  const params = new URLSearchParams();
  if (days) params.set('days', days);
  if (tiers.join(',') !== 'confirmed,probable,tentative') params.set('tiers', tiers.join(','));
  const query = params.toString();
  return `#patterns${query ? `?${query}` : ''}`;
}

function patternControls(days, tiers) {
  return `<div class="pattern-controls card card-pad">
    <div><div class="eyebrow">Time range</div><div class="segmented" style="margin-top:7px">
      ${[[null, 'All time'], [7, '7 days'], [30, '30 days'], [90, '90 days']].map(([value, label]) =>
        `<a class="${String(value ?? '') === String(days ?? '') ? 'active' : ''}" href="${patternUrl(value, tiers)}">${label}</a>`).join('')}
    </div></div>
    <div><div class="eyebrow">Evidence layers</div><div class="tier-filter" id="patternTiers" style="margin-top:7px">
      ${['confirmed', 'probable', 'tentative'].map(tier => `<label><input type="checkbox" value="${tier}" ${tiers.includes(tier) ? 'checked' : ''}><span>${tierBadge(tier)}</span></label>`).join('')}
    </div></div>
  </div>`;
}

function callouts(data) {
  const peakHour = data.hours.indexOf(Math.max(...data.hours));
  const busiest = [...data.daily].sort((a, b) => b.detections - a.detections)[0];
  const leader = data.by_species[0];
  return `<div class="pattern-callouts">
    <div class="pattern-callout soft-card"><strong>${hourLabel(peakHour)}</strong><span>peak hour · ${num(data.hours[peakHour])} detections</span></div>
    <div class="pattern-callout soft-card"><strong>${busiest ? dateLabel(busiest.day, 'short') : '—'}</strong><span>busiest day · ${num(busiest?.detections || 0)} detections</span></div>
    <div class="pattern-callout soft-card"><strong>${esc(leader?.common_name || '—')}</strong><span>leading species · ${num(leader?.detections || 0)} detections</span></div>
  </div>`;
}

function unusual(data) {
  const rows = [...data.by_species].filter(s => s.geo != null).sort((a, b) => a.geo - b.geo).slice(0, 8);
  if (!rows.length) return '<div class="empty">No species in the selected evidence layers.</div>';
  return `<div class="companion-list">${rows.map(row => `<div class="companion"><div><a href="${speciesHref(row.common_name)}">${esc(row.common_name)}</a><small>${esc(row.scientific_name)}</small></div>
    <div style="text-align:right">${tierBadge(row.tier)}<small>${esc(row.rarity)} · ${num(row.detections)} ${row.detections === 1 ? 'detection' : 'detections'}</small></div></div>`).join('')}</div>`;
}

function peakHour(row) {
  const hours = row.hours || [];
  return hours.indexOf(Math.max(...hours));
}

export async function renderPatterns(token, params = new URLSearchParams()) {
  const days = params.get('days') ? Number(params.get('days')) : null;
  const tiers = (params.get('tiers') || 'confirmed,probable,tentative').split(',').filter(Boolean);
  const query = new URLSearchParams({tiers: tiers.join(',')});
  if (days) query.set('days', days);
  const data = await api(`/api/patterns?${query}`);
  if (!routeIsCurrent(token)) return;
  const rangeName = days ? `the last ${days} days` : 'the whole journal';

  app.innerHTML = `<article class="page">
    ${pageHeader('The view from above', 'Patterns', `Step back from individual detections and read the rhythms of ${rangeName}: dawns, busy days, richness, reliability, and unusual voices.`)}
    ${patternControls(days, tiers)}
    ${stats([
      {value: data.totals.species || 0, label: 'species in view'},
      {value: num(data.totals.detections || 0), label: 'BirdNET detections'},
      {value: data.totals.days || 0, label: 'active journal days'},
      {value: data.totals.since ? data.totals.since.slice(5) : '—', label: 'range begins'},
    ])}
    <div style="margin-top:14px">${callouts(data)}</div>

    <div class="dossier-grid" style="margin-top:18px">
      <section class="card dossier-section"><h2>The accumulating chorus</h2><p>Detection volume by day; counts reflect analysis windows, not individual birds.</p>${areaChart(data.daily, 'detections', {label: 'All selected detections by day'})}</section>
      <section class="card dossier-section"><h2>Species richness</h2><p>How many distinct species appeared on each recorded day.</p>${dailySpeciesBars(data.daily)}</section>
    </div>

    <div class="dossier-grid" style="margin-top:18px">
      <section class="card dossier-section"><h2>The 24-hour rhythm</h2><p>Hover an hour to meet the voices inside it.</p>${hourBars(data.hours, {speciesByHour: data.hour_species})}</section>
      <section class="card dossier-section"><h2>Unusual voices</h2><p>Lowest local plausibility in the selected view. Reliability remains visible alongside rarity.</p>${unusual(data)}</section>
    </div>

    <section class="card dossier-section" style="margin-top:18px">
      <div class="section-head" style="margin-top:0"><div><div class="eyebrow gold">The soundscape score</div><h2>Watch the chorus pass through the day</h2><p>Every row is one species’ 24-hour signature, normalised to reveal its own shape. Gold outlines mark its peak hour; hover any square for the stored count.</p></div></div>
      <div class="filter-bar soft-card" style="padding:10px 12px;margin-bottom:12px">
        <label class="search"><span class="sr-only">Search the soundscape score</span><input id="scoreSearch" type="search" placeholder="Find a species in the score…" autocomplete="off"></label>
        <div class="segmented" id="scoreSort" aria-label="Sort soundscape score"><button class="active" data-sort="peak">Chorus order</button><button data-sort="count">Most heard</button><button data-sort="name">A–Z</button></div>
      </div>
      <div class="section-note" id="scoreCount" style="margin-bottom:8px"></div>
      <div id="soundscapeScore"></div>
    </section>

    <section class="card dossier-section" style="margin-top:18px"><h2>Day × hour</h2><p>Hover a cell to see which species made that hour. Horizontal scrolling preserves all 24 hours on small screens.</p>${heatmap(data.heatmap)}</section>

    <section class="card card-pad" style="margin-top:18px">
      <div class="eyebrow">How to read this</div>
      <p class="muted">Filters never delete or rewrite the archive. They change only which reliability layers are included in these derived views. A quiet cell means no stored detection in that hour; birdframe does not yet record a separate microphone-uptime history, so it should not be read as proof of absence.</p>
    </section>
  </article>`;

  document.querySelector('#patternTiers')?.addEventListener('change', event => {
    const selected = [...document.querySelectorAll('#patternTiers input:checked')].map(input => input.value);
    if (!selected.length) {
      event.target.checked = true;
      return;
    }
    location.hash = patternUrl(days, selected).slice(1);
  });

  const scoreHost = document.querySelector('#soundscapeScore');
  const scoreSearch = document.querySelector('#scoreSearch');
  let scoreSort = 'peak';
  const drawScore = () => {
    const queryText = scoreSearch.value.trim().toLowerCase();
    const rows = data.by_species.filter(row => !queryText || row.common_name.toLowerCase().includes(queryText) || row.scientific_name.toLowerCase().includes(queryText));
    rows.sort((a, b) => scoreSort === 'count' ? b.detections - a.detections
      : scoreSort === 'name' ? a.common_name.localeCompare(b.common_name)
      : peakHour(a) - peakHour(b) || b.detections - a.detections);
    scoreHost.innerHTML = soundscapeScore(rows);
    document.querySelector('#scoreCount').textContent = `${rows.length} of ${data.by_species.length} species · each row uses its own intensity scale`;
    initChartTooltips(scoreHost);
  };
  scoreSearch.addEventListener('input', drawScore);
  document.querySelector('#scoreSort').addEventListener('click', event => {
    const button = event.target.closest('button[data-sort]');
    if (!button) return;
    scoreSort = button.dataset.sort;
    document.querySelectorAll('#scoreSort button').forEach(el => el.classList.toggle('active', el === button));
    drawScore();
  });
  drawScore();
}
