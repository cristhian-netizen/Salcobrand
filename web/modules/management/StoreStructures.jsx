'use client';
import {useState} from 'react';
import {api} from '../../lib/sb';
import {useApi, Card, Loading, Empty, ErrorBox, Modal, Pill} from '../sb/ui';
import {SaveForm, sortByName, enc} from './shared';

export default function StoreStructures({store, go, notify, onSaved}) {
  const state = useApi(() => api('/api/admin/infrastructure?store_code=' + enc(store.code)), [store.code]);
  const [instance, setInstance] = useState(null);
  const [link, setLink] = useState(null);
  const data = state.data;
  const selected = data?.stores.find(s => s.code === store.code);
  const saved = () => {setInstance(null);setLink(null);state.reload();onSaved();notify('Góndolas del PDV actualizadas.');};
  return <div><ErrorBox error={state.error} onRetry={state.reload}/>{state.loading ? <Loading/> : data && (
<><Card title="Estructuras físicas" subtitle="Cada estructura mantiene su código y su historial de mediciones." body={false}>
        {!data.instances.length ? <Empty>No hay estructuras asignadas.</Empty> : <div className="sb-table"><table><thead><tr><th>Góndola</th><th>Etiqueta</th><th>Estado</th><th>Lecturas</th><th>Acciones</th></tr></thead><tbody>{data.instances.map(i => <tr key={i.id}><td><b>{i.type_name || 'Tipo eliminado'} #{i.number}</b><small>{i.point_id}</small></td><td>{i.label || 'Sin etiqueta'}<small>{i.note}</small></td><td><Pill kind={i.active ? 'ok' : ''}>{i.active ? 'Activa' : 'Inactiva'}</Pill></td><td>{i.readings_count}</td><td><div className="sb-actions"><button onClick={() => setInstance(i)}>Editar etiqueta</button><button onClick={() => go('gondolas/' + enc(i.point_id))}>Ver lecturas</button></div></td></tr>)}</tbody></table></div>}
      </Card><Card title="Góndolas existentes sin tipo" subtitle="Vincular suma una unidad activa al tipo elegido. Conserva el código, el planograma y todas las lecturas." body={false}>
        {!data.unlinked_points.length ? <Empty>No quedan góndolas sin vincular en este PDV.</Empty> : <div className="sb-table"><table><thead><tr><th>Góndola</th><th>Lecturas</th><th>Acción</th></tr></thead><tbody>{data.unlinked_points.map(p => <tr key={p.id}><td><b>{p.name}</b><small>{p.id}</small></td><td>{p.readings_count}</td><td><button disabled={!data.types.some(t => t.status === 'Activo') || selected?.deleted || selected?.status !== 'Activo'} onClick={() => setLink(p)}>Vincular a tipo</button></td></tr>)}</tbody></table></div>}
      </Card></>
  )}
    {instance && <Modal title="Editar etiqueta de góndola" onClose={() => setInstance(null)}><InstanceForm instance={instance} onSaved={saved} onClose={() => setInstance(null)}/></Modal>}
    {link && <Modal title="Vincular góndola existente" onClose={() => setLink(null)}><LinkForm point={link} store={store.code} data={data} onSaved={saved} onClose={() => setLink(null)}/></Modal>}
  </div>;
}

function InstanceForm({instance,onSaved,onClose}) {
  const [label,setLabel]=useState(instance.label);const [note,setNote]=useState(instance.note);
  return <SaveForm path={'/api/admin/shelf-instances/'+enc(instance.id)} method="PATCH" payload={() => ({label,note,version:instance.version})} onSaved={onSaved} onClose={onClose}>
    <p className="full">Código: {instance.point_id}. El código y las lecturas se conservan.</p><label className="full">Etiqueta<input value={label} maxLength={120} onChange={e => setLabel(e.target.value)}/></label><label className="full">Nota<textarea value={note} maxLength={1000} onChange={e => setNote(e.target.value)}/></label>
  </SaveForm>;
}
function LinkForm({point,store,data,onSaved,onClose}) {
  const [typeId,setTypeId]=useState(''); const assignment=data.assignments.find(a => a.store_code===store && a.type_id===typeId);
  return <SaveForm path="/api/admin/shelf-instances/link-existing" method="POST" payload={() => ({store_code:store,type_id:typeId,point_id:point.id,version:assignment?.version || 0})} onSaved={onSaved} onClose={onClose}>
    <p className="full">{point.name} ({point.id}). Se sumará una unidad activa; sus {point.readings_count} lecturas seguirán asociadas al mismo código.</p><label className="full">Tipo de góndola<select value={typeId} required onChange={e => setTypeId(e.target.value)}><option value="">Seleccionar tipo</option>{sortByName(data.types.filter(t => t.status==='Activo')).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
  </SaveForm>;
}
