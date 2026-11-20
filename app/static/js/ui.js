export const $ = (id) => document.getElementById(id);

export function show(el, text, ok) {
  el.innerHTML = `<div class="msg ${ok ? 'ok' : 'err'}"></div>`;
  el.firstChild.textContent = text;
}

let statusTimer = 0;

export function setStatus(text, kind) {
  const bar = $('e-status');
  clearTimeout(statusTimer);
  bar.classList.remove('is-idle', 'warn', 'err');
  if (kind === 'warn' || kind === 'err') bar.classList.add(kind);
  $('e-status-text').textContent = text;
  $('e-status-time').textContent = new Date().toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  });
  if (kind === 'ok' || kind === 'warn') {
    statusTimer = setTimeout(() => bar.classList.add('is-idle'), 5000);
  }
}

export function setBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = busy;
  btn.setAttribute('aria-busy', String(busy));
}

export function toast(text, ok = true) {
  const stack = $('toast-stack');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = `toast toast--${ok ? 'ok' : 'err'}`;
  el.setAttribute('role', ok ? 'status' : 'alert');
  el.innerHTML = `
    <svg class="icon toast__icon" aria-hidden="true"><use href="#${ok ? 'i-check' : 'i-alert'}"/></svg>
    <span class="toast__text"></span>
    <button class="toast__close" type="button" aria-label="Закрыть уведомление">
      <svg class="icon" aria-hidden="true"><use href="#i-x"/></svg>
    </button>`;
  el.querySelector('.toast__text').textContent = text;
  const remove = () => el.remove();
  let timer = setTimeout(remove, ok ? 3600 : 5600);
  const restart = (delay) => {
    clearTimeout(timer);
    timer = setTimeout(remove, delay);
  };
  el.querySelector('.toast__close').addEventListener('click', remove);
  el.addEventListener('mouseenter', () => clearTimeout(timer));
  el.addEventListener('mouseleave', () => restart(1800));
  stack.append(el);
}

export function fill(select, items, withEmpty) {
  select.innerHTML = '';
  if (withEmpty) select.append(new Option('— не выбрано —', ''));
  for (const item of items) select.append(new Option(item.name, item.id));
}

export function confirmAction({ title, text, confirmLabel, danger = false }) {
  const dialog = $('confirm-dialog');
  $('confirm-title').textContent = title;
  $('confirm-text').textContent = text;
  const ok = $('confirm-ok');
  ok.textContent = confirmLabel;
  ok.className = danger ? 'btn btn--danger-solid' : 'btn btn--primary';
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
  });
}
