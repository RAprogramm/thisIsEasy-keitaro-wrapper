// Shared autocomplete widget used by the creator and the editor.

import { $ } from './ui.js';
import { logEvent } from './activity.js';

const COMBO_DEBOUNCE_MS = 250;
export const COMBO_LIMIT = 20;

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
    const nameSpan = document.createElement('span');
    nameSpan.className = 'combo-list__name';
    appendHighlighted(nameSpan, entry.name, needle);
    item.append(nameSpan);
    if (/^\d+$/.test(String(entry.id))) {
      const idSpan = document.createElement('span');
      idSpan.className = 'muted mono';
      idSpan.textContent = `#${entry.id}`;
      item.append(idSpan);
    }
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

function suggestsOnText(input) {
  return !input.dataset.selectedId && Boolean(input.value.trim());
}

export function makeCombo(input, fetchItems, onSelect, loadingLabel = 'Ищу…') {
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
    ui.query = input.value;
    if (suggestsOnText(input)) refreshCombo(ui);
    else closeCombo(ui);
  };
  input.oninput = () => {
    ui.query = input.value;
    ui.requestId += 1;
    input.dataset.selectedId = '';
    clearTimeout(ui.timer);
    if (!input.value.trim()) {
      closeCombo(ui);
      return;
    }
    ui.timer = setTimeout(() => refreshCombo(ui), COMBO_DEBOUNCE_MS);
  };
  input.onkeydown = (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (ui.list.hidden) {
        if (suggestsOnText(input)) refreshCombo(ui);
      } else moveComboActive(ui, event.key === 'ArrowDown' ? 1 : -1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (!ui.list.hidden && ui.active >= 0) selectComboOption(ui, ui.items[ui.active]);
    } else if (event.key === 'Escape' || event.key === 'Tab') {
      closeCombo(ui);
    }
  };
  input.onblur = () => closeCombo(ui);
}
