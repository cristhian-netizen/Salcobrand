'use client';
import {useState} from 'react';
import {api} from '../../lib/sb';
import {ErrorBox} from '../sb/ui';

export const sortByName = items => [...items].sort((a, b) => a.name.localeCompare(b.name, 'es', {sensitivity: 'base', numeric: true}));
export const enc = encodeURIComponent;
export const alphabetical = values => [...new Set(values.filter(Boolean))].sort((a,b) => a.localeCompare(b,'es',{sensitivity:'base'}));
export function StatusField({value, onChange}) {
  return <label>Estado<select value={value} onChange={e => onChange(e.target.value)}><option>Activo</option><option>Inactivo</option></select></label>;
}
export function SaveForm({path, method, payload, onSaved, onClose, children}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    try { const saved = await api(path, {method, body: payload()}); onSaved(saved); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <form className="sb-form" onSubmit={submit}><fieldset className="mg-fields" disabled={busy}>{children}</fieldset>
    <div className="full"><ErrorBox error={error}/></div><div className="sb-actions"><button type="button" disabled={busy} onClick={onClose}>Cancelar</button><button className="action" disabled={busy}>{busy ? 'Guardando…' : 'Guardar'}</button></div>
  </form>;
}
