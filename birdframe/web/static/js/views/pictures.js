import {
  api, app, attr, esc, formBody, num, pageHeader, dateLabel, routeIsCurrent, toast,
} from '../core.js';
import {hourBars, initChartTooltips} from '../charts.js';

const aliases = {gallery: 'editions', make: 'reimagine', styles: 'library'};
const nice = value => String(value || '').replaceAll('-', ' ').replace(/\b\w/g, c => c.toUpperCase());

function shell(active, content) {
  return `<article class="page pictures-page">
    ${pageHeader('A private museum of the garden', 'Pictures', 'Every edition begins with a real listening day. Explore the archive, revisit a remembered chorus, or choose the visual language that tells it best.')}
    <nav class="subnav picture-subnav" aria-label="Picture rooms">
      <a class="${active === 'editions' ? 'active' : ''}" href="#pictures/editions">Editions</a>
      <a class="${active === 'reimagine' ? 'active' : ''}" href="#pictures/reimagine">Reimagine a day</a>
      <a class="${active === 'library' ? 'active' : ''}" href="#pictures/library">Style library</a>
    </nav>${content}</article>`;
}

function tagList(tags = [], limit = 99) {
  return `<div class="art-tags">${tags.slice(0, limit).map(tag => `<span>${esc(nice(tag))}</span>`).join('')}</div>`;
}

function editionCard(image, styleMap) {
  const day = image.source_day || image.generated_at.slice(0, 10);
  const species = image.species?.join(', ') || 'A quiet garden';
  const style = styleMap.get(image.style.replace(' (fallback)', ''));
  const profile = image.art_profile;
  const caption = `${dateLabel(day)} · ${image.style} · ${species}`;
  return `<article class="edition-card card">
    <button type="button" class="image-button edition-image" data-lightbox="/api/image/${image.id}" data-alt="${attr(image.style)} birdframe artwork" data-caption="${attr(caption)}">
      <img loading="lazy" src="/api/image/${image.id}" alt="${attr(image.style)} birdframe artwork">
      ${image.on_frame ? '<span class="edition-frame-mark">On the frame</span>' : ''}
    </button>
    <div class="edition-copy">
      <div class="eyebrow">${esc(style?.collection || 'Garden edition')}</div>
      <h2>${esc(dateLabel(day, 'short'))}</h2>
      <p class="edition-style">${esc(nice(image.style))}</p>
      ${profile ? `<p class="edition-archetype">${esc(profile.archetype)} · ${num(profile.species_count)} species</p>` : ''}
      <p class="edition-species">${esc(species)}</p>
      <div class="edition-actions">
        <button type="button" class="text-link" data-send-image="${image.id}">Send to frame →</button>
        <a class="text-link" href="#pictures/reimagine?day=${attr(day)}">Reimagine →</a>
      </div>
      <details class="edition-notes">
        <summary>Inside this edition</summary>
        ${image.style_reason ? `<div><b>Why this style</b><p>${esc(image.style_reason)}</p></div>` : ''}
        ${profile ? `<div><b>The day’s fingerprint</b><p>${esc(profile.summary)}</p>${tagList(profile.tags, 6)}</div>` : ''}
        <div><b>Made</b><p>${esc(new Date(image.generated_at).toLocaleString('en-GB', {dateStyle: 'medium', timeStyle: 'short'}))}</p></div>
        <div><b>Exact art prompt</b><p class="prompt-copy">${esc(image.prompt || 'Prompt provenance predates this edition.')}</p></div>
      </details>
    </div>
  </article>`;
}

async function sendImage(id, button) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = 'Sending…';
  try {
    await api(`/api/post/${id}`, {method: 'POST'});
    const poll = setInterval(async () => {
      const status = await api('/api/post/status').catch(() => null);
      if (!status || status.state === 'running') return;
      clearInterval(poll);
      button.disabled = false; button.textContent = original;
      if (status.publish === 'posted') toast('Picture accepted by the frame. The e-ink refresh takes about 30 seconds.');
      else if (status.publish === 'held') toast('The shared frame is currently held by someone else.');
      else toast(`The frame could not be reached${status.detail ? `: ${status.detail}` : '.'}`);
    }, 1500);
  } catch (error) {
    button.disabled = false; button.textContent = original; toast(error.message);
  }
}

