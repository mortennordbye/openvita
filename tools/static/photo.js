// Photo in the workbench: the person's photos from their OpenSelf profile (photos/, see SPEC section
// 2, Photos), and an editor that fits one to an audience: crop, straighten, colours, background.
// Everything is computed here on a canvas, no AI and no libraries; the server only stores the
// original, the result and the recipe (openself.web.api photo_*). Loaded before the page's inline
// script, so this file only declares functions; they use the page's helpers ($, el, icon, toast,
// target, tree, LANG, drawPath) when called.

const PH_T = {
  en: {
    photos: 'Photos', edits: 'Edits', add: 'Add photo', crop: 'Crop', colors: 'Colours', background: 'Background', save: 'Save',
    free: 'Free', rotate: 'Straighten', flip: 'Mirror', brightness: 'Brightness', contrast: 'Contrast', saturation: 'Saturation',
    warmth: 'Warmth', sharpen: 'Sharpness', keep: 'Keep', color: 'Colour', blur: 'Blur', tolerance: 'Reach', soft: 'Soft edge',
    blurAmount: 'Blur amount', showMask: 'Show what counts as background', name: 'Name', note: 'What is it for?',
    notePh: 'e.g. lighter, for the bank', size: 'Size', useInCv: 'Use in CVs (the profile\'s photo)', saveBtn: 'Save edit',
    reset: 'Reset', inUse: 'in CVs', use: 'Use in CVs', remove: 'Delete', original: 'original', editOf: 'edit of {0}',
    empty: 'No photos in the profile yet. Add one you already have; the original is kept as it is and every edit is saved next to it.',
    unsaved: 'Unsaved changes', ready: 'Photo editor', saved: 'Saved {0}', added: 'Added {0}', removed: 'Deleted {0}',
    nowUsed: '{0} is now the photo in CVs', overwrite: 'There is already an edit named {0}. Replace it?',
    confirmRemove: 'Delete {0}? It stays in the profile\'s history.', shrunk: 'Large photo: stored at {0} px on the long side',
    leave: 'You have unsaved changes in the photo editor.', badName: 'A name is lower-case letters, digits and -',
    newEdit: 'New edit from this photo', bgHint: 'Works best on a plain background. Raise Reach until the wall is covered, lower it if it eats into hair or clothes.',
    cvHint: 'New drafts use the profile\'s photo. In a CV you edit by hand: <img src="profile:{0}">',
  },
  nb: {
    photos: 'Bilder', edits: 'Redigeringer', add: 'Legg til bilde', crop: 'Beskjær', colors: 'Farger', background: 'Bakgrunn', save: 'Lagre',
    free: 'Fri', rotate: 'Rett opp', flip: 'Speilvend', brightness: 'Lysstyrke', contrast: 'Kontrast', saturation: 'Metning',
    warmth: 'Varme', sharpen: 'Skarphet', keep: 'Behold', color: 'Farge', blur: 'Uskarp', tolerance: 'Rekkevidde', soft: 'Myk kant',
    blurAmount: 'Uskarphet', showMask: 'Vis hva som regnes som bakgrunn', name: 'Navn', note: 'Hva er den til?',
    notePh: 'f.eks. lysere, til banken', size: 'Størrelse', useInCv: 'Bruk i CV-er (profilens bilde)', saveBtn: 'Lagre redigering',
    reset: 'Tilbakestill', inUse: 'i CV-er', use: 'Bruk i CV-er', remove: 'Slett', original: 'original', editOf: 'redigering av {0}',
    empty: 'Ingen bilder i profilen ennå. Legg til et du allerede har; originalen beholdes som den er, og hver redigering lagres ved siden av.',
    unsaved: 'Ulagrede endringer', ready: 'Bilderedigering', saved: 'Lagret {0}', added: 'La til {0}', removed: 'Slettet {0}',
    nowUsed: '{0} er nå bildet i CV-ene', overwrite: 'Det finnes allerede en redigering som heter {0}. Erstatte den?',
    confirmRemove: 'Slette {0}? Det blir liggende i profilens historikk.', shrunk: 'Stort bilde: lagret med {0} px på langsiden',
    leave: 'Du har ulagrede endringer i bilderedigeringen.', badName: 'Et navn er små bokstaver, tall og -',
    newEdit: 'Ny redigering fra dette bildet', bgHint: 'Virker best på ensfarget bakgrunn. Øk Rekkevidde til veggen er dekket, senk den hvis den spiser av hår eller klær.',
    cvHint: 'Nye utkast bruker profilens bilde. I en CV du redigerer selv: <img src="profile:{0}">',
  },
};
const pt = (k, ...a) => { let s = (PH_T[LANG] || PH_T.en)[k] ?? PH_T.en[k] ?? k; a.forEach((v, i) => { s = s.split('{' + i + '}').join(v); }); return s; };

const PH_FORMAT = 'openself-photo-edit-1';
const PH_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;
const PH_MAX_ORIGINAL = 2400;   // px on the long side; larger photos are stored smaller (every version goes into profile.age)
const PH_PREVIEW = 760;         // px on the long side of the live preview
const PH_ASPECTS = [['1:1', 1], ['4:5', 4 / 5], ['3:4', 3 / 4], ['free', 0]];
const PH_SWATCHES = ['#ffffff', '#eef1f5', '#dfe6ee', '#e9e4dc', '#cfd8e3', '#3b4250', '#1f2430'];
const PH_ADJUST = ['brightness', 'contrast', 'saturation', 'warmth', 'sharpen'];

