'use client';
import { useState } from 'react';
import { api } from '../../lib/sb';
import { useApi, Header, Loading, ErrorBox } from './ui';
import Findings from '../alerts/Findings';
import Rejections from '../alerts/Rejections';
import OperationalAlerts from '../alerts/OperationalAlerts';
import HomeReadingDetail from '../home/HomeReadingDetail';

const INITIAL = { status: 'Pendiente', store: '', point: '', from: '', to: '' };

export default function Alerts({ user, go, notify }) {
  const [filters, setFilters] = useState(INITIAL);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);
  const invalid = filters.from && filters.to && filters.from > filters.to;
  const query = new URLSearchParams(filters).toString();
  const { data, loading, error: loadError, reload } = useApi(
    async () => invalid ? null : { ...(await api('/api/alerts?' + query)), query }, [query, invalid],
  );
  const current = !invalid && data?.query === query ? data : null;
  function change(key, value) {
    setFilters(previous => ({ ...previous, [key]: value, ...(key === 'store' ? { point: '' } : {}) }));
    setError('');
  }
  async function toggle(row) {
    setBusy(true);
    setError('');
    try {
      const status = row.status === 'Resuelta' ? 'Pendiente' : 'Resuelta';
      await api(`/api/alerts/readings/${row.reading.id}/${row.kind}`, {
        method: 'PATCH', body: { status, version: row.version, fingerprint: row.fingerprint },
      });
      notify(status === 'Resuelta' ? 'Hallazgo marcado como resuelto.' : 'Hallazgo reabierto.');
      await reload();
    } catch (exception) { setError(exception.message); }
    finally { setBusy(false); }
  }
  async function resolveSupplier(id) {
    setBusy(true);
    setError('');
    try {
      await api(`/api/supplier-stockouts/${id}/resolve`, { method: 'POST' });
      notify('Quiebre de proveedor resuelto.');
      await reload();
    } catch (exception) { setError(exception.message); }
    finally { setBusy(false); }
  }
  return <section>
    <Header eyebrow="Operación" title="Alertas" subtitle="Revisiones rechazadas y hallazgos de tus puntos de venta.">
      <button type="button" disabled={busy || loading || invalid} onClick={reload}>Actualizar</button>
    </Header>
    <fieldset className="sb-toolbar alerts-filters" aria-label="Filtros de alertas" disabled={busy}>
      <label>Estado del hallazgo<select value={filters.status} onChange={event => change('status', event.target.value)}>
        <option value="">Todos</option><option>Pendiente</option><option>Resuelta</option>
      </select></label>
      <label>Punto de venta<select value={filters.store} onChange={event => change('store', event.target.value)}>
        <option value="">Todos los PDV</option>{(data?.stores || []).map(store => <option key={store.code} value={store.code}>{store.name} · {store.code}</option>)}
      </select></label>
      <label>Góndola<select value={filters.point} onChange={event => change('point', event.target.value)}>
        <option value="">Todas las góndolas</option>{(data?.points || []).filter(point => !filters.store || point.store_id === filters.store)
          .map(point => <option key={point.id} value={point.id}>{point.name}</option>)}
      </select></label>
      {[['from', 'Desde'], ['to', 'Hasta']].map(([key, label]) => <label key={key}>{label}
        <input type="date" value={filters[key]} onChange={event => change(key, event.target.value)} />
      </label>)}
      <button type="button" disabled={busy} onClick={() => { setFilters(INITIAL); setError(''); }}>Limpiar filtros</button>
    </fieldset>
    <ErrorBox error={invalid ? 'La fecha Desde debe ser anterior o igual a Hasta.' : error || loadError} onRetry={invalid ? undefined : reload} />
    {loading && !current && <Loading text="Consultando hallazgos…" />}
    {current && <>
      <Rejections data={current} user={user} onOpen={setSelected} />
      <Findings rows={current.findings} user={user} busy={busy || loading} onToggle={toggle} onOpen={setSelected} />
      <OperationalAlerts data={current} user={user} go={go} busy={busy || loading} onResolve={resolveSupplier} />
    </>}
    {selected && <HomeReadingDetail row={selected} user={user} go={go} onClose={() => { setSelected(null); reload(); }} />}
  </section>;
}
