import {api, app, esc, attr, ago, formBody, pageHeader, routeIsCurrent, toast, setListening} from '../core.js';

const ENUMS = {
  post_mode: ['daily', 'live', 'manual'],
  style_mode: ['responsive', 'rotate', 'pinned'],
  image_quality: ['low', 'medium', 'high'],
  image_provider: ['openai', 'gemini'],
};

function healthItem(ok, label, value) {
  return `<div class="health-item soft-card"><b><i class="health-dot ${ok ? '' : 'bad'}"></i>${esc(label)}</b><span>${esc(value)}</span></div>`;
}

function settingField(field) {
  const label = field.key.replaceAll('_', ' ');
  const note = field.restart ? 'Applies after restart' : 'Applies live';
  let control;
  if (ENUMS[field.key]) {
    control = `<select id="setting-${attr(field.key)}" data-key="${attr(field.key)}">${ENUMS[field.key].map(value => `<option value="${attr(value)}" ${String(field.value) === value ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select>`;
  } else {
    const type = typeof field.value === 'number' ? 'number' : field.key.includes('time') ? 'time' : 'text';
    const step = typeof field.value === 'number' && !Number.isInteger(field.value) ? ' step="any"' : '';
    control = `<input id="setting-${attr(field.key)}" type="${type}" data-key="${attr(field.key)}" value="${attr(field.value)}"${step}>`;
  }
  return `<div class="field"><div><label for="setting-${attr(field.key)}">${esc(label)}</label><small>${note}</small></div><div>${control}</div></div>`;
}

export async function renderSettings(token) {
  const settings = await api('/api/settings');
  const health = await api('/api/health');
  const blocked = await api('/api/blocked');
  if (!routeIsCurrent(token)) return;
  setListening(health.listening, health.listening ? 'Listening' : health.status);
  const archiveMb = (health.archive_bytes / 1_048_576).toFixed(1);
  const backupMb = (health.backup_bytes / 1_048_576).toFixed(1);

  app.innerHTML = `<article class="page">
    ${pageHeader('Care and feeding', 'Settings', 'The journal’s controls live away from the act of exploration. Detection history is never changed by ordinary settings edits.')}
    <section class="card card-pad"><div class="section-head" style="margin-top:0"><div><div class="eyebrow">System health</div><h2>birdframe right now</h2></div></div>
      <div class="health-grid">
        ${healthItem(health.listening, 'Microphone', health.status)}
        ${healthItem(true, 'Last detection', ago(health.last_detection_ago_s))}
        ${healthItem(health.openai_key_set, 'Image artist', health.openai_key_set ? 'paint model ready' : 'fallback poster mode')}
        ${healthItem(true, 'Local archive', `${archiveMb} MB`)}
        ${healthItem(health.backup_count > 0, 'Database backups', health.backup_count ? health.backup_count + ' snapshots · ' + backupMb + ' MB' : 'first snapshot pending')}
      </div>
    </section>

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

  document.querySelector('#settingsForm').addEventListener('submit', async event => {
    event.preventDefault();
    const body = {};
    document.querySelectorAll('[data-key]').forEach(control => { body[control.dataset.key] = control.value; });
    const message = document.querySelector('#settingsMessage');
    message.textContent = 'Saving…';
    try {
      const result = await api('/api/settings', formBody(body));
      message.textContent = `Saved ${result.saved.length} settings${result.restart_required?.length ? ` · restart needed for ${result.restart_required.join(', ')}` : ''}.`;
      toast('Settings saved.');
    } catch (error) { message.textContent = error.message; }
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
