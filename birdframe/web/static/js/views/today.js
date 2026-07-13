import {
  api, app, esc, num, percent, ago, dateLabel, speciesHref, tierBadge, playButton,
  pageHeader, setListening, state, stopPolling, toast, routeIsCurrent,
} from '../core.js';
import {activityRibbon, miniSpark} from '../charts.js';
import {speciesRows, stats, reliabilityLegend} from '../components.js';

function liveFeed(rows) {
  if (!rows?.length) return '<div class="empty">The microphone is open; the page is waiting for the next song.</div>';
  return `<div class="live-feed">${rows.map(row => `<div class="feed-row">
    <a href="${speciesHref(row.common_name)}">${esc(row.common_name)}</a>
    <span class="confidence-line" title="confidence ${row.confidence}"><i style="width:${Math.round(row.confidence * 100)}%"></i></span>
    <time class="mono">${esc(row.at)}</time>
  </div>`).join('')}</div>`;
}

function newestChips(names) {
  if (!names?.length) return '<span class="faint">No first-ever visitors today.</span>';
  return names.map(name => `<a class="tier tier-confirmed" href="${speciesHref(name)}">${esc(name)}</a>`).join(' ');
}

function todayHero(now) {
  const latest = now.latest;
  if (!latest) {
    return `<section class="today-hero card">
      <div><div class="eyebrow gold">Listening live</div><h2 class="latest-name">A quiet window</h2>
      <p class="scientific">The next voice will appear here.</p></div>
      ${miniSpark(now.activity, 'Song activity in the last hour')}
    </section>`;
  }
  return `<section class="today-hero card">
    <div>
      <div class="eyebrow gold">Latest from the window · ${ago(latest.seconds_ago)}</div>
      <h2 class="latest-name"><a href="${speciesHref(latest.common_name)}">${esc(latest.common_name)}</a></h2>
      <div class="scientific">${esc(latest.scientific_name)}</div>
      <div class="hero-meta">
        ${tierBadge(latest.tier)}
        <span>confidence <b>${percent(latest.confidence)}</b></span>
        <span>heard at <b class="mono">${esc(latest.at.slice(0, 5))}</b></span>
        ${playButton(latest.clip_url, latest.common_name)}
      </div>
    </div>
    ${miniSpark(now.activity, 'BirdNET detections during the last hour')}
  </section>`;
}

function fieldMoments(day, today) {
  if (!day) return '<div class="empty">Today’s field notes will grow as birds are heard.</div>';
  const first = day.first_detection, last = day.last_detection;
  return `<div class="moment-list">
    <div class="moment"><time>${esc(first.at.slice(0, 5))}</time><div><strong>${esc(first.common_name)}</strong><small>opened today’s journal</small></div></div>
    <div class="moment"><time>${esc(last.at.slice(0, 5))}</time><div><strong>${esc(last.common_name)}</strong><small>most recent voice</small></div></div>
    <div class="moment"><time>NEW</time><div><strong>${today.new_today?.length || 0} first-ever today</strong><small>${today.new_today?.slice(0, 3).join(', ') || 'The life list is holding steady'}</small></div></div>
    <div class="moment"><time>PEAK</time><div><strong>${esc(day.species[0]?.common_name || '—')}</strong><small>${num(day.species[0]?.count || 0)} detections today</small></div></div>
  </div>`;
}

async function refreshLive() {
  try {
    const now = await api('/api/now');
    const latest = document.querySelector('[data-live-latest]');
    if (latest && now.latest) latest.textContent = `${now.latest.common_name} · ${ago(now.latest.seconds_ago)}`;
    const feed = document.querySelector('#liveFeed');
    if (feed) feed.innerHTML = liveFeed(now.feed);
  } catch { /* a live refresh should never replace the journal */ }
}

async function captureMoment(button) {
  button.disabled = true;
  button.textContent = 'Starting the painting…';
  try {
    const start = await api('/api/capture', {method: 'POST'});
    if (start.status === 'running') {
      button.textContent = 'Painting in progress…';
    } else {
      button.textContent = `Painting ${start.species?.length || 'this'} moment…`;
    }
    const poll = setInterval(async () => {
      try {
        const job = await api('/api/capture/status');
        if (job.state === 'running') return;
        clearInterval(poll);
        button.disabled = false;
        button.textContent = 'Paint this moment';
        if (job.state === 'done') toast(`Moment captured · frame ${job.result}.`);
        else if (job.state === 'empty') toast('Nothing was heard in the current window.');
        else if (job.state === 'cancelled') toast('The painting was kept off the frame.');
        else toast(`Painting failed: ${job.result || 'unknown error'}`);
      } catch {
        clearInterval(poll); button.disabled = false; button.textContent = 'Paint this moment';
      }
    }, 1800);
  } catch (error) {
    button.disabled = false; button.textContent = 'Paint this moment'; toast(error.message);
  }
}

