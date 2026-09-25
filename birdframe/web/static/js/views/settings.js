import {api, app, esc, attr, ago, formBody, pageHeader, routeIsCurrent, toast, setListening} from '../core.js';

const ENUMS = {
  post_mode: ['daily', 'live', 'manual'],
  style_mode: ['responsive', 'rotate', 'pinned'],
  // xhigh and max exist only on the gpt-image-2.5 models; others fall back to high.
  image_quality: ['low', 'medium', 'high', 'xhigh', 'max'],
  image_provider: ['openai', 'gemini'],
};

// Free text (new models appear often) with the current ones one tap away.
const SUGGESTIONS = {
  openai_model: ['gpt-image-2.5-sunburst', 'gpt-image-2.5-flare', 'gpt-image-2', 'gpt-image-1.5'],
  gemini_model: ['gemini-3-pro-image', 'gemini-3.1-flash-image'],
};

const TIME_FIELDS = new Set(['live_window_start', 'live_window_end']);

function healthItem(ok, label, value) {
  return `<div class="health-item soft-card"><b><i class="health-dot ${ok ? '' : 'bad'}"></i>${esc(label)}</b><span>${esc(value)}</span></div>`;
}

// ── Posting schedule editor ──────────────────────────────────────────────────
// The config stores a plain string ("06:30 dawn, 12:00, 21:00 evening"); this
// widget is just a friendlier hand on the same value — a hidden input carries
// it through the ordinary settings save.

const SCHEDULE_PRESETS = [
  ['Once a day', '21:00 evening'],
  ['Twice a day', '08:00 morning, 20:00 evening'],
  ['Dawn to dusk', '06:30 dawn, 12:00 midday, 20:30 dusk'],
  ['Full day', '06:30 dawn, 12:00 midday, 15:30 afternoon, 18:30 evening, 21:00 dusk'],
];

function parseSchedule(value) {
  return (value || '').split(',').map(part => {
    const m = part.trim().match(/^(\d{1,2}):(\d{2})(?:\s+(.*\S))?$/);
    if (!m) return null;
    return {time: `${m[1].padStart(2, '0')}:${m[2]}`, label: m[3] || ''};
  }).filter(Boolean);
}

function serializeSchedule(slots) {
  return slots.map(s => (s.label ? `${s.time} ${s.label}` : s.time)).join(', ');
}

function scheduleRow(slot) {
  return `<div class="schedule-row">
    <input type="time" class="slot-time" value="${attr(slot.time)}" required>
    <input type="text" class="slot-label" value="${attr(slot.label)}" placeholder="label — dawn, midday…" maxlength="24">
    <button type="button" class="round-button slot-remove" title="Remove this time" aria-label="Remove this time">×</button>
  </div>`;
}

function scheduleEditor(value) {
  const slots = parseSchedule(value);
  if (!slots.length) slots.push({time: '21:00', label: 'evening'});
  return `<div class="field schedule-field"><div>
      <label for="scheduleRows">Posting schedule</label>
      <small>Applies live · each time paints the birds heard so far that day</small>
    </div>
    <div class="schedule-editor" id="scheduleEditor">
      <input type="hidden" data-key="post_times" id="postTimesValue" value="${attr(serializeSchedule(slots))}">
      <div class="schedule-presets">${SCHEDULE_PRESETS.map(([name, preset]) =>
        `<button type="button" class="preset-chip" data-preset="${attr(preset)}">${esc(name)}</button>`).join('')}</div>
      <div class="schedule-rows" id="scheduleRows">${slots.map(scheduleRow).join('')}</div>
      <div class="button-row">
        <button type="button" class="btn secondary small" id="addSlot">+ Add a time</button>
        <span class="section-note" id="scheduleSummary"></span>
      </div>
    </div>
  </div>`;
}

