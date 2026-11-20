import { $, esc, show, toast, setStatus, fill } from './ui.js';
import { api, errorMessage } from './api.js';

let dict = { offers: [] };
let currentCampaign = null;



function syncStatus() {
  const c = currentCampaign;
  const withOffers = c.streams.filter(s => s.schema === 'landings').length;
  const dirty = c.streams.filter(s => s.dirty).length;
  if (dirty) {
    setStatus(`Потоков: ${c.streams.length}, с офферами: ${withOffers}. Не отправлено в Keitaro: ${dirty} — нажмите «Отправить изменения в Keitarо»`, 'warn');
  } else {
    setStatus(`Потоков: ${c.streams.length}, с офферами: ${withOffers}. Всё синхронизировано с Keitaro`, 'ok');
  }
}


async function init() {
  try { dict = await api('/api/dictionaries'); } catch (e) { show($('c-msg'), e.message, false); return; }
  fill($('c-offer'), dict.offers, false);
  fill($('c-domain'), dict.domains, true);
  fill($('c-group'), dict.groups, true);
  fill($('c-source'), dict.sources, true);
  loadRecent();
}

async function loadRecent() {
  try {
    const rows = await api('/api/campaigns');
    const sel = $('e-recent');
    sel.innerHTML = '<option value="">—</option>';
    if (!rows.length) {
      const opt = new Option('Кампаний пока нет — создайте на вкладке «Создать»', '');
      opt.disabled = true;
      sel.append(opt);
    }
    for (const r of rows) sel.append(new Option(`${r.name} (#${r.id})`, r.id));
  } catch (e) { /* ignore */ }
}

async function loadCampaign(id) {
  if (!id) return show($('e-msg'), 'Введите ID кампании', false);
  const btn = $('e-load');
  btn.disabled = true;
  setStatus('Получаю потоки из Keitaro…');
  try {
    const params = new URLSearchParams();
    const from = $('e-from').value, to = $('e-to').value;
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    const qs = params.toString() ? '?' + params.toString() : '';
    currentCampaign = await api('/api/campaigns/' + id + qs);
    $('e-msg').innerHTML = '';
    $('e-open').disabled = false;
    render();
    syncStatus();
  } catch (e) {
    $('e-body').innerHTML = '';
    show($('e-msg'), e.message, false);
    setStatus(`Не удалось получить потоки: ${e.message}`, 'err');
  } finally { btn.disabled = false; }
}

const fmt = (n) => (Number(n) || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });

