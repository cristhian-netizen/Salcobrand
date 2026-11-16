'use client';
import {useEffect, useRef, useState} from 'react';
import {api, saveBlob} from '../../lib/sb';
import ClientIdentityForm from './ClientIdentityForm';
import ClientPreview from './ClientPreview';
import {DEFAULT_IDENTITY, DEFAULT_MODEL, identityOnly} from './identity.mjs';

const DRAFT_KEY = 'nv-console-drafts';
const snapshot = (tenant, model) => JSON.stringify({tenant, model});
const readDraft = (item, index) => ({...item, id: item.tenant ? item.id : item.draftId || item.organizationId || item.id || String(index), tenant: identityOnly(item.tenant || item), model: {...DEFAULT_MODEL, ...item.model}});
const writeDrafts = values => localStorage.setItem(DRAFT_KEY, JSON.stringify(values.map(item => ({...item.tenant, model: item.model, draftId: item.id, organizationId: item.organizationId, baseVersion: item.baseVersion, updatedAt: item.updatedAt}))));

export default function ClientConsole({user, onLogout, onPortal}) {
  const [directory, setDirectory] = useState(null), [selected, setSelected] = useState(null);
  const [tenant, setTenant] = useState(null), [model, setModel] = useState(DEFAULT_MODEL);
  const [baseline, setBaseline] = useState(''), [version, setVersion] = useState(null);
  const [drafts, setDrafts] = useState([]), [draftId, setDraftId] = useState('');
  const [editingDraftId, setEditingDraftId] = useState('');
  const [busy, setBusy] = useState(true), [processing, setProcessing] = useState(false);
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const form = useRef(null), generation = useRef(0);
  const dirty = tenant && baseline !== snapshot(tenant, model);
  const locked = busy || processing;
  useEffect(() => {
    let active = true;
    api('/api/internal/clients').then(value => { if (active) setDirectory(value); }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    try { const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || '[]'); if (Array.isArray(saved)) setDrafts(saved.map(readDraft)); } catch { setError('No se pudieron leer los borradores de este navegador.'); }
    return () => { active = false; generation.current++; };
  }, []);
  useEffect(() => {
    const warn = e => { if (dirty || locked) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, locked]);
  const leave = () => !dirty || window.confirm('Hay cambios sin guardar. ¿Quieres continuar sin guardarlos?');
  function put(value, nextModel, client, revision, id = '') {
    const clean = identityOnly(value);
    setTenant(clean); setModel({...DEFAULT_MODEL, ...nextModel}); setSelected(client); setVersion(revision); setDraftId(id); setEditingDraftId(id);
    setBaseline(snapshot(clean, {...DEFAULT_MODEL, ...nextModel})); setMessage(''); setError('');
  }
  async function open(id) {
    if (locked || !id || !leave()) return;
    const request = ++generation.current;
    setBusy(true); setError('');
    // Clear the binding while loading so a failure cannot apply to the previous client.
    setSelected(null); setTenant(null); setVersion(null);
    try {
      const value = await api('/api/internal/clients/' + encodeURIComponent(id));
      if (request === generation.current) put(value.tenant, value.model, {...value.organization, name: value.tenant.name}, value.version);
    } catch (e) { if (request === generation.current) setError(e.message); }
    finally { if (request === generation.current) setBusy(false); }
  }
  function newDraft() {
    if (locked || !leave()) return;
    generation.current++;
    put(structuredClone(DEFAULT_IDENTITY), DEFAULT_MODEL, null, null);
    setMessage('Borrador local. El alta del cliente y sus usuarios se realiza por separado.');
  }
  function loadDraft(id) {
    if (locked || !id || !leave()) return;
    const draft = drafts.find(item => item.id === id);
    if (!draft?.tenant) { setError('El borrador no tiene una identidad válida.'); return; }
    // A draft always opens detached. An explicit registered client is required for applying.
    put(draft.tenant, draft.model, null, null, id);
    setMessage('Borrador abierto sin cliente seleccionado. Para aplicar, abre el cliente registrado y utiliza «Cargar borrador en cliente».');
  }
  function attachDraft() {
    const draft = drafts.find(item => item.id === draftId);
    if (!selected || !draft) return;
    if (draft.organizationId !== selected.id || draft.tenant?.id !== selected.slug) { setError('El borrador no pertenece a este cliente registrado.'); return; }
    if (draft.baseVersion !== version) { setError('El borrador usa una versión anterior. Revisa los valores actuales antes de recrearlo.'); return; }
    if (!leave()) return;
    setTenant(identityOnly(draft.tenant)); setModel({...DEFAULT_MODEL, ...draft.model}); setEditingDraftId(draftId); setError(''); setMessage('Borrador cargado. Revisa la vista previa antes de aplicar al cliente seleccionado.');
  }
  function valid() { return form.current?.reportValidity(); }
  function saveDraft() {
    if (!valid()) return;
    const id = editingDraftId || crypto.randomUUID();
    const previous = drafts.find(item => item.id === id);
    if (!selected && !previous?.organizationId && directory?.clients.some(item => item.slug === tenant.id)) { setError('Este cliente ya está registrado. Ábrelo desde Cliente registrado.'); return; }
    // Detached edits retain their origin, never the last selected client.
    const draft = {id, tenant: identityOnly(tenant), model: {...model}, organizationId: selected?.id || previous?.organizationId || null, baseVersion: selected ? version : previous?.baseVersion ?? null, updatedAt: new Date().toISOString()};
    const values = [...drafts.filter(item => item.id !== id), draft];
    try { writeDrafts(values); setDrafts(values); setDraftId(id); setEditingDraftId(id); setBaseline(snapshot(tenant, model)); setError(''); setMessage('Borrador guardado solo en este navegador.'); }
    catch { setError('No se pudo guardar el borrador. Revisa el espacio disponible en este navegador.'); }
  }
  function removeDraft() {
    if (!draftId || !window.confirm('¿Eliminar este borrador local?')) return;
    const values = drafts.filter(item => item.id !== draftId);
    try { writeDrafts(values); setDrafts(values); if (draftId === editingDraftId) setEditingDraftId(''); setDraftId(''); setMessage('Borrador eliminado.'); } catch { setError('No se pudo eliminar el borrador.'); }
  }
  async function apply(e) {
    e.preventDefault();
    if (!selected || locked || user.read_only) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await api('/api/internal/clients/' + encodeURIComponent(selected.id), {method: 'PATCH', body: {tenant: identityOnly(tenant), model, version}});
      setVersion(result.version); setBaseline(snapshot(tenant, model));
      setSelected({...selected, name: tenant.name});
      setDirectory(value => ({...value, clients: value.clients.map(item => item.id === selected.id ? {...item, name: tenant.name} : item)}));
      setMessage('Identidad aplicada a ' + tenant.name + '. Se verá en el portal al volver a iniciar sesión.');
    } catch (exception) { setError(exception.message); }
    finally { setBusy(false); }
  }
  return <div className="client-console" data-console="true">
    <header className="client-console-header"><div><span className="nv-mark" aria-hidden="true">n</span><strong>Neuramorphic</strong><span>Consola interna</span></div><div>{onPortal && <button type="button" disabled={locked} onClick={() => { if (leave()) onPortal(); }}>Volver al portal</button>}<span>{user.username}</span><button type="button" disabled={locked} onClick={() => { if (leave()) onLogout(); }}>Cerrar sesión</button></div></header>
    <main><div className="client-console-heading"><span>ADMINISTRACIÓN INTERNA</span><h1>Identidad de clientes</h1><p>Configura la presentación del portal y las referencias de conexión al modelo.</p></div>
      {user.environment === 'profile-qa' && <p className="client-status">QA local · datos ficticios</p>}
      {user.read_only && <p className="client-status">Cuenta suspendida · solo consulta.</p>}
      <section className="client-picker"><label>Cliente registrado<select disabled={locked || !directory} value={selected?.id || ''} onChange={e => open(e.target.value)}><option value="">Selecciona un cliente</option>{directory?.clients.map(item => <option key={item.id} value={item.id}>{item.name}{item.id === directory.deployment_client_id ? ' · portal de este entorno' : ''}{item.active ? '' : ' · inactivo'}</option>)}</select></label><button type="button" disabled={locked} onClick={newDraft}>Nuevo borrador local</button>{selected && <button type="button" disabled={locked} onClick={() => open(selected.id)}>Recargar cliente</button>}</section>
      <section className="client-drafts"><label>Borradores de este navegador<select disabled={locked} value={draftId} onChange={e => setDraftId(e.target.value)}><option value="">Selecciona un borrador</option>{drafts.map(item => <option key={item.id} value={item.id}>{item.tenant?.name || item.id}</option>)}</select></label><button disabled={locked || !draftId} type="button" onClick={() => loadDraft(draftId)}>Abrir borrador</button>{selected && <button disabled={locked || !draftId} type="button" onClick={attachDraft}>Cargar borrador en cliente</button>}<button disabled={locked || !draftId} type="button" onClick={removeDraft}>Eliminar borrador</button></section>
      {error && <p className="client-error" role="alert">{error}</p>}{message && <p className="client-status" role="status">{message}</p>}
      {busy && <p role="status">Cargando…</p>}
      {tenant ? <div className="client-console-grid"><form ref={form} onSubmit={apply}><p className="client-binding">{selected ? 'Cliente seleccionado: ' + selected.name + ' · versión ' + version : 'Borrador local sin cliente seleccionado'}</p><ClientIdentityForm tenant={tenant} model={model} linked={!!selected} disabled={locked || user.read_only} onTenant={setTenant} onModel={setModel} onError={setError} onProcessing={setProcessing}/><div className="client-actions"><button type="button" disabled={locked} onClick={saveDraft}>Guardar borrador</button><button type="button" disabled={locked} onClick={() => { if (valid()) saveBlob(new Blob([JSON.stringify({...identityOnly(tenant), model}, null, 2)], {type: 'application/json'}), 'neuravision-' + tenant.id + '.json'); }}>Exportar JSON</button>{selected && <button className="client-primary" disabled={locked || user.read_only} type="submit">Aplicar identidad a {selected.name}</button>}</div></form><ClientPreview tenant={tenant}/></div> : !busy && <p className="client-empty">Selecciona un cliente registrado para revisar su identidad, o crea un borrador local.</p>}
    </main>
  </div>;
}
