'use client';
import {useCallback, useEffect, useState} from 'react';
import Login from '../modules/auth/Login';
import Sidebar, {allowed, labelOf} from '../modules/navigation/Sidebar';
import Icon from '../modules/navigation/icons';
import {auth, subscribeSession, hasPendingMutation, ROLE_NAMES} from '../lib/sb';
import {scopeLabel, can} from '../lib/profiles.mjs';
import Home from '../modules/sb/Home';
import HomeSkeleton from '../modules/home/HomeSkeleton';
import Scan from '../modules/sb/Scan';
import Gondolas from '../modules/sb/Gondolas';
import Measurements from '../modules/sb/Measurements';
import Review from '../modules/sb/Review';
import Alerts from '../modules/sb/Alerts';
import Planograms from '../modules/catalog/Planograms';
import Products from '../modules/catalog/Products';
import Reports from '../modules/sb/Reports';
import CaptureLinks from '../modules/sb/CaptureLinks';
import Users from '../modules/sb/Users';
import Account from '../modules/sb/Account';
import Help from '../modules/help/Help';
import Stores from '../modules/management/Stores';
import Infrastructure from '../modules/management/Infrastructure';
import Settings from '../modules/settings/Settings';
import Dashboard from '../modules/dashboard/Dashboard';
import AnalysisUsage from '../modules/usage/AnalysisUsage';
import ApiIntegrations from '../modules/settings/ApiIntegrations';
import ClientConsole from '../modules/identity/ClientConsole';
import {identityStyle, enabled} from '../modules/identity/identity.mjs';

const VIEWS = {'uso-analisis': AnalysisUsage, inicio: Home, escanear: Scan, mediciones: Measurements, gondolas: Gondolas, revision: Review, alertas: Alerts, planogramas: Planograms,
  reportes: Reports, dashboards: Dashboard, enlaces: CaptureLinks, usuarios: Users, cuenta: Account, ayuda: Help, pdv: Stores, infraestructura: Infrastructure, productos: Products, configuracion: Settings, apis: ApiIntegrations};

function parseHash() {
  const parts = (typeof window === 'undefined' ? '' : window.location.hash).replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  return {view: parts[0] || 'inicio', rest: parts.slice(1)};
}

export default function Page() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [homeEntry, setHomeEntry] = useState(false);
  const [route, setRoute] = useState({view: 'inicio', rest: []});
  const [navOpen, setNavOpen] = useState(false);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    setRoute(parseHash());
    setHomeEntry(window.location.hash.replace(/\/$/, '') === '#/inicio');
    const onHash = () => { setRoute(parseHash()); setNavOpen(false); };
    window.addEventListener('hashchange', onHash);
    auth.me().then(setUser).catch(() => setUser(null)).finally(() => setChecking(false));
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => subscribeSession(() => { setUser(null); setNotice('Tu sesión expiró. Inicia sesión nuevamente.'); }), []);
  useEffect(() => {
    const guard = e => { if (hasPendingMutation()) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, []);
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(''), 7000); return () => clearTimeout(t); }, [notice]);
  useEffect(() => { if (!navOpen) return; const k = e => { if (e.key === 'Escape') setNavOpen(false); }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [navOpen]);
  useEffect(() => { document.title = user?.internal && user.role !== 'local-neura' && (!user.portal_access || route.view === 'consola') ? 'Consola interna · NeuraVision' : user?.tenant?.name || 'Salcobrand'; }, [user, route.view]);

  const go = useCallback(path => { window.location.hash = '/' + String(path).replace(/^[#/]+/, ''); }, []);
  async function logout() {
    try { await auth.logout(); } catch {}
    setUser(null); setNavOpen(false); window.location.hash = '';
  }

  const toast = notice && <div className="nv-toast" role="status"><span>{notice}</span><button type="button" onClick={() => setNotice('')}>Cerrar</button></div>;

  if (checking && homeEntry) return <HomeSkeleton fullPage/>;
  if (checking) return <div className="nv-splash" role="status"><span className="nv-spinner" aria-hidden="true"/>Cargando…</div>;
  if (!user) return <>{toast}<Login onLogin={async (u, p) => { await auth.login(u, p); setUser(await auth.me()); }}/></>;
  if (user.internal && user.role !== 'local-neura' && (!user.portal_access || route.view === 'consola')) return <ClientConsole user={user} onLogout={logout} onPortal={user.portal_access ? () => go('inicio') : undefined}/>;

  const view = allowed(route.view, user.role) && VIEWS[route.view] && (route.view !== 'planogramas' || enabled(user, 'planograms')) ? route.view : user.role === 'local-neura' ? 'revision' : 'inicio';
  const View = VIEWS[view];
  return <>{toast}
    <div id="nv" className="shell" style={identityStyle(user.tenant)}>
      <Sidebar user={user} current={view} onSelect={id => { go(id); setNavOpen(false); }} onLogout={logout} open={navOpen} onClose={() => setNavOpen(false)}/>
      {navOpen && <div className="nv-scrim" onClick={() => setNavOpen(false)} aria-hidden="true"/>}
      <div className="nv-content">
        <header className="nv-topbar">
          <button className="nv-icon-button nv-menu" type="button" aria-label="Abrir menú" aria-expanded={navOpen} onClick={() => setNavOpen(true)}><Icon name="menu"/></button>
          <nav className="nv-breadcrumb" aria-label="Ubicación"><span>{user.tenant?.name || 'Salcobrand'}</span><Icon name="chevron" size={14}/><strong>{labelOf(view)}</strong></nav>
          <details className="nv-user-menu">
            <summary className="nv-topbar-user" aria-label="Menú de usuario"><span className="nv-avatar" aria-hidden="true">{user.username.slice(0,1).toUpperCase()}</span><span className="nv-topbar-user-text"><strong>{user.username}</strong><small>{ROLE_NAMES[user.role] || user.role} · {scopeLabel(user)}</small></span><Icon name="chevron" size={14}/></summary>
            <div className="nv-user-menu-items"><button type="button" onClick={event => {event.currentTarget.closest('details').open=false;go('cuenta');}}>Mi cuenta</button><button type="button" onClick={logout}>Cerrar sesión</button></div>
          </details>
        </header>
        <main>{user.read_only && <div className="sb-qa-banner" role="status">Tu cuenta está suspendida y permite solo consultas.</div>}{user.environment === 'profile-qa' && <div className="sb-qa-banner" role="status">QA local · datos ficticios · motor deshabilitado</div>}{user.environment === 'capture-dev' && <div className="sb-qa-banner" role="status">Desarrollo local · análisis real mediante Salcobrand dev</div>}<div className="nv-page" key={view + '/' + (route.rest[0] || '')}><View user={user} rest={view === route.view ? route.rest : []} go={go} notify={setNotice}/></div></main>
      </div>
    </div>
  </>;
}
