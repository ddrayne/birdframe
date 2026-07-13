import {
  api, app, attr, esc, num, dateLabel, relativeDay, pageHeader, routeIsCurrent,
  tierBadge, speciesHref,
} from '../core.js';
import {activityRibbon, hourBars} from '../charts.js';
import {clipCards, speciesRows, stats, reliabilityLegend} from '../components.js';

function dayCard(day) {
  const art = day.images?.[0];
  const reliable = day.top_species.filter(s => s.tier !== 'tentative');
  return `<a class="day-card card" href="#journal/${esc(day.day)}">
    <div class="day-card-body">
      <div class="eyebrow">${esc(relativeDay(day.day))}</div>
      <time datetime="${esc(day.day)}">${esc(dateLabel(day.day, 'short'))}</time>
      <div class="day-stats"><span>${day.species} species</span><span>${num(day.detections)} detections</span><span>${day.images.length} pictures</span></div>
      <div class="day-species">${reliable.slice(0, 4).map(s => `<span>${esc(s.common_name)}</span>`).join('')}
        ${day.new_species.length ? `<span style="color:var(--gold)">+${day.new_species.length} new</span>` : ''}</div>
    </div>
    ${art ? `<img class="day-art" loading="lazy" src="/api/image/${art.id}" alt="${attr(art.style)} artwork from ${attr(day.day)}">`
      : '<div class="day-art day-art-placeholder" aria-hidden="true">♧</div>'}
  </a>`;
}

function dayStory(day) {
  const solid = day.species.filter(s => s.tier !== 'tentative');
  const leader = solid[0] || day.species[0];
  const newText = day.new_species.length
    ? `${day.new_species.slice(0, 3).join(', ')} ${day.new_species.length === 1 ? 'joined' : 'joined'} the life list.`
    : 'The life list held steady.';
  return `${day.first_detection.common_name} opened the journal at ${day.first_detection.at.slice(0, 5)}. ` +
    `${leader ? `${leader.common_name} was the most persistent voice, with ${leader.count.toLocaleString()} detections. ` : ''}` + newText;
}

async function renderDay(token, dayName) {
  const day = await api(`/api/day/${dayName}`);
  const journal = await api('/api/journal?limit=366');
  if (!routeIsCurrent(token)) return;
  const days = journal.days.map(item => item.day);
  const index = days.indexOf(dayName);
  const newer = index > 0 ? days[index - 1] : null;
  const older = index >= 0 && index < days.length - 1 ? days[index + 1] : null;
  const artwork = day.images?.[0];
  const reliable = day.species.filter(s => s.tier !== 'tentative');

  app.innerHTML = `<article class="page">
    <a class="back-link" href="#journal">← All journal days</a>
    <section class="day-detail-head card">
      <div class="day-detail-copy">
        <div class="eyebrow">Field journal · ${esc(relativeDay(day.date))}</div>
        <h1>${esc(dateLabel(day.date))}</h1>
        <p class="muted" style="font:400 19px/1.5 var(--serif)">${esc(dayStory(day))}</p>
        <div class="button-row" style="margin-top:22px">
          ${older ? `<a class="btn secondary" href="#journal/${older}">← Older day</a>` : ''}
          ${newer ? `<a class="btn secondary" href="#journal/${newer}">Newer day →</a>` : ''}
        </div>
      </div>
      ${artwork ? `<button type="button" class="image-button" style="border:0;padding:0;background:none" data-lightbox="/api/image/${artwork.id}" data-alt="Artwork from ${attr(day.date)}" data-caption="${attr(dateLabel(day.date) + ' · ' + artwork.style)}"><img class="day-artwork" src="/api/image/${artwork.id}" alt="Artwork from ${attr(day.date)}"></button>`
        : '<div class="day-artwork day-art-placeholder" aria-hidden="true">♧</div>'}
    </section>

    <div style="margin-top:16px">${stats([
      {value: day.species_count, label: 'species detected'},
      {value: reliable.length, label: 'well-supported'},
      {value: num(day.detections), label: 'BirdNET detections'},
      {value: day.clips.length, label: 'saved recordings'},
    ])}</div>

    <div class="grid-2" style="margin-top:18px">
      <section class="card dossier-section"><h2>The day’s pulse</h2><p>Hover any 15-minute moment to see its voices and exact counts.</p>${activityRibbon(day.quarters, 'Bird activity through the day', day.quarter_species)}</section>
      <section class="card dossier-section"><h2>The daily rhythm</h2><p>Hover an hour to see which species made up the chorus.</p>${hourBars(day.hours, {height: 180, speciesByHour: day.hour_species})}</section>
    </div>

    <section>
      <div class="section-head"><div><div class="eyebrow">Sound archive</div><h2>Recordings kept from this day</h2><p>The clearest saved clip for each recorded species.</p></div></div>
      ${clipCards(day.clips)}
    </section>

    <section>
      <div class="section-head"><div><div class="eyebrow">Roll call</div><h2>${day.species_count} species in the journal</h2></div></div>
      ${reliabilityLegend()}
      <div class="card card-pad" style="margin-top:12px">${speciesRows(day.species, {showReasons: true})}</div>
    </section>

    ${day.new_species.length ? `<section class="card card-pad" style="margin-top:20px"><div class="eyebrow gold">Life-list firsts</div>
      <div class="button-row" style="margin-top:10px">${day.new_species.map(name => `<a class="btn secondary small" href="${speciesHref(name)}">${esc(name)}</a>`).join('')}</div></section>` : ''}
  </article>`;
}

export async function renderJournal(token, dayName = null) {
  if (dayName) return renderDay(token, dayName);
  const data = await api('/api/journal?limit=366');
  if (!routeIsCurrent(token)) return;
  const days = data.days;
  app.innerHTML = `<article class="page">
    <section class="journal-hero card">
      <div class="eyebrow">The accumulating record</div>
      <h1>The window, day by day</h1>
      <p>${num(data.totals.detections)} detections across ${data.totals.days} listening days have become a journal of ${data.totals.species} species—each day with its own rhythm, recordings, discoveries, and pictures.</p>
    </section>
    ${pageHeader('The archive', `${days.length} journal ${days.length === 1 ? 'day' : 'days'}`, 'Choose a day to reopen the soundscape. A blank hour means no stored detections, not a claim that no bird was present.')}
    <div class="journal-grid">${days.length ? days.map(dayCard).join('') : '<div class="empty">The first journal day has not begun yet.</div>'}</div>
  </article>`;
}
