import {
  cachedApi, app, attr, esc, num, percent, dateLabel, speciesHref, tierBadge, playButton,
  pageHeader, routeIsCurrent,
} from '../core.js';
import {
  clockTime, dawnRoster, growthChart, initChartTooltips, miniSpark, seasonChart, seasonClock,
  span, weekBars, wirePointerTooltip,
} from '../charts.js';
import {stats} from '../components.js';

const short = day => dateLabel(day, 'short');

// "18–23 Aug", or "28 Aug – 3 Sept" across a month.
function dayRange(first, last) {
  if (first === last) return short(first);
  return first.slice(0, 7) === last.slice(0, 7)
    ? `${Number(first.slice(8))}–${short(last)}` : `${short(first)} – ${short(last)}`;
}

// Daylight as "17 h 15".
function hours(minutes) {
  const whole = Math.round(minutes);
  return `${Math.floor(whole / 60)} h ${String(whole % 60).padStart(2, '0')}`;
}

// The season chart's groups, in the order the season reads.
const GROUPS = [
  {status: 'departed', title: 'Gone quiet', note: 'Heard regularly, then not for longer than chance explains: gone, or simply no longer calling.',
    detail: row => `last heard ${short(row.last)}`},
  {status: 'passage', title: 'Passing through', note: 'A stay in the middle of the season, silent before and after.',
    detail: row => dayRange(row.first, row.last)},
  {status: 'arrived', title: 'New arrivals', note: 'Silent at first, then heard regularly since.',
    detail: row => `since ${short(row.first)}`},
  {status: 'resident', title: 'Constant companions', note: 'Heard on at least half of all listening days.',
    detail: row => `${percent(row.share)} of days`},
  {status: 'occasional', title: 'Occasional visitors', note: 'Heard now and then.',
    detail: row => `${row.days} days`},
  {status: 'brief', title: 'Brief visits', note: 'Heard on one or two days.',
    detail: row => row.days === 1 ? short(row.first) : `${short(row.first)}, ${short(row.last)}`},
];

const SECTIONS = [
  ['seasonMovement', 'Comings & goings'], ['seasonLight', 'Light'], ['seasonVoices', 'Changing voices'],
  ['seasonVisitors', 'Visitors'], ['seasonRecords', 'Records'], ['seasonChronicle', 'Chronicle'],
];

function sectionHead(eyebrow, title, description) {
  return `<div class="section-head"><div><div class="eyebrow">${esc(eyebrow)}</div><h2>${esc(title)}</h2>${description ? `<p>${description}</p>` : ''}</div></div>`;
}

function story(data) {
  const [lede, ...rest] = data.story;
  return `<section class="season-story card">
    <div class="eyebrow gold">The story so far</div>
    <p class="season-lede">${esc(lede || '')}</p>
    ${rest.map(paragraph => `<p>${esc(paragraph)}</p>`).join('')}
  </section>`;
}

function moverList(rows, empty, line) {
  if (!rows.length) return `<p class="faint">${esc(empty)}</p>`;
  return `<ul class="mover-list">${rows.map(row => `<li>
    <div><a href="${speciesHref(row.common_name)}">${esc(row.common_name)}</a><small>${esc(line(row))}</small></div>
    ${playButton(row.clip_url, row.common_name, 'Best recording from your window')}
  </li>`).join('')}</ul>`;
}

