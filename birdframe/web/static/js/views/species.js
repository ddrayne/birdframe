import {
  api, cachedApi, app, attr, esc, num, percent, dateLabel, hourLabel, speciesHref,
  tierBadge, playButton, pageHeader, routeIsCurrent,
} from '../core.js';
import {areaChart, confidenceBars, hourBars} from '../charts.js';
import {clipCards, reliabilityLegend, stats} from '../components.js';

function speciesCard(species) {
  return `<a class="species-card card" href="${speciesHref(species.common_name)}" data-name="${attr(species.common_name.toLowerCase())}" data-tier="${attr(species.tier)}">
    <div><h2>${esc(species.common_name)}</h2><div class="scientific">${esc(species.scientific_name)}</div></div>
    <div class="species-tags">${tierBadge(species.tier, species.reasons)}<span class="muted">${esc(species.rarity)}</span></div>
    <div class="species-card-foot">
      <div><b>${num(species.total)}</b><small>detections</small></div>
      <div class="rhythm">${species.days} active days<br>peak ${hourLabel(species.peak_hour)}</div>
    </div>
  </a>`;
}

function directorySort(list, sort) {
  const copy = [...list];
  if (sort === 'name') copy.sort((a, b) => a.common_name.localeCompare(b.common_name));
  else if (sort === 'recent') copy.sort((a, b) => b.last_day.localeCompare(a.last_day) || b.total - a.total);
  else if (sort === 'new') copy.sort((a, b) => b.first_day.localeCompare(a.first_day) || b.total - a.total);
  else if (sort === 'rarity') copy.sort((a, b) => a.geo - b.geo || b.total - a.total);
  else copy.sort((a, b) => b.total - a.total);
  return copy;
}

async function renderDirectory(token) {
  const data = await cachedApi('/api/census', 20_000);
  if (!routeIsCurrent(token)) return;
  const directory = data.life_list;
  const tierCounts = Object.fromEntries(['confirmed', 'probable', 'tentative'].map(tier => [tier, directory.filter(s => s.tier === tier).length]));

  app.innerHTML = `<article class="page">
    ${pageHeader('The life list', 'Species', `Every voice birdframe has associated with a species—${directory.length} dossiers, each opening into rhythms, dates, recordings, confidence, companions, and artwork.`)}
    ${stats([
      {value: directory.length, label: 'species dossiers'},
      {value: tierCounts.confirmed, label: 'confirmed'},
      {value: tierCounts.probable, label: 'probable'},
      {value: tierCounts.tentative, label: 'tentative'},
    ])}
    <div class="section-head"><div><div class="eyebrow">Find a voice</div><h2>Explore the life list</h2></div></div>
    <div class="filter-bar card card-pad">
      <label class="search"><span class="sr-only">Search species</span><input id="speciesSearch" type="search" placeholder="Search common or scientific name…" autocomplete="off"></label>
      <div class="segmented" id="directoryTier" aria-label="Reliability filter">
        <button class="active" data-tier="all">All</button><button data-tier="confirmed">Confirmed</button><button data-tier="probable">Probable</button><button data-tier="tentative">Tentative</button>
      </div>
      <select id="speciesSort" aria-label="Sort species"><option value="count">Most detected</option><option value="name">A–Z</option><option value="recent">Heard most recently</option><option value="new">Newest to the journal</option><option value="rarity">Most unusual here</option></select>
    </div>
    <div style="margin-top:13px">${reliabilityLegend()}</div>
    <div class="section-note" id="directoryCount" style="margin:15px 0 0"></div>
    <div class="species-directory" id="speciesDirectory"></div>
  </article>`;

  let tier = 'all';
  const search = document.querySelector('#speciesSearch');
  const sort = document.querySelector('#speciesSort');
  const host = document.querySelector('#speciesDirectory');
  const draw = () => {
    const query = search.value.trim().toLowerCase();
    const filtered = directorySort(directory.filter(s =>
      (tier === 'all' || s.tier === tier) && (!query || s.common_name.toLowerCase().includes(query) || s.scientific_name.toLowerCase().includes(query))), sort.value);
    host.innerHTML = filtered.length ? filtered.map(speciesCard).join('') : '<div class="empty">No species match those filters.</div>';
    document.querySelector('#directoryCount').textContent = `${filtered.length} of ${directory.length} species`;
  };
  search.addEventListener('input', draw);
  sort.addEventListener('change', draw);
  document.querySelector('#directoryTier').addEventListener('click', event => {
    const button = event.target.closest('button[data-tier]');
    if (!button) return;
    tier = button.dataset.tier;
    document.querySelectorAll('#directoryTier button').forEach(el => el.classList.toggle('active', el === button));
    draw();
  });
  draw();
}

