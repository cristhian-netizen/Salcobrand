'use client';
// Nationwide dataset sweep (local-neura): the phone's ORIGINAL photos per active category.
// The File object goes straight into FormData — no canvas, no resize, no re-encode anywhere —
// so iPhone/Samsung hand over HEIC/JPEG at sensor resolution and the server stores it verbatim.
// Zero analysis: these uploads never touch the readings/engine pipeline.
import {useRef, useState} from 'react';
import {api} from '../../lib/sb';
import {useApi, Header, Card, Loading, Empty, ErrorBox} from '../sb/ui';
import Img from '../common/Img';
import {imageUrl} from '../../lib/images.mjs';
import {fmtMB, progressLabel, categorySummary, totalsOf, dimensionsLabel} from './dataset.mjs';

const enc = encodeURIComponent;

export default function DatasetImages({notify}) {
  const categories = useApi(() => api('/api/admin/dataset/categories'), []);
  const stores = useApi(() => api('/api/stores'), []);
  const [selected, setSelected] = useState('');
  const images = useApi(() => selected ? api('/api/admin/dataset/images?category=' + enc(selected)) : Promise.resolve(null), [selected]);
  const [store, setStore] = useState('');
  const [progress, setProgress] = useState(null); // {done, total, bytes} while originals upload sequentially
  const cameraInput = useRef(null);
  const galleryInput = useRef(null);

  const cats = categories.data?.categories || [];
  const current = cats.find(c => c.slug === selected);
  const grid = images.data?.images || [];
  const totals = totalsOf(grid);

  async function send(input) {
    const files = [...(input.files || [])];
    input.value = ''; // the same photo can be chosen again later
    if (!files.length || !selected || progress) return;
    const uploaded = [];
    const failures = [];
    for (let index = 0; index < files.length; index++) {
      const file = files[index];
      setProgress({done: index + 1, total: files.length, bytes: file.size});
      // The native camera file as-is: appended untouched, streamed untouched.
      const form = new FormData();
      form.append('category', selected);
      if (store) form.append('store_id', store);
      form.append('files', file, file.name || 'foto');
      try {
        const result = await api('/api/admin/dataset/images', {method: 'POST', form, timeout: 600000});
        uploaded.unshift(...(result.created || []));
        images.setData({images: [...uploaded, ...grid]}); // each original appears in the grid as it lands
      } catch (e) {
        failures.push(`${file.name || 'foto'}: ${e.message}`);
        if (e.status === 507) break; // service disk full: stop the sweep instead of failing photo by photo
      }
    }
    setProgress(null);
    categories.reload(); // chip totals
    if (failures.length) {
      images.reload();
      notify(`Se subieron ${uploaded.length} de ${files.length} fotos. ${failures[0]}`);
    } else {
      notify(uploaded.length === 1 ? 'Foto original guardada, sin comprimir.' : `${uploaded.length} fotos originales guardadas, sin comprimir.`);
    }
  }

  async function remove(image) {
    if (!window.confirm('¿Eliminar esta foto del dataset? El archivo original se borra del servidor.')) return;
    try {
      await api('/api/admin/dataset/images/' + enc(image.id), {method: 'DELETE'});
      images.setData({images: (images.data?.images || []).filter(i => i.id !== image.id)});
      categories.reload();
    } catch (e) { notify(e.message); }
  }

  return <section>
    <Header eyebrow="Verificación interna" title="Dataset images"
      subtitle="Barrido nacional de fotos por categoría activa. Cada foto se guarda tal cual la entrega el teléfono: sin comprimir, sin redimensionar y sin ningún análisis.">
      <button type="button" disabled={categories.loading || !!progress} onClick={() => { categories.reload(); if (selected) images.reload(); }}>Actualizar</button>
    </Header>
    <ErrorBox error={categories.error} onRetry={categories.reload}/>
    {categories.data?.warning && <div className="sb-qa-banner" role="status">{categories.data.warning}</div>}
    {categories.loading && !categories.data ? <Loading text="Cargando categorías activas…"/>
      : <Card title="Categorías activas" subtitle="Elige la categoría y toma las fotos con la cámara nativa del teléfono.">
        {!cats.length ? <Empty>No hay categorías disponibles por ahora.</Empty>
          : <div className="sb-dataset-chips">{cats.map(c =>
            <button key={c.slug} type="button" aria-pressed={selected === c.slug} disabled={!!progress}
              onClick={() => setSelected(c.slug)}>
              <strong>{c.name}</strong>
              <small>{categorySummary(c.count, c.bytes)}{c.active === false ? ' · catálogo inactivo' : ''}</small>
            </button>)}
          </div>}
        <label className="sb-dataset-store">PDV de origen (opcional)
          <select value={store} onChange={e => setStore(e.target.value)} disabled={!!progress}>
            <option value="">—</option>
            {(stores.data || []).map(s => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
          </select>
        </label>
      </Card>}
    {selected && <Card title={current?.name || selected} subtitle={categorySummary(totals.count, totals.bytes)}
      actions={<>
        <button className="action" type="button" disabled={!!progress || current?.active === false} onClick={() => cameraInput.current?.click()}>Tomar fotos</button>
        <button type="button" disabled={!!progress || current?.active === false} onClick={() => galleryInput.current?.click()}>Elegir de la galería</button>
      </>}>
      {current?.active === false && <p className="sb-hint">Este catálogo ya no está activo en Kilby: sus fotos se conservan, pero no se pueden agregar nuevas.</p>}
      {progress && <div className="sb-loading" role="status"><span className="nv-spinner" style={{width: 18, height: 18, borderWidth: 2}} aria-hidden="true"/>
        Subiendo original {progressLabel(progress.done, progress.total, progress.bytes)}</div>}
      <ErrorBox error={images.error} onRetry={images.reload}/>
      {images.loading && !images.data ? <Loading text="Cargando fotos…"/>
        : !grid.length ? <Empty>Aún no hay fotos en esta categoría. Tómalas con «Tomar fotos» o súbelas desde la galería.</Empty>
          : <div className="sb-dataset-grid">{grid.map(image => <figure key={image.id} className="sb-dataset-photo">
            <a href={image.url} target="_blank" rel="noreferrer" title="Abrir el archivo original">
              <Img src={imageUrl(image.url, 256)} alt=""/>{/* ?w= thumbnail for the GRID only; the link serves the original */}
            </a>
            <figcaption>
              <span>{fmtMB(image.bytes)}{dimensionsLabel(image) ? ' · ' + dimensionsLabel(image) : ''}{image.store_id ? ' · ' + image.store_id : ''}</span>
              <button className="link" type="button" disabled={!!progress} onClick={() => remove(image)}>Eliminar</button>
            </figcaption>
          </figure>)}</div>}
    </Card>}
    <input ref={cameraInput} type="file" accept="image/*" capture="environment" multiple hidden onChange={e => send(e.target)}/>
    <input ref={galleryInput} type="file" accept="image/*" multiple hidden onChange={e => send(e.target)}/>
  </section>;
}