function movement(data) {
  const by = status => data.species.filter(row => row.status === status);
  const arrived = by('arrived').sort((a, b) => b.first.localeCompare(a.first));
  const departed = by('departed').sort((a, b) => b.last.localeCompare(a.last));
  const passing = by('passage').sort((a, b) => b.first.localeCompare(a.first));
  return `<section class="season-section" id="seasonMovement">
    ${sectionHead('Migration and movement', 'Comings and goings', 'Who arrived, who went quiet and who passed through, judged by how unlikely each silence is to be chance.')}
    <div class="grid-3 movers">
      <section class="card card-pad mover"><div class="eyebrow">New arrivals</div><b>${arrived.length}</b>
        ${moverList(arrived, 'No newcomers yet.', row => `since ${short(row.first)} · heard on ${row.days === row.observed ? `all ${row.days}` : `${row.days} of ${row.observed}`} days`)}</section>
      <section class="card card-pad mover"><div class="eyebrow">Gone quiet</div><b>${departed.length}</b>
        ${moverList(departed, 'Every regular is still being heard.', row => `last heard ${short(row.last)} · silent ${row.quiet_for} days since`)}</section>
      <section class="card card-pad mover"><div class="eyebrow">Passing through</div><b>${passing.length}</b>
        ${moverList(passing, 'No passers-by yet.', row => `${dayRange(row.first, row.last)} · ${row.days} days`)}</section>
    </div>
    <section class="card dossier-section" style="margin-top:18px">
      <h2>The season chart</h2>
      <p>Every well-supported species, week by week: stronger where it was heard on more of that week’s listening days; the number ending each row counts the days it was heard. Touch or hover a week for its days and detections.</p>
      ${seasonChart(data.species, data.weeks, GROUPS)}
    </section>
  </section>`;
}

