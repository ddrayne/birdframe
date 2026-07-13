import {
  api, app, attr, esc, clearCache, formBody, pageHeader, routeIsCurrent, toast,
} from '../core.js';

function shell(active, content) {
  return `<article class="page">
    ${pageHeader('The visual diary', 'Pictures', 'The daily artwork belongs to the journal, while making, reviewing, and sending pictures remain deliberate actions.')}
    <nav class="subnav" aria-label="Picture tools">
      <a class="${active === 'gallery' ? 'active' : ''}" href="#pictures/gallery">Gallery</a>
      <a class="${active === 'make' ? 'active' : ''}" href="#pictures/make">Make a picture</a>
      <a class="${active === 'styles' ? 'active' : ''}" href="#pictures/styles">Art styles</a>
    </nav>${content}</article>`;
}

function galleryItems(images) {
  if (!images.length) return '<div class="empty">No pictures in this view yet.</div>';
  return `<div class="gallery-grid">${images.map(image => {
    const species = image.species?.join(', ') || 'A quiet day';
    const caption = `${image.generated_at.slice(0, 10)} · ${image.style} · ${species}`;
    return `<figure class="gallery-item">
      <button type="button" class="image-button" data-lightbox="/api/image/${image.id}" data-alt="${attr(image.style)} birdframe artwork" data-caption="${attr(caption)}"><img loading="lazy" src="/api/image/${image.id}" alt="${attr(image.style)} birdframe artwork"></button>
      <figcaption><strong>${esc(image.generated_at.slice(0, 10))} · ${esc(image.style)}</strong>${esc(species)}
        ${image.on_frame ? '<span class="on-frame">On the frame now</span>' : ''}
        <button type="button" class="text-link" style="display:block;margin-top:6px" data-send-image="${image.id}">Send to frame →</button>
      </figcaption>
    </figure>`;
  }).join('')}</div>`;
}

async function sendImage(id, button) {
  button.disabled = true;
  button.textContent = 'Sending…';
  try {
    await api(`/api/post/${id}`, {method: 'POST'});
    const poll = setInterval(async () => {
      const status = await api('/api/post/status').catch(() => null);
      if (!status || status.state === 'running') return;
      clearInterval(poll);
      button.disabled = false;
      button.textContent = 'Send to frame →';
      if (status.publish === 'posted') toast('Picture accepted by the frame. The e-ink refresh takes about 30 seconds.');
      else if (status.publish === 'held') toast('The shared frame is currently held by someone else.');
      else toast(`The frame could not be reached${status.detail ? `: ${status.detail}` : '.'}`);
    }, 1500);
  } catch (error) {
    button.disabled = false; button.textContent = 'Send to frame →'; toast(error.message);
  }
}

async function renderGallery(token) {
  const data = await api('/api/history');
  if (!routeIsCurrent(token)) return;
  app.innerHTML = shell('gallery', `<div class="filter-bar" style="margin-bottom:18px"><div class="segmented" id="galleryFilter"><button class="active" data-filter="all">All pictures</button><button data-filter="posted">Sent to frame</button></div><span class="section-note">${data.images.length} archived pictures</span></div><div id="galleryHost">${galleryItems(data.images)}</div>`);
  const page = app.querySelector('.page');
  document.querySelector('#galleryFilter').addEventListener('click', event => {
    const button = event.target.closest('button[data-filter]');
    if (!button) return;
    document.querySelectorAll('#galleryFilter button').forEach(el => el.classList.toggle('active', el === button));
    const rows = button.dataset.filter === 'posted' ? data.images.filter(image => image.posted_at) : data.images;
    document.querySelector('#galleryHost').innerHTML = galleryItems(rows);
  });
  page.addEventListener('click', event => {
    const button = event.target.closest('[data-send-image]');
    if (button) sendImage(button.dataset.sendImage, button);
  }, {once: false});
}

async function renderMake(token) {
  const styles = await api('/api/styles');
  if (!routeIsCurrent(token)) return;
  app.innerHTML = shell('make', `<div class="studio-layout">
    <section class="studio-panel card"><div class="eyebrow">A deliberate edition</div><h2>Paint today’s birds</h2>
      <p>Choose a style and create a fresh picture from today’s well-supported species. It enters the Gallery for review and is not sent to the shared frame automatically.</p>
      <label class="editor">Art style<select id="makeStyle"><option value="">Daily rotation</option>${styles.styles.map(style => `<option value="${attr(style.name)}">${esc(style.name)}${style.pinned ? ' · pinned' : ''}</option>`).join('')}</select></label>
      <div class="button-row" style="margin-top:18px"><button type="button" class="btn" id="makePicture" ${styles.key_set ? '' : 'disabled'}>Generate picture</button><span class="section-note" id="makeStatus">${styles.key_set ? 'A high-quality image usually takes around two minutes.' : 'Set an OpenAI key to use image generation.'}</span></div>
      <div id="makePreview"></div>
    </section>
    <aside class="story-card card"><div class="eyebrow">The safety rule</div><blockquote>Pictures can be remade. Detections remain untouched.</blockquote><small>The Studio reads today’s roll call; it never edits the listening archive.</small></aside>
  </div>`);
  document.querySelector('#makePicture')?.addEventListener('click', async event => {
    const button = event.currentTarget, status = document.querySelector('#makeStatus');
    button.disabled = true; status.textContent = 'Sending the scene to the artist…';
    try {
      const style = document.querySelector('#makeStyle').value;
      await api('/api/generate', formBody({style}));
      const started = Date.now();
      const poll = setInterval(async () => {
        const job = await api('/api/generate/status').catch(() => null);
        if (!job || job.state === 'running') { status.textContent = `Painting… ${Math.round((Date.now() - started) / 1000)}s`; return; }
        clearInterval(poll); button.disabled = false;
        if (job.state === 'done') {
          status.textContent = 'Picture ready in the Gallery.';
          document.querySelector('#makePreview').innerHTML = `<button type="button" class="image-button" style="border:0;background:none;padding:0" data-lightbox="/api/image/${job.image_id}" data-caption="New birdframe picture"><img style="max-width:320px;border-radius:13px;margin-top:20px" src="/api/image/${job.image_id}" alt="New birdframe picture"></button>`;
        } else status.textContent = `Could not generate: ${job.result || job.state}`;
      }, 1800);
    } catch (error) { button.disabled = false; status.textContent = error.message; }
  });
}

