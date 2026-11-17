import {normalize, regionFor, byLocationName} from '../../lib/locations.mjs';
export {regionFor, byLocationName} from '../../lib/locations.mjs';

export function captureStores(stores, points) {
  const known = new Map(stores.map(store => [store.code, store]));
  // Historical points can predate a PDV master record. Their scoped summary is
  // still the authority for whether the account can capture that point.
  for (const point of points) {
    const code = point.store_id || point.store_key || point.id;
    if (point.can_capture !== false && !known.has(code)) {
      known.set(code, {code, name: point.store_name || point.store || code, status: 'Activo', region: '', commune: ''});
    }
  }
  return [...known.values()].filter(store => store.status === 'Activo').sort(byLocationName);
}

export function filterCaptureStores(stores, regions, filters) {
  const selectedRegion = regionFor(regions, filters.region);
  const query = normalize(filters.query);
  return stores.filter(store => {
    const byCommune = regions.filter(region => region.communes.some(commune => normalize(commune.name) === normalize(store.commune)));
    const storedRegion = regionFor(regions, store.region) || (byCommune.length === 1 ? byCommune[0] : null);
    return (!filters.region || (selectedRegion && storedRegion?.code === selectedRegion.code))
      && (!filters.commune || normalize(store.commune) === normalize(filters.commune))
      && (!query || normalize(store.name + ' ' + store.code).includes(query));
  });
}

export const pointStoreCode = point => point.store_id || point.store_key || point.id;

// A type can have several physical records. Choose a compatible reference,
// preserving a single planogram rather than silently choosing between different plans.
export function capturePointForType(points, typeId, classification, plansEnabled = true) {
  const candidates = points.filter(point => point.infrastructure?.type_id === typeId && point.can_capture !== false);
  if (!plansEnabled) {
    candidates.sort((a,b) => (a.infrastructure.number - b.infrastructure.number) || a.id.localeCompare(b.id));
    return {point:candidates[0] || null,ambiguous:false};
  }
  const subs = classification.subcategories || [];
  const ranked = candidates.map(point => {
    const plan = point.planogram_classification;
    const match = plan?.category && (!classification.category || (plan.category === classification.category && subs.every(sub => plan.subcategories.includes(sub))));
    return {point,rank:match ? 0 : !plan?.category && point.planogram_id ? 1 : !point.planogram_id ? 2 : 3};
  }).filter(item => item.rank < 3);
  const rank = Math.min(...ranked.map(item => item.rank));
  const eligible = ranked.filter(item => item.rank === rank).map(item => item.point);
  if (new Set(eligible.map(point => point.planogram_id || '')).size > 1) return {point:null,ambiguous:true};
  eligible.sort((a,b) => (a.infrastructure.number - b.infrastructure.number) || a.id.localeCompare(b.id));
  return {point:eligible[0] || null,ambiguous:false};
}