export async function renderToday(token) {
  stopPolling();
  // The Store intentionally owns one SQLite connection. Keep local data reads
  // ordered; the calls are fast and this avoids competing cursors across the
  // FastAPI worker pool while the live listener is writing.
  const now = await api('/api/now');
  const today = await api('/api/today');
  const health = await api('/api/health').catch(() => ({listening: true, status: 'listening'}));
  if (!routeIsCurrent(token)) return;
  const day = await api(`/api/day/${today.date}`).catch(() => null);
  const narration = await api('/api/narration').catch(() => ({narration: ''}));
  if (!routeIsCurrent(token)) return;
  setListening(health.listening, health.listening ? 'Listening' : health.status);

  const reliable = today.species.filter(s => s.tier !== 'tentative');
  const story = narration.narration || (reliable.length
    ? `${reliable[0].common_name} leads a field journal of ${reliable.length} well-supported species today.`
    : 'A quiet page so far; birdframe is listening for the day’s first clear voice.');
  const clipCount = day?.clips?.length || 0;
  const weekday = new Intl.DateTimeFormat('en-GB', {weekday: 'long'}).format(new Date(`${today.date}T12:00:00`));

  app.innerHTML = `<article class="page">
    ${pageHeader(`${weekday} at your Edinburgh window`, 'Today', 'The living edge of your journal: what is singing, what is new, and how the day is taking shape.',
      `<a class="btn secondary" href="#journal/${today.date}">Open full day</a>`)}

    <div class="grid-main">
      ${todayHero(now)}
      <aside class="story-card card">
        <div class="eyebrow">Today in a sentence</div>
        <blockquote>“${esc(story)}”</blockquote>
        <small><span data-live-latest>${now.latest ? `${esc(now.latest.common_name)} · ${ago(now.latest.seconds_ago)}` : 'Listening for the first bird'}</span></small>
      </aside>
    </div>

    <div class="section-head"><div><div class="eyebrow">At a glance</div><h2>${dateLabel(today.date)}</h2></div></div>
    ${stats([
      {value: today.species.length, label: 'species detected'},
      {value: reliable.length, label: 'well-supported'},
      {value: num(day?.detections || 0), label: 'BirdNET detections'},
      {value: clipCount, label: 'saved recordings'},
    ])}

    <div class="grid-2" style="margin-top:18px">
      <section class="card card-pad">
        <div class="section-head" style="margin-top:0"><div><div class="eyebrow">Field notes</div><h2>Four moments from today</h2></div></div>
        ${fieldMoments(day, now)}
        <div class="today-actions"><button type="button" class="btn" data-action="capture-moment">Paint this moment</button>
          <a class="btn secondary" href="#pictures">Browse pictures</a></div>
      </section>
      <section class="card card-pad">
        <div class="section-head" style="margin-top:0"><div><div class="eyebrow">The day’s pulse</div><h2>From midnight to now</h2><p>Counts are model detections, not individual birds.</p></div></div>
        ${day ? activityRibbon(day.quarters, 'Bird activity through the day', day.quarter_species) : '<div class="empty">Waiting for today’s first trace.</div>'}
        <div class="section-head"><div><h3>First-ever visitors today</h3></div></div>
        <div class="button-row">${newestChips(now.new_today)}</div>
      </section>
    </div>

    <section>
      <div class="section-head"><div><div class="eyebrow">Today’s chorus</div><h2>Every species heard</h2><p>Nothing is hidden. Reliability makes the evidence legible.</p></div>
        <div class="segmented" id="todayTier"><button class="active" data-tier="all">All ${today.species.length}</button><button data-tier="solid">Supported ${reliable.length}</button><button data-tier="tentative">Tentative ${today.species.length - reliable.length}</button></div>
      </div>
      ${reliabilityLegend()}
      <div class="card card-pad" id="todaySpecies">${speciesRows(today.species, {showReasons: true})}</div>
    </section>

    <details class="card card-pad" style="margin-top:24px">
      <summary class="section-head" style="margin:0;cursor:pointer"><div><div class="eyebrow gold">Live stream</div><h2>Heard just now</h2><p>The raw recent feed, newest first.</p></div></summary>
      <div id="liveFeed">${liveFeed(now.feed)}</div>
    </details>
  </article>`;

  const speciesHost = document.querySelector('#todaySpecies');
  document.querySelector('#todayTier')?.addEventListener('click', event => {
    const button = event.target.closest('button[data-tier]');
    if (!button) return;
    document.querySelectorAll('#todayTier button').forEach(el => el.classList.toggle('active', el === button));
    const filtered = button.dataset.tier === 'all' ? today.species
      : button.dataset.tier === 'solid' ? reliable
      : today.species.filter(s => s.tier === 'tentative');
    speciesHost.innerHTML = speciesRows(filtered, {showReasons: true});
  });
  document.querySelector('[data-action="capture-moment"]')?.addEventListener('click', event => captureMoment(event.currentTarget));
  state.todayTimer = setInterval(refreshLive, 5000);
}
