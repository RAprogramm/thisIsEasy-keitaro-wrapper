import { plural } from './format.js';

const MAX_EVENTS = 100;
const LEVELS = {
  ok: 'Успешно',
  warn: 'Предупреждение',
  err: 'Ошибка',
  info: 'Информация',
};

const state = {
  active: new Map(),
  events: [],
  last: { text: 'Готово к работе', kind: '', at: null },
  open: false,
  seq: 0,
  tick: 0,
};

function byId(id) {
  return document.getElementById(id);
}

function timeText(date, withSeconds = false) {
  return date.toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  });
}

function scrollToBottom(list) {
  list.scrollTop = list.scrollHeight;
}

function setText(node, value) {
  if (node && node.textContent !== value) node.textContent = value;
}

function renderStatus() {
  const bar = byId('activity');
  const text = byId('activity-text');
  const time = byId('activity-time');
  const dot = byId('activity-dot');
  const spinner = byId('activity-spinner');
  if (!bar || !text) return;
  const running = [...state.active.values()];
  const busy = running.length > 0;
  bar.classList.toggle('is-busy', busy);
  bar.classList.remove('is-ok', 'is-warn', 'is-err', 'is-info');
  if (busy) {
    const latest = running[running.length - 1];
    const elapsed = Math.floor((Date.now() - running[0].startedAt) / 1000);
    const label =
      running.length > 1 ? `${latest.label} · ещё ${running.length - 1}` : latest.label;
    setText(text, label);
    setText(time, elapsed > 0 ? `${elapsed} с` : '');
    spinner.hidden = false;
    dot.hidden = true;
    return;
  }
  if (state.last.kind) bar.classList.add(`is-${state.last.kind}`);
  spinner.hidden = true;
  dot.hidden = false;
  setText(text, state.last.text);
  setText(time, state.last.at ? timeText(state.last.at) : '');
}

function renderRunning() {
  const list = byId('activity-running');
  if (!list) return;
  list.innerHTML = '';
  if (!state.active.size) {
    const empty = document.createElement('li');
    empty.className = 'activity__empty';
    empty.textContent = 'Нет активных запросов';
    list.append(empty);
    return;
  }
  for (const [id, operation] of state.active) {
    const item = document.createElement('li');
    item.className = 'activity__running-item';
    item.dataset.opId = String(id);
    const spinner = document.createElement('span');
    spinner.className = 'spinner spinner--xs';
    spinner.setAttribute('aria-hidden', 'true');
    const label = document.createElement('span');
    label.className = 'activity__running-label';
    label.textContent = operation.label;
    const elapsed = document.createElement('span');
    elapsed.className = 'activity__running-time';
    elapsed.textContent = `${Math.floor((Date.now() - operation.startedAt) / 1000)} с`;
    item.append(spinner, label, elapsed);
    list.append(item);
  }
}

function updateRunningTimes() {
  const list = byId('activity-running');
  if (!list) return;
  for (const [id, operation] of state.active) {
    const time = list.querySelector(
      `[data-op-id="${id}"] .activity__running-time`,
    );
    if (time) {
      time.textContent = `${Math.floor((Date.now() - operation.startedAt) / 1000)} с`;
    }
  }
}

function levelPrefix(level) {
  return LEVELS[level] ? `${LEVELS[level]}: ` : '';
}

function createEventItem(event) {
  const item = document.createElement('li');
  item.className = `activity__event activity__event--${event.level}`;
  const time = document.createElement('time');
  time.className = 'activity__event-time';
  time.dateTime = event.date.toISOString();
  time.textContent = timeText(event.date, true);
  const dot = document.createElement('span');
  dot.className = 'activity__event-dot';
  dot.setAttribute('aria-hidden', 'true');
  const text = document.createElement('span');
  text.className = 'activity__event-text';
  const prefix = document.createElement('span');
  prefix.className = 'sr-only';
  prefix.textContent = levelPrefix(event.level);
  text.append(prefix, document.createTextNode(event.text));
  item.append(time, dot, text);
  return item;
}

function emptyEventsItem() {
  const empty = document.createElement('li');
  empty.className = 'activity__empty';
  empty.textContent = 'Пока нет событий';
  return empty;
}

function renderEvents() {
  const list = byId('activity-events');
  if (!list) return;
  list.innerHTML = '';
  if (!state.events.length) {
    list.append(emptyEventsItem());
    return;
  }
  for (const event of state.events) list.append(createEventItem(event));
  scrollToBottom(list);
}

function appendEvent(event) {
  const list = byId('activity-events');
  if (!list) return;
  if (!list.querySelector('.activity__event')) list.innerHTML = '';
  list.append(createEventItem(event));
  scrollToBottom(list);
}

function renderBadge() {
  const badge = byId('activity-badge');
  if (!badge) return;
  const errors = state.events.filter((event) => event.level === 'err').length;
  badge.hidden = state.events.length === 0;
  badge.textContent = String(state.events.length);
  badge.classList.toggle('activity__badge--err', errors > 0);
  badge.title = errors
    ? `${state.events.length} ${plural(state.events.length, ['событие', 'события', 'событий'])}, ошибок: ${errors}`
    : `${state.events.length} ${plural(state.events.length, ['событие', 'события', 'событий'])}`;
}

function ensureTicker() {
  if (state.active.size && !state.tick) {
    state.tick = setInterval(() => {
      renderStatus();
      updateRunningTimes();
    }, 1000);
    return;
  }
  if (!state.active.size && state.tick) {
    clearInterval(state.tick);
    state.tick = 0;
  }
}

export function initActivity() {
  const toggle = byId('activity-toggle');
  const activity = byId('activity');
  if (!toggle || !activity) return;
  toggle.addEventListener('click', () => setOpen(!state.open));
  byId('activity-clear').addEventListener('click', () => {
    state.events = [];
    renderEvents();
    renderBadge();
  });
  activity.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !state.open) return;
    setOpen(false);
    toggle.focus();
  });
  renderStatus();
  renderBadge();
  renderRunning();
  renderEvents();
}

function setOpen(open) {
  state.open = open;
  byId('activity-panel').hidden = !open;
  const toggle = byId('activity-toggle');
  toggle.setAttribute('aria-expanded', String(open));
  if (!open) return;
  renderRunning();
  const list = byId('activity-events');
  if (list) scrollToBottom(list);
}

export function beginOperation(label) {
  const id = ++state.seq;
  state.active.set(id, { label, startedAt: Date.now() });
  renderStatus();
  renderRunning();
  ensureTicker();
  return id;
}

export function endOperation(id) {
  if (!state.active.delete(id)) return;
  renderStatus();
  renderRunning();
  ensureTicker();
}

export function setSummary(text, kind = '') {
  state.last = { text, kind, at: new Date() };
  renderStatus();
}

export function logEvent(level, text) {
  const event = { level, text, date: new Date() };
  const list = byId('activity-events');
  const overflow = state.events.length >= MAX_EVENTS;
  state.events.push(event);
  if (overflow) {
    state.events.shift();
    if (list) list.querySelector('.activity__event')?.remove();
  }
  appendEvent(event);
  state.last = { text, kind: level, at: event.date };
  renderStatus();
  renderBadge();
}

export function logAction(text) {
  logEvent('info', text);
}
