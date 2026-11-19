'use client';
// "Entrenar en Kilby" on Revisión para entrenamiento: product master and verified crops → Kilby catalog, then a training.
// Depends on Kilby's Neuravision dataset API (not deployed yet); until then the card shows Kilby's answer.
import {useEffect, useState} from 'react';
import {api, fmt} from '../../lib/sb';
import {useApi, Card, Loading, ErrorBox, Pill} from './ui';

const pct = v => (typeof v === 'number' ? `${(v * 100).toLocaleString('es-CL', {maximumFractionDigits: 1})} %` : '—');
const STATUS = {queued: 'En cola', running: 'Entrenando', done: 'Terminado', failed: 'Falló'};
const SKIPPED = {sin_job_kilby: 'lecturas anteriores a Kilby', sin_sku: 'sin SKU en el maestro', ajeno: 'productos ajenos'};

function Training({training, onPublish, busy}) {
  const m = training.metrics || {}, b = training.baseline || {};
  return <tr>
    <td>{fmt.dateTime(training.started_at)}<br/><small>{training.started_by}</small></td>
    <td><Pill kind={training.status === 'done' ? 'ok' : training.status === 'failed' ? 'bad' : 'warn'}>{STATUS[training.status] || training.status}</Pill>{training.error_es && <small className="sb-error"> {training.error_es}</small>}</td>
    <td className="sb-num">{pct(m.top1)} <small>vs {pct(b.top1)}</small></td>
    <td className="sb-num">{pct(m.top3)} <small>vs {pct(b.top3)}</small></td>
    <td>{training.version || '—'}{training.version && (training.published ? <> <Pill kind="ok">Publicada</Pill></>
      : <> <Pill kind="warn">Candidata</Pill> <button type="button" className="link" disabled={busy} onClick={() => onPublish(training.version)}>Publicar</button></>)}</td>
  </tr>;
}

export default function KilbyTraining({notify}) {
  const state = useApi(() => api('/api/internal/training/kilby', {timeout: 60000}), []);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  const data = state.data;
  const running = (data?.trainings || []).some(t => ['queued', 'running'].includes(t.status));
  useEffect(() => { if (!running) return; const t = setInterval(state.reload, 15000); return () => clearInterval(t); }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(action, message) {
    setBusy(true); setFailure('');
    try { await action(); notify?.(message); state.reload(); } catch (error) { setFailure(error.message); } finally { setBusy(false); }
  }
  const sync = full => run(() => api('/api/internal/training/kilby/sync' + (full ? '?full=true' : ''), {method: 'POST', timeout: 300000}), 'Productos enviados a Kilby.');
  const train = () => window.confirm('Se enviarán los productos y las etiquetas verificadas, y se iniciará un entrenamiento en Kilby (usa la cuota del plan). ¿Continuar?')
    && run(() => api('/api/internal/training/kilby/trainings', {method: 'POST', timeout: 300000}), 'Entrenamiento iniciado en Kilby.');
  const publish = version => window.confirm(`¿Publicar ${version}? Los próximos análisis usarán esta versión.`)
    && run(() => api(`/api/internal/training/kilby/versions/${encodeURIComponent(version)}/publish`, {method: 'POST'}), `Versión ${version} publicada.`);

  const catalog = data?.catalog, published = catalog?.published_version;
  return <Card title="Entrenar en Kilby" subtitle="Envía el maestro de productos y las etiquetas verificadas al catálogo de Neuravision en Kilby, y entrena una versión nueva."
    actions={<>
      <button type="button" disabled={busy || state.loading} onClick={() => sync(false)}>Sincronizar productos</button>
      <button type="button" disabled={busy || state.loading} onClick={() => sync(true)}>Reenviar todo</button>
      <button type="button" className="action" disabled={busy || state.loading || running || !catalog || catalog.trainings_left === 0} onClick={train}>Entrenar en Kilby</button>
    </>}>
    <ErrorBox error={failure || state.error} onRetry={state.reload}/>
    {state.loading && !data ? <Loading text="Consultando Kilby…"/> : data && <>
      {data.error && <p className="sb-error" role="alert">{data.error}</p>}
      <div className="sb-metrics">
        <article className="sb-metric"><span>Catálogo</span><strong>{catalog?.slug || '—'}</strong><small>{catalog ? `${catalog.products} productos · ${catalog.photos} fotos en Kilby` : 'Sin conexión'}</small></article>
        <article className="sb-metric"><span>Versión publicada</span><strong>{published?.version || '—'}</strong><small>top-1 {pct(published?.top1)} · top-3 {pct(published?.top3)}</small></article>
        <article className="sb-metric"><span>Productos</span><strong>{data.products.synced} / {data.products.local}</strong><small>{data.products.pending} pendientes{data.products.stuck ? ` · ${data.products.stuck} con error` : ''}</small></article>
        <article className="sb-metric"><span>Etiquetas listas</span><strong>{data.labels.ready}</strong><small>{Object.entries(data.labels.skipped).filter(([, n]) => n).map(([k, n]) => `${n} ${SKIPPED[k] || k}`).join(' · ') || 'Sin omitidas'}</small></article>
      </div>
      {catalog && <p className="sb-hint">Entrenamientos disponibles en el plan: {catalog.trainings_left ?? '—'}. Una versión nueva se publica sola si su top-1 iguala o supera el de la publicada; si no, queda como candidata.</p>}
      {data.products.errors.length > 0 && <details><summary>Errores de sincronización ({data.products.errors.length})</summary>
        <ul>{data.products.errors.map(e => <li key={e.sku}><b>{e.sku}</b>: {e.last_error}</li>)}</ul></details>}
      {data.trainings.length > 0 && <table className="sb-table"><thead><tr><th>Inicio</th><th>Estado</th><th>Top-1 vs publicada</th><th>Top-3 vs publicada</th><th>Versión</th></tr></thead>
        <tbody>{data.trainings.map(t => <Training key={t.id} training={t} busy={busy} onPublish={publish}/>)}</tbody></table>}
    </>}
  </Card>;
}
