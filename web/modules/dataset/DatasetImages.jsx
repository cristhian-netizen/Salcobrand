'use client';
// Nationwide dataset sweep (local-neura): the phone's ORIGINAL photos per active category.
// The File object goes straight into FormData — no canvas, no resize, no re-encode anywhere —
// so iPhone/Samsung hand over HEIC/JPEG at sensor resolution and the server stores it verbatim.
// Zero analysis: these uploads never touch the readings/engine pipeline.
import {useRef, useState} from 'react';
import {api, fmt} from '../../lib/sb';
import {useApi, Header, Card, Loading, Empty, ErrorBox, Pill, Modal} from '../sb/ui';
import Img from '../common/Img';
import {imageUrl} from '../../lib/images.mjs';
import {fmtMB, progressLabel, categorySummary, totalsOf, dimensionsLabel, linkStatus} from './dataset.mjs';

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
  const links = useApi(() => api('/api/admin/dataset/links'), []);
  const [creatingLink, setCreatingLink] = useState(false);
  const [createdUrl, setCreatedUrl] = useState(''); // the full URL exists only in this one response

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

  async function revokeLink(link) {
    if (!window.confirm('¿Revocar este enlace? Quien lo tenga ya no podrá subir fotos y no se puede deshacer. Las fotos ya enviadas se conservan.')) return;
    try {
      await api('/api/admin/dataset/links/' + enc(link.id) + '/revocar', {method: 'POST'});
      links.reload();
      notify('Enlace revocado.');
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
    <Card title="Enlaces de captura" subtitle="Enlaces sin usuario para que personal en terreno sume fotos a este mismo barrido desde su teléfono. Cada enlace fija la categoría y vence solo."
      actions={<button className="action" type="button" disabled={!cats.some(c => c.active !== false)} onClick={() => setCreatingLink(true)}>Nuevo enlace</button>}>
      <ErrorBox error={links.error} onRetry={links.reload}/>
      {links.loading && !links.data ? <Loading text="Cargando enlaces…"/>
        : !(links.data?.links || []).length ? <Empty>No hay enlaces de captura. Crea uno y compártelo por WhatsApp.</Empty>
          : <div className="sb-table"><table><thead><tr><th>Categoría</th><th>PDV</th><th className="sb-num">Fotos</th><th>Vence</th><th>Estado</th><th></th></tr></thead><tbody>
            {(links.data?.links || []).map(link => {
              const [kind, label] = linkStatus(link);
              return <tr key={link.id}>
                <td><b>{link.category_name}</b><small>Creado {fmt.date(link.created_at)}</small></td>
                <td>{link.store_id || '—'}</td>
                <td className="sb-num">{link.photos} / {link.max_photos}</td>
                <td>{fmt.date(link.expires_at)}</td>
                <td><Pill kind={kind}>{label}</Pill></td>
                <td className="sb-actions">{!link.revoked_at && <button type="button" onClick={() => revokeLink(link)}>Revocar</button>}</td>
              </tr>;
            })}
          </tbody></table></div>}
    </Card>
    {creatingLink && <CreateLink cats={cats.filter(c => c.active !== false)} stores={stores.data || []}
      onClose={() => setCreatingLink(false)}
      onCreated={link => { setCreatingLink(false); setCreatedUrl(link.url); links.reload(); }}/>}
    {createdUrl && <Modal title="Enlace creado" onClose={() => setCreatedUrl('')}>
      {/* The server kept only a hash: this is the ONLY moment the URL can be copied. */}
      <p>Comparte este enlace por WhatsApp con quien tomará las fotos. Por seguridad no se volverá a mostrar: cópialo ahora.</p>
      <p className="sb-dataset-link-url"><code>{createdUrl}</code></p>
      <div className="sb-actions">
        <button type="button" onClick={() => setCreatedUrl('')}>Cerrar</button>
        <button className="action" type="button" onClick={() => navigator.clipboard?.writeText(createdUrl).then(() => notify('Enlace copiado.'))}>Copiar enlace</button>
      </div>
    </Modal>}
    <input ref={cameraInput} type="file" accept="image/*" capture="environment" multiple hidden onChange={e => send(e.target)}/>
    <input ref={galleryInput} type="file" accept="image/*" multiple hidden onChange={e => send(e.target)}/>
  </section>;
}

function CreateLink({cats, stores, onClose, onCreated}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    const f = new FormData(e.currentTarget);
    const body = {category: String(f.get('category')), days: Number(f.get('days')) || 14, max_photos: Number(f.get('max_photos')) || 500};
    const store = String(f.get('store_id') || '').trim();
    if (store) body.store_id = store;
    try { onCreated(await api('/api/admin/dataset/links', {method: 'POST', body})); }
    catch (err) { setError(err.message); setBusy(false); }
  }
  return <Modal title="Nuevo enlace de captura" onClose={onClose}>
    {error && <div className="sb-error" role="alert">{error}</div>}
    <form className="sb-form" onSubmit={submit}>
      <label>Categoría<select name="category" required defaultValue={cats[0]?.slug}>
        {cats.map(c => <option key={c.slug} value={c.slug}>{c.name}</option>)}
      </select></label>
      <label>PDV de origen (opcional)<select name="store_id" defaultValue="">
        <option value="">—</option>
        {stores.map(s => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
      </select></label>
      <label>Vence en (días)<input name="days" type="number" min="1" max="60" defaultValue="14"/></label>
      <label>Máximo de fotos<input name="max_photos" type="number" min="1" max="5000" defaultValue="500"/></label>
      <div className="sb-actions"><button type="button" onClick={onClose}>Cancelar</button><button disabled={busy}>{busy ? 'Creando…' : 'Crear enlace'}</button></div>
    </form>
  </Modal>;
}