function wireScheduleEditor() {
  const editor = document.querySelector('#scheduleEditor');
  if (!editor) return;
  const rows = editor.querySelector('#scheduleRows');
  const hidden = editor.querySelector('#postTimesValue');
  const summary = editor.querySelector('#scheduleSummary');

  const currentSlots = () => [...rows.querySelectorAll('.schedule-row')].map(row => ({
    time: row.querySelector('.slot-time').value,
    label: row.querySelector('.slot-label').value.trim().replace(/,/g, ' '),
  })).filter(s => s.time);

  const sync = () => {
    const slots = currentSlots();
    hidden.value = serializeSchedule(slots);
    const times = slots.map(s => s.time);
    const dupes = times.filter((t, i) => times.indexOf(t) !== i);
    summary.textContent = dupes.length
      ? `Two posts share ${dupes[0]} — remove one.`
      : `${slots.length} post${slots.length === 1 ? '' : 's'} a day.`;
    rows.querySelectorAll('.slot-remove').forEach(btn => { btn.disabled = slots.length <= 1; });
    editor.querySelectorAll('.preset-chip').forEach(chip => {
      chip.classList.toggle('active', chip.dataset.preset === hidden.value);
    });
  };

  editor.addEventListener('click', event => {
    const preset = event.target.closest('.preset-chip');
    if (preset) {
      rows.innerHTML = parseSchedule(preset.dataset.preset).map(scheduleRow).join('');
      sync();
      return;
    }
    if (event.target.closest('#addSlot')) {
      rows.insertAdjacentHTML('beforeend', scheduleRow({time: '12:00', label: ''}));
      rows.lastElementChild.querySelector('.slot-time').focus();
      sync();
      return;
    }
    const remove = event.target.closest('.slot-remove');
    if (remove && !remove.disabled) { remove.closest('.schedule-row').remove(); sync(); }
  });
  editor.addEventListener('input', sync);
  sync();
}

