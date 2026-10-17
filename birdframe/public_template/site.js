/* The public edition of a birdframe journal: a read-only, static page.
   All data is embedded by the builder; nothing here writes anywhere. */
(() => {
  'use strict';

  const DATA = JSON.parse(document.getElementById('journal-data').textContent);
  const main = document.getElementById('main');
  const paintings = DATA.paintings;
  const species = DATA.species;
  const bySlug = new Map(species.map(b => [b.slug, b]));
  const byName = new Map(species.map(b => [b.name, b]));
  const byId = new Map(paintings.map(p => [p.id, p]));

  // ── small helpers ─────────────────────────────────────────────
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => (
    {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const asDate = day => new Date(`${day}T12:00:00`);
  const fmt = (day, style) => new Intl.DateTimeFormat('en-GB', {
    long: {weekday: 'long', day: 'numeric', month: 'long'},
    medium: {day: 'numeric', month: 'long', year: 'numeric'},
    short: {day: 'numeric', month: 'short'},
    month: {month: 'long', year: 'numeric'},
  }[style]).format(asDate(day));
  const hourLabel = h => (h === 0 ? 'midnight' : h === 12 ? 'noon' : `${h % 12}${h < 12 ? 'am' : 'pm'}`);
  const time = iso => iso.slice(11, 16);

  function picture(p, sizes, alt, eager = false) {
    const src = p.images;
    return `<img src="${src['960']}" srcset="${src['480']} 480w, ${src['960']} 960w, ${src['1200']} 1200w"
      sizes="${sizes}" width="1200" height="1600" alt="${esc(alt)}"
      ${eager ? 'fetchpriority="high"' : 'loading="lazy"'} decoding="async">`;
  }

  const altFor = p => `${p.style} painting of ${p.birds.length ? p.birds.join(', ') : 'a quiet garden'}, ${fmt(p.day, 'medium')}`;

  // A day as a sun-path dial, facing south from the window: midnight at the
  // bottom, dawn on the left, noon at the top, dusk on the right. Each petal
  // is an hour; its length is how much the bird sings then.
  function clock(bird, size, labels = false) {
    const c = 50, inner = labels ? 16 : 13, outer = labels ? 38 : 47, gap = 0.035;
    const angle = h => Math.PI / 2 + (h / 24) * 2 * Math.PI;
    const at = (r, a) => `${(c + r * Math.cos(a)).toFixed(2)} ${(c + r * Math.sin(a)).toFixed(2)}`;
    const petals = bird.rhythm.map((v, h) => {
      if (!v) return '';
      const a0 = angle(h) + gap, a1 = angle(h + 1) - gap;
      const r = inner + (outer - inner) * Math.sqrt(v);
      return `<path class="petal${h === bird.peak ? ' peak' : ''}" d="M${at(inner, a0)} L${at(r, a0)} A${r} ${r} 0 0 1 ${at(r, a1)} L${at(inner, a1)} A${inner} ${inner} 0 0 0 ${at(inner, a0)}Z"></path>`;
    }).join('');
    const marks = labels ? [[0, 'midnight'], [6, '6am'], [12, 'noon'], [18, '6pm']].map(([h, text]) => {
      const a = angle(h), anchor = h === 6 ? 'end' : h === 18 ? 'start' : 'middle';
      const nudge = h === 0 ? 8 : h === 12 ? -3 : 3;
      return `<line class="tick" x1="${(c + (outer + 1) * Math.cos(a)).toFixed(2)}" y1="${(c + (outer + 1) * Math.sin(a)).toFixed(2)}" x2="${(c + (outer + 5) * Math.cos(a)).toFixed(2)}" y2="${(c + (outer + 5) * Math.sin(a)).toFixed(2)}"></line>
        <text x="${(c + (outer + 8) * Math.cos(a)).toFixed(2)}" y="${(c + (outer + 8) * Math.sin(a) + nudge).toFixed(2)}" text-anchor="${anchor}">${text}</text>`;
    }).join('') : '';
    const view = labels ? '-14 -8 128 116' : '0 0 100 100';
    return `<svg class="clock" viewBox="${view}" width="${size}" height="${size}" role="img"
      aria-label="${esc(bird.name)} sings most around ${hourLabel(bird.peak)}">
      <circle class="dial" cx="${c}" cy="${c}" r="${outer}"></circle>
      <circle class="dial" cx="${c}" cy="${c}" r="${inner}"></circle>${petals}${marks}</svg>`;
  }

  const birdLink = name => {
    const bird = byName.get(name);
    return bird ? `<a href="#b-${bird.slug}">${esc(name)}</a>` : `<span>${esc(name)}</span>`;
  };
  const birdLine = names => names.length
    ? `<p class="bird-line">${names.map(birdLink).join('')}</p>` : '';

  function tile(p) {
    return `<a class="tile" href="#p-${p.id}">
      ${picture(p, '(min-width: 900px) 260px, (min-width: 700px) 30vw, 45vw', altFor(p))}
      <span class="date">${esc(fmt(p.day, 'short'))}</span>
      <span class="kind">${esc(p.style)}${p.frame ? ' <span class="hung" title="Hung on the frame">●</span>' : ''}</span></a>`;
  }

  const sectionHead = (title, link = '') => `<div class="section-head"><h2>${title}</h2>${link}</div>`;

  // Weekly presence: each square a week, darker for more days heard.
  function phenology(birds) {
    if (!DATA.since || !birds.length) return '<p class="empty">The season starts with the first morning of listening.</p>';
    const start = asDate(DATA.since);
    const weeks = Math.ceil(((asDate(DATA.until) - start) / 86400000 + 1) / 7);
    const monthCells = Array.from({length: weeks}, (_, w) => {
      const day = new Date(start.getTime() + w * 7 * 86400000);
      const first = w === 0 || day.getDate() <= 7;
      return `<th scope="col">${first ? `<span>${esc(new Intl.DateTimeFormat('en-GB', {month: 'short'}).format(day))}</span>` : ''}</th>`;
    }).join('');
    const rows = birds.map(b => {
      const cells = Array.from({length: weeks}, (_, w) => {
        const days = [...b.presence.slice(w * 7, w * 7 + 7)].filter(mark => mark === '1').length;
        if (!days) return '<td></td>';
        const weekOf = fmt(new Date(start.getTime() + w * 7 * 86400000).toISOString().slice(0, 10), 'short');
        return `<td data-days="${days}" style="--fill:${Math.round(22 + days / 7 * 78)}%" title="${esc(b.name)} · week of ${weekOf} · ${plural(days, 'day')}"></td>`;
      }).join('');
      return `<tr><th scope="row" class="bird"><a href="#b-${b.slug}">${esc(b.name)}</a></th>${cells}</tr>`;
    }).join('');
    return `<div class="phenology"><table><thead><tr><th class="bird"></th>${monthCells}</tr></thead><tbody>${rows}</tbody></table></div>
      <p class="legend">Heard on <i style="background:color-mix(in srgb,var(--forest) 33%,var(--surface-soft))"></i> 1 day
        <i style="background:color-mix(in srgb,var(--forest) 66%,var(--surface-soft))"></i> 4 days
        <i style="background:var(--forest)"></i> every day of the week</p>`;
  }

  // ── views ─────────────────────────────────────────────────────
  const number = n => new Intl.NumberFormat('en-GB').format(n || 0);
  const color = slug => `hsl(${[...slug].reduce((v, c) => (v * 31 + c.charCodeAt(0)) % 360, 0)} 65% 65%)`;
  const latestDay = DATA.days[0];
  const dayByDate = new Map(DATA.days.map(day => [day.day, day]));
  const countOn = (bird, day) => bird.history.find(row => row[0] === day)?.[1] || 0;
  const photo = (b, eager = false) => b.photo
    ? `<img class="bird-photo" src="${esc(b.photo.url)}" width="640" height="480" alt="Reference photograph of ${esc(b.name)}" ${eager ? 'fetchpriority="high"' : 'loading="lazy"'} decoding="async">`
    : `<span class="photo-placeholder" aria-hidden="true">${clock(b, 100)}</span>`;
  const photoCredit = b => b.photo ? `<figcaption class="photo-credit">Reference photograph · ${esc(b.photo.author)} · <a href="${esc(b.photo.licenseUrl || b.photo.source)}" target="_blank" rel="noopener">${esc(b.photo.license)}</a> · <a href="${esc(b.photo.source)}" target="_blank" rel="noopener">Wikimedia Commons ↗</a><span>${esc(b.photo.alterations)}</span></figcaption>` : '';
  const badge = b => `<span class="tier ${b.tier}">${esc(b.tier)}</span>`;
  let chartRange = 30, chartMetric = 'count', birdOrder = 'often', birdQuery = '';
  const comparison = new Set([...species].sort((a, b) => b.count - a.count).slice(0, 3).map(b => b.slug));
  let replayTimer = null, activeReplay = null, replaySlot = 0;
  const dayCache = new Map();
  const stat = (value, label, note = '') => `<div class="stat"><strong data-count="${value}">${number(value)}</strong><span>${label}</span>${note ? `<small>${note}</small>` : ''}</div>`;
  const empty = text => `<p class="empty">${text}</p>`;

  function hourBars(values, label = 'Detections by hour') {
    const max = Math.max(...values, 1);
    return `<div class="hour-chart" role="img" aria-label="${esc(label)}">
      <div class="hour-bars">${values.map((n, h) => `<div class="hour-bar" style="--height:${n / max * 100}%;--delay:${h * 18}ms;--hour-color:hsl(${175 + Math.abs(12 - h) * 12} 64% 60%)" tabindex="0" data-tip="${hourLabel(h)} · ${number(n)} detections" title="${hourLabel(h)} · ${number(n)} detections"><i></i></div>`).join('')}</div>
      <div class="axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div></div>`;
  }

  function orbit(day) {
    const values = day?.hours || Array(24).fill(0), max = Math.max(...values, 1);
    const arcs = values.map((n, h) => {
      if (!n) return '';
      const a = (h / 24 * Math.PI * 2) - Math.PI / 2;
      const x1 = 160 + 98 * Math.cos(a), y1 = 160 + 98 * Math.sin(a);
      const r = 104 + Math.sqrt(n / max) * 43;
      return `<line x1="${x1}" y1="${y1}" x2="${160 + r * Math.cos(a)}" y2="${160 + r * Math.sin(a)}" stroke="hsl(${160 + h * 7} 70% 65%)" stroke-width="10" stroke-linecap="round"><title>${hourLabel(h)} · ${number(n)} detections</title></line>`;
    }).join('');
    return `<div class="orbit"><svg viewBox="0 0 320 320" role="img" aria-label="${esc(day ? `Bird activity on ${fmt(day.day, 'medium')}` : 'Awaiting birdsong')}"><circle class="orbit-guide" cx="160" cy="160" r="92"/><circle class="orbit-guide" cx="160" cy="160" r="150"/>${arcs}<circle class="orbit-center" cx="160" cy="160" r="85"/></svg>
      <div class="orbit-number"><span class="label">${day?.day === DATA.today ? 'Heard today' : day ? esc(fmt(day.day, 'short')) : 'Waiting to hear'}</span><strong data-count="${day?.species || 0}">${day?.species || 0}</strong><span>species in the soundscape</span></div><span class="orbit-caption">24-hour activity · midnight at the top</span>${[...species].filter(b => b.photo && (!day || countOn(b, day.day) > 0)).sort((a, b) => countOn(b, day?.day) - countOn(a, day?.day)).slice(0, 3).map((b, i) => `<a class="orbit-portrait portrait-${i}" href="#b-${b.slug}" title="Meet ${esc(b.name)}">${photo(b, i === 0)}</a>`).join('')}</div>`;
  }

  const recording = (clip, name) => `<div class="recording"><div><b>${esc(name)}</b><span>${fmt(clip.day, 'short')} · ${clip.duration}s · ${Math.round(clip.confidence * 100)}% BirdNET match</span></div><audio controls preload="none" src="${esc(clip.url)}" aria-label="Listen to ${esc(name)}, recorded ${fmt(clip.day, 'medium')}">Your browser cannot play this recording. <a href="${esc(clip.url)}">Open audio</a></audio></div>`;
  function listeningRoom() {
    const birds = [...species].filter(b => b.clip).sort((a, b) => b.clip.day.localeCompare(a.clip.day) || b.clip.confidence - a.clip.confidence);
    return `<div class="page"><header class="view-header"><p class="eyebrow">The sound behind the record</p><h1>Bird recordings</h1><p>${number(DATA.recordingCount)} saved bird recordings. Start with a clear clip from each species, then open its profile or a day’s record to travel through the archive.</p></header><div class="listening-grid">${birds.map(b => `<article class="panel sound-card"><a href="#b-${b.slug}">${photo(b)}<span>${esc(b.scientific)} ↗</span></a>${recording(b.clip, b.name)}<a class="text-link" href="#b-${b.slug}">${b.clipCount} saved recordings · full bird profile →</a></article>`).join('') || empty('The first saved bird recording will appear here.')}</div></div>`;
  }
  async function showRecordingArchive(slug, button) {
    const b = bySlug.get(slug), host = document.getElementById('recording-archive');
    button.disabled = true; button.textContent = 'Opening the recording archive…';
    try {
      const response = await fetch(b.recordings); if (!response.ok) throw Error('Unavailable');
      const clips = await response.json();
      if (location.hash !== `#b-${slug}`) return;
      host.innerHTML = `<label class="clip-picker">Choose a recorded day<select id="clip-day">${clips.map((clip, i) => `<option value="${i}">${fmt(clip.day, 'medium')} · ${Math.round(clip.confidence * 100)}% match</option>`).join('')}</select></label><div id="archive-player">${recording(clips[0], b.name)}</div>`;
      document.getElementById('clip-day').addEventListener('change', event => {document.getElementById('archive-player').innerHTML = recording(clips[Number(event.target.value)], b.name);});
    } catch (_) {button.disabled = false; button.textContent = 'Could not open recordings — try again';}
  }

  function trend(bird) {
    if (!bird.previous) return bird.recent ? 'Active in recent records' : 'Quiet in recent records';
    const percent = Math.round((bird.recent / bird.previous - 1) * 100);
    return `${percent >= 0 ? '+' : '−'}${Math.abs(percent)}% detections`;
  }

  function historyChart(birds, range = 30, metric = 'count') {
    const days = [...DATA.days].reverse().slice(-range), max = Math.max(1, ...days.map(d => metric === 'species' ? d.species : birds ? birds.reduce((n, b) => n + countOn(b, d.day), 0) : d.count));
    if (!days.length) return empty('The first day of listening will appear here.');
    const w = 1000, h = 170, dx = w / days.length;
    const bars = days.map((day, i) => {
      const value = metric === 'species' ? day.species : birds ? birds.reduce((n, b) => n + countOn(b, day.day), 0) : day.count;
      return `<a href="#day-${day.day}" aria-label="${esc(fmt(day.day, 'medium'))}: ${number(value)} ${metric === 'species' ? 'species' : 'detections'}"><rect class="history-bar" x="${i * dx + 1}" y="${h - value / max * (h - 10)}" width="${Math.max(1, dx - 3)}" height="${Math.max(value ? 2 : 0, value / max * (h - 10))}" rx="2" style="--delay:${i * 8}ms;fill:hsl(${155 + i / days.length * 80} 62% 61%)"><title>${fmt(day.day, 'short')} · ${number(value)} ${metric === 'species' ? 'species' : 'detections'}</title></rect></a>`;
    }).join('');
    return `<div class="history-chart"><span class="chart-ceiling">${number(max)}</span><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${metric === 'species' ? 'Species' : 'Detection'} history. Select a day to explore."><path class="grid-line" d="M0 42H1000 M0 85H1000 M0 127H1000"/>${bars}</svg><div class="axis"><span>${fmt(days[0].day, 'short')}</span><span>Select any day to explore</span><span>${fmt(days.at(-1).day, 'short')}</span></div></div>`;
  }

  function heatmap(limit = 14) {
    const days = DATA.days.slice(0, limit), max = Math.max(1, ...days.flatMap(d => d.hours));
    return `<div class="heat-scroll"><div class="heatmap"><div class="heat-label"></div>${Array.from({length: 24}, (_, h) => `<span class="heat-hour">${h % 3 === 0 ? String(h).padStart(2, '0') : ''}</span>`).join('')}
      ${days.map(day => `<a class="heat-label" href="#day-${day.day}">${fmt(day.day, 'short')}</a>${day.hours.map((n, h) => `<a href="#day-${day.day}" class="heat-cell" style="--heat:${n ? 18 + Math.sqrt(n / max) * 82 : 0}%" title="${fmt(day.day, 'short')}, ${hourLabel(h)} · ${number(n)} detections" aria-label="${fmt(day.day, 'short')}, ${hourLabel(h)}: ${number(n)} detections"></a>`).join('')}`).join('')}</div></div><p class="chart-note">Each square is one hour. Brighter means more detections. Select a day to open its full record.</p>`;
  }

  function leader(bird, count, max) {
    return `<a class="leader" href="#b-${bird.slug}" style="--bird-color:${color(bird.slug)}"><span class="bird-avatar">${photo(bird)}</span><span class="leader-body"><b>${esc(bird.name)}</b><i style="--width:${count / Math.max(max, 1) * 100}%"></i></span><strong>${number(count)}</strong></a>`;
  }

  function fieldNotes() {
    const notes = DATA.fieldNotes;
    if (!notes?.notes.length) return '';
    return `<section class="section field-notes"><div class="section-head"><div><p class="eyebrow">From the recorded data</p><h2>Field notes</h2></div><a href="#explore">Ask the data ↗</a></div><div class="insight-grid">${notes.notes.map((note, i) => `<article class="insight-card"><span class="insight-index">0${i + 1}</span><h3>${esc(note.title)}</h3><p>${esc(note.body)}</p><a href="${esc(note.href)}" class="insight-evidence"><span>The evidence</span>${esc(note.evidence)} <b>↗</b></a></article>`).join('')}</div><p class="chart-note">${['generated', 'mixed'].includes(notes.mode) ? `AI-assisted field notes · written ${time(notes.written)} on ${fmt(notes.written.slice(0, 10), 'short')} · ` : ''}Every note links to its evidence. Counts describe acoustic detections, not individual birds.</p></section>`;
  }

  const metricValue = value => value === null || value === undefined ? '—' : Number(value).toFixed(1);
  function confidenceChart(b) {
    const bins = b.confidenceDistribution || [], max = Math.max(...bins, 1);
    return `<div class="confidence-chart" role="img" aria-label="Distribution of BirdNET model confidence for ${esc(b.name)}"><div>${bins.map((n, i) => `<span style="--height:${n / max * 100}%" tabindex="0" title="${i * 10}–${(i + 1) * 10}%: ${number(n)} detections"><i></i><small>${i * 10}</small></span>`).join('')}</div><p class="axis"><span>Model confidence %</span><span>Mean ${Math.round((b.meanConfidence || 0) * 100)}%</span></p></div>`;
  }

  function acousticPanel(b) {
    const a = b.acoustics;
    if (!a?.measurements) return `<div class="panel"><h3>Confidence scores</h3>${confidenceChart(b)}<p class="chart-note">Confidence is a model score, not a probability that this species was present. Acoustic level measurements are available only for newer recordings.</p></div>`;
    return `<section class="section"><div class="section-head"><div><p class="eyebrow">Inside the signal</p><h2>Confidence and acoustic measurements</h2></div><span class="chart-note">${number(a.measurements)} measured detection segments</span></div><div class="two-columns"><div class="panel"><h3>The confidence distribution</h3>${confidenceChart(b)}<p class="chart-note">All model matches, from tentative scores to the clearest ones. This is a model score, not a probability of presence.</p></div><div class="panel"><h3>The acoustic measurements</h3><dl class="comparison-facts"><div><dt>Mean signal-to-noise</dt><dd>${metricValue(a.meanSNR)} dB</dd></div><div><dt>Best signal-to-noise</dt><dd>${metricValue(a.bestSNR)} dB</dd></div><div><dt>Mean detected-segment level</dt><dd>${metricValue(a.meanLevel)} dBFS</dd></div><div><dt>Highest digital peak</dt><dd>${metricValue(a.peakLevel)} dBFS</dd></div><div><dt>Mean estimated noise floor</dt><dd>${metricValue(a.meanNoise)} dBFS</dd></div></dl><p class="chart-note">Levels refer to the recorder’s digital signal, not physical loudness. Distance, microphone gain, other sounds and recording coverage affect them. Older records may lack these measurements.</p></div></div></section>`;
  }

  let exploreQuery = '', exploreSort = 'count';
  function exploreView() {
    const questions = DATA.fieldNotes?.questions || [];
    return `<div class="page explore-page"><header class="view-header"><p class="eyebrow">Data explorer</p><h1>Explore the records</h1><p>Start with a question, then follow the evidence into birds, dates and recordings. Explore the complete species dataset below.</p></header><section class="question-workbench"><div class="question-list" role="group" aria-label="Questions about the record">${questions.map((q, i) => `<button data-question="${q.id}" aria-pressed="${i === 0}">${esc(q.question)}</button>`).join('')}</div><div id="question-answer" class="question-answer" aria-live="polite">${questions[0] ? questionAnswer(questions[0]) : empty('The first records will open this explorer.')}</div></section><section class="section"><div class="section-head"><div><p class="eyebrow">All the evidence, in one place</p><h2>Species dataset</h2></div><a href="species.csv" download>Download species CSV ↓</a></div><div class="bird-toolbar"><label class="search"><span>Search the dataset</span><input id="explore-search" type="search" placeholder="Common or scientific name…" value="${esc(exploreQuery)}"></label><label class="sort-label">Rank species by<select id="explore-sort"><option value="count" ${exploreSort === 'count' ? 'selected' : ''}>Total detections</option><option value="days" ${exploreSort === 'days' ? 'selected' : ''}>Recorded days</option><option value="snr" ${exploreSort === 'snr' ? 'selected' : ''}>Mean signal-to-noise</option><option value="confidence" ${exploreSort === 'confidence' ? 'selected' : ''}>Mean model confidence</option></select></label></div><p class="chart-note">Detection counts cover the archive. Confidence and acoustic summaries use up to the latest 366 recorded days; missing measurements are shown as a dash.</p><div class="table-scroll panel data-table"><table class="roll-call"><thead><tr><th>Species</th><th>Detections</th><th>Days</th><th>Mean match</th><th>Best match</th><th>Mean SNR</th><th>Peak dBFS</th><th>Measured</th></tr></thead><tbody id="explore-rows"></tbody></table></div></section><section class="panel methodology"><h3>How to read these data</h3><p>A microphone samples a place; it does not census individual birds. These are acoustic detections and model scores. Digital sound levels are affected by distance and microphone gain. Silence can mean a quiet bird, masking noise or a gap in recording. Photographs illustrate species and are not sighting photographs.</p></section></div>`;
  }
  function questionAnswer(q) {return `<p class="eyebrow">From the measured record</p><h2>${esc(q.evidence)}</h2><p>${esc(q.hint)}</p><a class="button primary" href="${esc(q.href)}">Explore the evidence ↗</a>`;}
  function drawExplorer() {
    const list = species.filter(b => `${b.name} ${b.scientific}`.toLowerCase().includes(exploreQuery.toLowerCase()));
    const score = b => exploreSort === 'snr' ? b.acoustics?.meanSNR ?? -Infinity : exploreSort === 'confidence' ? b.meanConfidence ?? -Infinity : b[exploreSort];
    list.sort((a, b) => score(b) - score(a));
    document.getElementById('explore-rows').innerHTML = list.map(b => `<tr><th><a href="#b-${b.slug}"><span class="dataset-avatar">${photo(b)}</span><span>${esc(b.name)}<small>${esc(b.scientific)}</small></span></a></th><td>${number(b.count)}</td><td>${b.days}</td><td>${b.meanConfidence === null ? '—' : `${Math.round(b.meanConfidence * 100)}%`}</td><td>${Math.round(b.confidence * 100)}%</td><td>${metricValue(b.acoustics?.meanSNR)}</td><td>${metricValue(b.acoustics?.peakLevel)}</td><td>${number(b.acoustics?.measurements)}</td></tr>`).join('') || '<tr><td colspan="8">No matching species.</td></tr>';
  }

  function home() {
    const day = latestDay;
    const ranked = [...species].map(b => [b, countOn(b, day?.day)]).filter(([, n]) => n).sort((a, b) => b[1] - a[1]);
    const movers = [...species].filter(b => b.recent).sort((a, b) => (b.recent - b.previous) - (a.recent - a.previous)).slice(0, 4);
    const latest = paintings[0];
    const faces = [...ranked.map(([b]) => b), ...species].filter((b, i, all) => b.photo && all.findIndex(x => x.slug === b.slug) === i).slice(0, 6);
    return `<div class="page observatory">
      <section class="observatory-hero"><div class="hero-copy"><p class="eyebrow"><span class="status-dot"></span>${esc(DATA.place)} · a birdsong observatory</p><h1>Birds heard<br><em>in ${esc(DATA.place)}.</em></h1><p class="hero-description">Acoustic detections, short recordings and daily paintings from one window. Explore the species and their recorded activity.</p><div class="hero-actions"><a class="button primary" href="#day-${day?.day || ''}">Explore ${day?.day === DATA.today ? 'today' : 'the latest day'} <span>↗</span></a><a class="text-link" href="#birds">Meet the ${species.length} species →</a></div><p class="snapshot">Refreshed every ${DATA.refreshMinutes} minutes · snapshot ${time(DATA.generated)} on ${fmt(DATA.generated.slice(0, 10), 'short')}</p></div>${orbit(day)}</section>
      <section class="stats-strip" aria-label="The archive in numbers">${stat(DATA.totalDetections, 'bird detections', 'calls recorded, not individual birds')}${stat(species.length, 'species in the record', 'confirmed and probable identifications')}${stat(DATA.listeningDays, 'days of bird records', `since ${DATA.since ? fmt(DATA.since, 'short') : 'the first call'}`)}${stat(paintings.length, 'original paintings', 'each one begins with birdsong')}</section>
      ${fieldNotes()}
      ${faces.length ? `<section class="section field-guide"><div class="section-head"><div><p class="eyebrow">Meet the neighbours</p><h2>Recorded species</h2></div><a href="#birds">The complete field guide ↗</a></div><div class="photo-strip">${faces.map(b => `<a class="photo-card" href="#b-${b.slug}" style="--bird-color:${color(b.slug)}">${photo(b)}<div><span>${esc(b.name)}</span><small>${number(b.count)} detections · ${b.days} days</small></div></a>`).join('')}</div><p class="chart-note">Species reference photographs from Wikimedia Commons. Open a bird for photo credits and its full record.</p></section>` : ''}
      <section class="section"><div class="section-head"><div><p class="eyebrow">The daily pulse</p><h2>${day ? esc(fmt(day.day, 'long')) : 'The first morning'}</h2></div><a href="#day-${day?.day || ''}">Open the daybook ↗</a></div><div class="two-columns"><div class="panel"><div class="panel-heading"><h3>Detections by hour</h3><span>${number(day?.count)} detections</span></div>${hourBars(day?.hours || Array(24).fill(0))}<p class="chart-note">An hour-by-hour picture of the latest recorded day. Explore the daybook for the quarter-hour replay.</p></div><div class="panel"><div class="panel-heading"><h3>Species recorded that day</h3><span>${day?.species || 0} species</span></div><div class="leaders">${ranked.slice(0, 6).map(([b, n]) => leader(b, n, ranked[0]?.[1])).join('') || empty('No trusted identifications yet.')}</div></div></div></section>
      ${DATA.recordingCount ? `<section class="section"><div class="section-head"><div><p class="eyebrow">Recordings</p><h2>Saved bird recordings</h2></div><a href="#listen">${number(DATA.recordingCount)} recordings ↗</a></div><div class="listening-grid">${[...species].filter(b => b.clip).sort((a, b) => countOn(b, latestDay?.day) - countOn(a, latestDay?.day)).slice(0, 3).map(b => `<article class="panel sound-card"><a href="#b-${b.slug}">${photo(b)}</a>${recording(b.clip, b.name)}</article>`).join('')}</div><p class="chart-note">Short recordings from the window. Other birds and background sounds may be audible too. Nothing plays until you choose it.</p></section>` : ''}
      <section class="section"><div class="section-head"><div><p class="eyebrow">Find the pattern</p><h2>Activity over time</h2></div><a href="#seasons">Explore the season ↗</a></div><div class="panel"><div class="chart-toolbar"><div class="segmented" aria-label="History measure"><button data-metric="count" class="${chartMetric === 'count' ? 'active' : ''}">Detections</button><button data-metric="species" class="${chartMetric === 'species' ? 'active' : ''}">Species</button></div><div class="segmented" aria-label="History range">${[7, 30, 90, 366].map(n => `<button data-range="${n}" class="${chartRange === n ? 'active' : ''}">${n === 366 ? 'All' : `${n} days`}</button>`).join('')}</div></div><div id="archive-chart">${historyChart(null, chartRange, chartMetric)}</div></div><div class="panel"><div class="panel-heading"><h3>The last fortnight, hour by hour</h3><span>Detection intensity</span></div>${heatmap()}</div></section>
      <section class="section"><div class="section-head"><div><p class="eyebrow">Recent momentum</p><h2>Changes in recorded activity</h2></div><a href="#compare">Compare species ↗</a></div><div class="momentum-grid">${movers.map(b => `<a class="momentum" href="#b-${b.slug}" style="--bird-color:${color(b.slug)}"><div class="momentum-photo">${photo(b)}${clock(b, 64)}</div><span>${esc(b.name)}</span><strong>${trend(b)}</strong><small>${number(b.recent)} in the latest seven recorded days · ${number(b.previous)} in the previous seven</small></a>`).join('')}</div><p class="chart-note">These are changes in recorded activity. Recording gaps, weather and background noise can change the counts too.</p></section>
      ${latest ? `<section class="section"><div class="section-head"><div><p class="eyebrow">Daily artwork</p><h2>Latest painting</h2></div><a href="#paintings">The painting collection ↗</a></div><div class="art-feature"><a href="#p-${latest.id}">${picture(latest, '(min-width: 900px) 430px, 90vw', altFor(latest))}</a><div><p class="eyebrow">The latest painting · ${fmt(latest.day, 'short')}</p><h3>${esc(latest.style)}</h3><p>${esc(latest.character || latest.reason || 'A day of listening, interpreted in paint.')}</p><p class="art-birds">${latest.birds.slice(0, 7).map(birdLink).join(' · ')}${latest.birds.length > 7 ? ` + ${latest.birds.length - 7} more` : ''}</p><a class="button" href="#p-${latest.id}">Look closer ↗</a><a class="text-link" href="#frame">Turn this screen into a picture frame →</a></div></div></section>` : ''}
    </div>`;
  }

  function birdCards(list) {
    return list.map(b => `<article class="bird-card" style="--bird-color:${color(b.slug)}"><a href="#b-${b.slug}"><div class="bird-card-top">${photo(b)}${badge(b)}<span class="card-clock">${clock(b, 64)}</span></div><h3>${esc(b.name)}</h3><p class="scientific">${esc(b.scientific)}</p><div class="bird-card-stats"><span><b>${number(b.count)}</b> detections</span><span><b>${b.days}</b> recorded days</span></div><div class="mini-rhythm" aria-hidden="true">${b.hours.map(n => `<i style="height:${Math.max(3, n / Math.max(...b.hours, 1) * 100)}%"></i>`).join('')}</div><p class="chart-note">Most active around ${hourLabel(b.peak)}</p></a><button class="compare-choice ${comparison.has(b.slug) ? 'selected' : ''}" data-compare="${b.slug}" aria-pressed="${comparison.has(b.slug)}">${comparison.has(b.slug) ? '✓ Selected for comparison' : '+ Add to comparison'}</button></article>`).join('');
  }

  function birdsView() {
    return `<div class="page"><header class="view-header"><p class="eyebrow">Species directory</p><h1>Bird species</h1><p>Search ${species.length} species. Find out when they call, how often they return, and which other birds share their days.</p></header><div class="bird-toolbar"><label class="search"><span>Find a bird</span><input id="bird-search" type="search" placeholder="Robin, crow, Erithacus…" value="${esc(birdQuery)}"></label><label class="sort-label">Order by<select id="bird-sort"><option value="often" ${birdOrder === 'often' ? 'selected' : ''}>Most detections</option><option value="days" ${birdOrder === 'days' ? 'selected' : ''}>Most recorded days</option><option value="new" ${birdOrder === 'new' ? 'selected' : ''}>Newest first record</option><option value="name" ${birdOrder === 'name' ? 'selected' : ''}>Name A–Z</option></select></label><a class="button" href="#compare">Compare <span id="compare-count">${comparison.size}</span> species ↗</a></div><p id="bird-results" class="chart-note"></p><div class="bird-grid" id="bird-grid"></div></div>`;
  }

  function drawBirds() {
    const list = species.filter(b => `${b.name} ${b.scientific}`.toLowerCase().includes(birdQuery.toLowerCase()));
    list.sort((a, b) => birdOrder === 'name' ? a.name.localeCompare(b.name) : birdOrder === 'new' ? b.first.localeCompare(a.first) : birdOrder === 'days' ? b.days - a.days : b.count - a.count);
    document.getElementById('bird-grid').innerHTML = birdCards(list) || empty('No matching birds. Try a common or scientific name.');
    document.getElementById('bird-results').textContent = `${list.length} species · select up to three for comparison`;
  }

  function birdView(slug) {
    const b = bySlug.get(slug);
    if (!b) return missing('That bird');
    const shown = paintings.filter(p => p.birds.includes(b.name));
    const share = DATA.listeningDays ? Math.round(b.history.length / DATA.listeningDays * 100) : 0;
    return `<article class="page"><header class="bird-head" style="--bird-color:${color(b.slug)}"><figure class="bird-portrait">${photo(b, true)}${photoCredit(b)}</figure><div class="view-header"><p class="eyebrow">${esc(b.rarity)} · ${badge(b)}</p><h1>${esc(b.name)}</h1><p class="scientific">${esc(b.scientific)}</p><p>${DATA.season?.statuses[b.name] ? `${esc(DATA.season.statuses[b.name])}. ` : ''}Heard on ${share}% of displayed recorded days. Its busiest hour is around ${hourLabel(b.peak)}.</p><button class="button compare-choice" data-compare="${b.slug}" aria-pressed="${comparison.has(b.slug)}">${comparison.has(b.slug) ? '✓ Selected for comparison' : '+ Add to comparison'}</button></div></header><div class="stats-strip">${stat(b.count, 'detections in the archive')}${stat(b.days, 'days heard')}${stat(Math.round(b.confidence * 100), 'best BirdNET match %', 'model confidence, not a probability of presence')}${stat(shown.length, 'paintings featuring this bird')}</div>${b.clip ? `<section class="section">${sectionHead(`Hear ${esc(b.name)}`, `<a href="#listen">The listening room ↗</a>`)}<div class="two-columns"><div class="panel"><p class="eyebrow">The clearest saved recording</p>${recording(b.clip, b.name)}<p class="chart-note">A saved clip from the window, labelled by its acoustic match. Background sounds and other species may be audible.</p></div><div class="panel" id="recording-archive"><h3>${b.clipCount} saved recordings</h3><p class="chart-note">Explore the saved best-of-day recording for this species through the archive.</p><button class="button" data-recordings="${b.slug}">Browse all ${b.clipCount} recordings →</button></div></div></section>` : ''}${b.photo?.intro ? `<section class="natural-history panel"><p class="eyebrow">Species background</p><p>${esc(b.photo.intro)}</p><a href="${esc(b.photo.article)}" target="_blank" rel="noopener">Read more on Wikipedia ↗</a><small>Introduction adapted from Wikipedia, available under <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">CC BY-SA 4.0</a>.</small></section>` : ''}<div class="two-columns"><section class="panel"><div class="panel-heading"><h3>A daily rhythm</h3><span>All recorded calls</span></div>${hourBars(b.hours, `${b.name} detections by hour`)}<p class="chart-note">Earliest time of day ${esc(b.earliest)} · latest ${esc(b.latest)}. First recorded ${fmt(b.first, 'medium')}; last ${fmt(b.last, 'medium')}.</p></section><section class="panel"><div class="panel-heading"><h3>Recent activity</h3><span>${trend(b)}</span></div>${historyChart([b], 30)}<p class="chart-note">${number(b.recent)} detections in the latest seven recorded days, compared with ${number(b.previous)} in the previous seven.</p></section></div>${acousticPanel(b)}<section class="section">${sectionHead('The record, day by day')}<div class="panel">${historyChart([b], 366)}${phenology([b])}</div></section><section class="section">${sectionHead('Sharing the same days')}<div class="companions">${b.companions.map(item => {const other = bySlug.get(item.slug); return `<a href="#b-${item.slug}" style="--bird-color:${color(item.slug)}"><span class="color-dot"></span><b>${esc(other.name)}</b><span>${item.days} shared recorded days</span></a>`;}).join('')}</div><p class="chart-note">Both species were recorded on the same day. This does not imply they were together or interacting.</p></section><section class="section">${sectionHead(`In ${shown.length} paintings`)}<div class="gallery">${shown.slice(0, 12).map(tile).join('')}</div>${shown.length > 12 ? '<a href="#paintings">Explore the complete painting collection →</a>' : ''}</section><section class="panel methodology"><h3>How this identification is assessed</h3><p>${esc(b.reasons.join('; '))}. The assessment combines the clearest acoustic match, regional plausibility and repeated records. A high model score alone does not prove a species was present.</p></section></article>`;
  }

  function dayView(day) {
    const summary = dayByDate.get(day);
    if (!summary) return missing('That day');
    return `<div class="page"><header class="view-header"><p class="eyebrow">The daybook · select a day, replay its voices</p><h1>${fmt(day, 'long')}</h1><div class="day-toolbar"><label>Recorded day<select id="day-select">${DATA.days.map(d => `<option value="${d.day}" ${d.day === day ? 'selected' : ''}>${fmt(d.day, 'medium')} · ${d.species} species</option>`).join('')}</select></label><button class="button" data-csv="${day}">Download day data ↓</button></div></header><div class="stats-strip">${stat(summary.count, 'bird detections')}${stat(summary.species, 'species heard')}<div class="stat"><strong>${summary.first || '—'}</strong><span>first recorded call</span></div><div class="stat"><strong>${summary.last || '—'}</strong><span>last recorded call</span></div></div><div id="day-detail" aria-live="polite" aria-busy="true"><p class="loading">Opening the quarter-hour record…</p></div></div>`;
  }

  async function loadDay(day) {
    if (!dayCache.has(day)) {
      const pending = fetch(`daily/${day}.json?v=${DATA.dayVersions[day]}`, {cache: 'no-cache'}).then(r => {if (!r.ok) throw Error('Day unavailable'); return r.json();});
      dayCache.set(day, pending);
      pending.catch(() => dayCache.delete(day));
    }
    return dayCache.get(day);
  }

  async function showDay(day) {
    try {
      const data = await loadDay(day);
      if (location.hash !== `#day-${day}` || !document.getElementById('day-detail')) return;
      activeReplay = data;
      replaySlot = data.quarters.indexOf(Math.max(...data.quarters));
      document.getElementById('day-detail').outerHTML = `<div id="day-detail" class="section"><section class="panel replay-panel"><div class="panel-heading"><div><p class="eyebrow">A day in 96 moments</p><h3>Replay the soundscape</h3></div><button id="replay-toggle" class="button primary" aria-pressed="false">▶ Play the day</button></div><p class="chart-note">A replay of the recorded quarter-hour totals. Select any bar or scrub through the day.</p><div class="quarter-chart">${data.quarters.map((n, i) => `<button data-quarter="${i}" style="--height:${n / Math.max(...data.quarters, 1) * 100}%" aria-label="${slotLabel(i)}: ${n} detections"><i></i></button>`).join('')}</div><div class="axis"><span>Midnight</span><span>06:00</span><span>Noon</span><span>18:00</span><span>Midnight</span></div><label class="scrubber">Explore the day<input id="replay-scrub" type="range" min="0" max="95" value="${replaySlot}"></label><div id="replay-readout"></div></section><section class="panel"><div class="panel-heading"><h3>The complete roll call</h3><span>${data.birds.length} species</span></div><div class="table-scroll"><table class="roll-call"><thead><tr><th>Species</th><th>Detections</th><th>First</th><th>Last</th><th>Best match</th><th>Daily rhythm</th>${DATA.recordingCount ? '<th>Recording</th>' : ''}</tr></thead><tbody>${data.birds.map(row => {const b = bySlug.get(row.slug); return `<tr><th><a href="#b-${row.slug}"><span class="color-dot" style="--bird-color:${color(row.slug)}"></span>${esc(b.name)}</a></th><td>${number(row.count)}</td><td>${row.first}</td><td>${row.last}</td><td>${Math.round(row.best * 100)}%</td><td><span class="table-rhythm" aria-label="Peak around ${hourLabel(row.hours.indexOf(Math.max(...row.hours)))}">${row.hours.map(n => `<i style="height:${Math.max(3, n / Math.max(...row.hours, 1) * 100)}%"></i>`).join('')}</span></td>${DATA.recordingCount ? `<td class="clip-cell">${row.clip ? recording(row.clip, b.name) : '—'}</td>` : ''}</tr>`;}).join('')}</tbody></table></div></section>${(dayByDate.get(day).paintings || []).length ? `<section class="section">${sectionHead('Painted from this day')}<div class="gallery">${dayByDate.get(day).paintings.map(id => byId.get(id)).filter(Boolean).map(tile).join('')}</div></section>` : ''}<p class="chart-note">Times use the recorder’s local clock. Detections are acoustic matches, not a count of individual birds. An empty interval may be quiet, masked by noise, or a recording gap.</p></div>`;
      updateReplay();
    } catch (_) {
      const host = document.getElementById('day-detail');
      if (host && location.hash === `#day-${day}`) host.innerHTML = '<p class="empty">This day could not be loaded. Please try again.</p><button class="button" id="retry-day">Try again</button>';
    }
  }

  const slotLabel = slot => `${String(Math.floor(slot / 4)).padStart(2, '0')}:${String(slot % 4 * 15).padStart(2, '0')}`;
  function updateReplay() {
    if (!activeReplay || !document.getElementById('replay-readout')) return;
    const entries = activeReplay.voices.filter(row => row[0] === replaySlot).sort((a, b) => b[2] - a[2]);
    document.getElementById('replay-readout').innerHTML = `<div class="replay-time"><strong>${slotLabel(replaySlot)}</strong><span>${number(activeReplay.quarters[replaySlot])} detections · ${entries.length} species in this quarter-hour</span></div><div class="replay-voices">${entries.map(([, slug, count]) => `<a href="#b-${slug}" style="--bird-color:${color(slug)}"><span class="color-dot"></span>${esc(bySlug.get(slug).name)}<b>${count}</b></a>`).join('') || '<p class="chart-note">No trusted bird detections in this interval.</p>'}</div>`;
    document.querySelectorAll('[data-quarter]').forEach(el => el.classList.toggle('active', Number(el.dataset.quarter) === replaySlot));
    document.getElementById('replay-scrub').value = replaySlot;
  }

  function compareView() {
    const chosen = [...comparison].map(slug => bySlug.get(slug)).filter(Boolean);
    return `<div class="page"><header class="view-header"><p class="eyebrow">Species comparison</p><h1>Compare bird activity</h1><p>Compare up to three birds. Each hourly line shows its share of that bird’s busiest hour, so a quiet species can still reveal its own daily rhythm.</p><a href="#birds" class="button">Choose birds (${chosen.length}/3) →</a></header>${chosen.length ? `<div class="compare-legend">${chosen.map(b => `<span style="--bird-color:${color(b.slug)}"><i></i>${esc(b.name)}</span>`).join('')}</div><section class="panel"><h3>The daily rhythms</h3><svg class="comparison-chart" viewBox="0 0 1000 250" role="img" aria-label="Normalized hourly rhythms of the selected birds"><path class="grid-line" d="M0 60H1000 M0 125H1000 M0 190H1000"/>${chosen.map(b => `<polyline class="rhythm-line" fill="none" stroke="${color(b.slug)}" stroke-width="4" stroke-linejoin="round" points="${b.hours.map((n, h) => `${h / 23 * 1000},${230 - n / Math.max(...b.hours, 1) * 210}`).join(' ')}"><title>${esc(b.name)} · busiest around ${hourLabel(b.peak)}</title></polyline>`).join('')}</svg><div class="axis"><span>Midnight</span><span>06:00</span><span>Noon</span><span>18:00</span><span>23:00</span></div></section><div class="comparison-cards">${chosen.map(b => `<div class="panel comparison-card" style="--bird-color:${color(b.slug)}"><a class="comparison-photo" href="#b-${b.slug}">${photo(b)}</a><span class="color-dot"></span><h3><a href="#b-${b.slug}">${esc(b.name)}</a></h3><dl class="comparison-facts"><div><dt>Detections</dt><dd>${number(b.count)}</dd></div><div><dt>Recorded days</dt><dd>${b.days}</dd></div><div><dt>Best acoustic match</dt><dd>${Math.round(b.confidence * 100)}%</dd></div><div><dt>First recorded</dt><dd>${fmt(b.first, 'short')}</dd></div><div><dt>Busiest hour</dt><dd>${hourLabel(b.peak)}</dd></div></dl>${historyChart([b], 30)}</div>`).join('')}</div>` : empty('Select birds from the species directory to start a comparison.')}</div>`;
  }

  function lightChart(light) {
    const rows = light.days.filter(d => d.sunrise !== null), min = Math.min(...rows.flatMap(d => [d.sunrise, d.first].filter(n => n !== null))) - 15;
    const max = Math.max(...rows.flatMap(d => [d.sunrise, d.first].filter(n => n !== null))) + 15;
    const x = i => i / Math.max(rows.length - 1, 1) * 1000, y = n => 205 - (n - min) / Math.max(max - min, 1) * 180;
    const marks = key => rows.map((d, i) => d[key] === null ? '' : `<circle cx="${x(i)}" cy="${y(d[key])}" r="${key === 'first' ? 4 : 2}" fill="${key === 'first' ? 'var(--forest)' : 'var(--gold)'}"><title>${fmt(d.day, 'short')} · ${key === 'first' ? esc(d.first_species) : 'Sunrise'} · ${minuteLabel(d[key])}</title></circle>`).join('');
    return `<div class="light-legend"><span><i style="background:var(--forest)"></i>First sustained chorus</span><span><i style="background:var(--gold)"></i>Sunrise</span></div><svg class="light-chart" viewBox="0 0 1000 230" role="img" aria-label="The first sustained chorus and sunrise through the season"><path class="grid-line" d="M0 50H1000 M0 120H1000 M0 190H1000"/>${marks('sunrise')}${marks('first')}</svg><div class="axis"><span>${rows.length ? fmt(rows[0].day, 'short') : ''}</span><span>Earlier calls sit lower on the chart</span><span>${rows.length ? fmt(rows.at(-1).day, 'short') : ''}</span></div>`;
  }

  const minuteLabel = n => n === null || n === undefined ? '—' : `${String(Math.floor(Math.round(n) / 60)).padStart(2, '0')}:${String(Math.round(n) % 60).padStart(2, '0')}`;
  function seasonSections() {
    const season = DATA.season;
    if (!season) return '';
    const {light, night, growth, records, trends, chronicle} = season;
    const dawn = light?.roster || [], nightBirds = night.species.slice(0, 6);
    const stones = growth.milestones;
    return `${light ? `<section class="section"><div class="section-head"><div><p class="eyebrow">Following the light</p><h2>Dawn chorus and sunrise</h2></div><span class="chart-note">${light.mornings} recorded mornings</span></div><div class="stats-strip"><div class="stat"><strong>${Math.abs(light.offset)} min</strong><span>median chorus onset ${light.offset <= 0 ? 'before' : 'after'} sunrise</span></div><div class="stat"><strong>${minuteLabel(light.start.first)}</strong><span>first chorus · opening seven mornings</span></div><div class="stat"><strong>${minuteLabel(light.now.first)}</strong><span>first chorus · latest seven mornings</span></div><div class="stat"><strong>${minuteLabel(light.now.sunrise)}</strong><span>sunrise · latest seven mornings</span></div></div><div class="panel">${lightChart(light)}<p class="chart-note">The chorus begins with two busy quarter-hours in a row. Birds that regularly call at night are left out of these timings. The current day is excluded.</p></div>${dawn.length ? `<div class="panel"><div class="panel-heading"><h3>The dawn roster</h3><span>Median minutes relative to sunrise</span></div><div class="dawn-roster">${dawn.map(row => `<a href="#b-${byName.get(row.common_name)?.slug}" class="dawn-row"><span>${esc(row.common_name)}</span><div><i style="left:${Math.max(0, 50 + Math.min(row.median, 0) / 6)}%;width:${Math.max(1, Math.min(Math.abs(row.median) / 6, 50))}%"></i></div><b>${row.median > 0 ? '+' : ''}${row.median} min</b><small>${row.mornings} mornings</small></a>`).join('')}</div></div>` : ''}</section>` : ''}
      ${nightBirds.length ? `<section class="section"><div class="section-head"><div><p class="eyebrow">After the light fades</p><h2>Night detections</h2></div></div><div class="photo-strip">${nightBirds.map(row => {const b = byName.get(row.common_name); return `<a href="#b-${b.slug}" class="photo-card">${photo(b)}<div><span>${esc(b.name)}</span><small>${row.nights} nights · ${number(row.detections)} night detections</small></div></a>`;}).join('')}</div><p class="chart-note">Night records fall after civil dusk or before the dawn window, which opens two hours before sunrise. These are recorded calls, not sightings.</p></section>` : ''}
      ${trends ? `<section class="section">${sectionHead('The voices changing through the season')}<div class="two-columns">${[['rising', 'More vocal lately'], ['falling', 'Quieter lately']].map(([key, title]) => `<div class="panel"><h3>${title}</h3><div class="season-trends">${trends[key].map(row => `<a href="#b-${byName.get(row.common_name)?.slug}"><span>${esc(row.common_name)}</span><b>${row.recent_rate} / day</b><small>previously ${row.earlier_rate} / day · ${row.ratio}×</small></a>`).join('') || empty('No substantial change in this part of the record.')}</div></div>`).join('')}</div><p class="chart-note">The latest ${trends.recent_days} finished recorded days versus the earlier record. Changes in recording coverage can affect these rates.</p></section>` : ''}
      <section class="section"><div class="section-head"><div><p class="eyebrow">A growing field guide</p><h2>Life-list milestones</h2></div></div><div class="milestones">${stones.map(stone => `<a href="#day-${stone.day}"><strong>${stone.count}</strong><span>species recorded</span><small>${fmt(stone.day, 'short')} · ${esc(stone.common_name)}</small></a>`).join('')}</div><div class="two-columns">${records.richest_day ? `<a class="record-card" href="#day-${records.richest_day.day}"><p class="eyebrow">The richest day</p><strong>${records.richest_day.species}<small> species</small></strong><span>${fmt(records.richest_day.day, 'medium')} ↗</span></a>` : ''}${records.busiest_day ? `<a class="record-card" href="#day-${records.busiest_day.day}"><p class="eyebrow">The busiest day</p><strong>${number(records.busiest_day.detections)}<small> detections</small></strong><span>${fmt(records.busiest_day.day, 'medium')} ↗</span></a>` : ''}</div></section>
      <section class="section">${sectionHead('The chronicle')}<div class="chronicle">${chronicle.slice(0, 16).map(event => `<a href="#day-${event.day}"><time>${fmt(event.day, 'short')}</time><div><b>${esc(event.title)}</b><p>${esc(event.detail)}</p></div><span>↗</span></a>`).join('')}</div></section>`;
  }

  function seasonsView() {
    const list = [...species].sort((a, b) => a.first.localeCompare(b.first) || b.days - a.days);
    const recent = [...species].sort((a, b) => b.first.localeCompare(a.first)).slice(0, 5);
    return `<div class="page"><header class="view-header"><p class="eyebrow">${DATA.since ? `The story since ${fmt(DATA.since, 'medium')}` : 'The long view'}</p><h1>Seasonal records</h1><p>Watch the changing cast of the window, from everyday companions to occasional voices passing through the record.</p></header><div class="panel"><div class="panel-heading"><h3>How many voices each day?</h3><span>Trusted species in the daily record</span></div>${historyChart(null, 366, 'species')}</div>${seasonSections()}<section class="section">${sectionHead('Through the season')}<div class="panel">${phenology(list)}</div><p class="chart-note">Each square is a week. Colour shows the days a bird was recorded; blank squares are not proof that a bird was absent.</p></section><section class="section">${sectionHead('The most recent first records')}<div class="first-records">${recent.map(b => `<a href="#b-${b.slug}" style="--bird-color:${color(b.slug)}"><span class="color-dot"></span><b>${esc(b.name)}</b><span>${fmt(b.first, 'medium')}</span>${badge(b)}</a>`).join('')}</div></section><div class="panel methodology"><h3>What the record can tell us</h3><p>A microphone hears only part of a place. More calls can mean more vocal activity, a change in conditions, or a change in recording coverage. First and last records mark when a species was heard here, rather than when it arrived or left.</p></div></div>`;
  }

  function hero(p) {
    return `<section class="hero" aria-label="The latest painting">
      <a href="#p-${p.id}"><figure class="print">${picture(p, '(min-width: 900px) 560px, 100vw', altFor(p), true)}</figure></a>
      <div class="museum-label">
        <p class="label">The latest painting</p>
        <h2 class="when">${esc(fmt(p.day, 'long'))}</h2>
        <p class="style">${esc(p.style)}</p>
        <p class="meta">${esc([p.collection, p.medium].filter(Boolean).join(' · '))}</p>
        ${p.reason ? `<p class="note">${esc(p.reason)}</p>` : ''}
        ${birdLine(p.birds)}
        <p class="actions"><a href="#p-${p.id}">About this painting →</a><a href="#frame">Show it full screen →</a></p>
      </div></section>`;
  }

  let collection = '';
  function paintingsView() {
    const collections = [...new Set(paintings.map(p => p.collection).filter(Boolean))].sort();
    const shown = paintings.filter(p => !collection || p.collection === collection);
    const months = new Map();
    shown.forEach(p => {
      const key = p.day.slice(0, 7);
      if (!months.has(key)) months.set(key, []);
      months.get(key).push(p);
    });
    const hung = paintings.some(p => p.frame);
    return `<div class="page">
      <section class="intro"><p class="label">The collection</p><h1>Paintings</h1>
        <p>Every painting here began as a day of listening at the window.${hung ? ' A gold dot marks those that hung on the frame.' : ''}</p></section>
      <section class="section">
        ${collections.length > 1 ? `<div class="chips" role="group" aria-label="Filter by collection">
          <button class="chip" type="button" data-collection="" aria-pressed="${!collection}">All</button>
          ${collections.map(c => `<button class="chip" type="button" data-collection="${esc(c)}" aria-pressed="${collection === c}">${esc(c)}</button>`).join('')}</div>` : ''}
        ${shown.length ? [...months].map(([key, list]) => `<div class="month"><h3>${esc(fmt(`${key}-01`, 'month'))}</h3>
          <div class="gallery">${list.map(tile).join('')}</div></div>`).join('') : '<p class="empty">No paintings yet.</p>'}
      </section></div>`;
  }

  function paintingView(id) {
    const p = byId.get(id);
    if (!p) return missing('That painting');
    const index = paintings.indexOf(p);
    const newer = paintings[index - 1], older = paintings[index + 1];
    return `<article class="page painting">
      <figure class="print">${picture(p, '(min-width: 900px) 600px, 100vw', altFor(p), true)}</figure>
      <div class="museum-label">
        <p class="label">Painted ${esc(fmt(p.made.slice(0, 10), 'short'))} at ${time(p.made)}</p>
        <h1 class="when">${esc(fmt(p.day, 'long'))}</h1>
        <p class="style">${esc(p.style)}</p>
        <p class="meta">${esc([p.collection, p.medium].filter(Boolean).join(' · '))}</p>
        ${p.lineage ? `<p class="meta">After ${esc(p.lineage)}</p>` : ''}
        ${p.reason ? `<p class="note">${esc(p.reason)}</p>` : ''}
        ${p.character ? `<p class="character">${esc(p.character)}</p>` : ''}
        ${p.birds.length ? `<p class="label">The birds in this painting</p>${birdLine(p.birds)}` : ''}
        ${p.frame ? '<p class="meta"><span class="hung">●</span> This one hung on the frame.</p>' : ''}
      </div>
      <details class="direction" data-art="${esc(p.id)}"><summary>Read the art direction given to the painter</summary><pre></pre></details>
      <nav class="pager" aria-label="More paintings">
        ${older ? `<a href="#p-${older.id}">← ${esc(fmt(older.day, 'short'))}</a>` : '<span></span>'}
        ${newer ? `<a href="#p-${newer.id}">${esc(fmt(newer.day, 'short'))} →</a>` : ''}
      </nav></article>`;
  }

  const missing = what => `<div class="page"><section class="intro"><h1>Not here</h1>
    <p>${what} isn't in this journal. <a href="#home">Back to the latest painting</a></p></section></div>`;

  // ── frame mode: any tablet becomes a picture frame ─────────────
  let wakeLock = null;
  function enterFrame() {
    const p = paintings[0];
    document.documentElement.style.overflow = 'hidden';
    const frame = document.createElement('div');
    frame.className = 'frame-mode';
    frame.innerHTML = `${p ? picture(p, '100vw', altFor(p), true) : '<p class="empty">No painting yet.</p>'}
      <a class="exit" href="#home">Leave frame mode</a>`;
    document.body.append(frame);
    const quiet = () => frame.classList.add('quiet');
    let hide = setTimeout(quiet, 4000);
    frame.addEventListener('pointerdown', () => {
      frame.classList.remove('quiet'); clearTimeout(hide); hide = setTimeout(quiet, 4000);
    });
    navigator.wakeLock?.request('screen').then(lock => { wakeLock = lock; }).catch(() => {});
  }
  function leaveFrame() {
    document.querySelector('.frame-mode')?.remove();
    document.documentElement.style.overflow = '';
    wakeLock?.release?.().catch?.(() => {});
    wakeLock = null;
  }


  let currentHash = null;
  function animateCounters() {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.querySelectorAll('[data-count]').forEach(el => {
      const total = Number(el.dataset.count);
      if (reduce || total < 20) return;
      const start = performance.now();
      const tick = now => {const p = Math.min(1, (now - start) / 850); el.textContent = number(Math.round(total * (1 - (1 - p) ** 3))); if (p < 1 && el.isConnected) requestAnimationFrame(tick);};
      requestAnimationFrame(tick);
    });
  }
  function render() {
    const hash = location.hash.slice(1) || 'home';
    if (hash === 'main') {main.focus(); return;}
    clearInterval(replayTimer); replayTimer = null; activeReplay = null;
    leaveFrame(); currentHash = hash;
    if (hash === 'frame') {enterFrame(); return;}
    let view, title, section;
    if (hash === 'paintings') {view = paintingsView(); title = 'Paintings'; section = 'paintings';}
    else if (hash.startsWith('p-')) {view = paintingView(hash.slice(2)); title = 'A painting'; section = 'paintings';}
    else if (hash === 'birds') {view = birdsView(); title = 'Birds'; section = 'birds';}
    else if (hash.startsWith('b-')) {view = birdView(hash.slice(2)); title = bySlug.get(hash.slice(2))?.name || 'A bird'; section = 'birds';}
    else if (hash.startsWith('day-')) {view = dayView(hash.slice(4)); title = 'Daybook'; section = 'daybook';}
    else if (hash === 'daybook') {location.replace(`#day-${latestDay?.day || ''}`); return;}
    else if (hash === 'compare') {view = compareView(); title = 'Compare birds'; section = 'birds';}
    else if (hash === 'explore') {view = exploreView(); title = 'Explore'; section = 'explore';}
    else if (hash === 'listen') {view = listeningRoom(); title = 'Listen'; section = 'listen';}
    else if (hash === 'seasons') {view = seasonsView(); title = 'Seasons'; section = 'seasons';}
    else {view = home(); title = null; section = 'home';}
    main.innerHTML = view;
    document.title = title ? `${title} · ${DATA.title}` : DATA.title;
    document.querySelectorAll('[data-nav]').forEach(a => a.classList.toggle('active', a.dataset.nav === section));
    window.scrollTo(0, 0); animateCounters();
    if (hash === 'birds') drawBirds();
    if (hash === 'explore') drawExplorer();
    if (hash.startsWith('day-')) showDay(hash.slice(4));
  }

  main.addEventListener('input', event => {
    if (event.target.id === 'explore-search') {exploreQuery = event.target.value; drawExplorer();}
    if (event.target.id === 'bird-search') {birdQuery = event.target.value; drawBirds();}
    if (event.target.id === 'replay-scrub') {replaySlot = Number(event.target.value); updateReplay();}
  });
  main.addEventListener('change', event => {
    if (event.target.id === 'explore-sort') {exploreSort = event.target.value; drawExplorer();}
    if (event.target.id === 'bird-sort') {birdOrder = event.target.value; drawBirds();}
    if (event.target.id === 'day-select') location.hash = `day-${event.target.value}`;
  });
  main.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.question) {const q = DATA.fieldNotes.questions.find(q => q.id === button.dataset.question); document.getElementById('question-answer').innerHTML = questionAnswer(q); main.querySelectorAll('[data-question]').forEach(el => el.setAttribute('aria-pressed', el === button));}
    if (button.dataset.recordings) showRecordingArchive(button.dataset.recordings, button);
    if (button.dataset.range || button.dataset.metric) {
      if (button.dataset.range) chartRange = Number(button.dataset.range);
      if (button.dataset.metric) chartMetric = button.dataset.metric;
      document.getElementById('archive-chart').innerHTML = historyChart(null, chartRange, chartMetric);
      document.querySelectorAll('[data-range]').forEach(el => el.classList.toggle('active', Number(el.dataset.range) === chartRange));
      document.querySelectorAll('[data-metric]').forEach(el => el.classList.toggle('active', el.dataset.metric === chartMetric));
    }
    if (button.dataset.collection !== undefined) {collection = button.dataset.collection; main.innerHTML = paintingsView();}
    if (button.dataset.compare) {
      const slug = button.dataset.compare;
      if (comparison.has(slug)) comparison.delete(slug);
      else if (comparison.size < 3) comparison.add(slug);
      else {button.textContent = 'Choose up to three — remove one first'; return;}
      button.setAttribute('aria-pressed', comparison.has(slug)); button.classList.toggle('selected', comparison.has(slug));
      button.textContent = comparison.has(slug) ? '✓ Selected for comparison' : '+ Add to comparison';
      const count = document.getElementById('compare-count'); if (count) count.textContent = comparison.size;
    }
    if (button.dataset.quarter !== undefined) {replaySlot = Number(button.dataset.quarter); updateReplay();}
    if (button.id === 'replay-toggle') {
      if (replayTimer) {clearInterval(replayTimer); replayTimer = null;}
      else replayTimer = setInterval(() => {replaySlot = (replaySlot + 1) % 96; updateReplay();}, 320);
      button.textContent = replayTimer ? 'Ⅱ Pause replay' : '▶ Play the day'; button.setAttribute('aria-pressed', Boolean(replayTimer));
    }
    if (button.id === 'retry-day') showDay(currentHash.slice(4));
    if (button.dataset.csv) {
      try {
        const data = await loadDay(button.dataset.csv);
        const quote = value => `"${String(value).replace(/"/g, '""')}"`;
        const rows = [['Date', 'Species', 'Scientific name', 'Detections', 'First recorded', 'Last recorded', 'Best model confidence'], ...data.birds.map(b => [data.day, bySlug.get(b.slug).name, bySlug.get(b.slug).scientific, b.count, b.first, b.last, b.best])];
        const url = URL.createObjectURL(new Blob([rows.map(row => row.map(quote).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'}));
        const link = document.createElement('a'); link.href = url; link.download = `birdframe-${data.day}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (_) {button.textContent = 'Download unavailable — try again';}
    }
  });
  main.addEventListener('play', event => {if (event.target.tagName === 'AUDIO') main.querySelectorAll('audio').forEach(audio => {if (audio !== event.target) audio.pause();});}, true);
  main.addEventListener('toggle', event => {
    const details = event.target.closest?.('details[data-art]');
    if (!details?.open || details.dataset.loaded) return;
    details.dataset.loaded = 'yes'; const pre = details.querySelector('pre'); pre.textContent = 'Loading…';
    fetch(`art/${details.dataset.art}.json`).then(r => r.json()).then(art => {pre.textContent = art.prompt || 'No art direction was recorded.';}).catch(() => {pre.textContent = 'The art direction could not be loaded.';});
  }, true);
  document.getElementById('colophon').innerHTML = `<div><p class="eyebrow">${esc(DATA.title)}</p><h2>About this record</h2></div><div><p>BirdNET listens; an image model paints. Explore the acoustic record of a window in ${esc(DATA.place)}.</p><p class="chart-note">Counts are acoustic detections, not individual birds. Only confirmed and probable species appear. Recording coverage is not a measure of absence.</p><p class="snapshot">Snapshot ${fmt(DATA.generated.slice(0, 10), 'medium')} · ${time(DATA.generated)} local time. <a href="#frame">Picture-frame mode ↗</a></p></div>`;
  window.addEventListener('hashchange', render); render();
  let checkingVersion = false;
  async function checkVersion() {
    if (document.hidden || checkingVersion || replayTimer || [...document.querySelectorAll('audio')].some(audio => !audio.paused)) return;
    checkingVersion = true;
    try {const response = await fetch('version.json', {cache: 'no-store'}); if (!response.ok) return; const next = await response.json(); if (typeof next.version === 'string' && next.version !== DATA.version) window.location.reload();} catch (_) {} finally {checkingVersion = false;}
  }
  window.setInterval(checkVersion, 60_000);
  document.addEventListener('visibilitychange', () => {if (document.hidden && replayTimer) {clearInterval(replayTimer); replayTimer = null; const button = document.getElementById('replay-toggle'); if (button) {button.textContent = '▶ Play the day'; button.setAttribute('aria-pressed', 'false');}} checkVersion();});
})();
