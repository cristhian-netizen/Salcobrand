import {profileOf} from '../../lib/profiles.mjs';
// [id, label, icon, roles]
export const MODULES = [
  ['productos', 'Productos', 'products', ['admin']],
  ['pdv', 'Puntos de venta', 'home', ['admin']],
  ['infraestructura', 'Infraestructura', 'infrastructure', ['admin']],
  ['inicio', 'Inicio', 'home', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['escanear', 'Escanear góndola', 'scan', ['replenisher', 'analyst']],
  ['gondolas', 'Detalle de medición', 'infrastructure', ['replenisher', 'analyst', 'viewer', 'admin','local-neura']],
  ['mediciones', 'Mediciones', 'reports', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['revision', 'Revisión', 'review', ['local-neura']],
  ['alertas', 'Alertas', 'alerts', ['replenisher', 'analyst', 'viewer', 'admin']],
  ['planogramas', 'Planogramas', 'planograms', ['admin']],
  ['reportes', 'Reportes', 'reports', ['analyst', 'viewer', 'admin']],
  ['uso-analisis', 'Uso de análisis', 'dashboards', ['viewer']],
  ['dashboards', 'Dashboards', 'dashboards', ['analyst', 'viewer']],
  ['enlaces', 'Enlaces de captura', 'link', []],
  ['usuarios', 'Personas y roles', 'people', ['admin']],
  ['cuenta', 'Mi cuenta', 'account', ['replenisher', 'analyst', 'viewer', 'admin','local-neura']],
  ['configuracion', 'Configuración', 'settings', ['admin']],
  ['ayuda', 'Ayuda y soporte', 'help', ['analyst', 'viewer', 'admin']],
];
export const GROUPS = [['Verificación interna', ['revision']], ['General', ['inicio']], ['Operación', ['escanear', 'mediciones', 'alertas']], ['Análisis', ['dashboards', 'reportes', 'uso-analisis']], ['Administración', ['pdv', 'infraestructura', 'productos', 'planogramas', 'usuarios', 'configuracion', 'ayuda']]];
export const labelOf = id => MODULES.find(m => m[0] === id)?.[1] || id;
export const allowed = (id, role) => !!MODULES.find(m => m[0] === id)?.[3].includes(profileOf(role));

