'use client';
import {sessionUrl} from '../../lib/tab-session.mjs';

import Icon from './icons';
import {ROLE_NAMES} from '../../lib/sb';
import {profileOf} from '../../lib/profiles.mjs';
import {enabled} from '../identity/identity.mjs';

import {MODULES, GROUPS, visibleInSidebar} from './modules.mjs';
export {allowed,labelOf} from './modules.mjs';

export default function Sidebar({user, current, onSelect, onLogout, open = false, onClose}) {
  const clientName = user.tenant?.name || 'Salcobrand';
  const isSalcobrand = user.tenant?.id === 'salcobrand' || clientName.trim().toLocaleLowerCase('es') === 'salcobrand';
  // The brand row already carries the Salcobrand lockup, so the large logo block only renders a tenant-provided logo.
  const clientLogo = user.tenant?.logo || null;
  return <aside className="nv-sidebar" data-open={open ? 'true' : undefined} aria-label="Navegación">
    <div className="nv-sidebar-top">
      <div className="nv-brand">{isSalcobrand && <img className="nv-brand-logo" src="/branding/salcobrand-logo.svg" alt="" width="34" height="34"/>}<span className="nv-brand-name">{clientName}</span></div>
      <button className="nv-icon-button nv-sidebar-close" type="button" onClick={onClose} aria-label="Cerrar menú"><Icon name="close"/></button>
    </div>
    {clientLogo && <div className="nv-client-logo"><img src={sessionUrl(clientLogo)} alt={isSalcobrand ? 'Farmacias Salcobrand' : clientName} width="112" height="112"/></div>}
    <nav aria-label="Principal">{GROUPS.map(([group, ids]) => {
      const visible = ids.filter(id => visibleInSidebar(id, user.role) && (id !== 'planogramas' || enabled(user, 'planograms')));
      return visible.length ? <div className="nv-nav-section" key={group}>
        <p className="nv-nav-group">{group}</p>
        {visible.map(id => { const [, label, icon] = MODULES.find(m => m[0] === id); return <button key={id} type="button" aria-current={current === id ? 'page' : undefined} onClick={() => onSelect(id)}><Icon name={icon}/>{label}</button>; })}
      </div> : null;
    })}</nav>
    <div className="nv-sidebar-footer">
      {user.internal && profileOf(user) !== 'local-neura' && <button className="nv-logout" type="button" onClick={() => onSelect('consola')}><Icon name="settings"/>Consola interna</button>}
      <div className="nv-user"><span className="nv-avatar" aria-hidden="true">{user.username.slice(0, 1).toUpperCase()}</span><div><strong>{user.username}</strong><small>{ROLE_NAMES[user.role] || user.role}</small></div></div>
      <button className="nv-logout" type="button" onClick={onLogout}><Icon name="logout"/>Cerrar sesión</button>
    </div>
  </aside>;
}
