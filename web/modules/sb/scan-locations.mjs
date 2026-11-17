const collator = new Intl.Collator('es', {sensitivity: 'base', numeric: true});
export const byLocationName = (left, right) => collator.compare(left.name, right.name);

const normalize = value => String(value || '').normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '').toLowerCase()
  .replace(/^region\s+(?:de\s+|del\s+)?/, '').replace(/[^a-z0-9]/g, '');
const aliases = {'13': ['Metropolitana'], '06': ["O'Higgins"], '11': ['Aysén'], '12': ['Magallanes']};

export function regionFor(regions, value) {
  if (!value) return null;
  return regions.find(region => [region.name, region.code, region.abbreviation, ...(aliases[region.code] || [])]
    .some(label => normalize(label) === normalize(value))) || null;
}

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
