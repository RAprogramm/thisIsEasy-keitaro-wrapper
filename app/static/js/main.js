import { $, show, toast, setStatus, fill, setBusy } from './ui.js';
import { initActivity, logAction, logEvent } from './activity.js';
import { api } from './api.js';
import { state } from './state.js';
import { esc, plural } from './format.js';

const COMBO_DEBOUNCE_MS = 150;
const COMBO_LIMIT = 20;

function syncStatus() {
  const campaign = state.currentCampaign;
  const total = campaign.streams.length;
  const dirty = campaign.streams.filter((stream) => stream.dirty).length;
  if (dirty) {
    setStatus(`Не опубликовано ${dirty} из ${total} ${plural(total, ['потока', 'потоков', 'потоков'])}`, 'warn');
  } else {
    setStatus(`Все потоки синхронизированы · ${total} ${plural(total, ['поток', 'потока', 'потоков'])}`, 'ok');
  }
}

function selectedCampaignId() {
  const input = $('e-id');
  return input.dataset.selectedId || (/^\d+$/.test(input.value.trim()) ? input.value.trim() : '');
}

async function init() {
  initActivity();
  try {
    state.dict = await api('/api/dictionaries');
  } catch (error) {
    show($('c-msg'), error.message, false);
    logEvent('err', `Не удалось загрузить справочники: ${error.message}`);
    return;
  }
  fill($('c-domain'), state.dict.domains, true);
  fill($('c-group'), state.dict.groups, true);
  fill($('c-source'), state.dict.sources, true);
  makeCombo(
    $('c-offer'),
    (query) => api(`/api/offers/search?q=${encodeURIComponent(query)}&limit=${COMBO_LIMIT}`),
    (item) => {
      $('c-offer').value = `${item.name} (#${item.id})`;
      $('c-offer').dataset.selectedId = String(item.id);
    },
    'Ищу офферы…',
  );
}

function campaignSkeleton() {
  const card = `<article class="card stream skeleton-card" aria-hidden="true">
    <div class="skeleton-card__head">
      <span class="skeleton skeleton--icon"></span>
      <div class="skeleton-card__lines">
        <span class="skeleton skeleton--line" style="width: 180px"></span>
        <span class="skeleton skeleton--line" style="width: 120px"></span>
      </div>
    </div>
    <div class="skeleton-card__body">
      <span class="skeleton skeleton--row"></span>
      <span class="skeleton skeleton--row"></span>
      <span class="skeleton skeleton--row"></span>
    </div>
  </article>`;
  return `<div class="skeleton-campaign">
    <span class="skeleton skeleton--heading"></span>
    ${card}${card}
  </div>`;
}

async function loadCampaign(id) {
  if (!id) {
    show($('e-msg'), 'Введите ID кампании', false);
    return;
  }
  const button = $('e-load');
  setBusy(button, true);
  logAction(`Загрузка кампании #${id} из Keitaro`);
  if (!state.currentCampaign) $('e-body').innerHTML = campaignSkeleton();
  try {
    const params = new URLSearchParams();
    const from = $('e-from').value;
    const to = $('e-to').value;
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    const query = params.toString() ? `?${params.toString()}` : '';
    state.currentCampaign = await api(`/api/campaigns/${id}${query}`);
    $('e-msg').innerHTML = '';
    $('e-open').disabled = false;
    render();
    syncStatus();
  } catch (error) {
    state.currentCampaign = null;
    $('e-body').innerHTML = '';
    $('e-open').disabled = true;
    show($('e-msg'), error.message, false);
    setStatus(error.message, 'err');
    toast(error.message, false);
  } finally {
    setBusy(button, false);
  }
}

function offerBadge(offer) {
  if (offer.status === 'pending_add') {
    return '<span class="badge badge--warning"><span class="badge__dot"></span>Не опубликован</span>';
  }
  if (offer.status === 'pending_remove') {
    return '<span class="badge badge--warning"><span class="badge__dot"></span>Будет удалён</span>';
  }
  if (offer.status === 'removed') {
    return '<span class="badge badge--neutral"><span class="badge__dot"></span>В архиве</span>';
  }
  return '';
}

