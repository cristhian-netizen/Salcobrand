'use client';
import {PASSWORD_PATTERN, PASSWORD_HELP} from '../../lib/password-policy.mjs';
import {orderRegions} from '../../lib/locations.mjs';
import {useState} from 'react';
import {api, ROLE_NAMES} from '../../lib/sb';
import {useApi, ErrorBox, Loading} from '../sb/ui';
import {sortByName} from './shared';

const CAPABILITIES = {
  admin:'Gestiona personas, accesos y catálogos. Consulta resultados y reportes.',
  analyst:'Captura, revisa mediciones, resuelve alertas y consulta dashboards y reportes en sus PDV.',
  replenisher:'Captura en sus PDV y consulta sus propias mediciones y alertas.',
  viewer:'Consulta mediciones, alertas, dashboards y reportes.',
};

export default function PersonForm({current, self, onClose, onSaved}) {
  const catalog = useApi(async () => {
    const [stores,locations] = await Promise.all([api('/api/admin/stores'),api('/api/admin/location-catalog')]);
    return {stores,locations};
  }, []);
  const [form,setForm] = useState({names:'',paternal:'',maternal:'',email:'',username:'',position:'',startDate:'',endDate:'',status:'Vigente',role:'replenisher',storeCodes:[],allStores:false,...current});
  const [enabled,setEnabled] = useState(!!current.access_enabled);
  const [password,setPassword] = useState('');
  const [confirmation,setConfirmation] = useState('');
  const [region,setRegion] = useState('');
  const [commune,setCommune] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const own = current.username === self.username;
  const readOnly = !!self.read_only;
  const scoped = ['analyst','replenisher'].includes(form.role);
  const preserve = current.access_enabled && current.role === form.role && form.status !== 'Vigente';
  const visible = sortByName(catalog.data?.stores || []).filter(store => (!region || store.region === region) && (!commune || store.commune === commune));
  const selected = new Set(form.storeCodes);
  const allVisible = visible.length > 0 && visible.every(store => selected.has(store.code));
  const change = key => ({value:form[key] || '',onChange:event => setForm({...form,[key]:event.target.value})});
  async function submit(event) {
    event.preventDefault();setBusy(true);setError('');
    try {
      if (enabled && !current.access_enabled && password !== confirmation) throw Error('Las contraseñas no coinciden.');
      const person = Object.fromEntries(['names','paternal','maternal','email','username','position','startDate','endDate','status','role','storeCodes','allStores'].map(key => [key,form[key]]));
      await api('/api/admin/people' + (current.id ? '/' + encodeURIComponent(current.id) : ''), {
        method:current.id ? 'PATCH' : 'POST',body:{person,version:current.version,enable_access:enabled,...(password ? {password} : {})},
      });
      onSaved();
    } catch (exception) {setError(exception.message);} finally {setBusy(false);}
  }
  return <form className="sb-form" onSubmit={submit}>
    <p className="full sb-hint">Solo Nombre de usuario, Email, Rol y Estado son obligatorios. Los datos personales, las fechas y los PDV se pueden completar después.</p>
    <fieldset className="mg-fields" disabled={busy || readOnly}>
      <label>Nombre de usuario<input {...change('username')} readOnly={!!current.access_enabled} required minLength={3} maxLength={80} autoComplete="off"/></label>
      <label>Email<input {...change('email')} type="email" required maxLength={180}/></label>
      <label>Rol<select {...change('role')} required disabled={own}>{Object.entries(ROLE_NAMES).filter(([value]) => value !== 'local-neura').map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label>Estado<select value={form.status} required disabled={own} onChange={event => setForm({...form,status:event.target.value,endDate:event.target.value === 'De baja' ? form.endDate : ''})}><option>Vigente</option><option>Suspendido</option><option>De baja</option></select></label>
      <label>Nombres<input {...change('names')} maxLength={100}/></label>
      <label>Apellido paterno<input {...change('paternal')} maxLength={80}/></label>
      <label>Apellido materno<input {...change('maternal')} maxLength={80}/></label>
      <label>Cargo<input {...change('position')} maxLength={120}/></label>
      <label>Fecha alta<input {...change('startDate')} type="date"/></label>
      {form.status === 'De baja' && <label>Fecha baja<input {...change('endDate')} type="date" min={form.startDate}/></label>}
      {scoped && <fieldset className="full people-store-scope" disabled={preserve}>
        <legend>PDV asignados (opcional)</legend><p className="sb-hint">Sin PDV asignados, esta cuenta no podrá consultar ni realizar mediciones de locales.</p>
          <div className="people-scope-filters"><label>Región<select value={region} onChange={event => {setRegion(event.target.value);setCommune('');}}><option value="">Todas las regiones</option>{orderRegions(catalog.data?.locations.regions || []).map(item => <option key={item.code}>{item.name}</option>)}</select></label>
          <label>Comuna<select value={commune} disabled={!region} onChange={event => setCommune(event.target.value)}><option value="">Todas las comunas</option>{sortByName(catalog.data?.locations.regions.find(item => item.name === region)?.communes || []).map(item => <option key={item.code}>{item.name}</option>)}</select></label></div>
          <label className="people-check"><input type="checkbox" checked={allVisible} disabled={!visible.length} ref={input => {if (input) input.indeterminate = !allVisible && visible.some(store => selected.has(store.code));}} onChange={event => {
            const next = new Set(selected);visible.forEach(store => event.target.checked ? next.add(store.code) : next.delete(store.code));setForm({...form,storeCodes:[...next]});
          }}/>Seleccionar todos</label><p className="sb-hint">Aplica a los PDV que coinciden con los filtros.</p>
          <div className="people-store-options">{catalog.loading ? <Loading/> : visible.length ? visible.map(store => <label className="people-check" key={store.code}><input type="checkbox" checked={selected.has(store.code)} onChange={event => {
            const next = new Set(selected);event.target.checked ? next.add(store.code) : next.delete(store.code);setForm({...form,storeCodes:[...next]});
          }}/>{store.name} · {store.code}</label>) : <p>No hay PDV con estos filtros.</p>}</div>
          <p className="sb-hint">{selected.size} PDV seleccionados</p>
        {preserve && <p className="sb-hint">La cuenta conservará sus PDV mientras esté suspendida o de baja.</p>}
      </fieldset>}
      <section className="full people-access"><h3>Acceso a la plataforma</h3><p>{CAPABILITIES[form.role]}</p>
        <label className="people-check"><input type="checkbox" checked={enabled} disabled={!!current.access_enabled} onChange={event => setEnabled(event.target.checked)}/>Habilitar inicio de sesión</label>
        {!enabled && <p className="sb-hint">Se guardará la ficha sin acceso. Para que pueda iniciar sesión, habilita esta opción y define una contraseña.</p>}
        {enabled && !current.access_enabled && <div className="people-scope-filters"><label>Contraseña inicial<input type="password" minLength={8} maxLength={512} pattern={PASSWORD_PATTERN} title={PASSWORD_HELP} required value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password"/></label><label>Repite la contraseña<input type="password" minLength={8} maxLength={512} pattern={PASSWORD_PATTERN} title={PASSWORD_HELP} required value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="new-password"/></label></div>}
        {enabled && !current.access_enabled && <p className="sb-hint">{PASSWORD_HELP} La contraseña se solicita únicamente al habilitar el inicio de sesión.</p>}
        <p className="sb-hint">Vigente permite operar. Suspendido permite entrar y consultar. De baja bloquea el acceso y conserva el historial.</p>
      </section>
    </fieldset>
    <div className="full"><ErrorBox error={error || catalog.error} onRetry={catalog.error ? catalog.reload : undefined}/></div>
    <div className="sb-actions"><button type="button" disabled={busy} onClick={onClose}>Cancelar</button><button type="submit" className="action" disabled={busy || catalog.loading || !!catalog.error || readOnly}>{busy ? 'Guardando…' : 'Guardar'}</button></div>
  </form>;
}