function render() {
  const c = currentCampaign;
  let html = `<h2>${esc(c.name)} <span class="muted">#${c.id}</span></h2>`;
  if (c.stats_error) html += `<div class="msg err">Статистика не загрузилась, цифры ниже недостоверны: ${esc(c.stats_error)}</div>`;
  for (const s of c.streams) {
    const isOffers = s.schema === 'landings';
    const dirtyCls = s.dirty ? 'dirty' : '';
    html += `<div class="card ${dirtyCls}"><div class="card-head"><strong>${esc(s.name || 'Поток')}</strong>`;
    html += `<span class="muted">${isOffers ? 'поток с офферами' : 'поток-редирект — без офферов'}</span>`;
    if (s.dirty) html += `<span class="badge pending">не отправлено в Keitaro</span>`;
    else if (isOffers) html += `<span class="badge sync">синхронизирован</span>`;
    html += `</div>`;
    if (!isOffers) { html += `<p class="muted">Этот поток настроен напрямую в Keitaro, обёртка его не меняет.</p></div>`; continue; }
    if (!s.offers.length) html += `<p class="muted">В потоке пока нет офферов — добавьте первый ниже.</p>`;
    html += `<div class="table-wrap"><table><thead><tr><th>Оффер</th><th class="num">Доля, %</th><th>Статус</th><th>Закрепить долю</th><th class="num">Клики</th><th class="num">Уники</th><th class="num">Конверсии</th><th class="num">Доход</th><th class="num">Расход</th><th class="num">Профит</th><th></th></tr></thead><tbody>`;
    for (const o of s.offers) {
      const st = o.stats || {};
      const removed = o.status === 'removed';
      const staged = removed || o.status === 'pending_remove';
      const rowCls = staged ? 'removed' : '';
      const statusBadge = o.status === 'pending_add' ? '<span class="badge pending">не отправлен</span>'
        : o.status === 'pending_remove' ? '<span class="badge pending">к удалению</span>'
        : o.status === 'removed' ? '<span class="badge removed">в архиве</span>' : '';
      html += `<tr class="${rowCls}">
        <td data-label="Оффер">${esc(o.name)} <span class="muted">#${o.offer_id}</span></td>
        <td class="num" data-label="Доля, %">${o.share}</td>
        <td data-label="Статус">${statusBadge}</td>
        <td data-label="Закрепить"><input type="checkbox" data-pin="${o.offer_id}" data-stream="${s.id}" title="Закрепить долю — не участвовать в пересчёте" ${o.pinned ? 'checked' : ''} ${staged ? 'disabled' : ''}></td>
        <td class="num" data-label="Клики">${fmt(st.clicks)}</td><td class="num" data-label="Уники">${fmt(st.unique_clicks)}</td><td class="num" data-label="Конверсии">${fmt(st.conversions)}</td>
        <td class="num" data-label="Доход">${fmt(st.revenue)}</td><td class="num" data-label="Расход">${fmt(st.cost)}</td><td class="num" data-label="Профит">${fmt(st.profit)}</td>
        <td class="actions" data-label="">
          ${removed
            ? `<button class="btn restore small" data-restore="${o.offer_id}" data-stream="${s.id}">Вернуть в поток</button>`
            : staged ? '' : `<button class="btn danger small" data-del="${o.offer_id}" data-stream="${s.id}">Убрать из потока</button>`}
        </td></tr>`;
    }
    html += `</tbody></table></div>
      <div class="row add-offer">
        <div><label>Добавить оффер в поток</label>
          <div class="combo">
            <input type="text" class="combo-input" data-combo="${s.id}" autocomplete="off" spellcheck="false"
              role="combobox" aria-expanded="false" aria-autocomplete="list" aria-controls="combo-list-${s.id}"
              placeholder="Начните вводить название или ID оффера">
            <ul class="combo-list" id="combo-list-${s.id}" role="listbox" hidden></ul>
          </div>
        </div>
        <div><button class="btn primary" data-add="${s.id}">Добавить в поток</button></div>
      </div>`;
    if (s.dirty) {
      html += `<div class="row add-offer">
        <button class="btn primary" data-push="${s.id}">Отправить изменения в Keitaro</button>
        <button class="btn" data-cancel="${s.id}">Отменить изменения</button>
      </div>`;
    }
    html += `</div>`;
  }
  $('e-body').innerHTML = html;

  $('e-body').querySelectorAll('[data-del]').forEach(b => b.onclick = () => changeOffer('DELETE', b, b.dataset.del, b.dataset.stream));
  $('e-body').querySelectorAll('[data-add]').forEach(b => b.onclick = () => addFromCombo(b.dataset.add));
  $('e-body').querySelectorAll('[data-combo]').forEach(inp => makeCombo(
    inp,
    offerFetcher(inp.dataset.combo),
    (it) => { inp.value = `${it.name} (#${it.id})`; inp.dataset.selectedId = it.id; },
  ));
  $('e-body').querySelectorAll('[data-restore]').forEach(b => b.onclick = () => restoreOffer(b, b.dataset.restore, b.dataset.stream));
  $('e-body').querySelectorAll('[data-push]').forEach(b => b.onclick = () => pushStream(b, b.dataset.push));
  $('e-body').querySelectorAll('[data-cancel]').forEach(b => b.onclick = () => cancelStream(b, b.dataset.cancel));
  $('e-body').querySelectorAll('[data-pin]').forEach(cb => cb.onchange = () => pinOffer(cb, cb.dataset.pin, cb.dataset.stream, cb.checked));
}

async function runAction(btn, action, okText, kind, onError) {
  if (btn) btn.disabled = true;
  try {
    currentCampaign = await action();
    $('e-msg').innerHTML = '';
    render();
    setStatus(okText, kind);
    toast(okText, true);
  } catch (e) {
    show($('e-msg'), e.message, false);
    setStatus(e.message, 'err');
    toast(e.message, false);
    if (onError) onError();
    else if (btn) btn.disabled = false;
  }
}

function changeOffer(method, btn, offerId, streamId) {
  if (!offerId) return;
  if (method === 'DELETE' && !confirm('Убрать оффер из потока? Он останется в архиве обёртки, пока вы не отмените изменение.')) return;
  const id = currentCampaign.id;
  const call = method === 'POST'
    ? () => api(`/api/campaigns/${id}/offers`, { method, body: JSON.stringify({ offer_id: Number(offerId), stream_id: Number(streamId) }) })
    : () => api(`/api/campaigns/${id}/offers/${offerId}?stream_id=${streamId}`, { method });
  const okText = method === 'POST'
    ? `Оффер #${offerId} добавлен в поток, доли пересчитаны. Изменения ещё не отправлены в Keitaro`
    : `Оффер #${offerId} убран из потока (доля 0%). Изменения ещё не отправлены в Keitaro`;
  return runAction(btn, call, okText, 'warn');
}