async function renderEditions(token) {
  const [history, library] = await Promise.all([api('/api/history'), api('/api/styles')]);
  if (!routeIsCurrent(token)) return;
  const styleMap = new Map(library.styles.map(style => [style.name, style]));
  const collections = [...new Set(library.styles.map(style => style.collection))].sort();
  app.innerHTML = shell('editions', `
    <section class="edition-intro">
      <div><div class="eyebrow">The collected days</div><h2>Your garden, interpreted</h2>
        <p>Not a feed of generated images: a growing visual autobiography of what was genuinely heard outside this window.</p></div>
      <div class="edition-count"><b>${num(history.images.length)}</b><span>archived editions</span></div>
    </section>
    <div class="filter-bar edition-filters">
      <select id="editionCollection" aria-label="Filter by collection"><option value="">All collections</option>${collections.map(value => `<option>${esc(value)}</option>`).join('')}</select>
      <select id="editionSeason" aria-label="Filter by season"><option value="">Every season</option><option>spring</option><option>summer</option><option>autumn</option><option>winter</option></select>
      <label class="check-filter"><input type="checkbox" id="editionPosted"> Sent to frame</label>
      <span class="section-note" id="editionResult"></span>
    </div>
    <div class="edition-grid" id="editionGrid"></div>`);
  const draw = () => {
    const collection = document.querySelector('#editionCollection').value;
    const season = document.querySelector('#editionSeason').value;
    const posted = document.querySelector('#editionPosted').checked;
    const rows = history.images.filter(image => {
      const style = styleMap.get(image.style.replace(' (fallback)', ''));
      return (!collection || style?.collection === collection)
        && (!season || image.art_profile?.season === season)
        && (!posted || image.posted_at);
    });
    document.querySelector('#editionResult').textContent = `${rows.length} ${rows.length === 1 ? 'edition' : 'editions'}`;
    document.querySelector('#editionGrid').innerHTML = rows.length
      ? rows.map(image => editionCard(image, styleMap)).join('')
      : '<div class="empty">No editions match this view.</div>';
  };
  draw();
  document.querySelectorAll('#editionCollection,#editionSeason,#editionPosted').forEach(control => control.addEventListener('change', draw));
  app.querySelector('.page').addEventListener('click', event => {
    const button = event.target.closest('[data-send-image]');
    if (button) sendImage(button.dataset.sendImage, button);
  });
}

function fingerprint(direction) {
  const p = direction.profile;
  const voices = direction.species.slice(0, 8).map(species =>
    `<a href="#species/${encodeURIComponent(species.common_name)}"><b>${esc(species.common_name)}</b><span>${num(species.count)} ${species.count === 1 ? 'detection' : 'detections'} · ${esc(species.first_heard)}–${esc(species.last_heard)}</span></a>`).join('');
  return `<section class="fingerprint card">
    <div class="fingerprint-lede"><div class="eyebrow">The day’s character</div><h2>${esc(p.archetype)}</h2><p>${esc(p.summary)}</p>${tagList(p.tags)}</div>
    <div class="fingerprint-stats">
      <div><b>${num(p.species_count)}</b><span>trusted species</span></div>
      <div><b>${num(p.detection_count)}</b><span>detections</span></div>
      <div><b>${num(p.active_span_hours)}h</b><span>active span</span></div>
      <div><b>${Math.round(p.dominant_share * 100)}%</b><span>leading voice</span></div>
    </div>
    <div class="fingerprint-chart"><div class="eyebrow">Activity through the day</div>${hourBars(p.hours, {height: 150, label: `Activity on ${direction.day}`})}</div>
    <div class="fingerprint-voices">${voices}</div>
  </section>`;
}

function recommendationCards(direction, stylesByName) {
  return direction.recommendations.slice(0, 3).map((rec, index) => {
    const style = stylesByName.get(rec.name);
    return `<button type="button" class="recommendation ${index === 0 ? 'recommended' : ''}" data-choose-style="${attr(rec.name)}">
      <span class="recommendation-number">0${index + 1}</span>
      <span><small>${esc(style?.collection || 'Art direction')}</small><b>${esc(nice(rec.name))}</b><em>${esc(rec.reason)}</em></span>
      <i>Choose</i>
    </button>`;
  }).join('');
}

function styleOptions(styles) {
  const groups = Map.groupBy ? Map.groupBy(styles, item => item.collection) : styles.reduce((map, style) => {
    if (!map.has(style.collection)) map.set(style.collection, []);
    map.get(style.collection).push(style); return map;
  }, new Map());
  return [...groups.entries()].map(([collection, rows]) =>
    `<optgroup label="${attr(collection)}">${rows.map(style => `<option value="${attr(style.name)}">${esc(nice(style.name))}</option>`).join('')}</optgroup>`).join('');
}

