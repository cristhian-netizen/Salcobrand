const collator = new Intl.Collator('es', {sensitivity: 'base', numeric: true});
export const byLocationName = (left, right) => collator.compare(left.name, right.name);

export const normalize = value => String(value || '').normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '').toLowerCase()
  .replace(/^region\s+(?:de\s+|del\s+)?/, '').replace(/[^a-z0-9]/g, '');
const aliases = {'13': ['Metropolitana'], '06': ["O'Higgins"], '11': ['Aysén'], '12': ['Magallanes']};

export function regionFor(regions, value) {
  if (!value) return null;
  return regions.find(region => [region.name, region.code, region.abbreviation, ...(aliases[region.code] || [])]
    .some(label => normalize(label) === normalize(value))) || null;
}


const REGION_ORDER = ['15','01','02','03','04','05','13','06','07','16','08','09','14','10','11','12'];
export const orderRegions = regions => [...regions].sort((a,b) => REGION_ORDER.indexOf(a.code) - REGION_ORDER.indexOf(b.code));
export const orderRegionNames = (names, regions) => [...new Set(names.filter(Boolean))].sort((a,b) => {
  const left = REGION_ORDER.indexOf(regionFor(regions,a)?.code), right = REGION_ORDER.indexOf(regionFor(regions,b)?.code);
  return (left < 0 ? 99 : left) - (right < 0 ? 99 : right) || collator.compare(a,b);
});