function rangeLinks(name, days) {
  const ranges = [[null, 'All time'], [7, '7 days'], [30, '30 days'], [90, '90 days']];
  return `<div class="segmented" aria-label="Species date range">${ranges.map(([value, label]) => {
    const query = value ? `?days=${value}` : '';
    return `<a class="${String(value ?? '') === String(days ?? '') ? 'active' : ''}" href="${speciesHref(name, query)}">${label}</a>`;
  }).join('')}</div>`;
}

function insight(d) {
  const peak = d.hours.indexOf(Math.max(...d.hours));
  const share = percent(d.share, d.share < .01 ? 1 : 0);
  const clip = d.clips.length ? ` There ${d.clips.length === 1 ? 'is' : 'are'} ${d.clips.length} saved ${d.clips.length === 1 ? 'recording' : 'recordings'} to revisit.` : '';
  return `${d.common_name} accounts for ${share} of detections in this range, with the strongest hourly concentration around ${hourLabel(peak)}. It was detected on ${d.days} recorded ${d.days === 1 ? 'day' : 'days'}.${clip}`;
}

function dailyTable(d) {
  const clips = new Map(d.clips.map(clip => [clip.day, clip]));
  const rows = [...d.daily].reverse();
  return `<div style="overflow:auto"><table class="day-table"><thead><tr><th>Date</th><th>Span</th><th class="number">Detections</th><th class="number">Best</th><th>Clip</th></tr></thead>
    <tbody>${rows.map(row => {
      const clip = clips.get(row.day);
      return `<tr><td><a href="#journal/${row.day}">${esc(dateLabel(row.day, 'short'))}</a></td><td>${esc(row.first_time)}–${esc(row.last_time)}</td><td class="number">${num(row.detections)}</td><td class="number">${Math.round(row.best_confidence * 100)}%</td><td>${clip ? playButton(clip.url, `${d.common_name} on ${row.day}`) : '—'}</td></tr>`;
    }).join('')}</tbody></table></div>`;
}

function observations(d) {
  if (!d.observations.length) return '<div class="empty">No observation rows in this range.</div>';
  return `<div class="observation-list" id="observationList">${d.observations.map(row => `<div class="observation">
    <time>${esc(row.ts.replace('T', ' '))}</time><span>BirdNET match</span><b class="mono">${Math.round(row.confidence * 100)}%</b>
  </div>`).join('')}</div>`;
}

function companions(d) {
  if (!d.companions.length) return '<div class="empty">No overlapping 15-minute soundscapes in this range.</div>';
  return `<div class="companion-list">${d.companions.map(item => `<div class="companion"><div>
    <a href="${speciesHref(item.common_name)}">${esc(item.common_name)}</a><small>${esc(item.scientific_name)}</small></div>
    <div style="text-align:right">${item.tier ? tierBadge(item.tier) : ''}<small>${num(item.shared_windows)} shared windows</small></div>
  </div>`).join('')}</div>`;
}

function artworks(d) {
  if (!d.images.length) return '';
  return `<section><div class="section-head"><div><div class="eyebrow">In the picture archive</div><h2>Artwork appearances</h2><p>Pictures whose stored roll call includes ${esc(d.common_name)}.</p></div></div>
    <div class="art-strip">${d.images.map(image => `<button type="button" class="art-tile image-button" style="border:0;background:none;padding:0;text-align:left" data-lightbox="/api/image/${image.id}" data-alt="${attr(image.style)} artwork" data-caption="${attr(image.generated_at.slice(0, 10) + ' · ' + image.style)}">
      <img loading="lazy" src="/api/image/${image.id}" alt="${attr(image.style)} artwork"><small>${esc(image.generated_at.slice(0, 10))} · ${esc(image.style)}</small></button>`).join('')}</div></section>`;
}