let ph = null;  // the open editor: {c, box, data, version, img, work, origName, name, recipe, aspect, dirty, showMask, ...}

function phActive() {
  if (!target.endsWith('/photo')) return false;
  const t = tree.find(x => x.person === target.split('/')[0]);
  return !!t && t.profile === 'profile';
}
function phLeave() { ph = null; $('view').classList.remove('phmode'); }
window.addEventListener('beforeunload', e => { if (ph && ph.dirty) { e.preventDefault(); e.returnValue = pt('leave'); } });

// ---- server ---------------------------------------------------------------------------------

async function phList(c) { return (await fetch('/photo-list?' + q({ c }), { cache: 'no-store' })).json(); }
const phUrl = (c, f, v) => '/photo-file?' + q({ c, f, v: v || '' });
async function phPost(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ c: ph.c }, body)) });
  let j = {}; try { j = await r.json(); } catch (e) { j = { ok: false, message: 'Bad answer from the server' }; }
  return j;
}
const phDataUrl = blob => new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = bad; r.readAsDataURL(blob); });
const phBlob = (canvas, type, quality) => new Promise(ok => canvas.toBlob(ok, type, quality));

// ---- the view -------------------------------------------------------------------------------

async function photoTick() {
  const c = target.split('/')[0];
  if (!ph || ph.c !== c || !$('view').querySelector('.ph')) await phMount(c);
  const d = await phList(c);
  if (!ph || ph.c !== c || !d.ok) return;
  if (d.version !== ph.version) { ph.data = d; ph.version = d.version; phDrawLists(); }
}

