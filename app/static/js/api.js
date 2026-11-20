import { beginOperation, endOperation } from './activity.js';

function requestLabel(path, method) {
  if (method === 'GET') {
    if (path.startsWith('/api/dictionaries')) return 'Загрузка справочников';
    if (path.startsWith('/api/offers/search')) return 'Поиск офферов';
    if (path.startsWith('/api/campaigns/search')) return 'Поиск кампаний';
    if (path === '/api/campaigns') return 'Список кампаний';
    const campaign = path.match(/^\/api\/campaigns\/(\d+)/);
    if (campaign) return `Загрузка кампании #${campaign[1]}`;
    return 'Запрос данных';
  }
  if (path === '/api/campaigns') return 'Создание кампании';
  const restore = path.match(/^\/api\/campaigns\/(\d+)\/offers\/(\d+)\/restore/);
  if (restore) return `Возврат оффера #${restore[2]}`;
  const pin = path.match(/^\/api\/campaigns\/(\d+)\/offers\/(\d+)\/pin/);
  if (pin) return path.includes('pinned=false')
    ? `Открепление оффера #${pin[2]}`
    : `Закрепление оффера #${pin[2]}`;
  const offers = path.match(/^\/api\/campaigns\/(\d+)\/offers(?:\/(\d+))?/);
  if (offers) {
    return method === 'DELETE' ? `Удаление оффера #${offers[2]}` : 'Добавление оффера';
  }
  if (path.includes('/push')) return 'Публикация в Keitaro';
  if (path.includes('/cancel')) return 'Отмена изменений';
  return 'Изменение данных';
}

function errorMessage(data) {
  const d = data && data.detail;
  if (Array.isArray(d)) {
    return d.map((e) => (e.loc || []).slice(1).join('.') + ': ' + e.msg).join('; ');
  }
  if (typeof d === 'string') return d;
  return JSON.stringify(data);
}

export async function api(path, opts = {}) {
  const { label, ...init } = opts;
  const operation = beginOperation(label || requestLabel(path, init.method || 'GET'));
  try {
    const r = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
    const text = await r.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!r.ok) throw new Error(errorMessage(data));
    return data;
  } finally {
    endOperation(operation);
  }
}
