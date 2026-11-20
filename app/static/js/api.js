export function errorMessage(data) {
  const d = data && data.detail;
  if (Array.isArray(d)) return d.map(e => (e.loc || []).slice(1).join('.') + ': ' + e.msg).join('; ');
  if (typeof d === 'string') return d;
  return JSON.stringify(data);
}

export async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
  if (!r.ok) throw new Error(errorMessage(data));
  return data;
}
