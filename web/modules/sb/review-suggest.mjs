// Gemini pre-labeling on the review screen: a suggestion only pre-selects a candidate. Confirming stores the
// human's choice exactly as before; NINGUNO or low confidence pre-selects nothing and says so.
export const MIN_CONFIDENCE = 0.5;

export function suggestionState(item) {
  const s = item?.suggestion;
  if (!s) return {kind: 'none'};
  if (!s.title || typeof s.confidence !== 'number' || s.confidence < MIN_CONFIDENCE) return {kind: 'sin-sugerencia'};
  return {kind: 'ok', title: s.title, pct: Math.round(s.confidence * 100)};
}

export function preselect(item, fallback) {
  const state = suggestionState(item);
  if (state.kind === 'ok') return state.title;
  if (state.kind === 'sin-sugerencia') return '';
  return fallback || '';
}

export function applySuggestions(payloads, readingId, suggestions) {
  const byKey = new Map((suggestions || []).map(s => [`${s.image_index}-${s.item_index}`, s]));
  return (payloads || []).map(p => p.reading_id !== readingId ? p : {...p, items: p.items.map(item => {
    const found = byKey.get(`${item.image_index}-${item.item_index}`);
    return found ? {...item, suggestion: found} : item;
  })});
}

export function suggestSummary(result) {
  const parts = [];
  if (result.sugeridos) parts.push(`${result.sugeridos} con sugerencia`);
  if (result.sin_sugerencia) parts.push(`${result.sin_sugerencia} sin sugerencia`);
  if (result.en_cache) parts.push(`${result.en_cache} ya sugeridos`);
  if (result.errores) parts.push(`${result.errores} con error${result.error ? ` (${result.error})` : ''}`);
  return 'IA: ' + (parts.join(' · ') || 'sin recortes pendientes') + '. Confirma o corrige cada recorte.';
}
