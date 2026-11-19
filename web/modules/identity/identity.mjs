export const FONTS = ['Arial', 'Verdana', 'Tahoma', 'Trebuchet MS', 'Georgia', 'Times New Roman', 'system-ui'];
export const DEFAULT_MODEL = {remoteOrgId: '', credentialEnv: 'INTEGRATION_NEURAVISION_KEY'};
export const DEFAULT_IDENTITY = {schema: 1, id: 'nuevo-cliente', name: 'Nuevo cliente', logo: '', theme: 'default', primaryColor: '#0074c8', sidebarColor: '#ffffff', modules: {vision: true, planograms: true, sales: false}, typography: {}};
export function identityOnly(value) {
  return Object.fromEntries(Object.keys(DEFAULT_IDENTITY).map(key => [key, structuredClone(value[key] ?? DEFAULT_IDENTITY[key])]));
}
export function onColor(hex) {
  const rgb = hex.replace('#', '').match(/../g)?.map(value => parseInt(value, 16) / 255) || [0, 0, 0];
  const light = rgb.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return light[0] * .2126 + light[1] * .7152 + light[2] * .0722 > .179 ? '#101828' : '#ffffff';
}
export function identityStyle(tenant = {}) {
  const sidebar = tenant.typography?.sidebar || {}, content = tenant.typography?.content || {};
  return {'--nv-primary': tenant.primaryColor || '#0074c8', '--nv-on-primary': onColor(tenant.primaryColor || '#0074c8'), '--nv-sidebar-bg': tenant.sidebarColor || '#ffffff', '--nv-sidebar-fg': sidebar.color || onColor(tenant.sidebarColor || '#ffffff'), '--nv-sidebar-font': sidebar.fontFamily || 'var(--nv-font)', '--nv-sidebar-size': sidebar.fontSize ? sidebar.fontSize + 'px' : '13.5px', ...(content.fontFamily ? {'--nv-font': content.fontFamily} : {}), ...(content.color ? {'--nv-text': content.color} : {})};
}
export const enabled = (user, key) => user?.tenant?.modules?.[key] !== false;
