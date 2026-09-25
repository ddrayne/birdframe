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

  function birdRow(b) {
    return `<li><a class="bird-row" href="#b-${b.slug}">${clock(b, 56)}
      <span class="name">${esc(b.name)}</span><span class="sci">${esc(b.scientific)}</span>
      <span class="when">Heard on ${plural(b.days, 'day')} · most often around ${hourLabel(b.peak)}</span></a></li>`;
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
  function home() {
    const latest = paintings[0];
    const heard = DATA.lastHeard
      ? `<span>Last heard: <b>${esc(DATA.lastHeard.name)}</b> at ${time(DATA.lastHeard.at)} on ${esc(fmt(DATA.lastHeard.at.slice(0, 10), 'short'))}</span>` : '';
    const notes = DATA.highlights.map(h => {
      const bird = h.bird && bySlug.get(h.bird);
      const dayPainting = h.day && paintings.find(p => p.day === h.day);
      return `<li class="note-item${bird ? '' : ' no-bird'}">${bird ? clock(bird, 52) : ''}
        <p class="label">${esc(h.label)}</p>
        ${bird ? `<p class="name"><a href="#b-${bird.slug}">${esc(bird.name)}</a></p>` : ''}
        <p class="text">${dayPainting ? `<a href="#p-${dayPainting.id}">${esc(h.text)}</a>` : esc(h.text)}</p></li>`;
    }).join('');
    const topBirds = [...species].sort((a, b) => b.days - a.days || a.name.localeCompare(b.name));
    return `<div class="page">
      <h1 class="sr-only">${esc(DATA.title)}</h1>
      ${latest ? hero(latest) : '<p class="empty">The first painting will hang here after the first day of listening.</p>'}
      <section class="about">
        <p class="label">A painted field journal</p>
        <p>A microphone at a window in ${esc(DATA.place)} listens for birdsong day and night. BirdNET names the singers, and an image model paints the birds of each day.</p>
        <p class="facts"><span><b>${species.length}</b> species</span><span><b>${DATA.listeningDays}</b> days of listening</span><span><b>${paintings.length}</b> paintings</span>${heard}</p>
      </section>
      ${notes ? `<section class="section">${sectionHead('Field notes')}<ul class="notes">${notes}</ul></section>` : ''}
      ${paintings.length > 1 ? `<section class="section">${sectionHead('Recent paintings', '<a href="#paintings">All paintings →</a>')}
        <div class="strip">${paintings.slice(1, 9).map(tile).join('')}</div></section>` : ''}
      ${species.length ? `<section class="section">${sectionHead('The birds', `<a href="#birds">All ${species.length} birds →</a>`)}
        <ul class="bird-list">${topBirds.slice(0, 6).map(birdRow).join('')}</ul></section>` : ''}
      ${species.length ? `<section class="section">${sectionHead('Through the season', '<a href="#seasons">Every bird →</a>')}
        ${phenology(topBirds.slice(0, 10).sort((a, b) => a.first.localeCompare(b.first)))}</section>` : ''}
    </div>`;
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

  let birdOrder = 'often';
  function birdsView() {
    const list = [...species].sort(birdOrder === 'name' ? (a, b) => a.name.localeCompare(b.name)
      : birdOrder === 'new' ? (a, b) => b.first.localeCompare(a.first) || a.name.localeCompare(b.name)
      : (a, b) => b.days - a.days || a.name.localeCompare(b.name));
    const sort = (key, text) => `<button class="chip" type="button" data-order="${key}" aria-pressed="${birdOrder === key}">${text}</button>`;
    return `<div class="page">
      <section class="intro"><p class="label">${plural(species.length, 'species')}</p><h1>Birds</h1>
        <p>Only birds that were heard clearly and are expected here are listed. Each dial is one day: petals show the hours a bird sings, and the gold petal is its busiest hour.</p></section>
      <section class="section"><div class="sorts" role="group" aria-label="Order">${sort('often', 'Most often')}${sort('name', 'A–Z')}${sort('new', 'Newest')}</div>
        ${list.length ? `<ul class="bird-list">${list.map(birdRow).join('')}</ul>` : '<p class="empty">No birds yet.</p>'}</section></div>`;
  }

  function birdView(slug) {
    const b = bySlug.get(slug);
    if (!b) return missing('That bird');
    const shown = paintings.filter(p => p.birds.includes(b.name));
    const wiki = `https://en.wikipedia.org/wiki/${encodeURIComponent(b.scientific.replace(/ /g, '_'))}`;
    return `<article class="page">
      <header class="bird-head">${clock(b, 260, true)}
        <div class="intro"><p class="label">${esc(b.rarity)}</p><h1>${esc(b.name)}</h1><p class="sci">${esc(b.scientific)}</p></div></header>
      <dl class="bird-facts">
        <div><dt class="label">First heard</dt><dd>${esc(fmt(b.first, 'short'))}</dd></div>
        <div><dt class="label">Last heard</dt><dd>${esc(fmt(b.last, 'short'))}</dd></div>
        <div><dt class="label">Heard on</dt><dd>${plural(b.days, 'day')}</dd></div>
        <div><dt class="label">Busiest hour</dt><dd>${hourLabel(b.peak)}</dd></div>
      </dl>
      <section class="section">${sectionHead('Through the season')}${phenology([b])}</section>
      <section class="section">${sectionHead(`In ${plural(shown.length, 'painting')}`)}
        ${shown.length ? `<div class="gallery">${shown.map(tile).join('')}</div>` : '<p class="empty">Not painted yet.</p>'}</section>
      <p class="actions"><a href="${wiki}" target="_blank" rel="noopener">Read about the ${esc(b.name)} on Wikipedia ↗</a></p>
    </article>`;
  }

  function seasonsView() {
    const list = [...species].sort((a, b) => a.first.localeCompare(b.first) || b.days - a.days);
    return `<div class="page">
      <section class="intro"><p class="label">${esc(DATA.since ? `Since ${fmt(DATA.since, 'medium')}` : 'Waiting for the first morning')}</p><h1>Seasons</h1>
        <p>Each square is a week at the window, and each row a bird, in the order they were first heard. The darker the square, the more days that bird was heard that week.</p></section>
      <section class="section">${phenology(list)}</section></div>`;
  }

  const missing = what => `<div class="page"><section class="intro"><h1>Not here</h1>
    <p>${what} isn't in this journal. <a href="#home">Back to the latest painting</a></p></section></div>`;

  // ── frame mode: any tablet becomes a picture frame ─────────────
  let wakeLock = null, frameTimer = null;
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
    // A fresh copy of the page carries the newest painting.
    frameTimer = setTimeout(() => location.reload(), 30 * 60 * 1000);
  }
  function leaveFrame() {
    document.querySelector('.frame-mode')?.remove();
    document.documentElement.style.overflow = '';
    wakeLock?.release?.().catch?.(() => {});
    wakeLock = null;
    clearTimeout(frameTimer);
  }

  // ── routing (plain anchors, so any link to a page works) ──────
  const scrollMemory = new Map();
  let shown = null, followedLink = false;
  document.addEventListener('click', event => {
    if (event.target.closest('a[href^="#"]')) followedLink = true;
  }, true);

  function render() {
    const hash = location.hash.slice(1) || 'home';
    if (hash === 'main') { main.focus(); return; }     // the skip link
    if (shown !== null) scrollMemory.set(shown, window.scrollY);
    const restore = followedLink ? null : scrollMemory.get(hash);
    followedLink = false;
    shown = hash;
    leaveFrame();
    if (hash === 'frame') { enterFrame(); return; }
    const [view, title, section] =
      hash === 'paintings' ? [paintingsView(), 'Paintings', 'paintings']
      : hash.startsWith('p-') ? [paintingView(hash.slice(2)), 'A painting', 'paintings']
      : hash === 'birds' ? [birdsView(), 'Birds', 'birds']
      : hash.startsWith('b-') ? [birdView(hash.slice(2)), bySlug.get(hash.slice(2))?.name || 'A bird', 'birds']
      : hash === 'seasons' ? [seasonsView(), 'Seasons', 'seasons']
      : [home(), null, 'home'];
    main.innerHTML = view;
    document.title = title ? `${title} · ${DATA.title}` : DATA.title;
    document.querySelectorAll('[data-nav]').forEach(a => a.classList.toggle('active', a.dataset.nav === section));
    window.scrollTo(0, restore || 0);
  }

  main.addEventListener('click', event => {
    const chip = event.target.closest('[data-collection]');
    if (chip) { collection = chip.dataset.collection; main.innerHTML = paintingsView(); return; }
    const order = event.target.closest('[data-order]');
    if (order) { birdOrder = order.dataset.order; main.innerHTML = birdsView(); }
  });

  // The full art direction is fetched only when someone asks to read it.
  main.addEventListener('toggle', event => {
    const details = event.target.closest?.('details[data-art]');
    if (!details?.open || details.dataset.loaded) return;
    details.dataset.loaded = 'yes';
    const pre = details.querySelector('pre');
    pre.textContent = 'Loading…';
    fetch(`art/${details.dataset.art}.json`).then(r => r.json())
      .then(art => { pre.textContent = art.prompt || 'No art direction was recorded.'; })
      .catch(() => { pre.textContent = 'The art direction could not be loaded.'; });
  }, true);

  document.getElementById('colophon').innerHTML = `
    <p>${esc(DATA.title)} is a birdframe journal. A microphone at a window in ${esc(DATA.place)} listens all day; BirdNET names the birds it hears, and an image model paints them. Only confident identifications of birds expected here are shown. Counts describe days a bird was heard, not how many birds there were.</p>
    <p>Updated ${esc(fmt(DATA.generated.slice(0, 10), 'medium'))} at ${time(DATA.generated)}. <a href="#frame">Frame mode</a> turns any tablet into a picture frame for the latest painting.</p>`;

  window.addEventListener('hashchange', render);
  render();
})();
