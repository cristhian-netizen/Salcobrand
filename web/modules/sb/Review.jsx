'use client';
import ShelfPhoto from '../management/ShelfPhoto';
import {useEffect, useRef, useState} from 'react';
import {api, fmt, download} from '../../lib/sb';
import {useApi, Header, Card, Loading, Empty, ErrorBox, StatusPill} from './ui';
import KilbyTraining from './KilbyTraining';
import {suggestionState, preselect, applySuggestions, suggestSummary} from './review-suggest.mjs';

function CropCard({payload, item, onDone}) {
  const suggestions = [...new Set([...(item.text_top3 || []), ...(item.visual_top3 || [])].map(s => s.title).filter(Boolean))].slice(0, 4);
  const titles = [...(payload.titles || [])].sort((a, b) => a.localeCompare(b, 'es', {sensitivity: 'base', numeric: true}));
  const ai = suggestionState(item);
  const [title, setTitle] = useState(() => preselect(item, suggestions[0]));
  const [facings, setFacings] = useState(item.facings ?? 1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const touched = useRef(false);
  useEffect(() => {
    // The AI suggestion lands after this card mounted: pre-select it in the dropdown unless the
    // person already chose something by hand.
    if (!touched.current && suggestionState(item).kind === 'ok') setTitle(preselect(item, ''));
  }, [item.suggestion]);
  const options = title && !titles.includes(title) ? [title, ...titles] : titles;
  async function confirm(chosen, verdict, reason) {
    setBusy(true); setError('');
    try {
      await api(`/api/readings/${payload.reading_id}/confirm`, {method: 'POST', body: {image_index: item.image_index, item_index: item.item_index, title: chosen, facings: Number.isFinite(Number(facings)) ? Number(facings) : null, verdict: verdict || null, reason: reason || null}});
      onDone(item);
    } catch (e) { setError(e.message); setBusy(false); }
  }
  return <article className="sb-crop">
    <ShelfPhoto photo={item.crop_url} thumb={768} name={`${item.product || 'Producto'} · nivel ${item.level}, posición ${item.position}`}/>
    <div><b>{item.product}</b> <StatusPill status={item.status}/></div>
    {item.ocr && <div className="ocr">Texto leído: {item.ocr}</div>}
    {ai.kind === 'ok' && <div className="ai-suggest">IA sugiere: <b>{ai.title}</b> · {ai.pct} %{item.suggestion?.ocr_text ? ` · lee «${item.suggestion.ocr_text}»` : ''}</div>}
    {ai.kind === 'sin-sugerencia' && <div className="ai-suggest none">IA sin sugerencia{item.suggestion?.ocr_text ? ` · lee «${item.suggestion.ocr_text}»` : ''}</div>}
    {suggestions.length > 0 && <div className="suggest">{suggestions.map(s => <button key={s} type="button" disabled={busy} onClick={() => confirm(s)} title="Confirmar como este producto">{s}</button>)}</div>}
    <label>Otro producto del planograma<select value={title} onChange={e => { touched.current = true; setTitle(e.target.value); }} disabled={busy}>
      <option value="">Elige…</option>{options.map(t => <option key={t} value={t}>{t}</option>)}
    </select></label>
    <div className="row">
      <label>Caras<input type="number" min="0" value={facings} onChange={e => setFacings(e.target.value)} disabled={busy}/></label>
      <div style={{display: 'grid', alignContent: 'end'}}><button type="button" disabled={busy || !title} onClick={() => confirm(title)}>Confirmar</button></div>
    </div>
    <div className="row">
      <button className="link" type="button" disabled={busy} onClick={() => confirm(null)}>No es del planograma</button>
      <label className="link-select" title="Se detectó la unidad pero el envase no se distingue. No crea etiqueta y no cuenta como producto ajeno; el motivo queda registrado.">No identificable:
        <select value="" disabled={busy} onChange={e => e.target.value && confirm(null, 'no_identificable', e.target.value)}>
          <option value="">motivo…</option>
          <option value="al_reves">Al revés / de espaldas</option>
          <option value="tapado">Tapado u oculto</option>
          <option value="borroso">Foto borrosa o reflejo</option>
          <option value="no_producto">No es un producto</option>
          <option value="otro">Otro</option>
        </select>
      </label>
    </div>
    {error && <div className="sb-error" role="alert">{error}</div>}
  </article>;
}

export default function Review({go, notify}) {
  const {data, error, loading, reload, setData} = useApi(() => api('/api/review/pending'), []);
  const kilby = useApi(() => api('/api/internal/training/kilby', {timeout: 60000}), []);
  const geminiOn = !!kilby.data?.gemini?.configured;
  const [suggesting, setSuggesting] = useState(null); // {id, done, total} while running
  function done(payload, item) {
    setData((data || []).map(p => p === payload ? {...p, items: p.items.filter(i => i !== item)} : p).filter(p => p.items.length));
    notify('Etiqueta de entrenamiento guardada.');
  }
  async function suggest(payload) {
    const total = payload.items.length;
    setSuggesting({id: payload.reading_id, done: 0, total});
    const sum = {sugeridos: 0, sin_sugerencia: 0, en_cache: 0, errores: 0, error: null};
    try {
      let current = data;
      for (let done = 0; ;) {
        const result = await api(`/api/internal/training/suggest/${payload.reading_id}?limit=20`, {method: 'POST', timeout: 120000});
        for (const k of ['sugeridos', 'sin_sugerencia', 'en_cache', 'errores']) sum[k] += result[k] || 0;
        sum.error = sum.error || result.error;
        current = applySuggestions(current, payload.reading_id, result.suggestions);
        setData(current);
        done = Math.min(total, total - (result.restantes || 0));
        setSuggesting({id: payload.reading_id, done, total});
        const progressed = (result.sugeridos || 0) + (result.sin_sugerencia || 0) + (result.en_cache || 0) > 0;
        if (!result.restantes || !progressed) break;
      }
      notify(suggestSummary(sum));
    } catch (e) { notify(e.message); } finally { setSuggesting(null); }
  }
  const total = (data || []).reduce((n, p) => n + p.items.length, 0);
  return <section>
    <Header eyebrow="Operación" title="Revisión para entrenamiento" subtitle="Verificación interna de productos para Neuramorphic. Las etiquetas se guardan separadas de las mediciones del cliente.">
      <button type="button" onClick={reload} disabled={loading}>Actualizar</button>
      <button type="button" onClick={() => download('/api/internal/training/labels.jsonl','Neuravision_Etiquetas_Entrenamiento.jsonl').catch(error=>notify(error.message))}>Exportar etiquetas</button>
    </Header>
    <ErrorBox error={error} onRetry={reload}/>
    <KilbyTraining notify={notify} state={kilby}/>
    {loading && !data ? <Loading text="Buscando recortes por revisar…"/> : !total ? <Card><Empty>No hay productos pendientes de verificación en las lecturas consultadas.</Empty></Card>
      : data.map(payload => <Card key={payload.reading_id} title={`${payload.point_id} · lectura #${payload.reading_id}`} subtitle={`${fmt.dateTime(payload.created_at)} · ${payload.items.length} por revisar`}
        actions={<>
          {geminiOn && <button type="button" disabled={!!suggesting} onClick={() => suggest(payload)}
            title="Gemini sugiere un candidato por recorte; tú confirmas o corriges.">
            {suggesting?.id === payload.reading_id ? `Sugiriendo… ${suggesting.done}/${suggesting.total}` : `Sugerir con IA (${payload.items.length} pendientes)`}</button>}
          <button className="link" type="button" onClick={() => go(`gondolas/${encodeURIComponent(payload.point_id)}/lectura/${payload.reading_id}`)}>Ver lectura</button>
        </>}>
        <div className="sb-crops">{payload.items.map(item => <CropCard key={`${item.image_index}-${item.item_index}${item.suggestion ? '-ia' : ''}`} payload={payload} item={item} onDone={i => done(payload, i)}/>)}</div>
      </Card>)}
  </section>;
}
