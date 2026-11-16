// Inline stroke icons (24px grid, currentColor). No runtime dependency.
const paths = {
  home: <><path d="M3.5 10.2 12 3.5l8.5 6.7V19a1.5 1.5 0 0 1-1.5 1.5h-4.2v-6h-5.6v6H5A1.5 1.5 0 0 1 3.5 19z"/></>,
  measurements: <><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2.8h6V4"/><path d="m9 13.2 2.1 2.1L15.2 11"/></>,
  scan: <><path d="M4 8.5h3.2L9 5.5h6l1.8 3H20v11H4z"/><circle cx="12" cy="13.5" r="3.4"/></>,
  alerts: <><path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.8 1.8H4.2z"/><path d="M10 20.5a2 2 0 0 0 4 0"/></>,
  dashboards: <><path d="M4 4v16h16"/><rect x="7.5" y="11" width="3" height="6" rx=".8"/><rect x="12.5" y="7" width="3" height="10" rx=".8"/><rect x="17.5" y="13" width="2.5" height="4" rx=".8"/></>,
  reports: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11v6"/><path d="m9.2 14.4 2.8 2.8 2.8-2.8"/></>,
  people: <><circle cx="9" cy="8" r="3.4"/><path d="M2.8 20a6.2 6.2 0 0 1 12.4 0"/><path d="M16 4.7a3.4 3.4 0 0 1 0 6.6"/><path d="M18.2 14.3a6.2 6.2 0 0 1 3 5.7"/></>,
  stores: <><path d="M3.8 9.5 5.4 4h13.2l1.6 5.5"/><path d="M3.8 9.5a2.7 2.7 0 0 0 5.4 0 2.7 2.7 0 0 0 5.6 0 2.7 2.7 0 0 0 5.4 0"/><path d="M5 12.2V20h14v-7.8"/><path d="M10 20v-4.8h4V20"/></>,
  infrastructure: <><rect x="4" y="3" width="16" height="18" rx="1.6"/><path d="M4 9h16M4 15h16"/><path d="M8 6h2M8 12h4M8 18h3"/></>,
  products: <><path d="M20.5 7.8 12 3.2 3.5 7.8v8.4l8.5 4.6 8.5-4.6z"/><path d="m3.5 7.8 8.5 4.6 8.5-4.6"/><path d="M12 12.4v8.4"/></>,
  planograms: <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/></>,
  usage: <><path d="M4 18a8 8 0 1 1 16 0"/><path d="m12 18 3.6-5.4"/><path d="M12 18h.01"/></>,
  settings: <><path d="M4 6.5h9M17 6.5h3M4 12h3M11 12h9M4 17.5h11M19 17.5h1"/><circle cx="15" cy="6.5" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17.5" r="2"/></>,
  help: <><circle cx="12" cy="12" r="8.8"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.5"/><path d="M12 17h.01"/></>,
  logout: <><path d="M14.5 4H18a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3.5"/><path d="m10 16-4-4 4-4"/><path d="M6 12h10"/></>,
  menu: <><path d="M4 6.5h16M4 12h16M4 17.5h16"/></>,
  close: <><path d="m6 6 12 12M18 6 6 18"/></>,
  chevron: <><path d="m9.5 6 6 6-6 6"/></>,
  arrow: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
  clock: <><circle cx="12" cy="12" r="8.8"/><path d="M12 7.5V12l3 2"/></>,
  score: <><path d="M12 3.5 14.6 9l5.9.7-4.4 4 1.2 5.8L12 16.6 6.7 19.5 7.9 13.7l-4.4-4L9.4 9z"/></>,
  review: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/></>,
  link: <><path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.2 1.2"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/></>,
  account: <><circle cx="12" cy="8.5" r="3.8"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/></>,
  trash: <><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/></>,
  download: <><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/></>,
  upload: <><path d="M12 20V9M7.5 13.5 12 9l4.5 4.5M5 4.5h14"/></>,
  plus: <><path d="M12 5v14M5 12h14"/></>,
};

export const navIcons = {
  'Inicio': 'home', 'Mediciones': 'measurements', 'Escanear': 'scan', 'Alertas': 'alerts', 'Dashboards': 'dashboards',
  'Reportes': 'reports', 'Personas y roles': 'people', 'Puntos de venta': 'stores', 'Infraestructura': 'infrastructure',
  'Productos': 'products', 'Planogramas': 'planograms', 'Uso de análisis': 'usage', 'Configuración': 'settings', 'Ayuda y soporte': 'help',
};

export default function Icon({ name, size = 18, className = 'nv-icon' }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{paths[name] || paths.chevron}</svg>;
}