async function phMount(c) {
  const box = el('div', 'ph');
  ph = { c, box, data: null, version: '', img: null, work: null, origName: '', name: '', recipe: null, aspect: 4 / 5,
         dirty: false, showMask: false, editing: '' };
  $('view').classList.add('phmode'); $('view').replaceChildren(box);
  $('dot').className = 'dot'; $('msg').textContent = pt('ready'); $('hits').textContent = '';
  try { const d = await (await fetch('/doc?' + q({ t: target }), { cache: 'no-store' })).json(); drawPath((d.files || []).map(f => ['', f]), d.root); } catch (e) { /* the path bar is a convenience */ }
  box.innerHTML = `
    <div class="ph-stage"><div class="ph-out"><canvas class="ph-canvas"></canvas><div class="ph-empty" hidden></div></div></div>
    <div class="ph-side">
      <section class="ph-sec"><h3>${pt('photos')}</h3><div class="ph-thumbs ph-orig"></div>
        <label class="btn ph-add"><input type="file" accept="image/jpeg,image/png,image/webp" hidden>${pt('add')}</label></section>
      <section class="ph-sec ph-editsec"><h3>${pt('edits')}</h3><div class="ph-edits"></div></section>
      <div class="ph-tools" hidden>
        <section class="ph-sec"><h3>${pt('crop')}</h3><div class="ph-cropbox"><canvas class="ph-src"></canvas><div class="ph-rect"><i data-h="nw"></i><i data-h="ne"></i><i data-h="sw"></i><i data-h="se"></i></div></div>
          <div class="ph-seg ph-aspects"></div>
          <div class="ph-row"><button class="btn ph-rl" title="-90°">↺ 90°</button><label class="ph-sl"><span>${pt('rotate')} <b class="ph-v" data-v="rotate"></b></span><input type="range" min="-45" max="45" step="0.5" data-k="rotate"></label><button class="btn ph-rr" title="+90°">↻ 90°</button></div>
          <label class="ph-check"><input type="checkbox" data-k="flip"> ${pt('flip')}</label></section>
        <section class="ph-sec"><h3>${pt('colors')}</h3>${PH_ADJUST.map(k => `<label class="ph-sl"><span>${pt(k)} <b class="ph-v" data-v="${k}"></b></span><input type="range" min="-100" max="100" step="1" data-a="${k}"></label>`).join('')}</section>
        <section class="ph-sec"><h3>${pt('background')}</h3><div class="ph-seg ph-modes"></div>
          <div class="ph-bgopts">
            <div class="ph-swatches"></div>
            <label class="ph-sl ph-o-color ph-o-blur"><span>${pt('tolerance')} <b class="ph-v" data-v="tolerance"></b></span><input type="range" min="0" max="100" step="1" data-b="tolerance"></label>
            <label class="ph-sl ph-o-color ph-o-blur"><span>${pt('soft')} <b class="ph-v" data-v="soft"></b></span><input type="range" min="0" max="100" step="1" data-b="soft"></label>
            <label class="ph-sl ph-o-blur"><span>${pt('blurAmount')} <b class="ph-v" data-v="blur"></b></span><input type="range" min="0" max="100" step="1" data-b="blur"></label>
            <label class="ph-check"><input type="checkbox" class="ph-mask"> ${pt('showMask')}</label>
            <p class="ph-hint">${pt('bgHint')}</p></div></section>
        <section class="ph-sec"><h3>${pt('save')}</h3>
          <label class="ph-field"><span>${pt('name')}</span><input class="ph-name" spellcheck="false"></label>
          <label class="ph-field"><span>${pt('note')}</span><input class="ph-note" placeholder="${pt('notePh')}"></label>
          <label class="ph-field"><span>${pt('size')}</span><select class="ph-size"><option value="600">600 px</option><option value="900">900 px</option><option value="1200">1200 px</option><option value="1600">1600 px</option></select></label>
          <label class="ph-check"><input type="checkbox" class="ph-use"> ${pt('useInCv')}</label>
          <div class="ph-row"><button class="btn primary ph-save">${pt('saveBtn')}</button><button class="btn ph-reset">${pt('reset')}</button></div>
          <p class="ph-hint ph-cvhint"></p></section>
      </div>
    </div>`;
  const $$ = s => box.querySelector(s);
  $$('.ph-add input').onchange = e => { const f = e.target.files[0]; e.target.value = ''; if (f) phUpload(f); };
  for (const [label, a] of PH_ASPECTS) {
    const b = el('button', 'btn', label === 'free' ? pt('free') : label); b.dataset.aspect = a;
    b.onclick = () => { ph.aspect = a; phFitCrop(); phChanged(); }; $$('.ph-aspects').append(b);
  }
  for (const m of ['keep', 'color', 'blur']) {
    const b = el('button', 'btn', pt(m)); b.dataset.mode = m;
    b.onclick = () => { ph.recipe.background.mode = m; phChanged(); }; $$('.ph-modes').append(b);
  }
  for (const s of PH_SWATCHES) {
    const b = el('button', 'ph-sw'); b.style.background = s; b.dataset.color = s; b.title = s;
    b.onclick = () => { ph.recipe.background.color = s; phChanged(); }; $$('.ph-swatches').append(b);
  }
  const pick = el('input', 'ph-pick'); pick.type = 'color'; pick.title = pt('color');
  pick.oninput = () => { ph.recipe.background.color = pick.value; phChanged(); }; $$('.ph-swatches').append(pick);
  box.querySelectorAll('input[type=range]').forEach(inp => inp.oninput = () => {
    const r = ph.recipe, v = Number(inp.value);
    if (inp.dataset.k === 'rotate') { const quarter = Math.round((r.rotate - phFine(r.rotate)) / 90) * 90; r.rotate = phWrap(quarter + v); phFitCrop(true); }
    else if (inp.dataset.a) r.adjust[inp.dataset.a] = v;
    else if (inp.dataset.b) r.background[inp.dataset.b] = v;
    phChanged();
  });
  $$('input[data-k=flip]').onchange = e => { ph.recipe.flip = e.target.checked; phChanged(); };
  $$('.ph-rl').onclick = () => { ph.recipe.rotate = phWrap(ph.recipe.rotate - 90); phFitCrop(true); phChanged(); };
  $$('.ph-rr').onclick = () => { ph.recipe.rotate = phWrap(ph.recipe.rotate + 90); phFitCrop(true); phChanged(); };
  $$('.ph-mask').onchange = e => { ph.showMask = e.target.checked; phPreview(); };
  $$('.ph-size').onchange = e => { ph.recipe.size = Number(e.target.value); phChanged(); };
  $$('.ph-note').oninput = e => { ph.recipe.note = e.target.value; ph.dirty = true; phStatus(); };
  $$('.ph-name').oninput = e => { ph.name = e.target.value.trim(); ph.dirty = true; phStatus(); };
  $$('.ph-save').onclick = phSave;
  $$('.ph-reset').onclick = () => { if (ph.origName) phStart(ph.origName, ph.editing ? null : undefined, true); };
  phCropDrag($$('.ph-cropbox'));
}

const phFine = r => { const q = Math.round(r / 90) * 90; return r - q; };           // the part of a rotation the slider shows
const phWrap = r => { let x = ((r + 180) % 360 + 360) % 360 - 180; return Math.round(x * 10) / 10; };

function phStatus() {
  if (!ph) return;
  $('dot').className = 'dot' + (ph.dirty ? ' busy' : ''); $('msg').textContent = ph.dirty ? pt('unsaved') : pt('ready');
}

function phTaken() { const d = ph.data || {}; return new Set([...(d.originals || []).map(p => p.name), ...(d.edits || []).map(e => e.name)]); }
function phFree(base) {
  const taken = phTaken(); base = (base || 'photo').slice(0, 56);
  if (!taken.has(base)) return base;
  for (let n = 2; ; n++) if (!taken.has(base + '-' + n)) return base + '-' + n;
}

