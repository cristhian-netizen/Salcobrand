'use client';

import Icon from './icons';
import {ROLE_NAMES} from '../../lib/sb';
import {profileOf, scopeLabel} from '../../lib/profiles.mjs';
import {enabled} from '../identity/identity.mjs';

// [id, label, icon, roles]
export const MODULES = [
  ['productos', 'Productos', 'products', ['admin']],
  ['pdv', 'Puntos de venta', 'home', ['admin']],
  ['infraestructura', 'Infraestructura', 'infrastructure', ['admin']],
  ['inicio', 'Inicio', 'home', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['escanear', 'Escanear góndola', 'scan', ['replenisher', 'analyst']],
  ['gondolas', 'Góndolas y lecturas', 'infrastructure', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['mediciones', 'Mediciones', 'reports', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['revision', 'Revisión', 'review', ['analyst']],
  ['alertas', 'Alertas', 'alerts', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['planogramas', 'Planogramas', 'planograms', ['admin']],
  ['reportes', 'Reportes', 'reports', ['analyst', 'viewer', 'admin']],
  ['uso-analisis', 'Uso de análisis', 'dashboards', ['viewer']],
  ['dashboards', 'Dashboards', 'dashboards', ['analyst', 'viewer', 'admin']],
  ['enlaces', 'Enlaces de captura', 'link', ['admin']],
  ['usuarios', 'Personas y roles', 'people', ['admin']],
  ['cuenta', 'Mi cuenta', 'account', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['configuracion', 'Configuración', 'settings', ['admin']],
  ['ayuda', 'Ayuda y soporte', 'help', ['analyst', 'viewer', 'admin']],
];
const GROUPS = [['General', ['inicio']], ['Operación', ['escanear', 'mediciones', 'gondolas', 'revision', 'alertas']], ['Análisis', ['dashboards', 'reportes', 'uso-analisis']], ['Administración', ['pdv', 'infraestructura', 'productos', 'planogramas', 'enlaces', 'usuarios', 'configuracion', 'cuenta', 'ayuda']]];
export const labelOf = id => MODULES.find(m => m[0] === id)?.[1] || id;
export const allowed = (id, role) => !!MODULES.find(m => m[0] === id)?.[3].includes(profileOf(role));

export default function Sidebar({user, current, onSelect, onLogout, open = false, onClose}) {
  const scope = scopeLabel(user);
  return <aside className="nv-sidebar" data-open={open ? 'true' : undefined} aria-label="Navegación">
    <div className="nv-sidebar-top">
      <div className="nv-brand"><span className="nv-mark" aria-hidden="true">n</span><span className="nv-brand-name">neuravision</span></div>
      <button className="nv-icon-button nv-sidebar-close" type="button" onClick={onClose} aria-label="Cerrar menú"><Icon name="close"/></button>
    </div>
    <div className="nv-tenant">
      {user.tenant?.logo ? <img src={user.tenant.logo} alt="Logo del cliente"/> : <span className="nv-tenant-initial" aria-hidden="true">{(user.tenant?.name || 'Salcobrand').slice(0,1)}</span>}
      <div className="nv-tenant-info"><strong>{user.tenant?.name || 'Salcobrand'}</strong><small>{scope}</small></div>
    </div>
    <nav aria-label="Principal">{GROUPS.map(([group, ids]) => {
      const visible = ids.filter(id => allowed(id, user.role) && (id !== 'planogramas' || enabled(user, 'planograms')));
      return visible.length ? <div className="nv-nav-section" key={group}>
        <p className="nv-nav-group">{group}</p>
        {visible.map(id => { const [, label, icon] = MODULES.find(m => m[0] === id); return <button key={id} type="button" aria-current={current === id ? 'page' : undefined} onClick={() => onSelect(id)}><Icon name={icon}/>{label}</button>; })}
      </div> : null;
    })}</nav>
    <div className="nv-sidebar-footer">
      {user.internal && <button className="nv-logout" type="button" onClick={() => onSelect('consola')}><Icon name="settings"/>Consola interna</button>}
      <div className="nv-user"><span className="nv-avatar" aria-hidden="true">{user.username.slice(0, 1).toUpperCase()}</span><div><strong>{user.username}</strong><small>{ROLE_NAMES[user.role] || user.role}</small></div></div>
      <button className="nv-logout" type="button" onClick={onLogout}><Icon name="logout"/>Cerrar sesión</button>
    </div>
  </aside>;
}