function offerRow(stream, offer) {
  const removed = offer.status === 'removed';
  const staged = removed || offer.status === 'pending_remove';
  const share = Math.max(0, Math.min(100, Number(offer.share) || 0));
  const pinLabel = `${offer.pinned ? 'Открепить' : 'Закрепить'} долю оффера ${offer.name}`;
  const action = staged
    ? `<button class="btn btn--success btn--sm" data-restore="${offer.offer_id}" data-stream="${stream.id}">
         <svg class="icon" aria-hidden="true"><use href="#i-undo"/></svg><span>Вернуть</span>
       </button>`
    : `<button class="btn btn--danger btn--sm" data-del="${offer.offer_id}" data-stream="${stream.id}">
         <svg class="icon" aria-hidden="true"><use href="#i-trash"/></svg><span>Убрать</span>
       </button>`;
  return `<tr class="${removed ? 'is-removed' : ''}">
    <td class="offer-cell" data-label="Оффер">
      <div class="offer-cell__main">
        <span class="offer-cell__name">${esc(offer.name)}</span>
        ${offerBadge(offer)}
      </div>
      <span class="offer-cell__id mono">#${offer.offer_id}</span>
    </td>
    <td class="num" data-label="Доля">
      <span class="share">
        <span class="share__main">
          <span class="share__value">${share}%</span>
          <label class="switch" title="Закреплённая доля не участвует в пересчёте">
            <input type="checkbox" data-pin="${offer.offer_id}" data-stream="${stream.id}"
              aria-label="${esc(pinLabel)}" ${offer.pinned ? 'checked' : ''} ${staged ? 'disabled' : ''}>
            <span class="switch__track" aria-hidden="true"></span>
          </label>
        </span>
        <span class="share__track"><span class="share__fill" style="width: ${share}%"></span></span>
      </span>
    </td>
    <td data-label="Статистика"></td>
    <td data-label="Тренды"></td>
    <td class="actions" data-label="">${action}</td>
  </tr>`;
}

function streamBadge(stream, hasOffers) {
  if (stream.dirty) {
    return '<span class="badge badge--warning"><span class="badge__dot"></span>Не опубликовано</span>';
  }
  if (!hasOffers) {
    return '<span class="badge badge--neutral"><span class="badge__dot"></span>Без офферов</span>';
  }
  return '<span class="badge badge--success"><span class="badge__dot"></span>Синхронизировано</span>';
}

function addOfferForm(stream) {
  return `<div class="stream__add">
    <div class="field">
      <label for="offer-input-${stream.id}">Добавить оффер</label>
      <div class="combo">
        <svg class="icon combo__icon" aria-hidden="true"><use href="#i-search"/></svg>
        <input id="offer-input-${stream.id}" type="text" class="combo-input" data-combo="${stream.id}"
          autocomplete="off" spellcheck="false" role="combobox" aria-expanded="false"
          aria-autocomplete="list" aria-controls="combo-list-${stream.id}"
          placeholder="Название или ID оффера">
        <ul class="combo-list" id="combo-list-${stream.id}" role="listbox" hidden></ul>
      </div>
    </div>
    <button class="btn btn--primary" data-add="${stream.id}" type="button">
      <svg class="icon" aria-hidden="true"><use href="#i-plus"/></svg><span>Добавить</span>
    </button>
  </div>`;
}

