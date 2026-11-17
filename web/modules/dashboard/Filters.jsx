import {orderRegionNames} from '../../lib/locations.mjs';

export const INITIAL = { region: '', commune: '', pdv_type: '', store: '', from: '', to: '', category: '', subcategory: '' };

const sorted = values => [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, 'es'));

export default function Filters({ value, options, geography = [], types = [], categories = {}, onChange }) {
  function change(key, next) {
    const reset = key === 'region' ? { commune: '', store: '' } : key === 'category' ? {subcategory: ''} : ['commune', 'pdv_type'].includes(key) ? { store: '' } : {};
    onChange({ ...value, ...reset, [key]: next });
  }
  const geographic = options.filter(store => (!value.region || store.region === value.region) && (!value.commune || store.commune === value.commune));
  const stores = geographic.filter(store => !value.pdv_type || store.pdv_type === value.pdv_type);
  const communes = geography.find(region => region.name === value.region)?.communes || [];
  return <div className="sb-toolbar dashboard-filters" aria-label="Filtros del dashboard">
    <label>Región<select value={value.region} onChange={event => change('region', event.target.value)}>
      <option value="">Todas las regiones</option>{orderRegionNames([...geography.map(region => region.name), ...options.map(store => store.region)], geography).map(region => <option key={region}>{region}</option>)}
    </select></label>
    <label>Comuna<select disabled={!value.region} value={value.commune} onChange={event => change('commune', event.target.value)}>
      <option value="">{value.region ? 'Todas las comunas' : 'Selecciona primero una región'}</option>
      {sorted([...communes.map(commune => commune.name), ...options.filter(store => store.region === value.region).map(store => store.commune)]).map(commune => <option key={commune}>{commune}</option>)}
    </select></label>
    <label>Tipo de PDV<select value={value.pdv_type} onChange={event => change('pdv_type', event.target.value)}>
      <option value="">Todos los tipos</option>{sorted([...types, ...geographic.map(store => store.pdv_type)]).map(type => <option key={type}>{type}</option>)}
    </select></label>
    <label>Punto de venta<select value={value.store} onChange={event => change('store', event.target.value)}>
      <option value="">Todos los PDV</option>{stores.map(store => <option key={store.code} value={store.code}>{store.name} · {store.code}</option>)}
    </select></label>
    <label>Categoría<select value={value.category} onChange={event => change('category', event.target.value)}><option value="">Todas las categorías</option>{sorted(Object.keys(categories)).map(category => <option key={category}>{category}</option>)}</select></label>
    <label>Subcategoría<select value={value.subcategory} disabled={!value.category} onChange={event => change('subcategory', event.target.value)}><option value="">{value.category ? 'Todas las subcategorías' : 'Selecciona primero una categoría'}</option>{sorted(categories[value.category] || []).map(subcategory => <option key={subcategory}>{subcategory}</option>)}</select></label>
    {[['from', 'Desde'], ['to', 'Hasta']].map(([key, label]) => <label key={key}>{label}<input type="date" value={value[key]} onChange={event => change(key, event.target.value)} /></label>)}
    <button type="button" onClick={() => onChange(INITIAL)}>Limpiar filtros</button>
  </div>;
}
