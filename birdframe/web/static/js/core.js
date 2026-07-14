export const app = document.querySelector('#app');

export const state = {
  routeToken: 0,
  caches: new Map(),
  todayTimer: null,
};

export async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body = null;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    throw new Error(body?.error || body?.detail || `Request failed (${response.status})`);
  }
  return body;
}

export async function cachedApi(path, ttl = 30_000) {
  const cached = state.caches.get(path);
  if (cached && Date.now() - cached.at < ttl) return cached.value;
  const value = await api(path);
  state.caches.set(path, {at: Date.now(), value});
  return value;
}

export function clearCache(prefix = '') {
  [...state.caches.keys()].forEach(key => { if (key.startsWith(prefix)) state.caches.delete(key); });
}

export const esc = value => String(value ?? '').replace(/[&<>"]/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;',
}[char]));

export const attr = value => esc(value).replace(/'/g, '&#39;');
export const num = value => Number(value || 0).toLocaleString();
export const percent = (value, digits = 0) => `${(Number(value || 0) * 100).toFixed(digits)}%`;
export const pad = value => String(value).padStart(2, '0');

export function dateLabel(day, style = 'long') {
  if (!day) return '—';
  const date = new Date(`${day}T12:00:00`);
  const opts = style === 'short'
    ? {month: 'short', day: 'numeric'}
    : {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'};
  return new Intl.DateTimeFormat('en-GB', opts).format(date);
}

export function relativeDay(day) {
  const today = new Date();
  const value = new Date(`${day}T12:00:00`);
  const delta = Math.round((today.setHours(12, 0, 0, 0) - value) / 86_400_000);
  if (delta === 0) return 'Today';
  if (delta === 1) return 'Yesterday';
  return dateLabel(day);
}

export function ago(seconds) {
  if (seconds == null) return 'not yet';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function hourLabel(hour) {
  const h = Number(hour);
  return `${h % 12 || 12}${h < 12 ? 'am' : 'pm'}`;
}

export function speciesHref(name, query = '') {
  return `#species/${encodeURIComponent(name)}${query}`;
}

export function speciesLink(name, scientific = '', extra = '') {
  return `<a class="species-link ${extra}" href="${speciesHref(name)}" title="Open ${attr(name)} dossier">
    ${esc(name)}${scientific ? `<span class="sr-only">, ${esc(scientific)}</span>` : ''}</a>`;
}

export function tierBadge(tier, reasons = []) {
  const why = Array.isArray(reasons) && reasons.length ? ` · ${reasons.join(', ')}` : '';
  return `<span class="tier tier-${attr(tier)}" title="${attr(tier + why)}">${esc(tier)}</span>`;
}

export function playButton(url, title, meta = 'Your window recording', className = 'round-button') {
  if (!url) return '';
  const label = className.includes('listen-button') ? '▶ Play' : '▶';
  return `<button type="button" class="${attr(className)}" data-audio="${attr(url)}"
    data-audio-title="${attr(title)}" data-audio-meta="${attr(meta)}" aria-label="Play ${attr(title)}">${label}</button>`;
}

export function pageHeader(eyebrow, title, description, actions = '') {
  return `<header class="page-head">
    <div><div class="eyebrow">${esc(eyebrow)}</div><h1>${title}</h1>${description ? `<p>${description}</p>` : ''}</div>
    ${actions ? `<div>${actions}</div>` : ''}
  </header>`;
}

export function loading(message = 'Reading the journal…') {
  app.innerHTML = `<div class="loading-page" role="status"><span class="wingbeat"></span><p>${esc(message)}</p></div>`;
}

export function errorView(error, back = '#today') {
  app.innerHTML = `<section class="error-page page"><div class="eyebrow">A quiet patch</div>
    <h1>That page could not be opened.</h1><p class="muted">${esc(error?.message || error)}</p>
    <p><a class="btn secondary" href="${attr(back)}">Return to the journal</a></p></section>`;
}

let toastTimer = null;
export function toast(message, duration = 4200) {
  const el = document.querySelector('#toast');
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, duration);
}

export function setListening(ok, label = 'Listening') {
  const el = document.querySelector('#listenStatus');
  el.classList.toggle('problem', !ok);
  el.querySelector('span').textContent = label;
}

const audio = new Audio();
let activeAudioButton = null;

function resetAudioButton() {
  if (activeAudioButton) {
    activeAudioButton.classList.remove('playing');
    activeAudioButton.textContent = activeAudioButton.classList.contains('listen-button') ? '▶ Play' : '▶';
  }
  activeAudioButton = null;
}

export function initAudio() {
  const dock = document.querySelector('#audioDock');
  const toggle = document.querySelector('#audioToggle');
  const close = document.querySelector('#audioClose');
  const progress = document.querySelector('#audioProgress');

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-audio]');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    const same = activeAudioButton === button;
    if (same && !audio.paused) {
      audio.pause();
      return;
    }
    resetAudioButton();
    activeAudioButton = button;
    audio.src = button.dataset.audio;
    document.querySelector('#audioTitle').textContent = button.dataset.audioTitle || 'Bird recording';
    document.querySelector('#audioMeta').textContent = button.dataset.audioMeta || 'Your window';
    dock.hidden = false;
    button.classList.add('playing');
    button.textContent = button.classList.contains('listen-button') ? 'Ⅱ Pause' : 'Ⅱ';
    audio.play().catch(() => toast('That recording could not be played.'));
  });

  audio.addEventListener('play', () => {
    toggle.textContent = 'Ⅱ';
    toggle.setAttribute('aria-label', 'Pause recording');
  });
  audio.addEventListener('pause', () => {
    toggle.textContent = '▶';
    toggle.setAttribute('aria-label', 'Resume recording');
    if (activeAudioButton) activeAudioButton.textContent = activeAudioButton.classList.contains('listen-button') ? '▶ Play' : '▶';
  });
  audio.addEventListener('timeupdate', () => {
    progress.style.width = audio.duration ? `${audio.currentTime / audio.duration * 100}%` : '0';
  });
  audio.addEventListener('ended', () => {
    resetAudioButton();
    dock.hidden = true;
  });
  toggle.addEventListener('click', () => audio.paused ? audio.play() : audio.pause());
  close.addEventListener('click', () => {
    audio.pause(); audio.removeAttribute('src'); resetAudioButton(); dock.hidden = true;
  });
}