function settingField(field) {
  const label = field.key.replaceAll('_', ' ');
  const note = field.restart ? 'Applies after restart' : 'Applies live';
  let control;
  if (ENUMS[field.key]) {
    // Keep an unexpected saved value visible; otherwise the browser would quietly
    // select the first option and the next save would change it.
    const current = String(field.value);
    const values = ENUMS[field.key].includes(current) ? ENUMS[field.key] : [current, ...ENUMS[field.key]];
    control = `<select id="setting-${attr(field.key)}" data-key="${attr(field.key)}">${values.map(value => `<option value="${attr(value)}" ${current === value ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select>`;
  } else if (field.key === 'post_times') {
    return scheduleEditor(field.value);
  } else if (SUGGESTIONS[field.key]) {
    control = `<input id="setting-${attr(field.key)}" type="text" data-key="${attr(field.key)}" value="${attr(field.value)}" list="options-${attr(field.key)}" autocapitalize="off" spellcheck="false">
      <datalist id="options-${attr(field.key)}">${SUGGESTIONS[field.key].map(value => `<option value="${attr(value)}">`).join('')}</datalist>`;
  } else {
    const type = typeof field.value === 'number' ? 'number' : TIME_FIELDS.has(field.key) ? 'time' : 'text';
    const step = typeof field.value === 'number' && !Number.isInteger(field.value) ? ' step="any"' : '';
    control = `<input id="setting-${attr(field.key)}" type="${type}" data-key="${attr(field.key)}" value="${attr(field.value)}"${step}>`;
  }
  return `<div class="field"><div><label for="setting-${attr(field.key)}">${esc(label)}</label><small>${note}</small></div><div>${control}</div></div>`;
}

function publicSiteCard(site) {
  if (!site?.enabled) {
    return `<section class="card card-pad" style="margin-top:18px"><div class="eyebrow">Public site</div>
      <h2 style="font:500 24px var(--serif)">Share the journal publicly</h2>
      <p class="muted">birdframe can build a read-only site of your paintings and birds, without audio, coordinates or doubtful birds, for any static host. Add <code>public_site_dir = "~/Sites/birdframe"</code> to config.toml and restart, or run <code>birdframe publish ~/Sites/birdframe</code>. To host it free on Cloudflare Pages, add <code>cloudflare_project</code> and <code>cloudflare_account_id</code> and store a token with <code>birdframe set-key cloudflare</code>.</p></section>`;
  }
  const when = stamp => esc(stamp.replace('T', ' ').slice(0, 16));
  const built = site.built_at ? `Last built ${when(site.built_at)} · ${site.paintings ?? 0} paintings, ${site.species ?? 0} birds` : 'Not built yet';
  const sent = site.host ? (site.deployed_at ? ` · sent to ${esc(site.host)} ${when(site.deployed_at)}` : ` · not yet sent to ${esc(site.host)}`) : '';
  const cadence = site.host
    ? `Rebuilt after each new painting and hourly otherwise; sent to ${esc(site.host)} with each new painting, and every few hours when the birds have changed.`
    : 'Rebuilt after each new painting and hourly otherwise.';
  return `<section class="card card-pad" style="margin-top:18px"><div class="section-head" style="margin-top:0"><div><div class="eyebrow">Public site</div>
      <h2>The journal, shared read-only</h2><p>${cadence}</p></div></div>
    <div class="button-row"><button type="button" class="btn secondary" id="publishSite">Publish now</button>
      ${site.url ? `<a class="btn secondary" href="${attr(site.url)}" target="_blank" rel="noopener">Open the public site ↗</a>` : ''}
      <span class="section-note" id="publishMessage">${site.running ? 'Publishing…' : site.error ? `Last attempt failed: ${esc(site.error)}` : built + sent}</span></div>
  </section>`;
}

export async function renderSettings(token) {
  const settings = await api('/api/settings');
  const health = await api('/api/health');
  const blocked = await api('/api/blocked');
  if (!routeIsCurrent(token)) return;
  setListening(health.listening, health.listening ? 'Listening' : health.status);
  const archiveMb = (health.archive_bytes / 1_048_576).toFixed(1);
  const backupMb = (health.backup_bytes / 1_048_576).toFixed(1);
  const audio = health.audio || {};
  const signal = audio.signal;
  const signalLabel = signal
    ? `${Number(signal.dynamic_rms_dbfs).toFixed(1)} dBFS changing signal`
    : 'waiting for a measured audio chunk';

  app.innerHTML = `<article class="page">
    ${pageHeader('Care and feeding', 'Settings', 'The journal’s controls live away from the act of exploration. Detection history is never changed by ordinary settings edits.')}
    <section class="card card-pad"><div class="section-head" style="margin-top:0"><div><div class="eyebrow">System health</div><h2>birdframe right now</h2></div></div>
      <div class="health-grid">
        ${healthItem(health.listening, 'Microphone', health.status)}
        ${healthItem(!audio.restart_required, 'Audio watchdog', `${audio.stream_restarts || 0} reconnects · ${audio.automatic_unmutes || 0} mute repairs · ${signalLabel}`)}
        ${healthItem(!audio.restart_required, 'Detector flow', audio.last_audio_chunk_ago_s == null ? 'waiting for first chunk' : `last audio chunk ${ago(audio.last_audio_chunk_ago_s)}`)}
        ${healthItem(true, 'Last detection', ago(health.last_detection_ago_s))}
        ${healthItem(health.openai_key_set, 'Image artist', health.openai_key_set ? `${health.image_model || 'paint model'} ready` : 'fallback poster mode')}
        ${healthItem(true, 'Local archive', `${archiveMb} MB`)}
        ${healthItem(health.backup_count > 0, 'Database backups', health.backup_count ? health.backup_count + ' snapshots · ' + backupMb + ' MB' : 'first snapshot pending')}
      </div>
    </section>

    ${publicSiteCard(health.public_site)}

    <section class="card card-pad" style="margin-top:18px"><div class="section-head" style="margin-top:0"><div><div class="eyebrow">Recovery</div><h2>Restore-ready database snapshots</h2><p>birdframe makes one consistent SQLite backup every day and keeps it for the configured retention period.</p></div></div>
      <div class="button-row"><button type="button" class="btn secondary" id="backupNow">Back up now</button><span class="section-note" id="backupMessage">${health.backup_latest ? 'Latest: ' + esc(health.backup_latest) : 'No snapshot yet.'}</span></div>
    </section>

    <form id="settingsForm" style="margin-top:18px">
      <div class="settings-groups">${settings.groups.map(group => `<section class="settings-group card"><h2>${esc(group.name)}</h2>${group.fields.map(settingField).join('')}</section>`).join('')}</div>
      <div class="button-row" style="margin-top:18px"><button type="submit" class="btn">Save settings</button><span class="section-note" id="settingsMessage"></span></div>
    </form>

    <div class="grid-2" style="margin-top:18px">
      <section class="card card-pad"><div class="eyebrow">Detection vetoes</div><h2 style="font:500 24px var(--serif)">Species marked “not here”</h2>
        <p class="muted">Vetoes stop future detection. The redesigned journal does not offer destructive history controls while exploring data.</p>
        <div class="blocked-list" id="blockedList">${blocked.blocked_species.length ? blocked.blocked_species.map(name => `<button type="button" class="blocked-chip" data-unblock="${attr(name)}" title="Allow future detections of ${attr(name)}">${esc(name)} ×</button>`).join('') : '<span class="faint">No species are blocked.</span>'}</div>
      </section>
      <section class="card card-pad"><div class="eyebrow">Artwork</div><h2 style="font:500 24px var(--serif)">Picture tools have their own room</h2>
        <p class="muted">Generate editions, manage visual styles, review the archive, and send a chosen picture to the shared frame.</p>
        <div class="button-row"><a class="btn secondary" href="#pictures/reimagine">Reimagine a day</a><a class="btn secondary" href="#pictures/library">Style library</a></div>
      </section>
    </div>
  </article>`;

  wireScheduleEditor();
  document.querySelector('#settingsForm').addEventListener('submit', async event => {
    event.preventDefault();
    const body = {};
    document.querySelectorAll('[data-key]').forEach(control => { body[control.dataset.key] = control.value; });
    const message = document.querySelector('#settingsMessage');
    message.textContent = 'Saving…';
    try {
      const result = await api('/api/settings', formBody(body));
      const count = result.saved.length;
      message.textContent = count
        ? `Saved ${count} ${count === 1 ? 'setting' : 'settings'}${result.restart_required?.length ? ` · restart needed for ${result.restart_required.join(', ').replaceAll('_', ' ')}` : ''}.`
        : 'Nothing had changed.';
      toast(count ? 'Settings saved.' : 'Settings unchanged.');
    } catch (error) { message.textContent = error.message; }
  });
  document.querySelector('#publishSite')?.addEventListener('click', async event => {
    const button = event.currentTarget, message = document.querySelector('#publishMessage');
    button.disabled = true; message.textContent = 'Publishing…';
    try {
      await api('/api/public/publish', {method: 'POST'});
      const poll = setInterval(async () => {
        const site = await api('/api/public').catch(() => null);
        if (!site || site.running) return;
        clearInterval(poll); button.disabled = false;
        message.textContent = site.error ? `Publishing failed: ${site.error}` : 'Published.';
        if (!site.error) toast('Public site published.');
      }, 1500);
    } catch (error) { button.disabled = false; message.textContent = error.message; }
  });
  document.querySelector('#backupNow').addEventListener('click', async event => {
    const button = event.currentTarget, message = document.querySelector('#backupMessage');
    button.disabled = true; message.textContent = 'Creating a consistent snapshot…';
    try {
      const result = await api('/api/backup', {method: 'POST'});
      message.textContent = 'Created ' + result.created + ' · ' + (result.bytes / 1_048_576).toFixed(1) + ' MB';
      toast('Database backup created.');
    } catch (error) { message.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.querySelector('#blockedList').addEventListener('click', async event => {
    const button = event.target.closest('[data-unblock]');
    if (!button) return;
    await api('/api/unblock', formBody({name: button.dataset.unblock}));
    button.remove(); toast(`${button.dataset.unblock} can be detected again.`);
  });
}
