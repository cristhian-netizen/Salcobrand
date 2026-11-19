'use client';
// Administración → APIs. The administrator enters, replaces, removes and tests keys; the Superusuario sees the status.
// The server never sends a key back: only whether it is configured, its source and its last 4 characters.
import {useState} from 'react';
import {api, fmt} from '../../lib/sb';
import {useApi, Header, Card, Loading, ErrorBox, Pill} from '../sb/ui';

const SOURCE = {panel: 'Guardada en el panel', entorno: 'Desde variable del servidor'};

function FieldStatus({field}) {
  if (field.unreadable) return <Pill kind="bad">No se puede leer: ingrésala de nuevo</Pill>;
  if (!field.configured) return <Pill kind="warn">Sin configurar</Pill>;
  return <><Pill kind="ok">Configurada</Pill> <small className="sb-hint">{SOURCE[field.source] || ''}{field.secret && field.last4 ? ` · termina en …${field.last4}` : ''}{!field.secret && field.value ? ` · ${field.value}` : ''}</small></>;
}

function TestResult({test}) {
  if (!test) return <p className="sb-hint">Conexión sin probar.</p>;
  return <p className={test.ok ? 'sb-hint' : 'sb-error'} role="status">
    {test.ok ? 'Conexión correcta' : 'Conexión con problemas'} · {test.message}{test.at ? ` · ${fmt.dateTime(test.at)}` : ''}{test.by ? ` · ${test.by}` : ''}
  </p>;
}

function IntegrationCard({item, canEdit, onSaved}) {
  const blank = Object.fromEntries(item.fields.map(f => [f.name, '']));
  const [values, setValues] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  const [probe, setProbe] = useState(null);
  const filled = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v));

  async function run(action) {
    setBusy(true); setFailure('');
    try { await action(); } catch (error) { setFailure(error.message); } finally { setBusy(false); }
  }
  const save = event => { event.preventDefault(); run(async () => {
    const result = await api(`/api/admin/integrations/${item.id}`, {method: 'PUT', body: {version: item.version, values: filled}});
    setValues(blank); setProbe(null); onSaved(result, 'Configuración de APIs guardada.');
  }); };
  const remove = field => run(async () => {
    if (!window.confirm(`¿Quitar «${field.label}»? ${field.name === 'api_key' ? 'Sin clave el análisis no se ejecuta.' : ''}`)) return;
    const result = await api(`/api/admin/integrations/${item.id}`, {method: 'PUT', body: {version: item.version, values: {}, remove: [field.name]}});
    onSaved(result, `«${field.label}» quitada.`);
  });
  const test = () => run(async () => {
    const candidate = Object.keys(filled).length ? {values: filled} : {};
    const result = await api(`/api/admin/integrations/${item.id}/test`, {method: 'POST', body: candidate, timeout: 60000});
    setProbe(result);
    if (!result.candidate) onSaved(null);
  });

  return <Card title={item.label} subtitle={item.description}
    actions={item.docs_url && <a className="link" href={item.docs_url} target="_blank" rel="noreferrer">Documentación</a>}>
    <table className="sb-table"><tbody>
      {item.fields.map(field => <tr key={field.name}>
        <th scope="row">{field.label}</th>
        <td><FieldStatus field={field}/>{canEdit && field.source === 'panel' && <> <button type="button" className="link" disabled={busy} onClick={() => remove(field)}>Quitar</button></>}</td>
      </tr>)}
    </tbody></table>
    <TestResult test={probe && probe.candidate ? probe : item.test}/>
    {item.updated_at && <p className="sb-hint">Último cambio {fmt.dateTime(item.updated_at)} · {item.updated_by}</p>}
    {canEdit ? <form onSubmit={save} autoComplete="off">
      <fieldset className="settings-fields" disabled={busy}>
        {item.fields.map(field => <label key={field.name}>
          {field.secret ? (field.configured ? `Reemplazar ${field.label.toLowerCase()}` : field.label) : field.label}
          <input type={field.secret ? 'password' : 'text'} autoComplete={field.secret ? 'new-password' : 'off'} spellCheck={false}
            maxLength={300} value={values[field.name]} placeholder={field.secret ? 'kai_…' : (field.value || '')}
            onChange={e => setValues({...values, [field.name]: e.target.value})}/>
          {field.help && <small>{field.help}</small>}
        </label>)}
        <ErrorBox error={failure}/>
        <div className="sb-actions">
          <button type="button" disabled={busy} onClick={test}>{Object.keys(filled).length ? 'Probar antes de guardar' : 'Probar conexión'}</button>
          <button type="submit" className="action" disabled={busy || !Object.keys(filled).length}>Guardar</button>
        </div>
      </fieldset>
    </form> : <p className="sb-hint">Solo un administrador puede ingresar o cambiar claves. Las claves nunca se muestran.</p>}
  </Card>;
}

export default function ApiIntegrations({notify, embedded = false}) {
  const {data, error, loading, reload, setData} = useApi(() => api('/api/admin/integrations'), []);
  function saved(item, message) {
    if (item) setData({...data, integrations: data.integrations.map(i => i.id === item.id ? item : i)});
    else reload();
    if (message) notify?.(message);
  }
  const description = 'Claves y valores de conexión de servicios externos. Se guardan cifradas en el servidor y nunca se envían al navegador.';
  const refreshButton = <button type="button" onClick={reload} disabled={loading}>Actualizar</button>;
  return <section aria-label="Configuración de APIs">
    {embedded ? <div className="sb-head"><div><h2>APIs</h2><p>{description}</p></div><div className="sb-actions">{refreshButton}</div></div>
      : <Header eyebrow="Administración" title="APIs" subtitle={description}>{refreshButton}</Header>}
    <ErrorBox error={error} onRetry={reload}/>
    {loading && !data ? <Loading text="Cargando APIs…"/> : data?.integrations.map(item =>
      <IntegrationCard key={item.id + ':' + item.version} item={item} canEdit={data.can_edit} onSaved={saved}/>)}
  </section>;
}
