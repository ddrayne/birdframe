import {
  api, state, loading, errorView, initAudio, initLightbox, stopPolling, setListening,
} from './core.js';
import {renderToday} from './views/today.js';
import {renderJournal} from './views/journal.js';
import {renderSpecies} from './views/species.js';
import {renderPatterns} from './views/patterns.js';
import {renderPictures} from './views/pictures.js';
import {renderSettings} from './views/settings.js';
import {initChartTooltips} from './charts.js';

function parseRoute() {
  const raw = location.hash.slice(1) || 'today';
  const queryAt = raw.indexOf('?');
  const path = queryAt >= 0 ? raw.slice(0, queryAt) : raw;
  const query = queryAt >= 0 ? raw.slice(queryAt + 1) : '';
  let parts;
  try { parts = path.split('/').filter(Boolean).map(decodeURIComponent); }
  catch { parts = ['today']; }
  return {top: parts[0] || 'today', detail: parts[1] || null, params: new URLSearchParams(query)};
}

function markNavigation(top) {
  document.querySelectorAll('[data-nav]').forEach(link => link.classList.toggle('active', link.dataset.nav === top));
}

async function renderRoute() {
  stopPolling();
  const route = parseRoute();
  const valid = ['today', 'journal', 'species', 'patterns', 'pictures', 'settings'];
  if (!valid.includes(route.top)) { location.replace('#today'); return; }
  const token = ++state.routeToken;
  markNavigation(route.top);
  loading(route.top === 'species' && route.detail ? `Opening the ${route.detail} dossier…` : 'Reading the field journal…');
  window.scrollTo({top: 0, behavior: 'instant'});
  document.title = `${route.detail || route.top} · birdframe`;
  try {
    if (route.top === 'today') await renderToday(token);
    else if (route.top === 'journal') await renderJournal(token, route.detail);
    else if (route.top === 'species') await renderSpecies(token, route.detail, route.params);
    else if (route.top === 'patterns') await renderPatterns(token, route.params);
    else if (route.top === 'pictures') await renderPictures(token, route.detail || 'editions', route.params);
    else if (route.top === 'settings') await renderSettings(token);
    if (token === state.routeToken) {
      initChartTooltips(document);
      document.querySelector('#app')?.focus({preventScroll: true});
    }
  } catch (error) {
    if (token === state.routeToken) errorView(error, route.top === 'today' ? '#journal' : '#today');
  }
}

async function initialise() {
  initAudio();
  initLightbox();
  try {
    const health = await api('/api/health');
    setListening(health.listening, health.listening ? 'Listening' : health.status);
  } catch { setListening(false, 'Offline'); }
  await renderRoute();
}

window.addEventListener('hashchange', renderRoute);
initialise();