function renderStream(stream) {
  const isOffers = stream.schema === 'landings';
  const activeOffers = stream.offers.filter((offer) => offer.status !== 'removed');
  const kind = isOffers
    ? `Поток с офферами · ${activeOffers.length} ${plural(activeOffers.length, ['оффер', 'оффера', 'офферов'])}`
    : 'Редирект-поток · содержимое остаётся в Keitaro';
  let html = `<article class="card stream ${stream.dirty ? 'stream--dirty' : ''}">
    <header class="stream__head">
      <div class="stream__identity">
        <span class="stream__icon" aria-hidden="true">
          <svg class="icon"><use href="#${isOffers ? 'i-stream' : 'i-redirect'}"/></svg>
        </span>
        <div>
          <h3 class="stream__name">${esc(stream.name || 'Поток')}</h3>
          <p class="stream__kind">${kind}</p>
        </div>
      </div>
      <div class="stream__badges">${streamBadge(stream, isOffers)}</div>
    </header>`;
  if (!isOffers) {
    return `${html}</article>`;
  }
  if (stream.offers.length) {
    html += `<div class="table-wrap">
      <table class="table">
        <thead><tr>
          <th scope="col">Оффер</th>
          <th scope="col" class="num">Доля</th>
          <th scope="col">Статистика</th>
          <th scope="col">Тренды</th>
          <th scope="col"><span class="sr-only">Действия</span></th>
        </tr></thead>
        <tbody>${stream.offers.map((offer) => offerRow(stream, offer)).join('')}</tbody>
      </table>
    </div>`;
  } else {
    html += `<div class="empty">
      <span class="empty__icon" aria-hidden="true"><svg class="icon"><use href="#i-offers"/></svg></span>
      <p class="empty__title">В потоке пока нет офферов</p>
      <p class="empty__text">Добавьте первый оффер — доли распределятся автоматически.</p>
    </div>`;
  }
  html += addOfferForm(stream);
  if (stream.dirty) {
    html += `<footer class="stream__actions">
      <p class="stream__hint">Изменения сохранены локально и ещё не отправлены в Keitaro.</p>
      <div class="stream__buttons">
        <button class="btn" data-cancel="${stream.id}" type="button">Отменить изменения</button>
        <button class="btn btn--primary" data-push="${stream.id}" type="button">
          <svg class="icon" aria-hidden="true"><use href="#i-upload"/></svg><span>Опубликовать в Keitaro</span>
        </button>
      </div>
    </footer>`;
  }
  return `${html}</article>`;
}

function campaignHead(campaign) {
  const offers = campaign.streams.reduce(
    (total, stream) => total + (stream.schema === 'landings' ? stream.offers.filter((o) => o.status !== 'removed').length : 0),
    0,
  );
  const dirty = campaign.streams.filter((stream) => stream.dirty).length;
  return `<section class="campaign-head">
    <div>
      <p class="eyebrow">Кампания <span class="mono">#${campaign.id}</span></p>
      <h2 class="campaign-head__title">${esc(campaign.name)}</h2>
    </div>
    <dl class="meta">
      <div class="meta__item"><dt>Потоки</dt><dd>${campaign.streams.length}</dd></div>
      <div class="meta__item"><dt>Офферы</dt><dd>${offers}</dd></div>
      <div class="meta__item${dirty ? ' meta__item--warning' : ''}"><dt>Не опубликовано</dt><dd>${dirty}</dd></div>
    </dl>
  </section>`;
}

function render() {
  const campaign = state.currentCampaign;
  let html = campaignHead(campaign);
  html += campaign.streams.map(renderStream).join('');
  $('e-body').innerHTML = html;
  wireStreamActions();
}

async function runAction(button, action, okText, kind, onError) {
  setBusy(button, true);
  try {
    state.currentCampaign = await action();
    $('e-msg').innerHTML = '';
    render();
    setStatus(okText, kind);
    toast(okText, true);
  } catch (error) {
    show($('e-msg'), error.message, false);
    setStatus(error.message, 'err');
    toast(error.message, false);
    if (onError) onError();
    else setBusy(button, false);
  }
}

async function changeOffer(method, button, offerId, streamId) {
  if (!offerId) return;
  const campaignId = state.currentCampaign.id;
  const call = method === 'POST'
    ? () => api(`/api/campaigns/${campaignId}/offers`, {
        method,
        body: JSON.stringify({ offer_id: Number(offerId), stream_id: Number(streamId) }),
      })
    : () => api(`/api/campaigns/${campaignId}/offers/${offerId}?stream_id=${streamId}`, { method });
  const okText = method === 'POST'
    ? `Оффер #${offerId} добавлен, доли пересчитаны`
    : `Оффер #${offerId} убран из потока и перемещён в архив`;
  logAction(
    method === 'POST'
      ? `Добавление оффера #${offerId} в поток #${streamId}`
      : `Удаление оффера #${offerId} из потока #${streamId}`,
  );
  return runAction(button, call, okText, 'warn');
}

function restoreOffer(button, offerId, streamId) {
  const campaignId = state.currentCampaign.id;
  logAction(`Возврат оффера #${offerId} в поток #${streamId}`);
  return runAction(
    button,
    () => api(`/api/campaigns/${campaignId}/offers/${offerId}/restore?stream_id=${streamId}`, { method: 'POST' }),
    `Оффер #${offerId} возвращён в поток`,
    'warn',
  );
}

function pushStream(button, streamId) {
  const campaignId = state.currentCampaign.id;
  logAction(`Публикация потока #${streamId} в Keitaro`);
  return runAction(
    button,
    () => api(`/api/campaigns/${campaignId}/push?stream_id=${streamId}`, { method: 'POST' }),
    'Изменения опубликованы в Keitaro',
    'ok',
  );
}

