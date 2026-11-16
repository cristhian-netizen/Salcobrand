'use client';
import {useState} from 'react';
import {api} from '../../lib/sb';
import {useApi, Header, Card, Loading, Empty, ErrorBox, Modal, Pill} from '../sb/ui';
import {SaveForm, StatusField, sortByName, enc} from './shared';
import ShelfPhoto from './ShelfPhoto';

export default function Infrastructure({notify}) {
  const state = useApi(() => api('/api/admin/shelf-types'), []);
  const [search, setSearch] = useState('');
  const [edit, setEdit] = useState(null);
  const [remove, setRemove] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const types = sortByName(state.data || []).filter(type =>
    `${type.name} ${type.kind} ${type.supplier}`.toLocaleLowerCase('es').includes(search.toLocaleLowerCase('es')));
  async function deleteType() {
    setBusy(true);setError('');
    try {
      await api('/api/admin/shelf-types/' + enc(remove.id) + '?version=' + remove.version, {method:'DELETE'});
      setRemove(null);state.reload();notify('Góndola eliminada.');
    } catch (exception) {setError(exception.message);} finally {setBusy(false);}
  }
  return <section>
    <Header eyebrow="Administración" title="Infraestructura" subtitle="Catálogo compartido de góndolas. Asigna los tipos y cantidades desde Puntos de venta.">
      <button className="action" type="button" onClick={() => setEdit({})}>Crear góndola</button>
    </Header>
    <ErrorBox error={state.error} onRetry={state.reload}/>
    <div className="sb-toolbar"><label>Buscar<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Nombre, código, tipo o fabricante"/></label><span className="sb-count">{types.length} {types.length === 1 ? 'góndola' : 'góndolas'}</span></div>
    {state.loading ? <Loading/> : <Card body={false}>
      {!types.length ? <Empty>No hay góndolas con estos filtros.</Empty> : <div className="sb-table"><table>
        <thead><tr><th>Góndola</th><th>Tipo</th><th>Proveedor/fabricante</th><th>Medidas</th><th>Estado</th><th>Acciones</th></tr></thead>
        <tbody>{types.map(type => <tr key={type.id}>
          <td><div className="mg-type"><ShelfPhoto photo={type.photo} name={type.name}/><b>{type.name}</b></div></td>
          <td>{type.kind}</td><td>{type.supplier || 'Sin especificar'}</td>
          <td><b>Ancho {type.width_cm} cm</b>{type.kind !== 'Vitrina' && <small>{type.height_cm ? `Alto ${type.height_cm} cm` : 'Alto por completar'}</small>}
            <small>{type.kind === 'Estante' ? `${type.levels} niveles · ` : ''}{type.depths.map((depth,index) => type.kind === 'Estante' ? `Nivel ${index+1} ${depth} cm` : `Profundidad ${depth} cm`).join(' · ')}</small></td>
          <td><Pill kind={type.status === 'Activo' ? 'ok' : ''}>{type.status}</Pill></td>
          <td><div className="sb-actions infrastructure-actions"><button type="button" onClick={() => setEdit(type)}>Editar</button><button type="button" onClick={() => {setError('');setRemove(type);}}>Eliminar</button></div></td>
        </tr>)}</tbody>
      </table></div>}
    </Card>}
    {edit && <Modal title={edit.id ? 'Editar góndola' : 'Crear góndola'} onClose={() => setEdit(null)}>
      <TypeForm type={edit} onSaved={() => {setEdit(null);state.reload();notify('Góndola guardada.');}} onClose={() => setEdit(null)}/>
    </Modal>}
    {remove && <Modal title="Eliminar góndola" onClose={() => !busy && setRemove(null)}>
      <p>¿Eliminar {remove.name} del catálogo?</p><p>Sus asignaciones quedarán en cero y sus estructuras se desactivarán. Las mediciones y referencias históricas se conservarán.</p>
      <ErrorBox error={error}/><div className="sb-actions"><button type="button" disabled={busy} onClick={() => setRemove(null)}>Cancelar</button><button type="button" className="action" disabled={busy} onClick={deleteType}>{busy ? 'Eliminando…' : 'Eliminar góndola'}</button></div>
    </Modal>}
  </section>;
}