function phDrawLists() {
  const d = ph.data, box = ph.box, $$ = s => box.querySelector(s);
  const orig = $$('.ph-orig'); orig.replaceChildren();
  for (const p of d.originals) {
    const t = el('div', 'ph-thumb' + (p.name === ph.origName ? ' on' : '') + (d.photo === p.file ? ' used' : ''));
    const img = el('img'); img.src = phUrl(ph.c, p.file, ph.version); img.alt = p.name; img.title = pt('newEdit');
    img.onclick = () => phConfirmLeave() && phStart(p.name);
    const x = el('button', 'ph-x', '×'); x.title = pt('remove'); x.onclick = () => phRemove(p.file);
    t.append(img, el('span', '', p.name), x); orig.append(t);
  }
  const list = $$('.ph-edits'); list.replaceChildren();
  $$('.ph-editsec').hidden = !d.edits.length;
  for (const e of d.edits) {
    const row = el('div', 'ph-edit' + (e.name === ph.editing ? ' on' : ''));
    const img = el('img'); if (e.file) img.src = phUrl(ph.c, e.file, ph.version);
    const col = el('div', 'col'); col.append(el('b', '', e.name), el('small', '', (e.recipe && e.recipe.note) || pt('editOf', (e.recipe && e.recipe.photo) || '?')));
    row.append(img, col);
    if (e.file && d.photo === e.file) row.append(el('span', 'ph-badge', pt('inUse')));
    const acts = el('div', 'ph-acts');
    if (e.file && d.photo !== e.file) { const u = el('button', 'btn', pt('use')); u.onclick = ev => { ev.stopPropagation(); phUse(e.file); }; acts.append(u); }
    const x = el('button', 'btn icon'); x.append(icon('trash')); x.title = pt('remove'); x.onclick = ev => { ev.stopPropagation(); phRemove(e.file || `photos/edits/${e.name}.jpg`); };
    acts.append(x); row.append(acts);
    row.onclick = () => e.recipe && phConfirmLeave() && phStart(e.recipe.photo.replace(/\.[a-z]+$/, ''), e);
    list.append(row);
  }
  const empty = $$('.ph-empty');
  empty.hidden = !!d.originals.length; empty.textContent = pt('empty');
  $$('.ph-canvas').hidden = !d.originals.length;
  if (!ph.origName && !ph.loading && d.originals.length) {
    // Open what the CVs use, else the newest edit, else a new edit of the first original.
    const used = d.edits.find(e => e.file && e.file === d.photo && e.recipe) || d.edits.find(e => e.recipe);
    const o = d.originals.find(p => p.file === d.photo);
    if (used) phStart(used.recipe.photo.replace(/\.[a-z]+$/, ''), used);
    else phStart((o || d.originals[0]).name);
  }
  if (!d.originals.length) { ph.origName = ''; box.querySelector('.ph-tools').hidden = true; }
}

function phConfirmLeave() { return !ph.dirty || confirm(pt('leave')); }

// Open an original for a new edit, or an existing edit (its recipe). reset keeps the name.
async function phStart(origName, edit, reset) {
  const p = ph.data.originals.find(x => x.name === origName);
  if (!p || ph.loading) return;
  ph.loading = true;
  try { await phOpen(p, origName, edit, reset); } finally { ph.loading = false; }
}
async function phOpen(p, origName, edit, reset) {
  const keepName = reset ? ph.name : '';
  if (ph.origName !== origName || !ph.img) {
    const blob = await (await fetch(phUrl(ph.c, p.file, ph.version))).blob();
    ph.img = await createImageBitmap(blob);  // EXIF orientation applied, like any <img>
    ph.work = phScaled(ph.img, 1600);
  }
  ph.origName = origName;
  const base = { format: PH_FORMAT, photo: p.file.split('/').pop(), crop: null, rotate: 0, flip: false,
                 adjust: Object.fromEntries(PH_ADJUST.map(k => [k, 0])),
                 background: { mode: 'keep', color: '#eef1f5', tolerance: 30, soft: 25, blur: 45 }, size: 900, note: '' };
  if (edit && edit.recipe && !reset) {
    const r = edit.recipe;
    ph.recipe = Object.assign(base, JSON.parse(JSON.stringify(r)));
    ph.recipe.adjust = Object.assign(base.adjust, r.adjust || {});
    ph.recipe.background = Object.assign({ mode: 'keep', color: '#eef1f5', tolerance: 30, soft: 25, blur: 45 }, r.background || {});
    ph.editing = edit.name; ph.name = edit.name;
    const c = ph.recipe.crop, rot = phRotatedSize(ph.work, ph.recipe);
    const a = c ? (c.w * rot.w) / (c.h * rot.h) : 0;
    ph.aspect = (PH_ASPECTS.find(([, x]) => x && Math.abs(x - a) < 0.01) || ['free', 0])[1];
  } else {
    ph.recipe = base; ph.editing = reset ? ph.editing : '';
    ph.name = keepName || phFree(ph.data.edits.length ? origName + '-cv' : 'cv');
    if (!reset) ph.aspect = 4 / 5;
  }
  if (!ph.recipe.crop) phFitCrop(true);
  ph.dirty = false;
  ph.box.querySelector('.ph-tools').hidden = false;
  ph.box.querySelector('.ph-use').checked = !ph.data.photo || (!!ph.editing && ph.data.photo === `photos/edits/${ph.editing}.jpg`);
  phSync(); phDrawLists(); phChanged(true);
}

// Put the recipe's values into the controls.
function phSync() {
  const r = ph.recipe, box = ph.box;
  box.querySelector('input[data-k=rotate]').value = phFine(r.rotate);
  box.querySelector('input[data-k=flip]').checked = !!r.flip;
  for (const k of PH_ADJUST) box.querySelector(`input[data-a=${k}]`).value = r.adjust[k] || 0;
  for (const k of ['tolerance', 'soft', 'blur']) box.querySelector(`input[data-b=${k}]`).value = r.background[k];
  box.querySelector('.ph-name').value = ph.name;
  box.querySelector('.ph-note').value = r.note || '';
  const size = box.querySelector('.ph-size'); if (![...size.options].some(o => Number(o.value) === r.size)) size.append(new Option(r.size + ' px', r.size)); size.value = String(r.size);
}