async function cancelStream(button, streamId) {
  const campaignId = state.currentCampaign.id;
  logAction(`Отмена изменений потока #${streamId}`);
  return runAction(
    button,
    () => api(`/api/campaigns/${campaignId}/cancel?stream_id=${streamId}`, { method: 'POST' }),
    'Изменения отменены, поток снова синхронизирован',
    'ok',
  );
}

function pinOffer(checkbox, offerId, streamId, pinned) {
  const campaignId = state.currentCampaign.id;
  checkbox.disabled = true;
  logAction(
    pinned
      ? `Закрепление доли оффера #${offerId}`
      : `Открепление доли оффера #${offerId}`,
  );
  return runAction(
    null,
    () => api(`/api/campaigns/${campaignId}/offers/${offerId}/pin?stream_id=${streamId}&pinned=${pinned}`, { method: 'POST' }),
    pinned
      ? `Доля оффера #${offerId} закреплена — пересчёты её не изменят`
      : `Доля оффера #${offerId} больше не закреплена`,
    'warn',
    () => {
      checkbox.checked = !pinned;
      checkbox.disabled = false;
    },
  );
}

function wireStreamActions() {
  const body = $('e-body');
  body.querySelectorAll('[data-del]').forEach((button) => {
    button.onclick = () => changeOffer('DELETE', button, button.dataset.del, button.dataset.stream);
  });
  body.querySelectorAll('[data-add]').forEach((button) => {
    button.onclick = () => addFromCombo(button);
  });
  body.querySelectorAll('[data-restore]').forEach((button) => {
    button.onclick = () => restoreOffer(button, button.dataset.restore, button.dataset.stream);
  });
  body.querySelectorAll('[data-push]').forEach((button) => {
    button.onclick = () => pushStream(button, button.dataset.push);
  });
  body.querySelectorAll('[data-cancel]').forEach((button) => {
    button.onclick = () => cancelStream(button, button.dataset.cancel);
  });
  body.querySelectorAll('[data-pin]').forEach((checkbox) => {
    checkbox.onchange = () => pinOffer(checkbox, checkbox.dataset.pin, checkbox.dataset.stream, checkbox.checked);
  });
  body.querySelectorAll('[data-combo]').forEach((input) => {
    makeCombo(
      input,
      offerFetcher(input.dataset.combo),
      (item) => {
        input.value = `${item.name} (#${item.id})`;
        input.dataset.selectedId = item.id;
      },
      'Ищу офферы…',
    );
  });
}

function addFromCombo(button) {
  const streamId = button.dataset.add;
  const input = $('e-body').querySelector(`[data-combo="${streamId}"]`);
  const typed = input.value.trim();
  const offerId = input.dataset.selectedId || (/^\d+$/.test(typed) ? typed : '');
  if (!offerId) {
    show($('e-msg'), 'Выберите оффер из списка или введите его ID', false);
    return;
  }
  changeOffer('POST', button, offerId, streamId);
}

function comboStream(streamId) {
  return state.currentCampaign.streams.find((stream) => String(stream.id) === String(streamId));
}

function appendHighlighted(item, name, needle) {
  const index = needle ? name.toLowerCase().indexOf(needle) : -1;
  if (index < 0) {
    item.append(document.createTextNode(name));
    return;
  }
  item.append(document.createTextNode(name.slice(0, index)));
  const mark = document.createElement('mark');
  mark.textContent = name.slice(index, index + needle.length);
  item.append(mark, document.createTextNode(name.slice(index + needle.length)));
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
    const item = document.createElement('li');
    item.className = 'combo-empty';
    item.setAttribute('role', 'option');
    item.setAttribute('aria-disabled', 'true');
    item.textContent = 'Ничего не найдено';
    ui.list.append(item);
  }
  const needle = ui.query.trim().toLowerCase();
  for (const entry of items) {
    const item = document.createElement('li');
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', 'false');
    item.id = `${ui.list.id}-opt-${entry.id}`;
    item.dataset.offerId = entry.id;
    appendHighlighted(item, entry.name, needle);
    const idSpan = document.createElement('span');
    idSpan.className = 'muted mono';
    idSpan.textContent = `#${entry.id}`;
    item.append(idSpan);
    item.onmousedown = (event) => {
      event.preventDefault();
      selectComboOption(ui, entry);
    };
    ui.list.append(item);
  }
  ui.list.hidden = document.activeElement !== ui.input;
  ui.input.setAttribute('aria-expanded', String(!ui.list.hidden));
  ui.active = -1;
  positionCombo(ui);
}