async function renderDossier(token, name, days) {
  const query = days ? `?days=${days}` : '';
  const dossier = await api(`/api/species/${encodeURIComponent(name)}${query}`);
  if (!routeIsCurrent(token)) return;
  const [wiki, extra] = await Promise.all([
    cachedApi(`/api/bird/${encodeURIComponent(dossier.scientific_name)}`, 86_400_000).catch(() => ({})),
    cachedApi(`/api/species-extra/${encodeURIComponent(dossier.scientific_name)}`, 86_400_000).catch(() => ({})),
  ]);
  if (!routeIsCurrent(token)) return;
  const peak = dossier.hours.indexOf(Math.max(...dossier.hours));
  const portrait = wiki.thumbnail
    ? `<img class="species-portrait" src="${attr(wiki.thumbnail)}" alt="${attr(dossier.common_name)}">`
    : '<div class="species-portrait-placeholder" aria-hidden="true">♧</div>';
  const rangeName = days ? `last ${days} days` : 'all time';

  app.innerHTML = `<article class="page">
    <a class="back-link" href="#species">← All species</a>
    <section class="species-hero card">
      <div class="species-hero-copy">
        <div class="eyebrow">Species dossier · rank #${dossier.rank || '—'} by detections</div>
        <h1>${esc(dossier.common_name)}</h1>
        <div class="scientific">${esc(dossier.scientific_name)} · ${tierBadge(dossier.tier, dossier.reasons)}</div>
        <p class="lede">${esc((wiki.extract || `A species heard at the Edinburgh window across ${dossier.days} recorded days.`).slice(0, 430))}${wiki.extract?.length > 430 ? '…' : ''}</p>
        <div class="listen-pair">
          ${dossier.clip_url ? playButton(dossier.clip_url, `${dossier.common_name} · your recording`, 'Best saved clip from your window', 'listen-button') : ''}
          ${extra.reference_audio ? playButton(extra.reference_audio, `${dossier.common_name} · reference song`, extra.reference_title || 'Reference recording', 'listen-button') : ''}
          ${wiki.url ? `<a class="btn secondary small" href="${attr(wiki.url)}" target="_blank" rel="noopener">Natural history ↗</a>` : ''}
        </div>
      </div>
      ${portrait}
      <div class="species-summary">
        <div><b>${num(dossier.total)}</b><span>detections · ${rangeName}</span></div>
        <div><b>${dossier.days}</b><span>days with detections</span></div>
        <div><b>${percent(dossier.share, dossier.share < .01 ? 1 : 0)}</b><span>of all detections</span></div>
        <div><b>${hourLabel(peak)}</b><span>peak hour</span></div>
      </div>
    </section>

    <div class="range-bar"><div><div class="eyebrow">Time range</div><div class="section-note">Charts and counts change; the reliability tier remains a lifetime assessment.</div></div>${rangeLinks(name, days)}</div>
    <div class="insight">${esc(insight(dossier))}</div>

    <div class="dossier-grid" style="margin-top:18px">
      <section class="card dossier-section"><h2>Day by day</h2><p>Detection intensity on days when this species appeared.</p>${areaChart(dossier.daily, 'detections', {label: `${dossier.common_name} detections by day`})}</section>
      <section class="card dossier-section"><h2>Confidence profile</h2><p>${num(dossier.total)} matches · average ${Math.round(dossier.avg_confidence * 100)}% · best ${Math.round(dossier.best_confidence * 100)}%</p>${confidenceBars(dossier.confidence_histogram)}</section>
    </div>

    <div class="dossier-grid" style="margin-top:18px">
      <section class="card dossier-section"><h2>When it is heard</h2><p>Detections from ${rangeName}, grouped by hour.</p>${hourBars(dossier.hours, {label: `${dossier.common_name} detections by hour`})}</section>
      <section class="card dossier-section"><h2>Soundscape companions</h2><p>Other species detected in the same 15-minute windows—not a claim of biological association.</p>${companions(dossier)}</section>
    </div>

    <section class="card dossier-section" style="margin-top:18px"><h2>The detection journal</h2><p>Every active day, with its span, evidence, and saved clip.</p>${dailyTable(dossier)}</section>

    <div class="dossier-grid" style="margin-top:18px">
      <section class="card dossier-section"><h2>Your recordings</h2><p>The clearest saved clip from each day.</p>${clipCards(dossier.clips)}</section>
      <section class="card dossier-section"><h2>Recent raw matches</h2><p>Individual stored rows, newest first. Repetition reflects BirdNET analysis windows, not a bird count.</p>${observations(dossier)}</section>
    </div>

    ${(extra.range_map || extra.gbif_url) ? `<section class="card dossier-section" style="margin-top:18px"><h2>Where in the world</h2><p>External distribution context; your window data remains local.</p>
      <div class="grid-2" style="align-items:center">${extra.range_map ? `<img class="range-map" loading="lazy" src="${attr(extra.range_map)}" alt="Global distribution map for ${attr(dossier.common_name)}">` : '<div></div>'}
      <div><p class="muted">Compare the species’ global distribution with BirdNET’s local plausibility rating: <strong>${esc(dossier.rarity)}</strong>.</p>
      ${extra.gbif_url ? `<a class="btn secondary" href="${attr(extra.gbif_url)}" target="_blank" rel="noopener">Explore occurrence records on GBIF ↗</a>` : ''}</div></div></section>` : ''}

    ${artworks(dossier)}
  </article>`;
}

export async function renderSpecies(token, name = null, params = new URLSearchParams()) {
  if (!name) return renderDirectory(token);
  const days = params.get('days') ? Number(params.get('days')) : null;
  return renderDossier(token, name, days);
}