let phRaf = 0;
function phChanged(fresh) {
  if (!ph || !ph.recipe) return;
  if (!fresh) ph.dirty = true;
  const r = ph.recipe, box = ph.box;
  box.querySelectorAll('.ph-aspects .btn').forEach(b => b.classList.toggle('on', Number(b.dataset.aspect) === ph.aspect));
  box.querySelectorAll('.ph-modes .btn').forEach(b => b.classList.toggle('on', b.dataset.mode === r.background.mode));
  box.querySelectorAll('.ph-sw').forEach(b => b.classList.toggle('on', b.dataset.color.toLowerCase() === r.background.color.toLowerCase()));
  box.querySelector('.ph-pick').value = r.background.color;
  box.querySelector('.ph-bgopts').dataset.mode = r.background.mode;
  const show = { rotate: (r.rotate > 0 ? '+' : '') + r.rotate + '°', tolerance: r.background.tolerance, soft: r.background.soft, blur: r.background.blur };
  for (const k of PH_ADJUST) show[k] = (r.adjust[k] > 0 ? '+' : '') + (r.adjust[k] || 0);
  box.querySelectorAll('.ph-v').forEach(b => { b.textContent = show[b.dataset.v]; });
  box.querySelector('.ph-cvhint').textContent = pt('cvHint', `photos/edits/${ph.name || 'cv'}.jpg`);
  phStatus();
  cancelAnimationFrame(phRaf); phRaf = requestAnimationFrame(() => { phDrawSource(); phPreview(); });
}

// ---- crop -----------------------------------------------------------------------------------

function phRotatedSize(img, r) {
  const a = r.rotate * Math.PI / 180, c = Math.abs(Math.cos(a)), s = Math.abs(Math.sin(a));
  return { w: Math.round(img.width * c + img.height * s), h: Math.round(img.width * s + img.height * c) };
}

// The crop at the current aspect: kept centred where it was, as large as it was, inside the photo.
function phFitCrop(whole) {
  const r = ph.recipe, rot = phRotatedSize(ph.work, r);
  let c = r.crop || { x: 0, y: 0, w: 1, h: 1 };
  let cx = (c.x + c.w / 2) * rot.w, cy = (c.y + c.h / 2) * rot.h, w = c.w * rot.w, h = c.h * rot.h;
  if (whole || !r.crop) { cx = rot.w / 2; cy = rot.h / 2; w = rot.w; h = rot.h; }
  if (ph.aspect) {
    const area = w * h; w = Math.sqrt(area * ph.aspect); h = w / ph.aspect;
    const k = Math.min(1, rot.w / w, rot.h / h); w *= k; h *= k;
    if (whole || !r.crop) { const t = Math.min(rot.w / w, rot.h / h); w *= t; h *= t; }
  }
  w = Math.min(w, rot.w); h = Math.min(h, rot.h);
  let x = Math.max(0, Math.min(rot.w - w, cx - w / 2)), y = Math.max(0, Math.min(rot.h - h, cy - h / 2));
  if ((whole || !r.crop) && ph.aspect) y = Math.max(0, Math.min(rot.h - h, (rot.h - h) * 0.25));  // portraits: keep the head, lose the bottom
  let c2 = { x: x / rot.w, y: y / rot.h, w: w / rot.w, h: h / rot.h };
  for (let i = 0; i < 80 && !phInside(c2); i++) {  // shrink about the centre until no empty corner shows
    const mx = c2.x + c2.w / 2, my = c2.y + c2.h / 2; c2 = { w: c2.w * 0.97, h: c2.h * 0.97 }; c2.x = mx - c2.w / 2; c2.y = my - c2.h / 2;
  }
  r.crop = phRound(c2);
}

// Whether a crop (fractions of the straightened photo) shows only the photo, no empty corner.
function phInside(c) {
  const r = ph.recipe, rot = phRotatedSize(ph.work, r), a = -r.rotate * Math.PI / 180, W = ph.work.width, H = ph.work.height;
  const cos = Math.cos(a), sin = Math.sin(a);
  for (const [fx, fy] of [[c.x, c.y], [c.x + c.w, c.y], [c.x, c.y + c.h], [c.x + c.w, c.y + c.h]]) {
    const px = fx * rot.w - rot.w / 2, py = fy * rot.h - rot.h / 2;
    const ux = px * cos - py * sin, uy = px * sin + py * cos;  // back into the unturned photo
    if (Math.abs(ux) > W / 2 + 0.5 || Math.abs(uy) > H / 2 + 0.5) return false;
  }
  return c.x >= -1e-6 && c.y >= -1e-6 && c.x + c.w <= 1 + 1e-6 && c.y + c.h <= 1 + 1e-6;
}
const phRound = c => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, Math.round(v * 10000) / 10000]));