function restoreOffer(btn, offerId, streamId) {
  const id = currentCampaign.id;
  return runAction(
    btn,
    () => api(`/api/campaigns/${id}/offers/${offerId}/restore?stream_id=${streamId}`, { method: 'POST' }),
    `Оффер #${offerId} возвращён в поток. Отправьте изменения в Keitaro, чтобы закрепить`,
    'warn',
  );
}

function pushStream(btn, streamId) {
  const id = currentCampaign.id;
  setStatus('Отправляю изменения в Keitaro…');
  return runAction(
    btn,
    () => api(`/api/campaigns/${id}/push?stream_id=${streamId}`, { method: 'POST' }),
    'Изменения отправлены в Keitaro',
    'ok',
  );
}

function cancelStream(btn, streamId) {
  if (!confirm('Отменить все не отправленные изменения в этом потоке?')) return;
  const id = currentCampaign.id;
  return runAction(
    btn,
    () => api(`/api/campaigns/${id}/cancel?stream_id=${streamId}`, { method: 'POST' }),
    'Изменения отменены, поток снова синхронизирован с Keitaro',
    'ok',
  );
}

function pinOffer(cb, offerId, streamId, pinned) {
  const id = currentCampaign.id;
  return runAction(
    null,
    () => api(`/api/campaigns/${id}/offers/${offerId}/pin?stream_id=${streamId}&pinned=${pinned}`, { method: 'POST' }),
    pinned
      ? `Доля оффера #${offerId} закреплена — пересчёты её не тронут`
      : `Доля оффера #${offerId} больше не закреплена`,
    'warn',
    () => { cb.checked = !pinned; },
  );
}

const COMBO_DEBOUNCE_MS = 150;
const COMBO_LIMIT = 20;

function comboStream(streamId) {
  return currentCampaign.streams.find(s => String(s.id) === String(streamId));
}

function appendHighlighted(li, name, needle) {
  const idx = needle ? name.toLowerCase().indexOf(needle) : -1;
  if (idx < 0) { li.append(document.createTextNode(name)); return; }
  li.append(document.createTextNode(name.slice(0, idx)));
  const mark = document.createElement('mark');
  mark.textContent = name.slice(idx, idx + needle.length);
  li.append(mark, document.createTextNode(name.slice(idx + needle.length)));
}

function closeCombo(ui) {
  ui.list.hidden = true;
  ui.input.setAttribute('aria-expanded', 'false');
  ui.input.removeAttribute('aria-activedescendant');
  ui.active = -1;
}

function renderComboOptions(ui, items) {
  ui.items = items;
  ui.list.innerHTML = '';
  if (!items.length) {
    const li = document.createElement('li');
    li.className = 'combo-empty';
    li.setAttribute('role', 'option');
    li.setAttribute('aria-disabled', 'true');
    li.textContent = 'Ничего не найдено';
    ui.list.append(li);
  }
  const needle = ui.query.trim().toLowerCase();
  for (const it of items) {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.id = `${ui.list.id}-opt-${it.id}`;
    li.dataset.offerId = it.id;
    appendHighlighted(li, it.name, needle);
    const idSpan = document.createElement('span');
    idSpan.className = 'muted';
    idSpan.textContent = ` #${it.id}`;
    li.append(idSpan);
    li.onmousedown = (e) => { e.preventDefault(); selectComboOption(ui, it); };
    ui.list.append(li);
  }
  ui.list.hidden = false;
  ui.input.setAttribute('aria-expanded', 'true');
  ui.active = -1;
}

async function refreshCombo(ui) {
  const query = ui.query;
  let rows;
  try {
    rows = await ui.fetchItems(query);
  } catch (e) { return; }
  if (ui.query !== query) return;
  renderComboOptions(ui, rows);
}

function selectComboOption(ui, it) {
  ui.onSelect(it);
  closeCombo(ui);
}

function moveComboActive(ui, delta) {
  const opts = [...ui.list.querySelectorAll('li[data-offer-id]')];
  if (!opts.length) return;
  ui.active = (ui.active + delta + opts.length) % opts.length;
  opts.forEach((li, i) => li.classList.toggle('active', i === ui.active));
  ui.input.setAttribute('aria-activedescendant', opts[ui.active].id);
  opts[ui.active].scrollIntoView({ block: 'nearest' });
}

