import {esc, num, speciesHref, tierBadge, playButton, hourLabel} from './core.js';

export function stats(items) {
  return `<div class="stats">${items.map(item => `<div class="stat card">
    <b>${item.value}</b><span>${esc(item.label)}</span>
  </div>`).join('')}</div>`;
}

export function speciesRows(species, {countLabel = 'detections', showReasons = false} = {}) {
  if (!species?.length) return '<div class="empty">No species match this view.</div>';
  return `<div class="species-list">${species.map(s => {
    const count = s.count ?? s.total ?? 0;
    const first = s.first_heard ?? s.earliest;
    const last = s.last_heard ?? s.latest;
    const peak = s.peak_hour != null ? ` · peak ${hourLabel(s.peak_hour)}` : '';
    return `<article class="species-row" data-tier="${esc(s.tier)}">
      <div>
        <h3><a href="${speciesHref(s.common_name)}">${esc(s.common_name)}</a> ${playButton(s.clip_url, s.common_name)}</h3>
        <div class="scientific">${esc(s.scientific_name)}</div>
        <div class="species-tags">${tierBadge(s.tier, s.reasons)}${s.rarity ? `<span class="muted">${esc(s.rarity)}</span>` : ''}</div>
        ${showReasons && s.reasons?.length ? `<small class="faint">${esc(s.reasons.join(' · '))}</small>` : ''}
      </div>
      <div class="row-rhythm">${first || '—'}–${last || '—'}${peak}</div>
      <div class="row-count"><b>${num(count)}</b><small>${esc(countLabel)}</small></div>
    </article>`;
  }).join('')}</div>`;
}

export function clipCards(clips) {
  if (!clips?.length) return '<div class="empty">No saved recording for this view.</div>';
  return `<div class="clip-grid">${clips.map(clip => {
    const confidence = `${Math.round(Number(clip.confidence || 0) * 100)}%`;
    return `<div class="clip-card soft-card">
    ${playButton(clip.url, clip.common_name || clip.day, `${clip.day || ''} · confidence ${confidence}`)}
    <div><strong>${esc(clip.common_name || clip.day)}</strong>
      <small>${clip.day && clip.common_name ? `${esc(clip.day)} · ` : ''}${clip.at ? `${esc(clip.at)} · ` : ''}confidence ${confidence}</small></div>
  </div>`; }).join('')}</div>`;
}

export function reliabilityLegend() {
  return `<div class="button-row" aria-label="Reliability legend">
    ${tierBadge('confirmed')} ${tierBadge('probable')} ${tierBadge('tentative')}
    <span class="section-note">All stored detections remain visible; tiers describe evidence, not deletion.</span>
  </div>`;
}
