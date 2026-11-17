'use client';
import {sessionUrl} from '../../lib/tab-session.mjs';
import {useMemo, useState} from 'react';
import {api, download, fmt} from '../../lib/sb';
import {can} from '../../lib/profiles.mjs';
import Icon from '../navigation/icons';
import {useApi, Header, Card, Loading, Empty, ErrorBox, ComplianceBar, Pill, StatusPill, Back, Modal} from './ui';
import ReadingView from './ReadingView';
import Measurements from './Measurements';

export default function Gondolas(props) {
  const {rest} = props;
  if (rest[0] && !rest[0].startsWith('local:')) {
    if (rest[1] === 'lectura' && rest[2]) return <ReadingPage {...props} pointId={rest[0]} readingId={rest[2]}/>;
    return <PointDetail {...props} pointId={rest[0]} tab={can(props.user, 'dashboard') ? rest[1] || 'lecturas' : 'lecturas'}/>;
  }
  return <Measurements {...props} rest={[]}/>;
}

function PointList({user, go, initialStore}) {
  const {data, error, loading, reload} = useApi(() => api('/api/summary?days=30'), []);
  const [store, setStore] = useState(initialStore);
  const [q, setQ] = useState('');
  const [creating, setCreating] = useState(false);
  const points = useMemo(() => (data?.points || []).filter(p => (!store || p.store_key === store)
    && (!q || `${p.name} ${p.id} ${p.planogram_name || ''}`.toLowerCase().includes(q.toLowerCase()))), [data, store, q]);
  return <section>
    <Header eyebrow="Operación" title="Góndolas y lecturas" subtitle="Cada góndola guarda su historial de lecturas, cumplimiento de planograma y reposición.">
      {can(user, 'manage') && <button className="action" type="button" onClick={() => setCreating(true)}><Icon name="plus" size={16}/>Nueva góndola</button>}
    </Header>
    <ErrorBox error={error} onRetry={reload}/>
    <div className="sb-toolbar">
      <label>Buscar<input value={q} onChange={e => setQ(e.target.value)} placeholder="Nombre, código o planograma"/></label>
      <label>Local<select value={store} onChange={e => setStore(e.target.value)}>
        <option value="">Todos los locales</option>{(data?.stores || []).map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
      </select></label>
      <span className="sb-count">{points.length} góndolas</span>
    </div>
    <Card body={false}>
      {loading && !data ? <Loading/> : points.length ? <div className="sb-table"><table><thead><tr><th>Góndola</th><th>Local</th><th>Planograma</th><th>Última lectura</th><th>Cumplimiento aprobado · 30 días</th><th className="sb-num">Quiebres</th><th className="sb-num">Por revisar</th></tr></thead><tbody>
        {points.map(p => <tr key={p.id} className="sb-click" onClick={() => go(`gondolas/${encodeURIComponent(p.id)}`)}>
          <td><b>{p.gondola || p.name}</b><small>{p.id}</small></td><td>{p.store_name || p.store || '—'}</td>
          <td>{p.planogram_name || <span className="sb-hint">Sin planograma</span>}</td>
          <td>{p.last ? fmt.ago(p.last.created_at) : <span className="sb-hint">Sin lecturas</span>}<small>{p.readings_count} lecturas</small></td>
          <td><ComplianceBar pct={p.performance?.compliance_pct}/></td>
          <td className="sb-num">{p.performance?.missing ? <Pill kind="bad">{p.performance.missing}</Pill> : 0}</td>
          <td className="sb-num">{p.last?.needs_review ? <Pill kind="warn">{p.last.needs_review}</Pill> : 0}</td>
        </tr>)}
      </tbody></table></div> : <Empty>No hay góndolas con estos filtros.</Empty>}
    </Card>
    {creating && <CreatePoint user={user} onClose={() => setCreating(false)} onCreated={p => { setCreating(false); go(`gondolas/${encodeURIComponent(p.id)}`); }}/>}
  </section>;
}

function CreatePoint({user, onClose, onCreated}) {
  const plans = useApi(() => api('/api/planograms'), []);
  const stores = useApi(() => api('/api/stores'), []);
  const [storeId,setStoreId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    const form = new FormData(e.currentTarget);
    for (const [k, v] of [...form.entries()]) if (!String(v).trim()) form.delete(k);
    try { onCreated(await api('/api/points', {method: 'POST', form})); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title="Nueva góndola" onClose={onClose}>
    {error && <div className="sb-error" role="alert">{error}</div>}
    <form className="sb-form" onSubmit={submit}>
      <label className="full">Nombre de la góndola<input name="name" required maxLength={120} placeholder="Ej.: Cuidado bucal 1"/></label>
      <label>Punto de venta<select name="store_id" required value={storeId} onChange={e => setStoreId(e.target.value)}><option value="">Seleccionar PDV</option>{(stores.data || []).filter(s => s.status === 'Activo').map(s => <option key={s.code} value={s.code}>{s.name} ({s.code})</option>)}</select></label>
      <label>Código de góndola (opcional)<input name="point_id" placeholder="Automático (SB-NNN)"/></label>
      <label className="full">Planograma<select key={storeId} name="planogram_id" defaultValue=""><option value="">Sin planograma</option>{(plans.data || []).filter(p => p.status!=='Inactivo' && (!p.store_code || p.store_code===storeId)).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      {user.role === 'tienda' && <p className="sb-hint full">Se creará en tu local ({user.store_name || user.store_id}).</p>}
      <div className="sb-actions"><button type="button" onClick={onClose}>Cancelar</button><button disabled={busy}>{busy ? 'Creando…' : 'Crear góndola'}</button></div>
    </form>
  </Modal>;
}

function PointDetail({user, go, pointId, tab, notify}) {
  const {data: point, error, loading, reload} = useApi(() => api(`/api/points/${encodeURIComponent(pointId)}`), [pointId]);
  const plans = useApi(() => api('/api/planograms'), []);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  async function assign(planogram_id) {
    setBusy(true); setActionError('');
    try { await api(`/api/points/${encodeURIComponent(pointId)}/planogram`, {method: 'PUT', body: {planogram_id: planogram_id || null}}); await reload(); notify('Planograma actualizado.'); }
    catch (e) { setActionError(e.message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!window.confirm(`¿Eliminar la góndola vacía ${pointId}?`)) return;
    setBusy(true);
    try { await api(`/api/points/${encodeURIComponent(pointId)}`, {method: 'DELETE'}); notify('Góndola eliminada.'); go(can(user,'train') ? 'revision' : 'mediciones'); }
    catch (e) { setActionError(e.message); setBusy(false); }
  }
  if (loading && !point) return <Loading text="Cargando góndola…"/>;
  if (!point) return <><Back onClick={() => go(can(user,'train') ? 'revision' : 'mediciones')}>{can(user,'train') ? 'Revisión' : 'Mediciones'}</Back><ErrorBox error={error} onRetry={reload}/></>;
  const readings = point.readings || [];
  return <section>
    <Back onClick={() => go(can(user,'train') ? 'revision' : 'mediciones')}>{can(user,'train') ? 'Revisión' : 'Mediciones'}</Back>
    <Header eyebrow={point.store_id || 'Góndola'} title={point.name} subtitle={`${point.id} · ${readings.length} lecturas · creada ${fmt.date(point.created_at)}`}>
      {can(user, 'report') && <button type="button" onClick={() => download(`/api/reports/measurements.csv?point=${encodeURIComponent(point.id)}`, `salcobrand-${point.id}.csv`).catch(e => setActionError(e.message))}><Icon name="download" size={16}/>CSV</button>}
      {can(user, 'scan') && point.can_capture !== false && <button className="action" type="button" onClick={() => go(`escanear/${encodeURIComponent(point.id)}`)}><Icon name="scan" size={16}/>Nueva lectura</button>}
    </Header>
    <ErrorBox error={actionError || error}/>
    {point.can_capture === false && <p className="sb-error">Esta estructura está inactiva. Puedes consultar sus lecturas anteriores.</p>}
    <p className="sb-hint">Planograma: {point.planogram_name || 'Sin asignar'}</p>
    <div className="sb-tabs" role="group" aria-label="Secciones de la góndola">
      {[['lecturas', 'Lecturas'], ...(can(user, 'dashboard') ? [['tendencias', 'Tendencias'], ['reposicion', 'Reposición y quiebres']] : [])].map(([id, label]) =>
        <button key={id} type="button" aria-pressed={tab === id} onClick={() => go(`gondolas/${encodeURIComponent(point.id)}/${id}`)}>{label}</button>)}
    </div>
    {tab === 'lecturas' && <Card body={false} title="Historial de lecturas">
      {readings.length ? <div className="sb-table"><table><thead><tr><th></th><th>Fecha</th><th>Estado</th><th className="sb-num">Caras</th><th>Cumplimiento</th><th>Puntaje</th><th className="sb-num">Por revisar</th></tr></thead><tbody>
        {readings.map(r => <tr key={r.id} className="sb-click" onClick={() => go(`gondolas/${encodeURIComponent(point.id)}/lectura/${r.id}`)}>
          <td style={{width: 76}}>{r.image_urls?.[0] ? <img className="sb-thumb" src={sessionUrl(r.image_urls[0])} alt="" loading="lazy"/> : <span className="sb-thumb"/>}</td>
          <td><b>{fmt.dateTime(r.created_at)}</b><small>Lectura #{r.id} · {r.image_urls?.length || 0} fotos</small></td>
          <td><Pill kind={r.review?.status === 'Aprobado' ? 'ok' : r.review?.status === 'Rechazado' ? 'bad' : 'warn'}>{r.review?.status || 'En revisión'}</Pill></td>
          <td className="sb-num">{r.total_facings}</td><td><ComplianceBar pct={r.compliance?.compliance_pct}/></td>
          <td>{r.standards ? <Pill kind={r.standards.score_band}>{r.standards.overall_score} · {r.standards.grade}</Pill> : '—'}</td>
          <td className="sb-num">{r.needs_review ? <Pill kind="warn">{r.needs_review}</Pill> : 0}</td>
        </tr>)}
      </tbody></table></div> : <Empty>Sin lecturas todavía. Usa “Nueva lectura” para analizar la góndola.</Empty>}
    </Card>}
    {tab === 'tendencias' && <Trends pointId={point.id}/>}
    {tab === 'reposicion' && <Replenishment pointId={point.id} user={user} notify={notify}/>}
  </section>;
}

function ReadingPage({user, go, pointId, readingId}) {
  const {data, error, loading, reload} = useApi(() => api(`/api/readings/${encodeURIComponent(readingId)}`), [readingId]);
  return <section>
    <Back onClick={() => go(`gondolas/${encodeURIComponent(pointId)}`)}>{pointId}</Back>
    <Header eyebrow={pointId} title={`Lectura #${readingId}`} subtitle={data ? fmt.dateTime(data.created_at) : ''}/>
    <ErrorBox error={error} onRetry={reload}/>
    {loading && !data ? <Loading text="Cargando lectura…"/> : data && <ReadingView reading={data} user={user} onDeleted={() => go(`gondolas/${encodeURIComponent(pointId)}`)} onConfirmGo={() => go('revision')}/>}
  </section>;
}

function Trends({pointId}) {
  const {data, error, loading, reload} = useApi(() => api(`/api/points/${encodeURIComponent(pointId)}/trends?limit=12`), [pointId]);
  if (loading && !data) return <Loading text="Calculando tendencias…"/>;
  if (error) return <ErrorBox error={error} onRetry={reload}/>;
  const rs = data?.readings || [];
  const max = Math.max(1, ...rs.map(r => r.compliance_pct ?? r.total_facings ?? 0));
  const usePct = rs.some(r => typeof r.compliance_pct === 'number');
  return <>
    <Card title={usePct ? 'Cumplimiento por lectura' : 'Caras detectadas por lectura'} subtitle={`Últimas ${rs.length} lecturas aprobadas`}>
      {rs.length ? <div className="sb-trend">{rs.map(r => { const v = usePct ? r.compliance_pct : r.total_facings; return <div key={r.id} title={fmt.dateTime(r.created_at)}>
        <b>{v == null ? '—' : usePct ? Math.round(v) + '%' : v}</b><i style={{height: `${Math.max(2, ((v || 0) / (usePct ? 100 : max)) * 120)}px`}}/><span>{r.date?.slice(5)}</span></div>; })}</div> : <Empty>Sin lecturas suficientes.</Empty>}
    </Card>
    <Card body={false} title="Productos del planograma" subtitle={data?.flag_counts ? Object.entries(data.flag_counts).map(([k, v]) => `${v} ${k}`).join(' · ') : ''}>
      {data?.skus?.length ? <div className="sb-table"><table><thead><tr><th>Producto</th><th>Posición</th><th className="sb-num">Esperadas</th><th>Serie (caras)</th><th>Tendencia</th></tr></thead><tbody>
        {data.skus.map(s => <tr key={s.planogram_item_id}><td><b>{s.title}</b>{s.tag && <small>{s.tag}</small>}</td><td>{s.section_label} · {s.position_in_section}</td>
          <td className="sb-num">{s.expected_facings}</td><td style={{fontVariantNumeric: 'tabular-nums'}}>{s.series.map(v => v ?? '·').join('  ')}</td>
          <td><StatusPill status={s.flag_kind} label={s.flag}/></td></tr>)}
      </tbody></table></div> : <Empty>Asigna un planograma para ver tendencias por producto.</Empty>}
    </Card>
  </>;
}

function Replenishment({pointId, user, notify}) {
  const rep = useApi(() => api(`/api/points/${encodeURIComponent(pointId)}/replenishment`), [pointId]);
  const actions = useApi(() => api(`/api/points/${encodeURIComponent(pointId)}/stock-actions`), [pointId]);
  const stockouts = useApi(() => api(`/api/points/${encodeURIComponent(pointId)}/supplier-stockouts`), [pointId]);
  const [error, setError] = useState('');
  async function run(fn, msg) { setError(''); try { await fn(); notify(msg); actions.reload(); stockouts.reload(); } catch (e) { setError(e.message); } }
  async function request(e) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    await run(() => api(`/api/points/${encodeURIComponent(pointId)}/stock-actions`, {method: 'POST', body: {product_title: f.get('product_title'), action_type: f.get('action_type'), quantity: Number(f.get('quantity')), note: f.get('note') || null, planogram_item_id: null}}), 'Solicitud registrada.');
    e.target.reset();
  }
  return <>
    <ErrorBox error={error}/>
    <div className="sb-grid-2">
      <Card body={false} title="Quiebres recurrentes" subtitle={rep.data ? `Espacio vacío promedio ${fmt.pct(rep.data.avg_empty_space_pct)} en las últimas lecturas` : ''}>
        {rep.loading && !rep.data ? <Loading/> : rep.data?.recurring_stockouts?.length ? <div className="sb-table"><table><thead><tr><th>Producto</th><th className="sb-num">Quiebres</th><th className="sb-num">Urgencia</th><th></th></tr></thead><tbody>
          {rep.data.recurring_stockouts.map(s => <tr key={s.product}><td><b>{s.product}</b><small>{s.brand}</small></td><td className="sb-num">{s.times_out_of_stock} de {s.times_seen}</td>
            <td className="sb-num"><Pill kind={s.urgency_pct >= 60 ? 'bad' : 'warn'}>{Math.round(s.urgency_pct)} %</Pill></td>
            <td>{can(user, 'resolve') && <button type="button" onClick={() => run(() => api(`/api/points/${encodeURIComponent(pointId)}/stock-actions`, {method: 'POST', body: {product_title: s.product, action_type: 'solicitud', quantity: 1, note: 'Quiebre recurrente', planogram_item_id: null}}), 'Solicitud de reposición creada.')}>Solicitar</button>}</td></tr>)}
        </tbody></table></div> : <Empty>Sin quiebres recurrentes en las últimas lecturas.</Empty>}
      </Card>
      {can(user, 'resolve') && <Card title="Nueva solicitud">
        <form className="sb-form" onSubmit={request}>
          <label className="full">Producto<input name="product_title" required/></label>
          <label>Tipo<select name="action_type"><option value="solicitud">Solicitud de reposición</option><option value="ajuste_robo">Ajuste por robo</option></select></label>
          <label>Cantidad<input name="quantity" type="number" min="1" defaultValue="1" required/></label>
          <label className="full">Nota<input name="note"/></label>
          <div className="sb-actions"><button>Registrar</button></div>
        </form>
      </Card>}
    </div>
    <Card body={false} title="Solicitudes abiertas">
      {actions.data?.length ? <div className="sb-table"><table><thead><tr><th>Producto</th><th>Tipo</th><th className="sb-num">Cantidad</th><th>Creada</th><th></th></tr></thead><tbody>
        {actions.data.map(a => <tr key={a.id}><td><b>{a.product_title}</b>{a.note && <small>{a.note}</small>}</td><td>{a.action_type === 'ajuste_robo' ? 'Ajuste por robo' : 'Reposición'}</td>
          <td className="sb-num">{a.quantity}</td><td>{fmt.ago(a.created_at)}<small>{a.created_by}</small></td>
          <td className="sb-actions">{can(user, 'resolve') && <><button type="button" onClick={() => run(() => api(`/api/stock-actions/${a.id}/resolve`, {method: 'POST'}), 'Solicitud resuelta.')}>Resolver</button>
            <button className="remove" type="button" onClick={() => run(() => api(`/api/stock-actions/${a.id}`, {method: 'DELETE'}), 'Solicitud eliminada.')}>Eliminar</button></>}</td></tr>)}
      </tbody></table></div> : <Empty>No hay solicitudes abiertas.</Empty>}
    </Card>
    <Card body={false} title="Quiebres de proveedor">
      {stockouts.data?.length ? <div className="sb-table"><table><thead><tr><th>Producto</th><th>Registrado</th><th></th></tr></thead><tbody>
        {stockouts.data.map(s => <tr key={s.id}><td><b>{s.product_title}</b>{s.note && <small>{s.note}</small>}</td><td>{fmt.ago(s.created_at)}<small>{s.created_by}</small></td>
          <td>{can(user, 'resolve') && <button type="button" onClick={() => run(() => api(`/api/supplier-stockouts/${s.id}/resolve`, {method: 'POST'}), 'Quiebre de proveedor resuelto.')}>Resolver</button>}</td></tr>)}
      </tbody></table></div> : <Empty>Sin quiebres de proveedor abiertos.</Empty>}
    </Card>
  </>;
}
