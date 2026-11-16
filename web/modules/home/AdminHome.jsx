import Icon from '../navigation/icons';
import { Header } from '../sb/ui';
import {enabled} from '../identity/identity.mjs';

const SHORTCUTS = [
  ['usuarios', 'Personas y roles', 'people'],
  ['pdv', 'Puntos de venta', 'stores'],
  ['infraestructura', 'Infraestructura', 'infrastructure'],
  ['productos', 'Productos', 'products'],
  ['planogramas', 'Planogramas', 'planograms'],
  ['configuracion', 'Configuración', 'settings'],
];

export default function AdminHome({ go, user }) {
  return <section>
    <Header title="Inicio" subtitle="Administra las cuentas, los puntos de venta y los catálogos de tu organización." />
    <nav className="home-shortcuts" aria-label="Accesos de administración">
      {SHORTCUTS.filter(([route]) => route !== 'planogramas' || enabled(user, 'planograms')).map(([route, label, icon]) => <button type="button" key={route} onClick={() => go(route)}>
        <Icon name={icon} size={22} /><span>{label}</span><Icon name="chevron" size={16} />
      </button>)}
    </nav>
  </section>;
}
