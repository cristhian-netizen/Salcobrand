'use client';
import SortableTable from '../tables/SortableTable';

import {orderRegions} from '../../lib/locations.mjs';
import {useState} from 'react';
import {api, download, fmt} from '../../lib/sb';
import {useApi, Header, Card, Loading, Empty, ErrorBox, Modal, Pill} from '../sb/ui';
import {SaveForm, StatusField, sortByName, enc} from './shared';
import StoreExcel from './StoreExcel';
import ShelfPhoto from './ShelfPhoto';

export default function Stores({notify}) {
  const [deleted, setDeleted] = useState(false);
  const stores = useApi(() => api('/api/admin/stores?include_deleted=' + deleted), [deleted]);
  const catalog = useApi(() => api('/api/admin/location-catalog'), []);
  const [q, setQ] = useState(''); const [region, setRegion] = useState(''); const [commune, setCommune] = useState(''); const [status, setStatus] = useState('');
  const [importing, setImporting] = useState(false);
  const [edit, setEdit] = useState(null); const [history, setHistory] = useState(null); const [retire, setRetire] = useState(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const filtered = (stores.data || []).filter(s => (!region || s.region === region) && (!commune || s.commune === commune) && (!status || s.status === status) && `${s.code} ${s.name} ${s.commune} ${s.address} ${s.description}`.toLocaleLowerCase('es').includes(q.toLocaleLowerCase('es')));
  async function exportFile(excel) {
    setBusy(true);setError('');
    try {
      const query = new URLSearchParams({search:q,region,commune,status,include_deleted:String(deleted)});
      await download('/api/admin/store-transfer/workbook.xlsx?' + query,
        'Salcobrand_PDV.xlsx');
    } catch (exception) {setError(exception.message);} finally {setBusy(false);}
  }
  async function changeStatus(s) {
    setBusy(true); setError('');
    try {
      await api('/api/admin/stores/' + enc(s.code) + (s.deleted ? '/restore' : '?version=' + s.version), {method: s.deleted ? 'POST' : 'DELETE', ...(s.deleted ? {body: {version: s.version}} : {})});
      setRetire(null); stores.reload(); notify(s.deleted ? 'PDV restaurado como inactivo. Puedes editarlo para activarlo.' : 'PDV eliminado del catálogo activo. Su historial se conserva.');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <section><Header eyebrow="Administración" title="Puntos de venta" subtitle="Datos del local, ubicación, encargado y cantidades de góndolas por tipo."><button type="button" disabled={busy} onClick={() => setImporting(true)}>Carga masiva</button><button className="action" disabled={!catalog.data} onClick={() => setEdit({})}>Crear PDV</button></Header>
    <ErrorBox error={stores.error || catalog.error || error} onRetry={() => {stores.reload(); catalog.reload();}}/>
    <div className="sb-toolbar store-filters"><label>Buscar<input value={q} onChange={e => setQ(e.target.value)} placeholder="Código, nombre o dirección"/></label>
      <label>Región<select value={region} onChange={e => {setRegion(e.target.value);setCommune('');}}><option value="">Todas las regiones</option>{orderRegions(catalog.data?.regions || []).map(r => <option key={r.code}>{r.name}</option>)}</select></label>
      <label>Comuna<select value={commune} disabled={!region} onChange={e => setCommune(e.target.value)}><option value="">{region ? 'Todas las comunas' : 'Selecciona primero una región'}</option>{sortByName(catalog.data?.regions.find(r => r.name === region)?.communes || []).map(c => <option key={c.code}>{c.name}</option>)}</select></label>
      <label>Estado<select value={status} onChange={e => setStatus(e.target.value)}><option value="">Todos</option><option>Activo</option><option>Inactivo</option></select></label>
      <div className="store-filter-actions"><label className="mg-check"><input type="checkbox" checked={deleted} onChange={e => setDeleted(e.target.checked)}/>Incluir eliminados</label>
      <button onClick={() => {setQ('');setRegion('');setCommune('');setStatus('');setDeleted(false);}}>Limpiar filtros</button><button type="button" disabled={busy || stores.loading} onClick={() => exportFile(true)}>Exportar Excel</button></div></div>
    <p className="sb-hint">El Excel incluye los PDV según los filtros de la tabla y sus relaciones de góndolas.</p>
    <Card body={false}>{stores.loading ? <Loading/> : !filtered.length ? <Empty>No hay puntos de venta con estos filtros.</Empty> : <div className="sb-table"><SortableTable><thead><tr><th>PDV</th><th>Tipo</th><th>Ubicación</th><th>Encargado de Local</th><th>Tipos y cantidad de góndolas</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{filtered.map(s => <tr key={s.code}>
      <td><b>{s.name}</b><small>{s.code}</small>{s.needs_completion && <Pill kind="warn">Completar datos</Pill>}</td><td>{s.store_type || 'Sin definir'}</td><td>{s.region || 'Sin región'}<small>{s.commune} · {s.address}</small></td><td>{s.manager || 'Sin asignar'}</td><td>{s.shelf_types?.length ? s.shelf_types.map(type => <small key={type.type_id}>{type.quantity} × {type.name}</small>) : 'Sin asignar'}</td><td><Pill kind={s.deleted ? 'bad' : s.status === 'Activo' ? 'ok' : ''}>{s.deleted ? 'Eliminado' : s.status}</Pill></td>
      <td className="store-actions-cell"><div className="sb-actions store-row-actions">{!s.deleted && <button onClick={() => setEdit(s)}>Editar</button>}<button onClick={() => setHistory(s)}>Historial</button><button onClick={() => {setError('');setRetire(s);}}>{s.deleted ? 'Restaurar' : 'Eliminar'}</button></div></td>
    </tr>)}</tbody></SortableTable></div>}</Card>
    {edit && catalog.data && <Modal title={edit.code ? 'Editar PDV' : 'Crear PDV'} wide onClose={() => setEdit(null)}><StoreForm store={edit} catalog={catalog.data} onClose={() => setEdit(null)} onSaved={() => {setEdit(null);stores.reload();notify('PDV guardado.');}}/></Modal>}
    {history && <History store={history} onClose={() => setHistory(null)}/>}
    {importing && <Modal title="Carga masiva de puntos de venta" wide onClose={() => setImporting(false)}><StoreExcel onClose={() => setImporting(false)} onSaved={result => {setImporting(false);stores.reload();notify(`${result.creates} PDV creados y ${result.updates} actualizados.`);}}/></Modal>}
    {retire && <Modal title={retire.deleted ? 'Restaurar PDV' : 'Eliminar PDV'} onClose={() => !busy && setRetire(null)}><p>{retire.name} ({retire.code})</p><p>{retire.deleted ? 'Se restaurará como Inactivo. Revisa sus datos antes de activarlo.' : 'Dejará de estar disponible para nuevas capturas. Se conservarán sus góndolas, mediciones e historial.'}</p><ErrorBox error={error}/><div className="sb-actions"><button disabled={busy} onClick={() => setRetire(null)}>Cancelar</button><button className="action" disabled={busy} onClick={() => changeStatus(retire)}>{busy ? 'Procesando…' : retire.deleted ? 'Restaurar PDV' : 'Eliminar PDV'}</button></div></Modal>}
  </section>;
}

function StoreForm({store, catalog, onSaved, onClose}) {
  const infrastructure = useApi(() => api('/api/admin/infrastructure' + (store.code ? '?store_code=' + enc(store.code) : '')), [store.code]);
  const [quantities, setQuantities] = useState({});
  const assignment = type => infrastructure.data?.assignments.find(item => item.store_code === store.code && item.type_id === type.id);

  const [form, setForm] = useState({code: '', name: '', store_type: catalog.store_types.includes('Farmacia') ? 'Farmacia' : catalog.store_types[0] || '', region: '', commune: '', address: '', manager: '', status: 'Activo', description: '', ...store});
  const field = key => ({value: form[key], onChange: e => setForm({...form, [key]: e.target.value})});
  const communes = catalog.regions.find(r => r.name === form.region)?.communes || [];
  const payload = () => {
    if (!infrastructure.data || infrastructure.loading || infrastructure.error) throw Error('Espera a que se cargue el catálogo de góndolas.');
    return {...Object.fromEntries(['name','store_type','region','commune','address','manager','status','description', store.code ? 'version' : 'code'].map(k => [k, form[k]])),
      assignments:infrastructure.data.types.map(type => ({type_id:type.id,quantity:Number(quantities[type.id] ?? assignment(type)?.quantity ?? 0),version:assignment(type)?.version || 0}))};
  };
  return <SaveForm path={'/api/admin/stores' + (store.code ? '/' + enc(store.code) : '')} method={store.code ? 'PATCH' : 'POST'} payload={payload} onSaved={onSaved} onClose={onClose}>
    <label>Código PDV<input {...field('code')} required maxLength={20} pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,19}" disabled={!!store.code}/></label>
    <label>Nombre del PDV<input {...field('name')} required maxLength={120}/></label><label>Tipo de PDV<select {...field('store_type')} required><option value="">Seleccionar tipo</option>{[...catalog.store_types].sort((a,b) => a.localeCompare(b,'es')).map(t => <option key={t}>{t}</option>)}</select></label>
    <StatusField value={form.status} onChange={status => setForm({...form,status})}/>
    <label>Región<select value={form.region} required onChange={e => setForm({...form,region:e.target.value,commune:''})}><option value="">Seleccionar región</option>{orderRegions(catalog.regions).map(r => <option key={r.code}>{r.name}</option>)}</select></label>
    <label>Comuna<select {...field('commune')} required disabled={!form.region}><option value="">Seleccionar comuna</option>{sortByName(communes).map(c => <option key={c.code || c.name}>{c.name}</option>)}</select></label>
    <label className="full">Dirección<input {...field('address')} required maxLength={200}/></label><label className="full">Encargado de Local<input {...field('manager')} required maxLength={120}/></label><label className="full">Descripción<textarea {...field('description')} maxLength={2000}/></label>
    <fieldset className="full store-assignments"><legend>Cantidad de góndolas por tipo</legend>
      <p className="sb-hint">Indica 0 para los tipos que no existen en este local.</p>
      <ErrorBox error={infrastructure.error} onRetry={infrastructure.reload}/>
      {infrastructure.loading ? <Loading/> : infrastructure.data?.types.length ? sortByName(infrastructure.data.types).map(type => <div className="store-assignment" key={type.id}>
        <ShelfPhoto photo={type.photo} name={type.name}/>
        <div><b>{type.name}</b><small>{type.kind} · Ancho {type.width_cm} cm · {type.levels} {type.levels === 1 ? 'nivel' : 'niveles'}</small><small>{type.depths.map((depth,index) => `Nivel ${index+1} ${depth} cm`).join(' · ')}</small>{type.status !== 'Activo' && <small>Tipo inactivo</small>}</div>
        <label>Cantidad de {type.name}<input type="number" min="0" max="10000" step="1" required value={quantities[type.id] ?? assignment(type)?.quantity ?? 0} onChange={event => setQuantities({...quantities,[type.id]:event.target.value})}/></label>
      </div>) : <p>Crea primero los tipos en Infraestructura.</p>}
    </fieldset>
  </SaveForm>;
}

function History({store, onClose}) {
  const data = useApi(() => api('/api/admin/stores/' + enc(store.code) + '/history'), [store.code]);
  const labels = {'store.create':'PDV creado','store.update':'PDV editado','store.retire':'PDV eliminado','store.restore':'PDV restaurado','assignment.quantity':'Cantidad actualizada','assignment.type-delete':'Tipo de góndola eliminado','instance.link-existing':'Góndola vinculada','instance.label':'Etiqueta editada'};
  return <Modal title={'Historial · ' + store.code} onClose={onClose}><ErrorBox error={data.error} onRetry={data.reload}/>{data.loading ? <Loading/> : !data.data?.length ? <Empty>Sin cambios registrados desde la migración.</Empty> : <ol className="mg-history">{data.data.map((e,i) => <li key={i}><b>{labels[e.action] || e.action}</b><small>{fmt.dateTime(e.created_at)} · {e.actor}</small><details><summary>Ver cambio</summary><pre>{JSON.stringify({antes:e.before,después:e.after},null,2)}</pre></details></li>)}</ol>}</Modal>;
}