export async function sendImageToFrame(id, button) {
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

export function openLightbox(src, caption, imageAlt = '') {
  const box = document.querySelector('#lightbox');
  document.querySelector('#lightboxImage').src = src;
  document.querySelector('#lightboxImage').alt = imageAlt;
  document.querySelector('#lightboxCaption').innerHTML = caption;
  // Any archived image can go to the frame straight from the viewer.
  const send = document.querySelector('#lightboxSend');
  const archived = /^\/api\/image\/(\d+)$/.exec(src);
  send.hidden = !archived;
  if (archived) send.dataset.sendImage = archived[1];
  box.hidden = false;
  document.body.style.overflow = 'hidden';
}

export function closeLightbox() {
  document.querySelector('#lightbox').hidden = true;
  document.body.style.overflow = '';
}

export function initLightbox() {
  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-lightbox]');
    if (trigger) {
      event.preventDefault();
      openLightbox(trigger.dataset.lightbox, trigger.dataset.caption || '', trigger.dataset.alt || '');
    }
    const send = event.target.closest('#lightboxSend');
    if (send) { sendImageToFrame(send.dataset.sendImage, send); return; }
    if (event.target.closest('[data-action="close-lightbox"]') || event.target.id === 'lightbox') closeLightbox();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeLightbox(); });
}

export function stopPolling() {
  if (state.todayTimer) clearInterval(state.todayTimer);
  state.todayTimer = null;
}

export function routeIsCurrent(token) { return token === state.routeToken; }

export function formBody(data) {
  return {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)};
}
