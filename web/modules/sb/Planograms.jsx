'use client';
import SortableTable from '../tables/SortableTable';

import {useState} from 'react';
import {api} from '../../lib/sb';
import {can} from '../../lib/profiles.mjs';
import Icon from '../navigation/icons';
import {useApi, Header, Card, Loading, Empty, ErrorBox, Pill, Back, Modal} from './ui';

const clp = v => typeof v === 'number' ? '$' + Math.round(v).toLocaleString('es-CL') : '—';
const isStaff = u => can(u, 'manage');

export default function Planograms(props) {
  return props.rest[0] ? <Detail {...props} id={props.rest[0]}/> : <List {...props}/>;
}

function List({user, go}) {
  const {data, error, loading, reload} = useApi(() => api('/api/planograms'), []);
  const [importing, setImporting] = useState(false);
  return <section>
    <Header eyebrow="Análisis" title="Planogramas" subtitle="La referencia contra la que se mide cada góndola: productos, posiciones, caras esperadas y precios.">
      {isStaff(user) && <button className="action" type="button" onClick={() => setImporting(true)}><Icon name="upload" size={16}/>Importar</button>}
    </Header>
    <ErrorBox error={error} onRetry={reload}/>
    <Card body={false}>
      {loading && !data ? <Loading/> : data?.length ? <div className="sb-table"><SortableTable><thead><tr><th>Planograma</th><th className="sb-num">Productos</th><th className="sb-num">Bandas</th><th className="sb-num">Módulo</th></tr></thead><tbody>
        {data.map(p => <tr key={p.id} className="sb-click" onClick={() => go(`planogramas/${encodeURIComponent(p.id)}`)}><td><b>{p.name}</b><small>{p.id}</small></td>
          <td className="sb-num">{p.item_count}</td><td className="sb-num">{p.bands ?? '—'}</td><td className="sb-num">{p.module_cm ? `${p.module_cm} cm` : '—'}</td></tr>)}
      </tbody></SortableTable></div> : <Empty>No hay planogramas cargados.</Empty>}
    </Card>
    {importing && <ImportPlanogram onClose={() => setImporting(false)} onDone={id => { setImporting(false); reload(); go(`planogramas/${encodeURIComponent(id)}`); }}/>}
  </section>;
}

export function ImportPlanogram({onClose, onDone}) {
  const [kind, setKind] = useState('pdf');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    const f = new FormData(e.currentTarget), form = new FormData();
    const file = f.get('file');
    if (!file || !file.size) { setError('Elige un archivo.'); setBusy(false); return; }
    form.append(kind === 'pdf' ? 'pdf' : 'file', file);
    for (const k of ['planogram_id', 'name']) if (String(f.get(k) || '').trim()) form.append(k, f.get(k));
    form.append('replace', f.get('replace') ? 'true' : 'false');
    try { const r = await api(`/api/admin/planograms/import-${kind}`, {method: 'POST', form, timeout: 120000}); onDone(r.id); } catch (err) { setError(err.message); setBusy(false); }
  }
  return <Modal title="Importar planograma" onClose={onClose}>
    {error && <div className="sb-error" role="alert">{error}</div>}
    <form className="sb-form" onSubmit={submit}>
      <label>Formato<select value={kind} onChange={e => setKind(e.target.value)}><option value="pdf">PDF (con texto, no escaneado)</option><option value="json">JSON</option></select></label>
      <label>Archivo<input name="file" type="file" accept={kind === 'pdf' ? 'application/pdf' : 'application/json,.json'} required/></label>
      <label>Código (opcional)<input name="planogram_id" placeholder="Se genera del nombre"/></label>
      <label>Nombre (opcional)<input name="name"/></label>
      <label className="full" style={{display: 'flex', gap: 8, alignItems: 'center'}}><input name="replace" type="checkbox"/>Reemplazar si ya existe</label>
      <div className="sb-actions"><button type="button" onClick={onClose}>Cancelar</button><button disabled={busy}>{busy ? 'Importando…' : 'Importar'}</button></div>
    </form>
  </Modal>;
}

function Detail({user, go, id, notify}) {
  const {data, error, loading, reload} = useApi(() => api(`/api/planograms/${encodeURIComponent(id)}`), [id]);
  const [actionError, setActionError] = useState('');
  async function remove() {
    if (!window.confirm(`¿Eliminar el planograma ${data.name}? Se desasigna de las góndolas que lo usan.`)) return;
    try { await api(`/api/admin/planograms/${encodeURIComponent(id)}`, {method: 'DELETE'}); notify('Planograma eliminado.'); go('planogramas'); } catch (e) { setActionError(e.message); }
  }
  return <section>
    <Back onClick={() => go('planogramas')}>Planogramas</Back>
    <ErrorBox error={error || actionError} onRetry={error ? reload : undefined}/>
    {loading && !data ? <Loading/> : data && <>
      <Header eyebrow={data.id} title={data.name} subtitle={`${data.items?.length || 0} productos · ${data.bands ?? '—'} bandas${data.module_cm ? ` · módulo ${data.module_cm} cm` : ''}${data.source_filename ? ` · ${data.source_filename}` : ''}`}>
        {isStaff(user) && <button className="remove" type="button" onClick={remove}><Icon name="trash" size={15}/>Eliminar</button>}
      </Header>
      <Card body={false}>
        {data.items?.length ? <div className="sb-table"><SortableTable><thead><tr><th>Posición</th><th>Producto</th><th>Código</th><th className="sb-num">Caras</th><th className="sb-num">Precio</th></tr></thead><tbody>
          {data.items.map(i => <tr key={i.id}><td>{i.section_label} · banda {i.band} · {i.position_in_section}</td>
            <td><b>{i.title}</b>{i.tag && <> <Pill kind="info">{i.tag}</Pill></>}</td><td>{i.internal_code || '—'}<small>{i.barcode || ''}</small></td>
            <td className="sb-num">{i.expected_facings}</td><td className="sb-num">{clp(i.price_clp)}</td></tr>)}
        </tbody></SortableTable></div> : <Empty>Este planograma no tiene productos.</Empty>}
      </Card>
    </>}
  </section>;
}