function positionCombo(ui) {
  if (ui.list.hidden) return;
  ui.list.classList.remove('combo-list--up');
  const listRect = ui.list.getBoundingClientRect();
  const inputRect = ui.input.getBoundingClientRect();
  const barSpace = 56;
  if (
    listRect.bottom > window.innerHeight - barSpace &&
    inputRect.top > listRect.height + barSpace
  ) {
    ui.list.classList.add('combo-list--up');
  }
}

function renderComboState(ui, message, kind = 'loading') {
  ui.items = [];
  ui.active = -1;
  ui.list.innerHTML = '';
  const item = document.createElement('li');
  item.className = `combo-state combo-state--${kind}`;
  item.setAttribute('role', 'option');
  item.setAttribute('aria-disabled', 'true');
  if (kind === 'loading') {
    const spinner = document.createElement('span');
    spinner.className = 'spinner spinner--xs';
    spinner.setAttribute('aria-hidden', 'true');
    item.append(spinner);
  }
  item.append(document.createTextNode(message));
  ui.list.append(item);
  ui.list.hidden = document.activeElement !== ui.input;
  ui.input.setAttribute('aria-expanded', String(!ui.list.hidden));
  positionCombo(ui);
}

async function refreshCombo(ui) {
  const requestId = ++ui.requestId;
  if (document.activeElement === ui.input) renderComboState(ui, ui.loadingLabel);
  ui.input.setAttribute('aria-busy', 'true');
  let rows;
  try {
    rows = await ui.fetchItems(ui.query);
  } catch (error) {
    if (ui.requestId === requestId) {
      renderComboState(ui, `Не удалось загрузить: ${error.message}`, 'error');
      logEvent('err', `Не удалось загрузить список: ${error.message}`);
    }
    return;
  } finally {
    if (ui.requestId === requestId) ui.input.removeAttribute('aria-busy');
  }
  if (ui.requestId !== requestId) return;
  renderComboOptions(ui, rows);
}

function selectComboOption(ui, item) {
  ui.onSelect(item);
  closeCombo(ui);
}

function moveComboActive(ui, delta) {
  const options = [...ui.list.querySelectorAll('li[data-offer-id]')];
  if (!options.length) return;
  ui.active = (ui.active + delta + options.length) % options.length;
  options.forEach((item, index) => {
    item.classList.toggle('active', index === ui.active);
    item.setAttribute('aria-selected', String(index === ui.active));
  });
  ui.input.setAttribute('aria-activedescendant', options[ui.active].id);
  options[ui.active].scrollIntoView({ block: 'nearest' });
}

function makeCombo(input, fetchItems, onSelect, loadingLabel = 'Ищу…') {
  const ui = {
    input,
    list: $(input.getAttribute('aria-controls')),
    query: '',
    items: [],
    active: -1,
    timer: 0,
    requestId: 0,
    loadingLabel,
    fetchItems,
    onSelect,
  };
  input.onfocus = () => {
    ui.query = '';
    refreshCombo(ui);
  };
  input.oninput = () => {
    ui.query = input.value;
    ui.requestId += 1;
    input.dataset.selectedId = '';
    clearTimeout(ui.timer);
    ui.timer = setTimeout(() => refreshCombo(ui), COMBO_DEBOUNCE_MS);
  };
  input.onkeydown = (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (ui.list.hidden) refreshCombo(ui);
      else moveComboActive(ui, event.key === 'ArrowDown' ? 1 : -1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (!ui.list.hidden && ui.active >= 0) selectComboOption(ui, ui.items[ui.active]);
    } else if (event.key === 'Escape' || event.key === 'Tab') {
      closeCombo(ui);
    }
  };
  input.onblur = () => closeCombo(ui);
}

function offerFetcher(streamId) {
  return async (query) => {
    const rows = await api(`/api/offers/search?q=${encodeURIComponent(query)}&limit=${COMBO_LIMIT}`);
    const used = new Set(
      (comboStream(streamId)?.offers ?? []).filter((offer) => offer.status !== 'removed').map((offer) => offer.offer_id),
    );
    return rows.filter((offer) => !used.has(offer.id));
  };
}

