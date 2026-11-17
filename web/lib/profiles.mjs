export const ROLE_NAMES = {admin: 'Administrador', analyst: 'Analista', replenisher: 'Reponedor', viewer: 'Superusuario', 'local-neura':'local-neura'};
const LEGACY = {supervisor: 'analyst', tienda: 'replenisher'};
export const profileOf = user => {
  const role = typeof user === 'string' ? user : user?.profile || user?.role;
  return LEGACY[role] || (Object.hasOwn(ROLE_NAMES, role) ? role : null);
};
const permissions = {
  read: ['admin', 'analyst', 'replenisher', 'viewer','local-neura'],
  train: ['local-neura'],
  scan: ['analyst', 'replenisher'], review: ['analyst'], resolve: ['analyst'],
  manage: ['admin'], report: ['admin', 'analyst', 'viewer'], dashboard: ['analyst', 'viewer'],
};
export const can = (user, action) => !(profileOf(user) === 'local-neura' && !user?.internal) && !(user?.read_only && ['scan','review','resolve','train'].includes(action)) && (permissions[action] || []).includes(profileOf(user));
export const normalizeUser = user => user ? {...user, profile: profileOf(user), role: profileOf(user)} : user;
export function scopeLabel(user) {
  if (profileOf(user) === 'local-neura') return 'Verificación interna · Neuramorphic';
  const stores = user.store_ids || (user.store_id ? [user.store_id] : []);
  return stores.length ? (stores.length === 1 ? user.store_name || stores[0] : `${stores.length} PDV asignados`)
    : ['replenisher', 'analyst'].includes(profileOf(user)) ? 'Sin PDV asignados' : 'Todos los locales';
}
