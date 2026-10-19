// Profile in the workbench: OpenSelf's UI (openself/openself/web/static/app.js, served under
// /openself/) mounted in #view for the person's profile. Loaded before the page's inline
// script, so this file only declares functions; they use the page's helpers when called.

let pfUI = null, pfC = '';

function pfActive() {
  if (!target.endsWith('/raw')) return false;
  const c = target.split('/')[0], t = tree.find(x => x.person === c);
  return !!t && t.profile === 'profile';
}
function pfHost(c) {
  const route = { profile: '/profile', state: '/profile-state', log: '/profile-log', show: '/profile-show', asof: '/profile-asof' };
  const send = async (path, body) => {
    const r = await fetch(path, { method: 'POST', headers: { 'X-OpenVita': '1', 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ c }, body)) });
    let j = {}; try { j = await r.json(); } catch (e) { j = { ok: false, message: 'Bad answer from the server' }; }
    j.status = r.status; return j;
  };
  return {
    key: c,
    get: async (name, params) => (await fetch(route[name] + '?' + q(Object.assign({ c }, params || {})), { cache: 'no-store' })).json(),
    post: (name, body) => send('/profile-' + name, body),
    status: (text, kind) => { $('msg').textContent = text; $('dot').className = 'dot' + (kind ? ' ' + kind : ''); },
    toast, hits: text => { $('hits').textContent = text; },
    path: (files, root) => drawPath(files.map(f => ['', f]), root),
    changed: () => loadComments(),
    // "Ask for an interview": a request in feedback.json that the assistant picks up (see AGENTS.md).
    request: async (id, comment, quote) => { const j = await send('/profile-request', { id, comment: comment || '', quote: quote || '' }); loadComments(); return j; },
  };
}
async function profileTick() {
  const c = target.split('/')[0];
  if (!pfUI || pfC !== c || !$('view').querySelector('.os')) {
    if (pfUI) pfUI.destroy();
    pfC = c; $('view').classList.add('pfmode'); $('view').replaceChildren();
    pfUI = OpenSelfUI($('view'), pfHost(c));
  }
  await pfUI.tick();
}
function pfSearch(needle, jump) { if (pfUI) pfUI.search(needle, jump); }