function phDrawSource() {
  const cv = ph.box.querySelector('.ph-src'), src = phRotated(ph.work, ph.recipe), box = ph.box.querySelector('.ph-cropbox');
  const maxW = box.clientWidth || 280, k = Math.min(maxW / src.width, 260 / src.height);
  cv.width = Math.round(src.width * k); cv.height = Math.round(src.height * k);
  const ctx = cv.getContext('2d'); ctx.drawImage(src, 0, 0, cv.width, cv.height);
  const c = ph.recipe.crop, rect = ph.box.querySelector('.ph-rect');
  Object.assign(rect.style, { left: c.x * cv.width + 'px', top: c.y * cv.height + 'px', width: c.w * cv.width + 'px', height: c.h * cv.height + 'px' });
}

function phCropDrag(box) {
  let drag = null;
  box.addEventListener('pointerdown', e => {
    if (!ph || !ph.recipe) return;
    const cv = box.querySelector('.ph-src'), h = e.target.dataset && e.target.dataset.h;
    if (!h && e.target !== box.querySelector('.ph-rect')) return;
    drag = { h, x: e.clientX, y: e.clientY, c: Object.assign({}, ph.recipe.crop), W: cv.width, H: cv.height };
    box.setPointerCapture(e.pointerId); e.preventDefault();
  });
  box.addEventListener('pointermove', e => {
    if (!drag) return;
    const r = ph.recipe, rot = phRotatedSize(ph.work, r), c0 = drag.c;
    const dx = (e.clientX - drag.x) / drag.W, dy = (e.clientY - drag.y) / drag.H;
    let { x, y, w, h } = c0;
    if (!drag.h) { x = Math.max(0, Math.min(1 - w, x + dx)); y = Math.max(0, Math.min(1 - h, y + dy)); }
    else {
      const left = drag.h.includes('w'), top = drag.h.includes('n');
      let nw = Math.max(0.05, w + (left ? -dx : dx)), nh = Math.max(0.05, h + (top ? -dy : dy));
      if (ph.aspect) {  // keep the shape: in pixels w/h = aspect
        const f = ph.aspect * rot.h / rot.w;  // w = f * h in fractions
        if (Math.abs(dx) * rot.w > Math.abs(dy) * rot.h) nh = nw / f; else nw = nh * f;
      }
      const ax = left ? x + w : x, ay = top ? y + h : y;  // the fixed corner
      nw = Math.min(nw, left ? ax : 1 - ax); nh = Math.min(nh, top ? ay : 1 - ay);
      if (ph.aspect) { const f = ph.aspect * rot.h / rot.w; if (nw / nh > f) nw = nh * f; else nh = nw / f; }
      x = left ? ax - nw : ax; y = top ? ay - nh : ay; w = nw; h = nh;
    }
    const next = { x, y, w, h };
    if (!phInside(next)) return;  // never past the photo's edge
    r.crop = phRound(next); phChanged();
  });
  const end = () => { drag = null; };
  box.addEventListener('pointerup', end); box.addEventListener('pointercancel', end);
}

// ---- pixels ---------------------------------------------------------------------------------

function phScaled(img, max) {
  const k = Math.min(1, max / Math.max(img.width, img.height)), c = document.createElement('canvas');
  c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
  const ctx = c.getContext('2d'); ctx.imageSmoothingQuality = 'high'; ctx.drawImage(img, 0, 0, c.width, c.height);
  return c;
}

// The photo turned by rotate degrees (clockwise) and mirrored, on a canvas just big enough.
function phRotated(img, r) {
  const { w, h } = phRotatedSize(img, r), c = document.createElement('canvas'); c.width = w; c.height = h;
  const ctx = c.getContext('2d'); ctx.imageSmoothingQuality = 'high';
  ctx.translate(w / 2, h / 2); ctx.rotate(r.rotate * Math.PI / 180); if (r.flip) ctx.scale(-1, 1);
  ctx.drawImage(img, -img.width / 2, -img.height / 2);
  return c;
}

// The edit itself: a canvas with the long side `long` pixels. The same steps for the preview and
// the saved image, so what you see is what is stored.
function phRender(img, r, long, mask) {
  const rot = phRotated(img, r), c = r.crop;
  const sx = c.x * rot.width, sy = c.y * rot.height, sw = c.w * rot.width, sh = c.h * rot.height;
  const k = long / Math.max(sw, sh), W = Math.max(1, Math.round(sw * k)), H = Math.max(1, Math.round(sh * k));
  const out = document.createElement('canvas'); out.width = W; out.height = H;
  const ctx = out.getContext('2d'); ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(rot, sx, sy, sw, sh, 0, 0, W, H);
  const im = ctx.getImageData(0, 0, W, H), d = im.data;
  const bg = r.background || { mode: 'keep' };
  const m = bg.mode !== 'keep' || mask ? phMask(d, W, H, bg) : null;
  phAdjust(d, W, H, r.adjust || {});
  if (bg.mode === 'color') {
    const col = [1, 3, 5].map(i => parseInt(bg.color.slice(i, i + 2), 16));
    for (let p = 0, i = 0; p < W * H; p++, i += 4) { const a = m[p]; if (a) for (let ch = 0; ch < 3; ch++) d[i + ch] = d[i + ch] + (col[ch] - d[i + ch]) * a; }
  } else if (bg.mode === 'blur') {
    const rad = Math.max(1, Math.round((bg.blur || 0) / 100 * 0.035 * Math.max(W, H)));
    const blurred = [0, 1, 2].map(ch => { const f = new Float32Array(W * H); for (let p = 0; p < W * H; p++) f[p] = d[p * 4 + ch]; return phBoxBlur(f, W, H, rad, 3); });
    for (let p = 0, i = 0; p < W * H; p++, i += 4) { const a = m[p]; if (a) for (let ch = 0; ch < 3; ch++) d[i + ch] = d[i + ch] + (blurred[ch][p] - d[i + ch]) * a; }
  }
  // Corners left empty by straightening: white (a JPEG has no transparency).
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] < 255) { const a = d[i + 3] / 255; for (let ch = 0; ch < 3; ch++) d[i + ch] = d[i + ch] * a + 255 * (1 - a); d[i + 3] = 255; }
  if (mask && m) for (let p = 0, i = 0; p < W * H; p++, i += 4) { const a = m[p] * 0.55; d[i] += (255 - d[i]) * a; d[i + 1] *= 1 - a; d[i + 2] *= 1 - a; }
  ctx.putImageData(im, 0, 0);
  return out;
}