function styleItem(style) {
  return `<article class="style-item soft-card">
    ${style.has_preview ? `<img loading="lazy" src="/api/styles/${attr(style.name)}/preview.png" alt="${attr(style.name)} example">` : '<div class="style-placeholder">♧</div>'}
    <div><h3>${esc(style.name)} ${style.pinned ? '<span class="tier tier-confirmed">pinned</span>' : ''}</h3><p>${esc(style.prompt)}</p>
      <div class="button-row"><button type="button" class="btn secondary small" data-edit-style="${attr(style.name)}">Edit</button>
      <button type="button" class="btn secondary small" data-pin-style="${attr(style.name)}">${style.pinned ? 'Unpin' : 'Pin'}</button>
      <button type="button" class="text-link" data-preview-style="${attr(style.name)}">Generate example</button>
      <button type="button" class="text-link" style="color:var(--red)" data-delete-style="${attr(style.name)}">Delete</button></div>
    </div>
  </article>`;
}

async function renderStyles(token) {
  const data = await api('/api/styles');
  if (!routeIsCurrent(token)) return;
  app.innerHTML = shell('styles', `<div class="studio-layout">
    <section><div class="section-head" style="margin-top:0"><div><h2>Art direction</h2><p>Markdown-backed styles remain editable without a frontend build.</p></div><button type="button" class="btn" id="newStyle">New style</button></div><div class="style-list">${data.styles.map(styleItem).join('')}</div></section>
    <aside class="studio-panel card" id="styleEditor"><div class="eyebrow">Style editor</div><h2 id="styleEditorTitle">Choose a style</h2><p id="styleEditorIntro">Edit an existing direction or start a new one. The prompt must include <code>{scene}</code>.</p><form class="editor" id="styleForm" hidden>
      <label>Name<input id="styleName" required></label><label>Prompt<textarea id="stylePrompt" rows="8" required></textarea></label><label>Avoid<textarea id="styleAvoid" rows="3"></textarea></label>
      <div class="button-row"><button class="btn" type="submit">Save style</button><button class="btn secondary" type="button" id="cancelStyle">Cancel</button></div><span class="section-note" id="styleMessage"></span>
    </form></aside>
  </div>`);
  const page = app.querySelector('.page');
  const form = document.querySelector('#styleForm');
  let editing = null;
  const openEditor = style => {
    editing = style?.name || null; form.hidden = false;
    document.querySelector('#styleEditorTitle').textContent = style ? `Edit ${style.name}` : 'New art style';
    document.querySelector('#styleName').value = style?.name || '';
    document.querySelector('#stylePrompt').value = style?.prompt || 'A distinctive artwork depicting {scene}.';
    document.querySelector('#styleAvoid').value = style?.avoid || '';
    document.querySelector('#styleName').focus();
  };
  document.querySelector('#newStyle').addEventListener('click', () => openEditor(null));
  document.querySelector('#cancelStyle').addEventListener('click', () => { form.hidden = true; editing = null; });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const name = document.querySelector('#styleName').value.trim();
    const body = {name, prompt: document.querySelector('#stylePrompt').value, avoid: document.querySelector('#styleAvoid').value};
    try {
      const response = await fetch(`/api/styles/${encodeURIComponent(editing || name || 'style')}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save style');
      clearCache('/api/styles'); toast(`${name} saved.`); await renderStyles(token);
    } catch (error) { document.querySelector('#styleMessage').textContent = error.message; }
  });
  page.addEventListener('click', async event => {
    const edit = event.target.closest('[data-edit-style]');
    if (edit) openEditor(data.styles.find(style => style.name === edit.dataset.editStyle));
    const pin = event.target.closest('[data-pin-style]');
    if (pin) {
      const style = data.styles.find(item => item.name === pin.dataset.pinStyle);
      await api(style.pinned ? '/api/styles/unpin' : `/api/styles/${encodeURIComponent(style.name)}/pin`, {method: 'POST'});
      await renderStyles(token);
    }
    const preview = event.target.closest('[data-preview-style]');
    if (preview) {
      preview.disabled = true; preview.textContent = 'Painting example…';
      try {
        await api(`/api/styles/${encodeURIComponent(preview.dataset.previewStyle)}/preview`, {method: 'POST'});
        toast('Example generation started. Reopen Styles in a moment to see it.');
      } catch (error) { toast(error.message); }
    }
    const remove = event.target.closest('[data-delete-style]');
    if (remove && confirm(`Delete the “${remove.dataset.deleteStyle}” art style?`)) {
      try {
        await api(`/api/styles/${encodeURIComponent(remove.dataset.deleteStyle)}`, {method: 'DELETE'});
        toast(`${remove.dataset.deleteStyle} deleted.`); await renderStyles(token);
      } catch (error) { toast(error.message); }
    }
  });
}

export async function renderPictures(token, subpage = 'gallery') {
  if (subpage === 'make') return renderMake(token);
  if (subpage === 'styles') return renderStyles(token);
  return renderGallery(token);
}