async function renderReimagine(token, params) {
  const [library, journal] = await Promise.all([api('/api/styles'), api('/api/journal?limit=366')]);
  if (!routeIsCurrent(token)) return;
  if (!journal.days.length) {
    app.innerHTML = shell('reimagine', '<div class="empty">The first listening day will appear here as soon as birds are heard.</div>');
    return;
  }
  const requested = params?.get('day');
  const initialDay = journal.days.some(row => row.day === requested) ? requested : journal.days[0].day;
  const stylesByName = new Map(library.styles.map(style => [style.name, style]));
  app.innerHTML = shell('reimagine', `
    <section class="reimagine-hero">
      <div><div class="eyebrow">Return to a real listening day</div><h2>What should this day become?</h2>
        <p>Choose a date from the field journal. Its species, timing, weather, and first arrivals become art direction—without changing a single detection.</p></div>
      <label class="day-picker">Listening day<select id="reimagineDay">${journal.days.map(row => `<option value="${attr(row.day)}" ${row.day === initialDay ? 'selected' : ''}>${esc(dateLabel(row.day))} · ${row.species} species</option>`).join('')}</select></label>
    </section>
    <div id="directionHost"><div class="loading-inline">Reading the character of this day…</div></div>
    <section class="create-edition card" id="createEdition" hidden>
      <div><div class="eyebrow">Create an interpretation</div><h2>Make this edition yours</h2>
        <p id="selectedStyleStory"></p></div>
      <label>Chosen style<select id="reimagineStyle">${styleOptions(library.styles)}</select></label>
      <div class="button-row"><button type="button" class="btn" id="makePicture" ${library.key_set ? '' : 'disabled'}>Create this edition</button>
        <span class="section-note" id="makeStatus">${library.key_set ? 'A high-quality image usually takes around two minutes and uses one image generation.' : 'Set an OpenAI key to use image generation.'}</span></div>
      <div id="makePreview"></div>
    </section>`);

  let direction = null;
  const describeStyle = name => {
    const style = stylesByName.get(name);
    const rec = direction?.recommendations.find(item => item.name === name);
    document.querySelector('#selectedStyleStory').textContent = rec?.reason || style?.description || 'A deliberate contrasting interpretation.';
  };
  const loadDay = async day => {
    const host = document.querySelector('#directionHost');
    host.innerHTML = '<div class="loading-inline">Reading the character of this day…</div>';
    direction = await api(`/api/art-direction/${day}`);
    if (!routeIsCurrent(token)) return;
    const existing = direction.editions.length ? `<div class="existing-editions"><div class="eyebrow">Already imagined</div><div>${direction.editions.map(image => `<button type="button" data-lightbox="/api/image/${image.id}" data-caption="${attr(image.style)}"><img src="/api/image/${image.id}" alt="${attr(image.style)} edition"></button>`).join('')}</div></div>` : '';
    host.innerHTML = `${fingerprint(direction)}
      <section class="recommendations"><div class="section-head"><div><div class="eyebrow">The art director’s shortlist</div><h2>Three ways into the day</h2><p>Recommendations are deterministic: revisit this date and its fit stays the same.</p></div></div>
        <div class="recommendation-grid">${recommendationCards(direction, stylesByName)}</div></section>${existing}`;
    const chosen = direction.recommendations[0]?.name || library.styles[0]?.name;
    document.querySelector('#reimagineStyle').value = chosen;
    describeStyle(chosen);
    document.querySelector('#createEdition').hidden = !direction.species.length;
    initChartTooltips(host);
    history.replaceState(null, '', `#pictures/reimagine?day=${day}`);
  };
  document.querySelector('#reimagineDay').addEventListener('change', event => loadDay(event.target.value));
  document.querySelector('#reimagineStyle').addEventListener('change', event => describeStyle(event.target.value));
  document.querySelector('#directionHost').addEventListener('click', event => {
    const choice = event.target.closest('[data-choose-style]');
    if (!choice) return;
    document.querySelector('#reimagineStyle').value = choice.dataset.chooseStyle;
    describeStyle(choice.dataset.chooseStyle);
    document.querySelector('#createEdition').scrollIntoView({behavior: 'smooth', block: 'center'});
  });
  document.querySelector('#makePicture').addEventListener('click', async event => {
    const button = event.currentTarget, status = document.querySelector('#makeStatus');
    button.disabled = true; status.textContent = 'The edition is beginning…';
    try {
      const day = document.querySelector('#reimagineDay').value;
      const style = document.querySelector('#reimagineStyle').value;
      await api('/api/generate', formBody({style, day}));
      const started = Date.now();
      const poll = setInterval(async () => {
        const job = await api('/api/generate/status').catch(() => null);
        if (!job || job.state === 'running') {
          status.textContent = `Painting ${dateLabel(day, 'short')}… ${Math.round((Date.now() - started) / 1000)}s`; return;
        }
        clearInterval(poll); button.disabled = false;
        if (job.state === 'done') {
          status.textContent = 'Your new edition is ready.';
          document.querySelector('#makePreview').innerHTML = `<div class="new-edition"><button type="button" class="image-button" data-lightbox="/api/image/${job.image_id}" data-caption="New ${attr(style)} edition"><img src="/api/image/${job.image_id}" alt="New ${attr(style)} edition"></button><div><div class="eyebrow">Fresh from the studio</div><h3>${esc(nice(style))}</h3><p><a href="#pictures/editions">See it in Editions →</a></p></div></div>`;
        } else status.textContent = job.state === 'empty' ? 'No well-supported species are available to picture on this day.' : `Could not generate: ${job.result || job.state}`;
      }, 1800);
    } catch (error) { button.disabled = false; status.textContent = error.message; }
  });
  await loadDay(initialDay);
}