function renderOffers(filter) {
  const needle = filter.trim().toLowerCase();
  const items = state.dict.offers.filter(
    (offer) => !needle || offer.name.toLowerCase().includes(needle) || String(offer.id) === needle,
  );
  $('offers-count').textContent = `${items.length} ${plural(items.length, ['оффер', 'оффера', 'офферов'])}`;
  $('offers-list').innerHTML = items.length
    ? items.map((offer) => `<div class="chip">
        <span class="chip__name">${esc(offer.name)}</span>
        <span class="chip__id mono">#${offer.id}</span>
      </div>`).join('')
    : '<p class="empty-inline">Ничего не найдено</p>';
}

function switchTab(name, focus = false) {
  const createActive = name === 'create';
  $('view-create').classList.toggle('hidden', !createActive);
  $('view-edit').classList.toggle('hidden', createActive);
  for (const tab of [$('tab-create'), $('tab-edit')]) {
    const active = tab.id === (createActive ? 'tab-create' : 'tab-edit');
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  }
}

const tabs = [$('tab-create'), $('tab-edit')];
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => switchTab(index === 0 ? 'create' : 'edit'));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : index === 0 ? 1 : 0;
    switchTab(target === 0 ? 'create' : 'edit', true);
  });
});

$('create-form').onsubmit = async (event) => {
  event.preventDefault();
  const button = event.target.querySelector('button[type="submit"]');
  const typedOffer = $('c-offer').value.trim();
  const offerId =
    $('c-offer').dataset.selectedId || (/^\d+$/.test(typedOffer) ? typedOffer : '');
  if (!offerId) {
    show($('c-msg'), 'Выберите оффер из списка или введите его ID', false);
    return;
  }
  const body = {
    name: $('c-name').value.trim(),
    geo: $('c-geo').value.trim().toUpperCase(),
    offer_id: Number(offerId),
    domain_id: $('c-domain').value ? Number($('c-domain').value) : null,
    group_id: $('c-group').value ? Number($('c-group').value) : null,
    source_id: $('c-source').value ? Number($('c-source').value) : null,
  };
  logAction(`Создание кампании «${body.name}»`);
  setBusy(button, true);
  try {
    const campaign = await api('/api/campaigns', { method: 'POST', body: JSON.stringify(body) });
    show($('c-msg'), `Создана кампания #${campaign.id} «${campaign.name}» — откройте её в редакторе`, true);
    toast(`Кампания #${campaign.id} создана`, true);
    setStatus(`Кампания #${campaign.id} «${campaign.name}» создана`, 'ok');
    $('e-id').value = campaign.id;
    $('e-id').dataset.selectedId = String(campaign.id);
  } catch (error) {
    show($('c-msg'), error.message, false);
    toast(error.message, false);
    setStatus(error.message, 'err');
  } finally {
    setBusy(button, false);
  }
};

$('e-load').onclick = () => loadCampaign(selectedCampaignId());
$('e-open').onclick = () => {
  if (state.currentCampaign) window.open(`${state.currentCampaign.keitaro_url}/admin/#!/campaigns/`, '_blank');
};
$('e-offers').onclick = () => {
  const panel = $('offers-panel');
  const hidden = panel.classList.toggle('hidden');
  $('e-offers').setAttribute('aria-expanded', String(!hidden));
  $('e-offers').querySelector('span').textContent = hidden ? 'Все офферы' : 'Скрыть офферы';
  if (!hidden) {
    renderOffers($('offers-filter').value);
    $('offers-filter').focus();
  }
};
$('offers-filter').oninput = (event) => renderOffers(event.target.value);
$('e-from').onchange = () => {
  if (state.currentCampaign) loadCampaign(String(state.currentCampaign.id));
};
$('e-to').onchange = () => {
  if (state.currentCampaign) loadCampaign(String(state.currentCampaign.id));
};

makeCombo(
  $('e-id'),
  (query) => api(`/api/campaigns/search?q=${encodeURIComponent(query)}&limit=${COMBO_LIMIT}`),
  (item) => {
    $('e-id').value = `${item.name} (#${item.id})`;
    $('e-id').dataset.selectedId = String(item.id);
    loadCampaign(String(item.id));
  },
  'Ищу кампании…',
);

init();