function makeCombo(input, fetchItems, onSelect) {
  const ui = {
    input,
    list: $(input.getAttribute('aria-controls')),
    query: '',
    items: [],
    active: -1,
    timer: 0,
    fetchItems,
    onSelect,
  };
  input.onfocus = () => { ui.query = ''; refreshCombo(ui); };
  input.oninput = () => {
    ui.query = input.value;
    input.dataset.selectedId = '';
    clearTimeout(ui.timer);
    ui.timer = setTimeout(() => refreshCombo(ui), COMBO_DEBOUNCE_MS);
  };
  input.onkeydown = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (ui.list.hidden) refreshCombo(ui);
      else moveComboActive(ui, e.key === 'ArrowDown' ? 1 : -1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (!ui.list.hidden && ui.active >= 0) selectComboOption(ui, ui.items[ui.active]);
    } else if (e.key === 'Escape' || e.key === 'Tab') {
      closeCombo(ui);
    }
  };
  input.onblur = () => closeCombo(ui);
}

function offerFetcher(streamId) {
  return async (query) => {
    const rows = await api(`/api/offers/search?q=${encodeURIComponent(query)}&limit=${COMBO_LIMIT}`);
    const used = new Set((comboStream(streamId)?.offers ?? []).filter(o => o.status !== 'removed').map(o => o.offer_id));
    return rows.filter(o => !used.has(o.id));
  };
}

function addFromCombo(streamId) {
  const input = $('e-body').querySelector(`[data-combo="${streamId}"]`);
  const typed = input.value.trim();
  const offerId = input.dataset.selectedId || (/^\d+$/.test(typed) ? typed : '');
  if (!offerId) { show($('e-msg'), 'Выберите оффер из списка или введите его ID', false); return; }
  changeOffer('POST', input, offerId, streamId);
}

function renderOffers(filter) {
  const needle = filter.trim().toLowerCase();
  const items = dict.offers.filter(o => !needle || o.name.toLowerCase().includes(needle) || String(o.id) === needle);
  $('offers-list').innerHTML = items.length
    ? items.map(o => `<div class="chip">${esc(o.name)} <span class="muted">#${o.id}</span></div>`).join('')
    : '<span class="muted">Ничего не найдено</span>';
}

$('tab-create').onclick = () => switchTab('create');
$('tab-edit').onclick = () => switchTab('edit');
function switchTab(name) {
  $('view-create').classList.toggle('hidden', name !== 'create');
  $('view-edit').classList.toggle('hidden', name !== 'edit');
  $('tab-create').classList.toggle('active', name === 'create');
  $('tab-edit').classList.toggle('active', name === 'edit');
}

$('create-form').onsubmit = async (e) => {
  e.preventDefault();
  const body = {
    name: $('c-name').value.trim(),
    geo: $('c-geo').value.trim(),
    offer_id: Number($('c-offer').value),
    domain_id: $('c-domain').value ? Number($('c-domain').value) : null,
    group_id: $('c-group').value ? Number($('c-group').value) : null,
    source_id: $('c-source').value ? Number($('c-source').value) : null,
  };
  const btn = e.target.querySelector('button[type=submit]');
  btn.disabled = true;
  try {
    const r = await api('/api/campaigns', { method: 'POST', body: JSON.stringify(body) });
    show($('c-msg'), `Создана кампания #${r.id} «${r.name}» — откройте её в редакторе`, true);
    $('e-id').value = r.id;
    loadRecent();
  } catch (e2) { show($('c-msg'), e2.message, false); } finally { btn.disabled = false; }
};

$('e-load').onclick = () => {
  const el = $('e-id');
  const id = el.dataset.selectedId || (/^\d+$/.test(el.value.trim()) ? el.value.trim() : '');
  if (!id) return show($('e-msg'), 'Введите ID кампании или выберите её из списка', false);
  loadCampaign(id);
};
makeCombo(
  $('e-id'),
  (query) => api(`/api/campaigns/search?q=${encodeURIComponent(query)}&limit=${COMBO_LIMIT}`),
  (it) => {
    $('e-id').value = `${it.name} (#${it.id})`;
    $('e-id').dataset.selectedId = String(it.id);
    loadCampaign(String(it.id));
  },
);
$('e-open').onclick = () => {
  if (currentCampaign) window.open(`${currentCampaign.keitaro_url}/admin/#!/campaigns/`, '_blank');
};
$('e-offers').onclick = () => {
  const panel = $('offers-panel');
  panel.classList.toggle('hidden');
  $('e-offers').textContent = panel.classList.contains('hidden') ? 'Показать все офферы' : 'Скрыть все офферы';
  if (!panel.classList.contains('hidden')) { renderOffers($('offers-filter').value); $('offers-filter').focus(); }
};
$('offers-filter').oninput = (e) => renderOffers(e.target.value);
$('e-from').onchange = () => { if ($('e-id').value) $('e-load').click(); };
$('e-to').onchange = () => { if ($('e-id').value) $('e-load').click(); };
$('e-recent').onchange = (e) => {
  if (e.target.value) {
    $('e-id').value = e.target.value;
    $('e-id').dataset.selectedId = e.target.value;
    loadCampaign(e.target.value);
  }
};

init();
