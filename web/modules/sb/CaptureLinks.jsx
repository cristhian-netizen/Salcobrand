'use client';
import {useState} from 'react';
import {api, fmt} from '../../lib/sb';
import Icon from '../navigation/icons';
import {useApi, Header, Card, Loading, Empty, ErrorBox, Pill, Modal} from './ui';

export default function CaptureLinks({notify}) {
  const {data, error, loading, reload} = useApi(() => api('/api/admin/capture-links'), []);
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState(null);
  const [actionError, setActionError] = useState('');
  async function toggle(link) {
    setActionError('');
    try { await api(`/api/admin/capture-links/${encodeURIComponent(link.token)}/${link.active ? 'desactivar' : 'activar'}`, {method: 'POST'}); reload(); notify(link.active ? 'Enlace desactivado.' : 'Enlace activado.'); }
    catch (e) { setActionError(e.message); }
  }
  const urlOf = l => l.url || `${window.location.origin}/captura/${l.token}`;
  return <section>
    <Header eyebrow="Administración" title="Enlaces de captura" subtitle="Enlaces sin usuario para que el personal de cada local suba fotos desde su teléfono. Las fotos se guardan, no se analizan.">
      <button className="action" type="button" onClick={() => setCreating(true)}><Icon name="plus" size={16}/>Nuevo enlace</button>
    </Header>
    <ErrorBox error={error || actionError} onRetry={error ? reload : undefined}/>
    <Card body={false}>
      {loading && !data ? <Loading/> : data?.length ? <div className="sb-table"><table><thead><tr><th>Local</th><th>Enlace</th><th className="sb-num">Fotos</th><th>Última</th><th>Estado</th><th></th></tr></thead><tbody>
        {data.map(l => <tr key={l.token}><td><b>{l.label || l.store_id}</b><small>{l.universal ? `Universal · ${l.locales?.length || 0} locales` : l.store_id}</small></td>
          <td><button className="link" type="button" onClick={() => navigator.clipboard?.writeText(urlOf(l)).then(() => notify('Enlace copiado.'))} title="Copiar">/captura/{l.token}</button>
            <small>{l.expires_at ? `Vence ${fmt.date(l.expires_at)}` : 'Sin vencimiento'} · máx. {l.max_per_day}/día</small></td>
          <td className="sb-num">{l.fotos ?? 0}</td><td>{l.ultima ? fmt.ago(l.ultima) : '—'}</td>
          <td>{l.active ? <Pill kind="ok">Activo</Pill> : <Pill>Inactivo</Pill>}</td>
          <td className="sb-actions"><button type="button" onClick={() => setViewing(l)}>Fotos</button><button type="button" onClick={() => toggle(l)}>{l.active ? 'Desactivar' : 'Activar'}</button></td></tr>)}
      </tbody></table></div> : <Empty>No hay enlaces de captura.</Empty>}
    </Card>
    {creating && <Create onClose={() => setCreating(false)} onCreated={() => { setCreating(false); reload(); notify('Enlace creado.'); }}/>}
    {viewing && <Captures link={viewing} onClose={() => setViewing(null)}/>}
  </section>;
}

function Create({onClose, onCreated}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    const f = new FormData(e.currentTarget);
    const body = {store_id: String(f.get('store_id')).trim().toUpperCase(), label: String(f.get('label')).trim(), max_per_day: Number(f.get('max_per_day')) || 600};
    if (Number(f.get('days')) > 0) body.days = Number(f.get('days'));
    try { await api('/api/admin/capture-links', {method: 'POST', body}); onCreated(); } catch (err) { setError(err.message); setBusy(false); }
  }
  return <Modal title="Nuevo enlace de captura" onClose={onClose}>
    {error && <div className="sb-error" role="alert">{error}</div>}
    <form className="sb-form" onSubmit={submit}>
      <label>Código de local<input name="store_id" required placeholder="Ej.: L128"/></label>
      <label>Nombre del local<input name="label" required placeholder="Ej.: Local 128"/></label>
      <label>Vence en (días, opcional)<input name="days" type="number" min="1"/></label>
      <label>Máximo de fotos por día<input name="max_per_day" type="number" min="1" defaultValue="600"/></label>
      <div className="sb-actions"><button type="button" onClick={onClose}>Cancelar</button><button disabled={busy}>{busy ? 'Creando…' : 'Crear enlace'}</button></div>
    </form>
  </Modal>;
}

function Captures({link, onClose}) {
  const {data, error, loading} = useApi(() => api(`/api/admin/captures?token=${encodeURIComponent(link.token)}&limit=200`), [link.token]);
  return <Modal title={`Fotos · ${link.label || link.store_id}`} onClose={onClose}>
    <ErrorBox error={error}/>
    {loading ? <Loading/> : data?.length ? <div className="sb-previews">{data.map(c => <figure key={c.id}>
      <a href={c.url} target="_blank" rel="noreferrer"><img src={c.url} alt={`Foto ${c.id}`} loading="lazy"/></a>
      <figcaption><span>{fmt.dateTime(c.created_at)}</span><span>{c.tipo}</span></figcaption></figure>)}</div> : <Empty>Este enlace aún no tiene fotos.</Empty>}
  </Modal>;
}
