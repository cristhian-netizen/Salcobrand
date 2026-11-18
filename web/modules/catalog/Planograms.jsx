'use client';
import SortableTable from '../tables/SortableTable';

import {orderRegions} from '../../lib/locations.mjs';
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
import PlanogramForm from './PlanogramForm';
import PlanogramAssignments from './PlanogramAssignments';
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
  const [category, setCategory] = useState('');
  const [subcategory, setSubcategory] = useState('');
  const [status, setStatus] = useState('');
  const [assigning,setAssigning]=useState(null);
  const [edit, setEdit] = useState(null);
  const [deleting, setDeleting] = useState(null);
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
    const locals=stores.filter(s=>(p.assigned_store_codes || (p.store_code?[p.store_code]:[])).includes(s.code));
    return (
      (!region || locals.some(s=>s.region===region)) &&
      (!commune || locals.some(s=>s.commune===commune&&(!region||s.region===region))) &&
      (!store || locals.some(s=>s.code===store)) &&
      (!status || p.status === status) &&
      (!category || p.category === category) &&
      (!subcategory || (p.subcategories || (p.subcategory ? [p.subcategory] : [])).includes(subcategory)) &&
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
            {orderRegions(data.data?.locations.regions || []).map((r) => (
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
        <label>Categoría<select value={category} onChange={e=>{setCategory(e.target.value);setSubcategory('');}}><option value="">Todas las categorías</option>{[...new Set([...Object.keys(data.data?.classification?.categories || {}),...(data.data?.planograms || []).map(p=>p.category).filter(Boolean)])].sort((a,b)=>a.localeCompare(b,'es')).map(name=><option key={name}>{name}</option>)}</select></label>
        <label>Subcategoría<select value={subcategory} disabled={!category} onChange={e=>setSubcategory(e.target.value)}><option value="">Todas las subcategorías</option>{[...new Set([...(data.data?.classification?.categories?.[category] || []),...(data.data?.planograms || []).filter(p=>p.category===category).flatMap(p=>p.subcategories || (p.subcategory ? [p.subcategory] : []))])].sort((a,b)=>a.localeCompare(b,'es')).map(name=><option key={name}>{name}</option>)}</select></label>
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
            setStatus('');setCategory('');setSubcategory('');
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
            <SortableTable>
              <thead>
                <tr>
                  <th>Planograma</th>
                  <th>PDV asignados</th>
                  <th>Categoría</th><th>Subcategoría</th>
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
                    </td>
                    <td data-sort-value={p.assigned_count||0}><button type="button" className="link" onClick={()=>setAssigning(p)}>{p.assigned_count||0} PDV · Ver lista</button></td>
                    <td>{p.category || 'Sin categoría'}</td><td>{(p.subcategories || (p.subcategory ? [p.subcategory] : [])).join(', ') || 'Sin subcategorías'}</td>
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
                      <div className="sb-actions planogram-row-actions">
                        <button type="button" onClick={()=>setAssigning(p)}>Asignar a PDV</button>
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
            </SortableTable>
          </div>
        )}
      </Card>
      {assigning && data.data && <Modal wide title="Asignar planograma a PDV" onClose={()=>setAssigning(null)}><PlanogramAssignments plan={assigning} catalog={data.data} onEdit={()=>{setEdit(assigning);setAssigning(null);}} onSaved={()=>{setAssigning(null);data.reload();notify('Asignaciones del planograma guardadas.');}}/></Modal>}
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
            onSaved={(saved) => {
              if(!edit.id)setAssigning(saved);
              close();
              data.reload();
              notify('Planograma guardado.');
            }}
          />
        </Modal>
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
