'use client';
import SortableTable from '../tables/SortableTable';

import {useState} from 'react';
import {api, ROLE_NAMES} from '../../lib/sb';
import {useApi, Header, Card, Loading, Empty, ErrorBox, Pill, Modal} from './ui';
import PersonForm from '../management/PersonForm';
import StoreExcel from '../management/StoreExcel';

export default function Users({user, notify}) {
  const state = useApi(() => api('/api/admin/people'), []);
  const [search,setSearch] = useState('');
  const [editing,setEditing] = useState(null);
  const [reset,setReset] = useState(null);
  const [remove,setRemove] = useState(null);
  const [importing,setImporting] = useState(false);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const rows = (state.data || []).filter(person => [person.name,person.username,person.email,person.position,ROLE_NAMES[person.role]].join(' ').toLocaleLowerCase('es').includes(search.toLocaleLowerCase('es')));
  const saved = () => {setEditing(null);setReset(null);setImporting(false);state.reload();notify('Persona y permisos guardados.');};
  async function deletePerson() {
    setBusy(true);setError('');
    try {
      await api('/api/admin/people/' + encodeURIComponent(remove.id) + '?version=' + remove.version,{method:'DELETE'});
      setRemove(null);state.reload();notify('Persona y acceso eliminados.');
    } catch (exception) {setError(exception.message);} finally {setBusy(false);}
  }
  return <section>
    <Header eyebrow="Administración" title="Personas y roles" subtitle="Cuentas, permisos y antecedentes históricos del equipo.">
      <button type="button" disabled={user.read_only} onClick={() => setImporting(true)}>Carga masiva</button>
      <button type="button" className="action" disabled={user.read_only} onClick={() => setEditing({})}>Crear usuario</button>
    </Header>
    <ErrorBox error={state.error} onRetry={state.reload}/>
    <div className="sb-toolbar"><label>Buscar<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Persona, usuario, email, cargo o rol"/></label><span className="sb-count">{rows.length} personas</span></div>
    <Card body={false}>{state.loading ? <Loading/> : rows.length ? <div className="sb-table"><SortableTable>
      <thead><tr><th>Persona</th><th>Usuario / email</th><th>Rol / cargo</th><th>Vigencia</th><th>Estado</th><th>Acceso</th><th>Ámbito PDV</th><th>Acciones</th></tr></thead>
      <tbody>{rows.map(person => <tr key={person.id}>
        <td><b>{person.name}</b>{person.needs_completion && <small>Completar ficha</small>}</td>
        <td>{person.username}<small>{person.email || 'Email por completar'}</small></td>
        <td>{ROLE_NAMES[person.role] || 'Perfil no habilitado'}<small>{person.position || 'Sin cargo registrado'}</small></td>
        <td>{person.startDate || 'Sin fecha registrada'}{person.endDate && <small>Baja {person.endDate}</small>}</td>
        <td><Pill kind={person.status === 'Vigente' ? 'ok' : person.status === 'Suspendido' ? 'warn' : 'bad'}>{person.status}</Pill></td>
        <td>{!person.access_enabled ? 'Sin acceso' : person.status === 'De baja' ? 'Bloqueado' : person.status === 'Suspendido' ? 'Solo lectura' : 'Habilitado'}</td>
        <td>{['admin','viewer'].includes(person.role) || person.allStores ? 'Todos los PDV' : person.storeCodes.length ? person.storeCodes.join(', ') : 'Sin PDV asignados'}</td>
        <td><div className="sb-actions people-actions"><button type="button" onClick={() => setEditing(person)}>Editar</button>
          {person.access_enabled && <button type="button" disabled={user.read_only} onClick={() => setReset(person)}>Cambiar contraseña</button>}
          {person.username !== user.username && <button type="button" disabled={user.read_only} onClick={() => {setError('');setRemove(person);}}>Eliminar</button>}
        </div></td>
      </tr>)}</tbody>
    </SortableTable></div> : <Empty>No hay personas con estos filtros.</Empty>}</Card>
    {editing && <Modal title={editing.id ? 'Editar usuario' : 'Crear usuario'} wide onClose={() => setEditing(null)}><PersonForm current={editing} self={user} onClose={() => setEditing(null)} onSaved={saved}/></Modal>}
    {reset && <Modal title="Cambiar contraseña" onClose={() => setReset(null)}><PasswordForm person={reset} onClose={() => setReset(null)} onSaved={saved}/></Modal>}
    {importing && <Modal title="Carga masiva de personas" wide onClose={() => setImporting(false)}>
      <StoreExcel onClose={() => setImporting(false)} onSaved={saved} endpoint="/api/admin/people" templatePath="/api/admin/people/template.xlsx" templateName="Plantilla_Personas.xlsx"
        columns={ [['name','Persona'],['username','Nombre de usuario'],['email','Email'],['position','Cargo'],['status','Estado'],['action','Acción']] }>
        <p>La hoja Personas crea o actualiza fichas por nombre de usuario. Después puedes habilitar el acceso desde Editar usuario. Los cambios de rol, estado y PDV de cuentas existentes se gestionan en su ficha.</p>
      </StoreExcel>
    </Modal>}
    {remove && <Modal title="Eliminar persona" onClose={() => !busy && setRemove(null)}><p>¿Eliminar a {remove.name} ({remove.username})?</p><p>Se retirarán la ficha y su acceso. Las mediciones y su autor histórico se conservarán.</p><ErrorBox error={error}/><div className="sb-actions"><button type="button" disabled={busy} onClick={() => setRemove(null)}>Cancelar</button><button type="button" className="action" disabled={busy} onClick={deletePerson}>{busy ? 'Eliminando…' : 'Eliminar persona'}</button></div></Modal>}
  </section>;
}

function PasswordForm({person,onClose,onSaved}) {
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  async function submit(event) {
    event.preventDefault();setBusy(true);setError('');
    const form = new FormData(event.currentTarget);
    try {
      if (form.get('password') !== form.get('confirmation')) throw Error('Las contraseñas no coinciden.');
      const result = await api('/api/admin/people/' + encodeURIComponent(person.id) + '/password',{
        method:'POST',body:{version:person.version,password:form.get('password'),confirmation:form.get('confirmation')},
      });
      if (result.reauthenticate) window.location.reload();
      else onSaved();
    } catch (exception) {setError(exception.message);} finally {setBusy(false);}
  }
  return <form className="sb-form" onSubmit={submit}><p className="full">Usuario {person.username}. La nueva contraseña cerrará las sesiones de esta cuenta.</p>
    <label className="full">Nueva contraseña<input name="password" type="password" minLength={12} maxLength={512} required autoComplete="new-password" disabled={busy}/></label>
    <label className="full">Repite la nueva contraseña<input name="confirmation" type="password" minLength={12} maxLength={512} required autoComplete="new-password" disabled={busy}/></label>
    <div className="full"><ErrorBox error={error}/></div><div className="sb-actions"><button type="button" disabled={busy} onClick={onClose}>Cancelar</button><button type="submit" className="action" disabled={busy}>{busy ? 'Guardando…' : 'Guardar contraseña'}</button></div>
  </form>;
}
