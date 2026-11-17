'use client';
import { useEffect, useState } from 'react';
import { profileOf, scopeLabel } from '../../lib/profiles.mjs';
import { api } from '../../lib/sb';
import { useApi, Header, Loading, ErrorBox } from './ui';
import AdminHome from '../home/AdminHome';
import FieldHome from '../home/FieldHome';
import ViewerHome from '../home/ViewerHome';
import HomeReadingDetail from '../home/HomeReadingDetail';

export default function Home({ user, go }) {
  if (profileOf(user) === 'admin') return <AdminHome go={go} user={user} />;
  return <OperationalHome user={user} go={go} />;
}

function OperationalHome({ user, go }) {
  const [selected, setSelected] = useState(null);
  const { data, error, loading, reload } = useApi(() => api('/api/home'), []);
  const role = profileOf(user);
  useEffect(() => {
    if (role !== 'replenisher') return;
    const refresh = () => { if (document.visibilityState === 'visible') reload(); };
    const timer = setInterval(refresh, 15000);
    window.addEventListener('focus', refresh);
    return () => { clearInterval(timer); window.removeEventListener('focus', refresh); };
  }, [role, reload]);
  const descriptions = {
    analyst: 'Tu trabajo de análisis y las revisiones pendientes de tus PDV.',
    replenisher: 'Tus mediciones y las decisiones de revisión del analista.',
    viewer: 'Prioridades para la toma de decisiones.',
  };
  return <section>
    <Header eyebrow={scopeLabel(user)} title="Inicio" subtitle={descriptions[role]}>
      {role !== 'viewer' && <button type="button" className="action" onClick={() => go('escanear')}>Escanear góndola</button>}
      {role === 'viewer' && <button type="button" className="action" onClick={() => go('dashboards')}>Ver dashboards</button>}
    </Header>
    <ErrorBox error={error} onRetry={reload} />
    {loading && !data && <Loading text="Cargando inicio…" />}
    {data && (role === 'viewer'
      ? <ViewerHome data={data} go={go} onOpen={setSelected} />
      : <FieldHome data={data} role={role} onOpen={setSelected} />)}
    {selected && <HomeReadingDetail row={selected} user={user} go={go} onClose={() => { setSelected(null); reload(); }} />}
  </section>;
}
