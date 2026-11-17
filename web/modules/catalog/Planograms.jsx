'use client';
import { useEffect, useState } from 'react';
import { api } from '../../lib/sb';
import {
  useApi,
  Header,
  Card,
  Loading,
  Empty,
  ErrorBox,
  Modal,
  Pill,
} from '../sb/ui';
import { ImportPlanogram } from '../sb/Planograms';
import PlanogramForm from './PlanogramForm';
import { enc, sortByName } from '../management/shared';

export default function Planograms({ rest, go, notify }) {
  const data = useApi(async () => {
    const [catalog, stores, locations] = await Promise.all([
      api('/api/admin/catalog'),
      api('/api/admin/stores'),
      api('/api/admin/location-catalog'),
    ]);
    return { ...catalog, stores, locations };
  }, []);
  const [search, setSearch] = useState('');
  const [region, setRegion] = useState('');
  const [commune, setCommune] = useState('');
  const [store, setStore] = useState('');
  const [status, setStatus] = useState('');
  const [edit, setEdit] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (rest[0] && data.data)
      setEdit(data.data.planograms.find((p) => p.id === rest[0]) || null);
  }, [rest[0], data.data]);
  const stores = data.data?.stores || [];
  const communes =
    data.data?.locations.regions.find((r) => r.name === region)?.communes || [];
  const plans = (data.data?.planograms || []).filter((p) => {
    const local = stores.find((s) => s.code === p.store_code);
    return (
      (!region || local?.region === region) &&
      (!commune || local?.commune === commune) &&
      (!store || p.store_code === store) &&
      (!status || p.status === status) &&
      `${p.name} ${p.description} ${p.id}`
        .toLocaleLowerCase('es')
        .includes(search.toLocaleLowerCase('es'))
    );
  });
  function close() {
    setEdit(null);
    if (rest[0]) go('planogramas');
  }
  async function remove() {
    setBusy(true);
    setError('');
    try {
      await api(
        '/api/admin/catalog/planograms/' +
          enc(deleting.id) +
          '?version=' +
          deleting.version,
        { method: 'DELETE' },
      );
      setDeleting(null);
      close();
      data.reload();
      notify('Planograma eliminado.');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <Header eyebrow="Administración" title="Planogramas">
        <button
          className="action"
          disabled={!data.data}
          onClick={() => setEdit({})}
        >
          Crear planograma
        </button>
        <button onClick={() => setImporting(true)}>Importar PDF/JSON</button>
      </Header>
      <ErrorBox error={data.error} onRetry={data.reload} />
      <div className="sb-toolbar">
        <label>
          Buscar
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Nombre o descripción"
          />
        </label>
        <label>
          Región
          <select
            value={region}
            onChange={(e) => {
              setRegion(e.target.value);
              setCommune('');
              setStore('');
            }}
          >
            <option value="">Todas las regiones</option>
            {sortByName(data.data?.locations.regions || []).map((r) => (
              <option key={r.code}>{r.name}</option>
            ))}
          </select>
        </label>
        <label>
          Comuna
          <select
            value={commune}
            disabled={!region}
            onChange={(e) => {
              setCommune(e.target.value);
              setStore('');
            }}
          >
            <option value="">Todas las comunas</option>
            {sortByName(communes).map((c) => (
              <option key={c.name}>{c.name}</option>
            ))}
          </select>
        </label>
        <label>
          Punto de venta
          <select value={store} onChange={(e) => setStore(e.target.value)}>
            <option value="">Todos los PDV</option>
            {sortByName(
              stores.filter(
                (s) =>
                  (!region || s.region === region) &&
                  (!commune || s.commune === commune),
              ),
            ).map((s) => (
              <option key={s.code} value={s.code}>
                {s.name} ({s.code})
              </option>
            ))}
          </select>
        </label>
        <label>
          Estado
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Todos</option>
            <option>Activo</option>
            <option>Inactivo</option>
          </select>
        </label>
        <button
          onClick={() => {
            setSearch('');
            setRegion('');
            setCommune('');
            setStore('');
            setStatus('');
          }}
        >
          Limpiar filtros
        </button>
      </div>
      <Card body={false}>
        {data.loading ? (
          <Loading />
        ) : !plans.length ? (
          <Empty>No hay planogramas con estos filtros.</Empty>
        ) : (
          <div className="sb-table">
            <table>
              <thead>
                <tr>
                  <th>Planograma</th>
                  <th>Punto de venta</th>
                  <th>Versión</th>
                  <th>Estado</th>
                  <th>Productos / caras</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {sortByName(plans).map((p) => (
                  <tr key={p.id}>
                    <td>
                      <b>{p.name}</b>
                      <small>{p.id}</small>
                      {p.category && <small>{p.category} · {p.subcategories?.join(', ')}</small>}
                    </td>
                    <td>
                      {stores.find((s) => s.code === p.store_code)?.name ||
                        'Pendiente de asignar PDV'}
                      <small>{p.store_code}</small>
                    </td>
                    <td>{p.version || 'Referencia anterior'}</td>
                    <td>
                      <Pill kind={p.status === 'Activo' ? 'ok' : ''}>
                        {p.status}
                      </Pill>
                    </td>
                    <td>
                      {p.item_count} / {p.face_count}
                    </td>
                    <td>
                      <div className="sb-actions">
                        <button onClick={() => setEdit(p)}>Editar</button>
                        <button
                          className="remove"
                          onClick={() => {
                            setError('');
                            setDeleting(p);
                          }}
                        >
                          Eliminar
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {edit && data.data && (
        <Modal
          wide
          title={edit.id ? 'Editar planograma' : 'Crear planograma'}
          onClose={close}
        >
          <PlanogramForm
            plan={edit}
            catalog={data.data}
            onClose={close}
            onSaved={() => {
              close();
              data.reload();
              notify('Planograma guardado.');
            }}
          />
        </Modal>
      )}
      {importing && (
        <ImportPlanogram
          onClose={() => setImporting(false)}
          onDone={() => {
            setImporting(false);
            data.reload();
            notify('Planograma importado.');
          }}
        />
      )}
      {deleting && (
        <Modal
          title="Eliminar planograma"
          onClose={() => !busy && setDeleting(null)}
        >
          <p>
            ¿Eliminar {deleting.name}? Las góndolas quedarán sin esta asignación
            y las mediciones conservarán su referencia anterior.
          </p>
          <ErrorBox error={error} />
          <div className="sb-actions">
            <button disabled={busy} onClick={() => setDeleting(null)}>
              Cancelar
            </button>
            <button className="remove" disabled={busy} onClick={remove}>
              Confirmar eliminación
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