// Brightness, contrast, saturation, warmth and sharpness, each -100..100 (0 is none).
function phAdjust(d, W, H, a) {
  const br = (a.brightness || 0) * 0.6, ct = 1 + (a.contrast || 0) / 100 * 0.8, st = 1 + (a.saturation || 0) / 100,
        wm = (a.warmth || 0) * 0.3, sh = (a.sharpen || 0) / 100;
  if (sh) {
    const blur = [0, 1, 2].map(ch => { const f = new Float32Array(W * H); for (let p = 0; p < W * H; p++) f[p] = d[p * 4 + ch]; return phBoxBlur(f, W, H, 1, 1); });
    for (let p = 0, i = 0; p < W * H; p++, i += 4) for (let ch = 0; ch < 3; ch++) {
      const v = d[i + ch], b = blur[ch][p];
      d[i + ch] = sh > 0 ? v + (v - b) * sh * 1.5 : v + (b - v) * -sh;
    }
  }
  if (!br && ct === 1 && st === 1 && !wm) return;
  for (let i = 0; i < d.length; i += 4) {
    let r = d[i], g = d[i + 1], b = d[i + 2];
    r = (r + br - 128) * ct + 128; g = (g + br - 128) * ct + 128; b = (b + br - 128) * ct + 128;
    const y = 0.299 * r + 0.587 * g + 0.114 * b;
    r = y + (r - y) * st; g = y + (g - y) * st; b = y + (b - y) * st;
    d[i] = r + wm; d[i + 1] = g + wm * 0.15; d[i + 2] = b - wm;
  }
}

// What is background: the colours along the top and the sides (where a portrait's wall is),
// grown inwards over every connected pixel close to one of them, stopping at sharp edges (the
// outline of hair, face and clothes). Returns 0..1 per pixel, with a soft edge. No model: this is
// a flood fill, so it suits plain walls and studio backdrops.
function phMask(d, W, H, bg) {
  const tol = bg.tolerance ?? 30, thr = 8 + tol * 0.9, thr2 = thr * thr, edge = 6 + tol * 0.35, edge2 = edge * edge;
  const samples = [], at = (x, y) => (y * W + x) * 4;
  const step = Math.max(1, Math.round(Math.max(W, H) / 300));
  for (let x = 0; x < W; x += step) samples.push(at(x, 0));
  for (let y = 0; y < H * 0.85; y += step) { samples.push(at(0, y)); samples.push(at(W - 1, y)); }
  const clusters = [];
  for (const i of samples) {
    if (d[i + 3] < 128) continue;
    let best = null, bd = 26 * 26;
    for (const c of clusters) { const dr = d[i] - c.r / c.n, dg = d[i + 1] - c.g / c.n, db = d[i + 2] - c.b / c.n, dd = dr * dr + dg * dg + db * db; if (dd < bd) { bd = dd; best = c; } }
    if (best) { best.r += d[i]; best.g += d[i + 1]; best.b += d[i + 2]; best.n++; } else clusters.push({ r: d[i], g: d[i + 1], b: d[i + 2], n: 1 });
  }
  clusters.sort((a, b) => b.n - a.n);
  const refs = clusters.filter(c => c.n >= samples.length * 0.06).slice(0, 4).map(c => [c.r / c.n, c.g / c.n, c.b / c.n]);
  const near = i => {
    if (d[i + 3] < 128) return true;  // the empty corners of a straightened photo
    for (const [r, g, b] of refs) { const dr = d[i] - r, dg = d[i + 1] - g, db = d[i + 2] - b; if (dr * dr + dg * dg + db * db < thr2) return true; }
    return false;
  };
  const m = new Uint8Array(W * H), queue = new Int32Array(W * H);
  let head = 0, tail = 0;
  const smooth = (p, q) => {  // no sharp step between neighbours p and q
    const i = p * 4, j = q * 4;
    if (d[i + 3] < 128 || d[j + 3] < 128) return true;
    const dr = d[i] - d[j], dg = d[i + 1] - d[j + 1], db = d[i + 2] - d[j + 2];
    return dr * dr + dg * dg + db * db < edge2;
  };
  const seed = (p, from) => { if (!m[p] && near(p * 4) && (from < 0 || smooth(p, from))) { m[p] = 1; queue[tail++] = p; } };
  for (let x = 0; x < W; x++) seed(x, -1);
  for (let y = 0; y < H; y++) { seed(y * W, -1); seed(y * W + W - 1, -1); }
  while (head < tail) {
    const p = queue[head++], x = p % W;
    if (x > 0) seed(p - 1, p); if (x < W - 1) seed(p + 1, p);
    if (p >= W) seed(p - W, p); if (p < W * (H - 1)) seed(p + W, p);
  }
  const f = new Float32Array(W * H); for (let p = 0; p < W * H; p++) f[p] = m[p];
  const rad = Math.round((bg.soft ?? 25) / 100 * 0.02 * Math.max(W, H));
  return rad ? phBoxBlur(f, W, H, rad, 2) : f;
}

