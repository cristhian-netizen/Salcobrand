const collator = new Intl.Collator('es', {numeric: true, sensitivity: 'base'});
export function sortableValue(value) {
  if (typeof value === 'number') return value;
  const text = String(value ?? '').trim();
  if (!text || ['—', 'Sin dato', 'Sin datos'].includes(text)) return null;
  if (/^[-+]?\$?\s*\d[\d.,\s]*\s*%?$/.test(text)) {
    const clean = text.replace(/[$%\s]/g, '');
    const number = clean.includes(',') ? clean.replaceAll('.', '').replace(',', '.') : /^[-+]?\d{1,3}(\.\d{3})+$/.test(clean) ? clean.replaceAll('.', '') : clean;
    return Number(number);
  }
  return text;
}
export function compareValues(left, right, direction = 'asc') {
  const a = sortableValue(left), b = sortableValue(right);
  if (a == null || b == null) return a == null ? (b == null ? 0 : 1) : -1;
  const result = typeof a === 'number' && typeof b === 'number' ? a - b : collator.compare(String(a), String(b));
  return direction === 'desc' ? -result : result;
}
