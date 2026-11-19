'use client';
// "Entrenar en Kilby" on Revisión para entrenamiento: product master and verified crops → the Kilby catalog of each
// product's category, then one training per catalog. The tabs pick the catalog the counters and actions refer to.
import {useEffect, useState} from 'react';
import {api, fmt} from '../../lib/sb';
import {Card, Loading, ErrorBox, Pill} from './ui';

const pct = v => (typeof v === 'number' ? `${(v * 100).toLocaleString('es-CL', {maximumFractionDigits: 1})} %` : '—');
const STATUS = {queued: 'En cola', running: 'Entrenando', done: 'Terminado', failed: 'Falló'};
const SKIPPED = {sin_job_kilby: 'lecturas anteriores a Kilby', sin_sku: 'sin SKU en el maestro', ajeno: 'productos ajenos', no_identificable: 'no identificables'};

function Training({training, onPublish, busy}) {
  const m = training.metrics || {}, b = training.baseline || {};
  return <tr>
    <td>{fmt.dateTime(training.started_at)}<br/><small>{training.started_by}</small></td>
    <td><Pill kind={training.status === 'done' ? 'ok' : training.status === 'failed' ? 'bad' : 'warn'}>{STATUS[training.status] || training.status}</Pill>{training.error_es && <small className="sb-error"> {training.error_es}</small>}</td>
    <td className="sb-num">{pct(m.top1)} <small>vs {pct(b.top1)}</small></td>
    <td className="sb-num">{pct(m.top3)} <small>vs {pct(b.top3)}</small></td>
    <td>{training.version || '—'}{training.version && (training.published ? <> <Pill kind="ok">Publicada</Pill></>
      : <> <Pill kind="warn">Candidata</Pill> <button type="button" className="link" disabled={busy} onClick={() => onPublish(training)}>Publicar</button></>)}</td>
  </tr>;
}

