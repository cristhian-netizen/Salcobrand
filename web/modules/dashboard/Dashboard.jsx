'use client';
import { useEffect, useState } from 'react';
import { api, download } from '../../lib/sb';
import { profileOf } from '../../lib/profiles.mjs';
import { enabled } from '../identity/identity.mjs';
import { useApi, Header, Loading, ErrorBox, Card } from '../sb/ui';
import HomeReadingDetail from '../home/HomeReadingDetail';
import Filters, { INITIAL } from './Filters';
import Performance from './Performance';
import Operations from './Operations';
import Brands from './Brands';
import NetworkCalendar from './NetworkCalendar';
import DashboardTable from './DashboardTable';
import Preferences, { DEFAULT_PANELS, loadPreferences } from './Preferences';

const PENDING = [
  { name: 'Sell-out / Sell-in vs. sell-out', source: 'Ventas y despachos por PDV, producto y fecha.' },
  { name: 'Rotación / Velocidad de venta / Días de cobertura', source: 'Inventario y ventas.' },
  { name: 'Integridad de precio', source: 'Precio observado y precio de referencia vigente por producto.' },
  { name: 'Ejecución de promociones', source: 'Promociones vigentes y exhibición esperada.' },
  { name: 'Mermas / vencimientos', source: 'Evidencia legible y confirmación del hallazgo.' },
];

export default function Dashboard({ user, go, notify }) {
  const [filters, setFilters] = useState(INITIAL);
  const [selected, setSelected] = useState(null);
  const [customizing, setCustomizing] = useState(false);
  const [panels, setPanels] = useState(DEFAULT_PANELS);
  const [busy, setBusy] = useState(false);
  const [exportError, setExportError] = useState('');
  const preferenceKey = 'nv-dashboard-' + (user.tenant?.id || 'salcobrand') + '-' + profileOf(user);
  useEffect(() => setPanels(loadPreferences(preferenceKey)), [preferenceKey]);
  const invalid = filters.from && filters.to && filters.from > filters.to;
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value)).toString();
  const { data, error, loading, reload } = useApi(async () => invalid ? null : { ...(await api('/api/dashboard?' + query)), query }, [query, invalid]);
  const current = data?.query === query && !invalid ? data : null;
  async function exportFile(kind) {
    setBusy(true);
    setExportError('');
    try { await download(`/api/dashboard/export/${kind}.csv?${query}`, `Neuravision_Dashboard_${kind}.csv`); }
    catch (exception) { setExportError(exception.message); }
    finally { setBusy(false); }
  }
  function savePreferences(value) {
    try {
      localStorage.setItem(preferenceKey, JSON.stringify(value));
      setPanels(value);
      setCustomizing(false);
    } catch { notify('No se pudieron guardar las preferencias en este navegador.'); }
  }
  return <section>
    <Header eyebrow="Análisis" title="Dashboards" subtitle="Resultados y calidad de las mediciones por ubicación.">
      <button type="button" onClick={() => setCustomizing(true)}>Personalizar indicadores</button>
      <button type="button" disabled={busy || !current || loading} onClick={() => exportFile('operation')}>Exportar KPI operativos</button>
      <button type="button" disabled={busy || !current || loading} onClick={() => exportFile('measurements')}>Descargar CSV</button>
    </Header>
    <Filters value={filters} options={data?.options || []} geography={data?.geography} types={data?.pdvTypes} categories={data?.categories} onChange={setFilters} />
    <ErrorBox error={invalid ? 'La fecha Desde debe ser anterior o igual a Hasta.' : exportError || error} onRetry={invalid ? undefined : reload} />
    {loading && !current && <Loading text="Cargando dashboard…" />}
    {current && <>
      <Performance data={current} exportFile={exportFile} busy={busy} onOpen={setSelected} />
      {panels.operation && <>
        <Operations data={current.operation} cutoff={current.cutoff} />
        <NetworkCalendar data={current} filters={filters} onSelect={store => setFilters({ ...filters, store })} />
      </>}
      {enabled(user, 'vision') && panels.vision && <Brands data={current.brands} />}
      {user.tenant?.modules?.sales && <Card title="Ventas e inventario"><p>Requiere integración de ventas e inventario.</p></Card>}
      {panels.business && <Card title="Indicadores por conectar" body={false}><DashboardTable rows={PENDING} columns={[
        ['name', 'Indicador'], ['source', 'Datos necesarios'],
      ]} /></Card>}
    </>}
    {customizing && <Preferences value={panels} onSave={savePreferences} onClose={() => setCustomizing(false)} />}
    {selected && <HomeReadingDetail row={selected} user={user} go={go} onClose={() => { setSelected(null); reload(); }} />}
  </section>;
}