function styleCard(style) {
  return `<article class="library-card card" data-style-card data-collection="${attr(style.collection)}" data-search="${attr([style.name, style.description, style.lineage, style.medium].join(' ').toLowerCase())}">
    <button type="button" class="library-visual" data-open-style="${attr(style.name)}">
      ${style.has_preview ? `<img loading="lazy" src="/api/styles/${attr(style.name)}/preview.png" alt="${attr(style.name)} example">` : `<span><i>BF</i><b>${esc(nice(style.name))}</b><small>${esc(style.medium || style.collection)}</small></span>`}
    </button>
    <div class="library-copy"><div class="eyebrow">${esc(style.collection)}</div><h2>${esc(nice(style.name))}${style.pinned ? '<span class="pinned-mark">house style</span>' : ''}</h2>
      <p>${esc(style.description || style.prompt)}</p>${tagList(style.affinities, 4)}
      <button type="button" class="text-link" data-open-style="${attr(style.name)}">Explore this direction →</button></div>
  </article>`;
}

function styleDetail(style, keySet) {
  const source = /^https?:\/\//.test(style.source || '') ? `<a href="${attr(style.source)}" target="_blank" rel="noopener">Explore a collection source ↗</a>` : '';
  return `<div class="style-detail-head">
      <div><div class="eyebrow">${esc(style.collection)}</div><h2>${esc(nice(style.name))}</h2><p>${esc(style.description)}</p></div>
      <button class="detail-close" type="button" data-close-style aria-label="Close">×</button>
    </div>
    <dl class="style-dna">
      <div><dt>Lineage</dt><dd>${esc(style.lineage || 'A personal studio direction')}</dd></div>
      <div><dt>Material</dt><dd>${esc(style.medium || 'Mixed media')}</dd></div>
      <div><dt>Palette</dt><dd>${esc(style.palette || 'Led by the listening day')}</dd></div>
      <div><dt>Best with</dt><dd>${tagList(style.affinities)}</dd></div>
    </dl>
    <div class="style-detail-actions">
      <button type="button" class="btn" data-edit-style="${attr(style.name)}">Edit direction</button>
      <button type="button" class="btn secondary" data-pin-style="${attr(style.name)}">${style.pinned ? 'Return to responsive director' : 'Make house style'}</button>
      <button type="button" class="text-link" data-preview-style="${attr(style.name)}" ${keySet ? '' : 'disabled'}>${style.has_preview ? 'Regenerate example' : 'Generate example'}</button>
      ${source}<button type="button" class="text-link danger-link" data-delete-style="${attr(style.name)}">Delete</button>
    </div>
    <details class="edition-notes"><summary>Read the full studio prompt</summary><p class="prompt-copy">${esc(style.prompt)}</p><b>Avoid</b><p>${esc(style.avoid)}</p></details>`;
}