export default function KilbyTraining({notify, state}) {
  // Revisión loads /api/internal/training/kilby once and shares it: this card and the IA button read the same answer.
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  const [chosen, setChosen] = useState('');
  const data = state.data;
  const catalogs = data?.catalogs || [];
  const selected = catalogs.find(c => c.slug === chosen) || catalogs.find(c => c.slug === data?.default_catalog) || catalogs[0] || null;
  const running = (data?.trainings || []).some(t => ['queued', 'running'].includes(t.status));
  useEffect(() => { if (!running) return; const t = setInterval(state.reload, 15000); return () => clearInterval(t); }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(action, message) {
    setBusy(true); setFailure('');
    try { await action(); notify?.(message); state.reload(); } catch (error) { setFailure(error.message); } finally { setBusy(false); }
  }
  const sync = full => run(() => api('/api/internal/training/kilby/sync' + (full ? '?full=true' : ''), {method: 'POST', timeout: 300000}), 'Productos enviados a Kilby.');
  const fallback = !catalogs.length ? data?.catalog : null; // older server answer or no catalogs yet: global view, as before
  const train = () => {
    const target = selected || fallback;
    if (!target || !window.confirm(`Se enviarán los productos y las etiquetas verificadas del catálogo «${target.name || target.slug}», y se iniciará un entrenamiento en Kilby (usa la cuota del plan). ¿Continuar?`)) return;
    run(() => api('/api/internal/training/kilby/trainings', {method: 'POST', timeout: 300000, body: selected ? {catalog: selected.slug} : {}}), 'Entrenamiento iniciado en Kilby.');
  };
  const publish = training => window.confirm(`¿Publicar ${training.version}${training.catalog ? ` en «${training.catalog}»` : ''}? Los próximos análisis de ese catálogo usarán esta versión.`)
    && run(() => api(`/api/internal/training/kilby/versions/${encodeURIComponent(training.version)}/publish${training.catalog ? `?catalog=${encodeURIComponent(training.catalog)}` : ''}`, {method: 'POST'}), `Versión ${training.version} publicada.`);

  const published = selected ? selected.published_version : fallback?.published_version;
  const trainings = (data?.trainings || []).filter(t => !selected || !t.catalog || t.catalog === selected.slug);
  const unsent = selected ? (selected.pending || 0) + (selected.stuck || 0) : null;
  const skippedText = Object.entries(data?.labels?.skipped || {}).filter(([, n]) => n).map(([k, n]) => `${n} ${SKIPPED[k] || k}`).join(' · ');
  return <Card title="Entrenar en Kilby" subtitle="Envía el maestro de productos y las etiquetas verificadas a los catálogos de Neuravision en Kilby (cada producto va al catálogo de su categoría), y entrena una versión nueva por catálogo."
    actions={<>
      <button type="button" disabled={busy || state.loading} onClick={() => sync(false)}>Sincronizar productos</button>
      <button type="button" disabled={busy || state.loading} onClick={() => sync(true)}>Reenviar todo</button>
      <button type="button" className="action" disabled={busy || state.loading || running || (!selected && !fallback) || (!(selected || fallback)?.trainings_unlimited && (selected || fallback)?.trainings_left === 0)} onClick={train}>
        {selected && catalogs.length > 1 ? `Entrenar «${selected.slug}»` : 'Entrenar en Kilby'}</button>
    </>}>
    <ErrorBox error={failure || state.error} onRetry={state.reload}/>
    {state.loading && !data ? <Loading text="Consultando Kilby…"/> : data && <>
      {data.error && <p className="sb-error" role="alert">{data.error}</p>}
      {catalogs.length > 1 && <div className="sb-tabs" role="group" aria-label="Catálogo de Kilby">
        {catalogs.map(c => <button key={c.slug} type="button" aria-pressed={selected?.slug === c.slug} onClick={() => setChosen(c.slug)}>
          {c.name || c.slug}{(c.pending || 0) + (c.stuck || 0) > 0 ? ` · ${(c.pending || 0) + (c.stuck || 0)} por enviar` : ''}</button>)}
      </div>}
      {selected ? <div className="sb-metrics">
        <article className="sb-metric"><span>Catálogo</span><strong>{selected.slug}</strong><small>{`${selected.products ?? '—'} productos · ${selected.photos ?? '—'} fotos en Kilby`}</small></article>
        <article className="sb-metric"><span>Versión publicada</span><strong>{published?.version || '—'}</strong><small>top-1 {pct(published?.top1)} · top-3 {pct(published?.top3)}</small></article>
        <article className="sb-metric"><span>Sincronización</span><strong>{selected.synced || 0} / {(selected.synced || 0) + unsent}</strong><small>{unsent ? `${unsent} por enviar${selected.stuck ? ` · ${selected.stuck} con error` : ''}` : 'Al día con el maestro'}</small></article>
        <article className="sb-metric"><span>Etiquetas listas</span><strong>{selected.labels_ready ?? 0}</strong><small>{skippedText || 'Sin omitidas'}</small></article>
      </div> : <div className="sb-metrics">
        <article className="sb-metric"><span>Catálogo</span><strong>{fallback?.slug || '—'}</strong><small>{fallback ? `${fallback.products} productos · ${fallback.photos} fotos en Kilby` : 'Sin conexión'}</small></article>
        <article className="sb-metric"><span>Versión publicada</span><strong>{published?.version || '—'}</strong><small>top-1 {pct(published?.top1)} · top-3 {pct(published?.top3)}</small></article>
        <article className="sb-metric"><span>Productos</span><strong>{data.products.synced} / {data.products.local}</strong><small>{data.products.pending} pendientes{data.products.stuck ? ` · ${data.products.stuck} con error` : ''}</small></article>
        <article className="sb-metric"><span>Etiquetas listas</span><strong>{data.labels.ready}</strong><small>{skippedText || 'Sin omitidas'}</small></article>
      </div>}
      {(selected || fallback) && <p className="sb-hint">Entrenamientos disponibles en el plan{selected ? ` para «${selected.slug}»` : ''}: {(selected || fallback).trainings_unlimited ? 'sin límite (habilitado por Kilby)' : ((selected || fallback).trainings_left ?? '—')}. Una versión nueva se publica sola si su top-1 iguala o supera el de la publicada; si no, queda como candidata. Mientras haya pocas fotos reales confirmadas, ese top-1 se mide sobre todo con fotos de catálogo y no refleja la góndola: si una candidata aprendió de fotos reales, publícala a mano y compárala escaneando una góndola (siempre puedes volver a la versión anterior).</p>}
      {selected && catalogs.length > 1 && data.default_catalog && <p className="sb-hint">Al entrenar se envían solo las etiquetas de lecturas analizadas con «{selected.slug}». Las lecturas sin catálogo registrado (anteriores a los catálogos por categoría) cuentan para el catálogo configurado «{data.default_catalog}».</p>}
      {data.products.errors.length > 0 && <details><summary>Errores de sincronización ({data.products.errors.length})</summary>
        <ul>{data.products.errors.map(e => <li key={e.sku}><b>{e.sku}</b>{e.catalog ? <small> → {e.catalog}</small> : null}: {e.last_error}</li>)}</ul></details>}
      {trainings.length > 0 && <table className="sb-table"><thead><tr><th>Inicio</th><th>Estado</th><th>Top-1 vs publicada</th><th>Top-3 vs publicada</th><th>Versión</th></tr></thead>
        <tbody>{trainings.map(t => <Training key={t.id} training={t} busy={busy} onPublish={publish}/>)}</tbody></table>}
    </>}
  </Card>;
}