function lightTable(data) {
  const weeks = new Map();
  data.light.days.forEach(day => {
    const monday = new Date(`${day.day}T12:00:00Z`);
    monday.setUTCDate(monday.getUTCDate() - ((monday.getUTCDay() + 6) % 7));
    const key = monday.toISOString().slice(0, 10);
    if (!weeks.has(key)) weeks.set(key, []);
    weeks.get(key).push(day);
  });
  const mean = (rows, key) => {
    const values = rows.map(row => row[key]).filter(value => value != null);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  };
  return `<details class="table-view"><summary>Read the light as a table</summary>
    <div style="overflow:auto"><table class="day-table"><thead><tr><th>Week of</th><th class="number">Sunrise</th><th class="number">First voice</th><th class="number">Last voice</th><th class="number">Sunset</th></tr></thead>
    <tbody>${[...weeks].map(([week, rows]) => `<tr><td>${esc(short(week))}</td>${['sunrise', 'first', 'last', 'sunset'].map(key => `<td class="number">${clockTime(mean(rows, key))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
    <p class="section-note">Weekly averages over the days birdframe listened.</p></details>`;
}

// "40 min before sunrise", "17 min after sunset", "at sunset".
function relative(minutes, anchor) {
  if (minutes == null) return '';
  return minutes === 0 ? `at ${anchor}` : `${span(minutes)} ${minutes < 0 ? 'before' : 'after'} ${anchor}`;
}

function lightCallouts(light) {
  const {start, now} = light;
  const moved = Math.abs((now.sunrise ?? 0) - (start.sunrise ?? 0)) >= 20;
  const pair = (a, b) => moved ? `${clockTime(a)} → ${clockTime(b)}` : clockTime(b);
  const tile = (value, label) => `<div class="pattern-callout soft-card"><strong>${value}</strong><span>${esc(label)}</span></div>`;
  return `<div class="light-callouts">
    ${tile(pair(start.sunrise, now.sunrise), moved ? 'sunrise, first week → this week' : 'sunrise this week')}
    ${tile(pair(start.first, now.first), `first voice · usually ${relative(light.offset, 'sunrise')}`)}
    ${tile(pair(start.last, now.last), light.evening_offset == null ? 'last voice'
      : `last voice · usually ${relative(light.evening_offset, 'sunset')}`)}
    ${tile(moved ? `${hours(start.daylight)} → ${hours(now.daylight)}` : hours(now.daylight), 'daylight, sunrise to sunset')}
  </div>`;
}

function nightList(night) {
  if (!night.species.length) return '<div class="empty">Nothing well-supported heard after dark yet.</div>';
  return `<div class="companion-list">${night.species.slice(0, 6).map(row => `<div class="companion">
    <div><a href="${speciesHref(row.common_name)}">${esc(row.common_name)}</a><small>${row.nocturnal ? 'keeps night hours · ' : ''}${esc(dayRange(row.first, row.last))}</small></div>
    <div style="text-align:right"><b class="mono">${num(row.nights)}</b><small>${row.nights === 1 ? 'night' : 'nights'} · ${num(row.detections)} after dark</small></div>
  </div>`).join('')}</div>`;
}

function lightSection(data) {
  const light = data.light;
  if (!light) {
    return `<section class="season-section" id="seasonLight">${sectionHead('Light and song', 'The chorus follows the sun', '')}
      <div class="empty">A few mornings of listening will show how the chorus keeps time with the sun.</div></section>`;
  }
  return `<section class="season-section" id="seasonLight">
    ${sectionHead('Light and song', 'The chorus follows the sun', 'Every quarter-hour of every listening day, shaded by how much was heard. The gold lines are sunrise and sunset; the other pair traces when the day birds got going and fell quiet, as a week’s median.')}
    <section class="card dossier-section">
      <div id="seasonClock"></div>
      <div class="chart-legend" aria-hidden="true">
        <span><i class="key-ramp"></i>fewer → more detections</span>
        <span><i class="key-line sun"></i>sunrise and sunset</span>
        <span><i class="key-line voice"></i>first and last voice</span>
      </div>
      ${lightCallouts(light)}
      ${lightTable(data)}
    </section>
    <div class="dossier-grid" style="margin-top:18px">
      <section class="card dossier-section"><h2>Who wakes first</h2>
        <p>When each regular singer usually gets going, against sunrise. The bar spans the middle half of its mornings; a stray call before dawn doesn’t count.</p>
        <div id="dawnRoster"></div></section>
      <section class="card dossier-section"><h2>After dark</h2>
        <p>Detections between the end of dusk and two hours before sunrise, so the dawn chorus isn’t counted as night song.</p>
        ${nightList(data.night)}
        <h3 class="mini-head">After dark, week by week</h3>
        ${weekBars(data.weeks, data.night.weekly, {width: 400, height: 150, label: 'Detections after dark by week',
          tip: (week, value) => `Week of ${short(week.start)}\n${num(value || 0)} detections after dark`})}
      </section>
    </div>
  </section>`;
}

function voiceRow(row, rising) {
  const weekly = row.weekly.map(value => value ?? 0);
  return `<div class="voice-row">
    <div><a href="${speciesHref(row.common_name)}">${esc(row.common_name)}</a>
      <small>${num(row.earlier_rate)} → ${num(row.recent_rate)} detections a day</small></div>
    ${miniSpark(weekly, `${row.common_name} detections a day, week by week`)}
    <b>${rising ? '↑' : '↓'} ${row.earlier_rate ? (row.recent_rate / row.earlier_rate).toFixed(1) : '—'}×</b>
  </div>`;
}

function voicesSection(data) {
  const trends = data.trends;
  const chorus = data.weeks.map(week => week.days ? Math.round(week.detections / week.days) : null);
  const weekly = weekBars(data.weeks, chorus, {label: 'Detections per listening day, by week',
    tip: (week, value) => week.days
      ? `Week of ${short(week.start)}\n${num(value)} detections a day\n${week.species} well-supported species · ${week.days} listening ${week.days === 1 ? 'day' : 'days'}`
      : `Week of ${short(week.start)}\nNot listening`});
  const body = trends
    ? `<div class="grid-2">
        <section class="card card-pad"><h3 class="mini-head" style="margin-top:0">Heard more lately</h3>
          ${trends.rising.length ? trends.rising.map(row => voiceRow(row, true)).join('') : '<p class="faint">No voice has grown markedly louder.</p>'}</section>
        <section class="card card-pad"><h3 class="mini-head" style="margin-top:0">Heard less lately</h3>
          ${trends.falling.length ? trends.falling.map(row => voiceRow(row, false)).join('') : '<p class="faint">No voice has grown markedly quieter.</p>'}</section>
      </div>`
    : '<div class="empty">Changing voices need five weeks of listening: three to compare and two before them.</div>';
  return `<section class="season-section" id="seasonVoices">
    ${sectionHead('Lately', 'Changing voices', trends
      ? `Detections a day over the last ${trends.recent_days} days (since ${esc(short(trends.since))}) against the season before, for birds heard throughout. More detections can mean more birds, or the same birds singing more.`
      : '')}
    ${body}
    <section class="card dossier-section" style="margin-top:18px"><h2>The chorus, week by week</h2>
      <p>Detections per listening day. Touch or hover a week for its species count.</p>${weekly}</section>
  </section>`;
}

function visitorRow(row, {doubtful = false} = {}) {
  const dates = row.days === 1 ? short(row.first) : `${dayRange(row.first, row.last)} · ${row.days} days`;
  const why = doubtful ? row.reasons : row.why;
  return `<div class="visitor">
    <div><a href="${speciesHref(row.common_name)}">${esc(row.common_name)}</a> ${playButton(row.clip_url, row.common_name, 'Best recording from your window')}
      <small class="scientific">${esc(row.scientific_name)}</small></div>
    <div class="visitor-why">${tierBadge(row.tier, row.reasons)}${why.map(text => `<span>${esc(text)}</span>`).join('')}</div>
    <div class="visitor-when"><span>${esc(dates)}</span><small>best match ${Math.round(row.best_confidence * 100)}%</small></div>
  </div>`;
}

function visitorsSection(data) {
  const {notable, doubtful, doubtful_total: doubtfulTotal} = data.visitors;
  return `<section class="season-section" id="seasonVisitors">
    ${sectionHead('Surprises', 'Notable visitors', 'Well-supported birds that are uncommon here, passed through or came only briefly, each with its best recording if one was kept.')}
    <div class="card card-pad">${notable.length ? notable.map(row => visitorRow(row)).join('') : '<p class="faint">No unusual or fleeting visitors yet.</p>'}</div>
    ${doubtfulTotal ? `<details class="card card-pad doubtful" style="margin-top:14px">
      <summary><div><span class="eyebrow">Listen and judge</span><b>${doubtfulTotal} doubtful ${doubtfulTotal === 1 ? 'record' : 'records'}</b>
        <small>Too implausible, faint or rare to count in the story above. A recording is the best way to decide.</small></div>
        <span class="btn secondary small"><span class="if-closed">Show</span><span class="if-open">Hide</span></span></summary>
      <div style="margin-top:12px">${doubtful.map(row => visitorRow(row, {doubtful: true})).join('')}</div>
      ${doubtfulTotal > doubtful.length ? `<p class="section-note">Showing the ${doubtful.length} clearest. The Species page lists them all.</p>` : ''}
    </details>` : ''}
  </section>`;
}

function recordTile(label, value, detail, href = null) {
  return `<${href ? `a href="${attr(href)}"` : 'div'} class="record soft-card">
    <span class="eyebrow">${esc(label)}</span><b>${value}</b><small>${detail}</small></${href ? 'a' : 'div'}>`;
}

function recordsSection(data) {
  const r = data.records;
  const tiles = [];
  if (r.richest_day) tiles.push(recordTile('Richest day', `${r.richest_day.species} species`, esc(dateLabel(r.richest_day.day)), `#journal/${r.richest_day.day}`));
  if (r.busiest_day) tiles.push(recordTile('Busiest day', `${num(r.busiest_day.detections)}`, `detections on ${esc(dateLabel(r.busiest_day.day))}`, `#journal/${r.busiest_day.day}`));
  if (r.earliest_voice) tiles.push(recordTile('Earliest voice', esc(r.earliest_voice.at), `${esc(r.earliest_voice.common_name)} · ${esc(short(r.earliest_voice.day))}`, `#journal/${r.earliest_voice.day}`));
  if (r.latest_voice) tiles.push(recordTile('Latest voice', esc(r.latest_voice.at), `${esc(r.latest_voice.common_name)} · ${esc(short(r.latest_voice.day))}`, `#journal/${r.latest_voice.day}`));
  if (r.longest_chorus) tiles.push(recordTile('Longest chorus', esc(span(r.longest_chorus.minutes)), `${esc(r.longest_chorus.from)}–${esc(r.longest_chorus.to)} · ${esc(short(r.longest_chorus.day))}`, `#journal/${r.longest_chorus.day}`));
  if (r.most_faithful) tiles.push(recordTile('Most faithful', esc(r.most_faithful.common_name), `heard on ${r.most_faithful.days} of ${r.most_faithful.of} days`, speciesHref(r.most_faithful.common_name)));
  if (r.most_heard) tiles.push(recordTile('Most heard', esc(r.most_heard.common_name), `${num(r.most_heard.detections)} detections`, speciesHref(r.most_heard.common_name)));
  const milestones = data.growth.milestones;
  return `<section class="season-section" id="seasonRecords">
    ${sectionHead('The record book', 'Records and the life list', 'Bests from every listening day so far. Each opens the day or the bird behind it.')}
    <div class="records-grid">${tiles.join('') || '<div class="empty">Records begin with the first full day.</div>'}</div>
    <section class="card dossier-section" style="margin-top:18px"><h2>The life list grows</h2>
      <p>Well-supported species heard at the window, accumulating day by day.</p>
      ${growthChart(data.growth.points)}
      ${milestones.length ? `<div class="milestones">${milestones.map(m => `<a href="${speciesHref(m.common_name)}"><b>${m.count}</b><span>${esc(m.common_name)}</span><small>${esc(short(m.day))}</small></a>`).join('')}</div>` : ''}
    </section>
  </section>`;
}

const KIND_LABEL = {
  start: 'Begins', arrival: 'Arrival', departure: 'Last heard', passage: 'Passage',
  first: 'New species', return: 'Return', milestone: 'Milestone', record: 'Record',
};

function chronicleSection(data) {
  const months = new Map();
  data.chronicle.forEach((event, i) => {
    const key = event.day.slice(0, 7);
    if (!months.has(key)) months.set(key, []);
    months.get(key).push({...event, later: i >= 10});
  });
  const monthName = key => new Intl.DateTimeFormat('en-GB', {month: 'long', year: 'numeric', timeZone: 'UTC'})
    .format(new Date(`${key}-15T12:00:00Z`));
  const link = event => event.species ? speciesHref(event.species) : `#journal/${event.day}`;
  return `<section class="season-section" id="seasonChronicle">
    ${sectionHead('Chronicle', 'The season, as it happened', 'Arrivals, last records, passers-by, returns, new species and records, newest first.')}
    <div class="card card-pad chronicle" data-collapsed="${data.chronicle.length > 10}">${[...months].map(([key, events]) => `<section${events[0].later ? ' class="later"' : ''}>
      <h3>${esc(monthName(key))}</h3>
      <ol>${events.map(event => `<li data-kind="${attr(event.kind)}"${event.later ? ' class="later"' : ''}>
        <time datetime="${attr(event.day)}">${esc(short(event.day))}</time>
        <span class="chronicle-kind">${esc(KIND_LABEL[event.kind] || event.kind)}</span>
        <div><a href="${attr(link(event))}">${esc(event.title)}</a><small>${esc(event.detail)}</small></div>
      </li>`).join('')}</ol></section>`).join('')}
      ${data.chronicle.length > 10 ? `<button type="button" class="text-link chronicle-more">Show the whole chronicle · ${data.chronicle.length} events</button>` : ''}</div>
  </section>`;
}

function methods(data) {
  const m = data.methods;
  return `<section class="card card-pad season-methods">
    <div class="eyebrow">How to read this</div>
    <p>Everything here is worked out from stored detections; nothing is changed or deleted. Counts are BirdNET detections (calls and phrases), never numbers of birds, and only confirmed and probable species tell the story.</p>
    <p><strong>Gone quiet</strong> means a bird heard on a share of days went unheard for so long that, had it still been calling as often, the silence would have a less than ${Math.round(m.silence_chance * 100)}-in-100 chance (and at least ${m.min_silence} listening days). It may have left, or only stopped calling. Arrivals and silent spells are judged the same way, and a day the microphone was off is never counted as silence.</p>
    <p><strong>The first voice</strong> is when a day bird got going and kept going: two quarter-hours in a row, each with at least two detections and a fifth of its busiest around dawn, so a stray call in the night doesn’t count. Birds heard per hour of night at least a quarter as often as by day, like owls or geese overhead, keep their own hours and are left out of dawn and dusk timings. Sunrise and sunset are calculated for the window’s configured location.</p>
  </section>`;
}

export async function renderSeasons(token) {
  const data = await cachedApi('/api/seasons', 60_000);
  if (!routeIsCurrent(token)) return;
  const place = data.place || 'the window';
  if (!data.listening_days) {
    app.innerHTML = `<article class="page">${pageHeader('The long view', 'Seasons', '')}
      <div class="empty">Nothing heard yet. The season’s story begins with the first bird.</div></article>`;
    return;
  }
  const counts = data.counts;
  const clock = seasonClock(data.clock, data.light?.days || []);
  app.innerHTML = `<article class="page seasons-page">
    ${pageHeader('The long view', 'Seasons', `How life at the ${esc(place)} window has changed since ${esc(dateLabel(data.since))}: who arrived and who went quiet, how the chorus keeps time with the sun, and the season’s records.`)}
    ${story(data)}
    <div style="margin-top:16px">${stats([
      {value: num(data.listening_days), label: 'listening days'},
      {value: counts.species, label: 'well-supported species'},
      {value: counts.arrived + counts.passage, label: 'arrivals & passers-by'},
      {value: counts.departed, label: 'gone quiet'},
    ])}</div>
    <nav class="jump-bar segmented" aria-label="Season sections">${SECTIONS.map(([id, label]) => `<button type="button" data-jump="${id}">${esc(label)}</button>`).join('')}</nav>
    ${movement(data)}
    ${lightSection(data)}
    ${voicesSection(data)}
    ${visitorsSection(data)}
    ${recordsSection(data)}
    ${chronicleSection(data)}
    ${methods(data)}
  </article>`;

  const clockHost = document.querySelector('#seasonClock');
  if (clockHost) {
    clockHost.innerHTML = clock.html;
    wirePointerTooltip(clockHost.querySelector('.season-clock'), clock.resolve);
  }
  const roster = document.querySelector('#dawnRoster');
  if (roster) {
    const rows = data.light.roster;
    const draw = all => {
      roster.innerHTML = dawnRoster(all ? rows : rows.slice(0, 12)) + (rows.length > 12
        ? `<button type="button" class="text-link roster-more">${all ? 'Show fewer' : `Show all ${rows.length}`}</button>` : '');
      initChartTooltips(roster);
      roster.querySelector('.roster-more')?.addEventListener('click', () => draw(!all));
    };
    draw(false);
  }
  document.querySelector('.season-chart')?.addEventListener('click', event => {
    const button = event.target.closest('[data-more]');
    const members = button?.previousElementSibling;
    if (!members) return;
    const open = members.dataset.collapsed === 'true';
    members.dataset.collapsed = String(!open);
    button.textContent = open ? 'Show fewer' : `Show all ${button.dataset.more}`;
  });
  document.querySelector('.chronicle-more')?.addEventListener('click', event => {
    event.currentTarget.closest('.chronicle').dataset.collapsed = 'false';
    event.currentTarget.remove();
  });
  document.querySelector('.jump-bar')?.addEventListener('click', event => {
    const button = event.target.closest('[data-jump]');
    document.getElementById(button?.dataset.jump || '')?.scrollIntoView({behavior: 'smooth', block: 'start'});
  });
}
