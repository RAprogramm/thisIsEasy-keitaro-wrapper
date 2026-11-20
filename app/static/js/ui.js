export const $ = (id) => document.getElementById(id);

export function esc(v) { const d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML; }

export function show(el, text, ok) { el.innerHTML = `<div class="msg ${ok ? 'ok' : 'err'}"></div>`; el.firstChild.textContent = text; }

export function toast(text, ok = true) {
  const stack = $('toast-stack');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = `toast ${ok ? 'ok' : 'err'}`;
  el.setAttribute('role', ok ? 'status' : 'alert');
  el.textContent = text;
  stack.append(el);
  let timer = setTimeout(() => el.remove(), ok ? 3200 : 5200);
  el.addEventListener('mouseenter', () => clearTimeout(timer));
  el.addEventListener('mouseleave', () => { timer = setTimeout(() => el.remove(), 1600); });
  el.addEventListener('click', () => el.remove());
}

export function setStatus(text, kind) {
  const bar = $('e-status');
  bar.classList.remove('hidden', 'warn', 'err');
  if (kind) bar.classList.add(kind);
  $('e-status-text').textContent = text;
  $('e-status-time').textContent = new Date().toLocaleTimeString('ru-RU');
}

export function fill(sel, items, withEmpty) {
  sel.innerHTML = '';
  if (withEmpty) sel.append(new Option('— по умолчанию —', ''));
  for (const it of items) sel.append(new Option(it.name, it.id));
}
