'use client';
import {useState} from 'react';
import {api, fmt, download} from '../../lib/sb';
import {useApi, Header, Card, Loading, Empty, ErrorBox, StatusPill} from './ui';

function CropCard({payload, item, onDone}) {
  const suggestions = [...new Set([...(item.text_top3 || []), ...(item.visual_top3 || [])].map(s => s.title).filter(Boolean))].slice(0, 4);
  const [title, setTitle] = useState(suggestions[0] || '');
  const [facings, setFacings] = useState(item.facings ?? 1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function confirm(chosen) {
    setBusy(true); setError('');
    try {
      await api(`/api/readings/${payload.reading_id}/confirm`, {method: 'POST', body: {image_index: item.image_index, item_index: item.item_index, title: chosen, facings: Number.isFinite(Number(facings)) ? Number(facings) : null}});
      onDone(item);
    } catch (e) { setError(e.message); setBusy(false); }
  }
  return <article className="sb-crop">
    <img src={item.crop_url} alt={`Recorte nivel ${item.level}, posición ${item.position}`} loading="lazy"/>
    <div><b>{item.product}</b> <StatusPill status={item.status}/></div>
    {item.ocr && <div className="ocr">Texto leído: {item.ocr}</div>}
    {suggestions.length > 0 && <div className="suggest">{suggestions.map(s => <button key={s} type="button" disabled={busy} onClick={() => confirm(s)} title="Confirmar como este producto">{s}</button>)}</div>}
    <label>Otro producto del planograma<select value={title} onChange={e => setTitle(e.target.value)} disabled={busy}>
      <option value="">Elige…</option>{(payload.titles || []).map(t => <option key={t} value={t}>{t}</option>)}
    </select></label>
    <div className="row">
      <label>Caras<input type="number" min="0" value={facings} onChange={e => setFacings(e.target.value)} disabled={busy}/></label>
      <div style={{display: 'grid', alignContent: 'end'}}><button type="button" disabled={busy || !title} onClick={() => confirm(title)}>Confirmar</button></div>
    </div>
    <button className="link" type="button" disabled={busy} onClick={() => confirm(null)}>No es del planograma</button>
    {error && <div className="sb-error" role="alert">{error}</div>}
  </article>;
}

export default function Review({go, notify}) {
  const {data, error, loading, reload, setData} = useApi(() => api('/api/review/pending'), []);
  function done(payload, item) {
    setData((data || []).map(p => p === payload ? {...p, items: p.items.filter(i => i !== item)} : p).filter(p => p.items.length));
    notify('Etiqueta de entrenamiento guardada.');
  }
  const total = (data || []).reduce((n, p) => n + p.items.length, 0);
  return <section>
    <Header eyebrow="Operación" title="Revisión para entrenamiento" subtitle="Verificación interna de productos para Neuramorphic. Las etiquetas se guardan separadas de las mediciones del cliente.">
      <button type="button" onClick={reload} disabled={loading}>Actualizar</button>
      <button type="button" onClick={() => download('/api/internal/training/labels.jsonl','Neuravision_Etiquetas_Entrenamiento.jsonl').catch(error=>notify(error.message))}>Exportar etiquetas</button>
    </Header>
    <ErrorBox error={error} onRetry={reload}/>
    {loading && !data ? <Loading text="Buscando recortes por revisar…"/> : !total ? <Card><Empty>No hay productos pendientes de verificación en las lecturas consultadas.</Empty></Card>
      : data.map(payload => <Card key={payload.reading_id} title={`${payload.point_id} · lectura #${payload.reading_id}`} subtitle={`${fmt.dateTime(payload.created_at)} · ${payload.items.length} por revisar`}
        actions={<button className="link" type="button" onClick={() => go(`gondolas/${encodeURIComponent(payload.point_id)}/lectura/${payload.reading_id}`)}>Ver lectura</button>}>
        <div className="sb-crops">{payload.items.map(item => <CropCard key={`${item.image_index}-${item.item_index}`} payload={payload} item={item} onDone={i => done(payload, i)}/>)}</div>
      </Card>)}
  </section>;
}