// A box blur run `passes` times (three is close to a Gaussian), separable, on one channel.
function phBoxBlur(src, W, H, r, passes) {
  let a = src, b = new Float32Array(W * H);
  const line = (get, set, n) => {
    let sum = 0; const w = 2 * r + 1;
    for (let i = -r; i <= r; i++) sum += get(Math.min(n - 1, Math.max(0, i)));
    for (let i = 0; i < n; i++) { set(i, sum / w); sum += get(Math.min(n - 1, i + r + 1)) - get(Math.max(0, i - r)); }
  };
  for (let p = 0; p < passes; p++) {
    for (let y = 0; y < H; y++) { const o = y * W; line(i => a[o + i], (i, v) => { b[o + i] = v; }, W); }
    [a, b] = [b, a === src ? new Float32Array(W * H) : a];
    for (let x = 0; x < W; x++) line(i => a[i * W + x], (i, v) => { b[i * W + x] = v; }, H);
    [a, b] = [b, a];
  }
  return a;
}

function phPreview() {
  if (!ph || !ph.work || !ph.recipe) return;
  const out = phRender(ph.work, ph.recipe, PH_PREVIEW, ph.showMask), cv = ph.box.querySelector('.ph-canvas');
  cv.width = out.width; cv.height = out.height; cv.getContext('2d').drawImage(out, 0, 0);
}

// ---- actions --------------------------------------------------------------------------------

async function phUpload(file) {
  let blob = file, note = '';
  try {
    const img = await createImageBitmap(file);
    if (Math.max(img.width, img.height) > PH_MAX_ORIGINAL || file.size > 3e6 || !/^image\/(jpeg|png|webp)$/.test(file.type)) {
      blob = await phBlob(phScaled(img, PH_MAX_ORIGINAL), 'image/jpeg', 0.92);
      note = pt('shrunk', Math.min(PH_MAX_ORIGINAL, Math.max(img.width, img.height)));
    }
  } catch (e) { toast(String(e)); return; }
  const base = file.name.replace(/\.[^.]+$/, '').toLowerCase().normalize('NFKD').replace(/[æ]/g, 'ae').replace(/[ø]/g, 'o')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'photo';
  const name = phFree(base);
  const j = await phPost('/photo-add', { name, data: await phDataUrl(blob) });
  if (!j.ok) { toast(j.message || 'Not saved'); return; }
  toast(pt('added', j.file) + (note ? ' · ' + note : ''));
  ph.data = await phList(ph.c); ph.version = ph.data.version;
  if (phConfirmLeave()) { ph.dirty = false; await phStart(name); } else phDrawLists();
}

async function phSave() {
  const name = ph.name;
  if (!PH_NAME.test(name)) { toast(pt('badName')); return; }
  if (name !== ph.editing && ph.data.edits.some(e => e.name === name) && !confirm(pt('overwrite', name))) return;
  const btn = ph.box.querySelector('.ph-save'); btn.disabled = true;
  try {
    const r = JSON.parse(JSON.stringify(ph.recipe));
    if (!r.note) delete r.note;
    const out = phRender(ph.img, r, r.size, false);
    const j = await phPost('/photo-save', { name, recipe: r, use: ph.box.querySelector('.ph-use').checked,
                                            data: await phDataUrl(await phBlob(out, 'image/jpeg', 0.9)) });
    if (!j.ok) { toast(j.message || 'Not saved'); return; }
    ph.dirty = false; ph.editing = name;
    ph.data = await phList(ph.c); ph.version = ph.data.version; phDrawLists(); phStatus();
    toast(pt('saved', j.file));
  } finally { btn.disabled = false; }
}

async function phUse(file) {
  const j = await phPost('/photo-use', { file });
  if (!j.ok) { toast(j.message || 'Not saved'); return; }
  toast(pt('nowUsed', file));
  ph.data = await phList(ph.c); ph.version = ph.data.version; phDrawLists();
}

async function phRemove(file) {
  if (!confirm(pt('confirmRemove', file))) return;
  const j = await phPost('/photo-remove', { file });
  if (!j.ok) { toast(j.message || 'Not deleted'); return; }
  toast(pt('removed', file));
  const wasOpen = file === `photos/edits/${ph.editing}.jpg` || file.split('/').pop().replace(/\.[a-z]+$/, '') === ph.origName;
  ph.data = await phList(ph.c); ph.version = ph.data.version;
  if (wasOpen) { ph.editing = ''; if (!ph.data.originals.some(p => p.name === ph.origName)) { ph.origName = ''; ph.img = null; } }
  phDrawLists();
}