function TypeForm({type, onSaved, onClose}) {
  const [form, setForm] = useState({name:'',kind:'Estante',supplier:'',width_cm:'',depths:[30],photo:'',status:'Activo',...type,height_cm:type.height_cm ?? ''});
  const [photoError, setPhotoError] = useState('');
  const [processing, setProcessing] = useState(false);
  async function photo(file) {
    if (!file) return;
    setPhotoError('');setProcessing(true);
    try {
      if (!['image/jpeg','image/png','image/webp'].includes(file.type) || file.size > 5*1024*1024) throw Error('Usa una foto JPG, PNG o WebP de hasta 5 MB.');
      const bitmap = await createImageBitmap(file);
      const ratio = Math.min(1,640/Math.max(bitmap.width,bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1,Math.round(bitmap.width*ratio));
      canvas.height = Math.max(1,Math.round(bitmap.height*ratio));
      canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
      bitmap.close();
      setForm(current => ({...current,photo:canvas.toDataURL('image/jpeg',0.75)}));
    } catch (exception) {setPhotoError(exception.message || 'No se pudo leer la fotografía.');}
    finally {setProcessing(false);}
  }
  const field = key => ({value:form[key],onChange:event => setForm({...form,[key]:event.target.value})});
  return <SaveForm path={'/api/admin/shelf-types' + (type.id ? '/' + enc(type.id) : '')} method={type.id ? 'PATCH' : 'POST'} payload={() => {
    if (processing) throw Error('Espera a que termine de cargar la fotografía.');
    return {name:form.name,kind:form.kind,supplier:form.supplier,height_cm:form.kind === 'Vitrina' ? null : Number(form.height_cm),width_cm:Number(form.width_cm),depths:(form.kind === 'Estante' ? form.depths : form.depths.slice(0,1)).map(Number),photo:form.photo,status:form.status,...(type.id ? {version:type.version} : {})};
  }} onSaved={onSaved} onClose={onClose}>
    <label>Nombre/código<input {...field('name')} required maxLength={120}/></label>
    <label>Proveedor/fabricante<input {...field('supplier')} maxLength={160}/></label>
    <label>Tipo de góndola<select {...field('kind')}><option>Estante</option><option>Vin</option><option>Vitrina</option></select></label>
    <StatusField value={form.status} onChange={status => setForm({...form,status})}/>
    <label>Ancho (cm)<input {...field('width_cm')} type="number" min="0.1" max="1000" step="any" required/></label>
    {form.kind !== 'Vitrina' && <label>Alto (cm)<input {...field('height_cm')} type="number" min="0.1" max="1000" step="any" required/></label>}
    {form.kind === 'Estante' && <>
      <label className="full">Número de niveles<input type="number" min="1" max="100" step="1" value={form.depths.length} required onChange={event => {
        const count = Number(event.target.value);
        if (Number.isInteger(count) && count >= 1 && count <= 100) setForm({...form,depths:Array.from({length:count},(_,index) => form.depths[index] ?? 30)});
      }}/></label><p className="full sb-hint">Niveles numerados desde abajo hacia arriba. Todas las medidas están en centímetros.</p>
    </>}
    {(form.kind === 'Estante' ? form.depths : form.depths.slice(0,1)).map((depth,index) => <label key={index}>{form.kind === 'Estante' ? `Profundidad nivel ${index+1} (cm)` : 'Profundidad (cm)'}<input type="number" min="0.1" max="1000" step="any" required value={depth} onChange={event => setForm({...form,depths:form.depths.map((value,i) => i === index ? event.target.value : value)})}/></label>)}
    <label className="full">Foto del tipo de góndola<input type="file" accept="image/jpeg,image/png,image/webp" disabled={processing} onChange={event => {photo(event.target.files[0]);event.target.value='';}}/><small>JPG, PNG o WebP, hasta 5 MB. Se guarda una miniatura de hasta 640 px.</small></label>
    {processing && <p className="full" role="status">Preparando fotografía…</p>}<div className="full"><ErrorBox error={photoError}/></div>
    {form.photo && <div className="full mg-photo"><ShelfPhoto photo={form.photo} name={form.name || 'Góndola'}/><button type="button" disabled={processing} onClick={() => setForm({...form,photo:''})}>Quitar foto</button></div>}
  </SaveForm>;
}
