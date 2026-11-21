import { $, show, toast, setStatus, setBusy } from './ui.js';
import { initActivity, logAction, logEvent } from './activity.js';
import { api } from './api.js';
import { state } from './state.js';
import { esc, plural } from './format.js';
import { makeCombo, COMBO_LIMIT } from './combo.js';

function comboId(input) {
  const typed = input.value.trim();
  return input.dataset.selectedId || (/^\d+$/.test(typed) ? typed : '');
}

function setComboSelection(input, item) {
  input.value = `${item.name} (#${item.id})`;
  input.dataset.selectedId = String(item.id);
}

function reportError(message, messageEl = $('e-msg')) {
  show(messageEl, message, false);
  setStatus(message, 'err');
  toast(message, false);
}

function clearEditor() {
  state.currentCampaign = null;
  $('e-body').innerHTML = '';
  $('e-open').disabled = true;
  showEditorLevel(false);
}

function showEditorLevel(streamsView) {
  const campaign = state.currentCampaign;
  const atStreams = streamsView && Boolean(campaign);
  $('edit-pick').classList.toggle('hidden', atStreams);
  $('edit-streams').classList.toggle('hidden', !atStreams);
  $('e-crumb-root').classList.toggle('hidden', !atStreams);
  $('e-crumb-root-current').classList.toggle('hidden', atStreams);
  $('e-crumb-sep').classList.toggle('hidden', !atStreams);
  $('e-crumb-campaign').classList.toggle('hidden', !atStreams);
  if (campaign) {
    $('e-crumb-campaign').textContent = campaign.name;
    $('e-title').textContent = `${campaign.name} (#${campaign.id})`;
  }
}

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
  return comboId($('e-id'));
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
  makeCombo(
    $('c-offer'),
    (query) => api(`/api/offers/search?q=${encodeURIComponent(query)}&limit=${COMBO_LIMIT}`),
    (item) => setComboSelection($('c-offer'), item),
    'Ищу офферы…',
  );
  makeGeoCombo();
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
    clearEditor();
    reportError(error.message);
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
  return `<tr class="${staged ? 'is-removed' : ''}">
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
  showEditorLevel(true);
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
    reportError(error.message);
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
      (item) => setComboSelection(input, item),
      'Ищу офферы…',
    );
  });
}

function addFromCombo(button) {
  const streamId = button.dataset.add;
  const input = $('e-body').querySelector(`[data-combo="${streamId}"]`);
  const offerId = comboId(input);
  if (!offerId) {
    show($('e-msg'), 'Выберите оффер из списка или введите его ID', false);
    return;
  }
  changeOffer('POST', button, offerId, streamId);
}

function comboStream(streamId) {
  return state.currentCampaign.streams.find((stream) => String(stream.id) === String(streamId));
}

let countryItems = null;

async function countryFetcher(query) {
  if (!countryItems) {
    const codes = await api('/api/countries');
    const names = new Intl.DisplayNames(['ru'], { type: 'region' });
    countryItems = codes.map((code) => ({ id: code, name: `${code} — ${names.of(code) ?? code}` }));
  }
  const seg = query.split(',').pop().trim().toLowerCase();
  const matched = !seg
    ? countryItems
    : countryItems.filter((c) => c.name.toLowerCase().includes(seg));
  return matched.slice(0, COMBO_LIMIT);
}

function makeGeoCombo() {
  makeCombo(
    $('c-geo'),
    countryFetcher,
    (item) => {
      const parts = $('c-geo').value.split(',');
      parts.pop();
      $('c-geo').value = [...parts, item.id].join(',');
    },
    'Ищу страну…',
  );
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
    ? `<ul class="offer-list">
        ${items
          .map(
            (offer) => `<li>
              <span class="offer-list__name">${esc(offer.name)}</span>
              <span class="offer-list__id mono">#${offer.id}</span>
            </li>`,
          )
          .join('')}
      </ul>`
    : '<p class="empty-inline">Ничего не найдено</p>';
}

function switchTab(name, focus = false) {
  const createActive = name === 'create';
  $('view-create').classList.toggle('hidden', !createActive);
  $('view-edit').classList.toggle('hidden', createActive);
  if (!createActive) showEditorLevel(Boolean(state.currentCampaign));
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
  const offerId = comboId($('c-offer'));
  if (!offerId) {
    show($('c-msg'), 'Выберите оффер из списка или введите его ID', false);
    return;
  }
  const body = {
    name: $('c-name').value.trim(),
    geo: $('c-geo').value.trim().toUpperCase(),
    offer_id: Number(offerId),
  };
  logAction(`Создание кампании «${body.name}»`);
  setBusy(button, true);
  try {
    const campaign = await api('/api/campaigns', { method: 'POST', body: JSON.stringify(body) });
    show($('c-msg'), `Создана кампания #${campaign.id} «${campaign.name}» — откройте её в редакторе`, true);
    toast(`Кампания #${campaign.id} создана`, true);
    setStatus(`Кампания #${campaign.id} «${campaign.name}» создана`, 'ok');
    setComboSelection($('e-id'), campaign);
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
  if (state.currentCampaign) {
    window.open(`${state.currentCampaign.keitaro_url}/admin/#!/campaigns/${state.currentCampaign.id}/edit`, '_blank');
  }
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
    setComboSelection($('e-id'), item);
    if ($('e-autofetch').checked) {
      loadCampaign(String(item.id));
      return;
    }
    clearEditor();
    setStatus(`Кампания #${item.id} выбрана — нажмите «Загрузить потоки»`, 'warn');
  },
  'Ищу кампании…',
);

$('e-crumb-root').onclick = () => {
  clearEditor();
  $('e-id').value = '';
  delete $('e-id').dataset.selectedId;
  $('e-id').focus();
};

init();