async function renderLibrary(token) {
  const data = await api('/api/styles');
  if (!routeIsCurrent(token)) return;
  const collections = [...new Set(data.styles.map(style => style.collection))].sort();
  app.innerHTML = shell('library', `
    <section class="director card">
      <div><div class="eyebrow">Your resident art director</div><h2>Let each day choose its own visual language</h2>
        <p>Responsive mode reads the day’s richness, timing, weather, balance, and first arrivals. Rotation stays available when you want pure variety; a house style overrides both.</p></div>
      <div class="director-mode"><span>Daily direction</span><div class="segmented">
        <button data-style-mode="responsive" class="${data.mode === 'responsive' ? 'active' : ''}">Responsive</button>
        <button data-style-mode="rotate" class="${data.mode === 'rotate' ? 'active' : ''}">Rotate</button>
        ${data.mode === 'pinned' ? '<button class="active" disabled>House style</button>' : ''}
      </div><small>${data.mode === 'pinned' ? 'One direction is pinned below.' : data.mode === 'responsive' ? 'The day and the style meet each other.' : 'Styles take a simple daily turn.'}</small></div>
    </section>
    <section class="library-head"><div><div class="eyebrow">Twenty-one ways of seeing</div><h2>The collection</h2><p>Historic lineages and contemporary data portraits, all grounded in the birds actually heard here.</p></div><button type="button" class="btn" id="newStyle">Create a direction</button></section>
    <div class="filter-bar library-filters"><label class="search"><input id="styleSearch" placeholder="Search lineage, medium, or feeling…" aria-label="Search styles"></label>
      <select id="collectionFilter"><option value="">Every collection</option>${collections.map(value => `<option>${esc(value)}</option>`).join('')}</select><span class="section-note" id="styleResult"></span></div>
    <div class="library-grid" id="styleGrid">${data.styles.map(styleCard).join('')}</div>
    <aside class="style-detail card" id="styleDetail" hidden></aside>
    <aside class="style-editor card" id="styleEditor" hidden>
      <div class="style-detail-head"><div><div class="eyebrow">Style DNA</div><h2 id="styleEditorTitle"></h2></div><button class="detail-close" type="button" data-cancel-style aria-label="Close">×</button></div>
      <form class="editor" id="styleForm">
        <div class="editor-pair"><label>Name<input id="styleName" required></label><label>Collection<input id="styleCollection" required></label></div>
        <label>Description<textarea id="styleDescription" rows="3" placeholder="What does this direction let us feel?"></textarea></label>
        <label>Historic lineage<input id="styleLineage"></label>
        <div class="editor-pair"><label>Medium<input id="styleMedium"></label><label>Palette<input id="stylePalette"></label></div>
        <label>Best with <input id="styleAffinities" placeholder="dawn-heavy, rain, species-rich"></label>
        <label>Collection source <input id="styleSource" type="url" placeholder="https://…"></label>
        <label>Prompt<textarea id="stylePrompt" rows="9" required></textarea><small>Include <code>{scene}</code>, which is filled with the real day.</small></label>
        <label>Avoid<textarea id="styleAvoid" rows="3"></textarea></label>
        <div class="button-row"><button class="btn" type="submit">Save direction</button><button class="btn secondary" type="button" data-cancel-style>Cancel</button><span class="section-note" id="styleMessage"></span></div>
      </form>
    </aside>`);
  const page = app.querySelector('.page');
  let editing = null;
  const filter = () => {
    const query = document.querySelector('#styleSearch').value.trim().toLowerCase();
    const collection = document.querySelector('#collectionFilter').value;
    let shown = 0;
    document.querySelectorAll('[data-style-card]').forEach(card => {
      const visible = (!query || card.dataset.search.includes(query)) && (!collection || card.dataset.collection === collection);
      card.hidden = !visible; if (visible) shown += 1;
    });
    document.querySelector('#styleResult').textContent = `${shown} directions`;
  };
  filter();
  document.querySelector('#styleSearch').addEventListener('input', filter);
  document.querySelector('#collectionFilter').addEventListener('change', filter);
  const openDetail = style => {
    document.querySelector('#styleEditor').hidden = true;
    const detail = document.querySelector('#styleDetail');
    detail.innerHTML = styleDetail(style, data.key_set); detail.hidden = false;
    detail.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  };
  const openEditor = style => {
    editing = style?.name || null;
    document.querySelector('#styleDetail').hidden = true;
    const editor = document.querySelector('#styleEditor'); editor.hidden = false;
    document.querySelector('#styleEditorTitle').textContent = style ? `Edit ${nice(style.name)}` : 'Create a direction';
    document.querySelector('#styleName').value = style?.name || '';
    document.querySelector('#styleCollection').value = style?.collection || 'Personal Studio';
    document.querySelector('#styleDescription').value = style?.description || '';
    document.querySelector('#styleLineage').value = style?.lineage || '';
    document.querySelector('#styleMedium').value = style?.medium || '';
    document.querySelector('#stylePalette').value = style?.palette || '';
    document.querySelector('#styleAffinities').value = style?.affinities?.join(', ') || '';
    document.querySelector('#styleSource').value = style?.source || '';
    document.querySelector('#stylePrompt').value = style?.prompt || 'A distinctive artwork depicting {scene}.';
    document.querySelector('#styleAvoid').value = style?.avoid || '';
    editor.scrollIntoView({behavior: 'smooth', block: 'start'});
  };
  document.querySelector('#newStyle').addEventListener('click', () => openEditor(null));
  document.querySelector('#styleForm').addEventListener('submit', async event => {
    event.preventDefault();
    const name = document.querySelector('#styleName').value.trim();
    const body = {
      name, collection: document.querySelector('#styleCollection').value,
      description: document.querySelector('#styleDescription').value,
      lineage: document.querySelector('#styleLineage').value,
      medium: document.querySelector('#styleMedium').value,
      palette: document.querySelector('#stylePalette').value,
      affinities: document.querySelector('#styleAffinities').value.split(',').map(item => item.trim()).filter(Boolean),
      source: document.querySelector('#styleSource').value,
      prompt: document.querySelector('#stylePrompt').value,
      avoid: document.querySelector('#styleAvoid').value,
    };
    try {
      const response = await fetch(`/api/styles/${encodeURIComponent(editing || name || 'style')}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save this direction');
      toast(`${nice(name)} saved.`); await renderLibrary(token);
    } catch (error) { document.querySelector('#styleMessage').textContent = error.message; }
  });
  page.addEventListener('click', async event => {
    const open = event.target.closest('[data-open-style]');
    if (open) openDetail(data.styles.find(style => style.name === open.dataset.openStyle));
    if (event.target.closest('[data-close-style]')) document.querySelector('#styleDetail').hidden = true;
    if (event.target.closest('[data-cancel-style]')) document.querySelector('#styleEditor').hidden = true;
    const edit = event.target.closest('[data-edit-style]');
    if (edit) openEditor(data.styles.find(style => style.name === edit.dataset.editStyle));
    const mode = event.target.closest('[data-style-mode]');
    if (mode) { await api(`/api/styles/mode/${mode.dataset.styleMode}`, {method: 'POST'}); toast('Daily art direction updated.'); await renderLibrary(token); }
    const pin = event.target.closest('[data-pin-style]');
    if (pin) {
      const style = data.styles.find(item => item.name === pin.dataset.pinStyle);
      await api(style.pinned ? '/api/styles/unpin' : `/api/styles/${encodeURIComponent(style.name)}/pin`, {method: 'POST'});
      toast(style.pinned ? 'Responsive art direction restored.' : `${nice(style.name)} is now the house style.`);
      await renderLibrary(token);
    }
    const preview = event.target.closest('[data-preview-style]');
    if (preview) {
      preview.disabled = true; preview.textContent = 'Painting example…';
      try { await api(`/api/styles/${encodeURIComponent(preview.dataset.previewStyle)}/preview`, {method: 'POST'}); toast('Example generation started. Return to the library in a moment.'); }
      catch (error) { preview.disabled = false; toast(error.message); }
    }
    const remove = event.target.closest('[data-delete-style]');
    if (remove && confirm(`Delete the “${nice(remove.dataset.deleteStyle)}” direction?`)) {
      try { await api(`/api/styles/${encodeURIComponent(remove.dataset.deleteStyle)}`, {method: 'DELETE'}); toast('Direction deleted.'); await renderLibrary(token); }
      catch (error) { toast(error.message); }
    }
  });
}

export async function renderPictures(token, subpage = 'editions', params = new URLSearchParams()) {
  const page = aliases[subpage] || subpage;
  if (page === 'reimagine') return renderReimagine(token, params);
  if (page === 'library') return renderLibrary(token);
  return renderEditions(token);
}
