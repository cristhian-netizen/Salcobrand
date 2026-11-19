// Public capture route (/captura#<token>): statically exported, reachable without any session.
// Everything here is deliberately neutral — title, description, icon, colors — so the page says
// nothing about whose system it is; the client component strips the portal favicon at runtime
// because the app-level icon files would otherwise apply to every exported route.
import './captura.css';
import CapturePage from '../../modules/captura/CapturePage';

const NEUTRAL_ICON = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="#9ca3af"/></svg>');

export const metadata = {
  title: {absolute: 'Fotos'},
  description: 'Envío de fotos',
  robots: {index: false, follow: false},
  icons: {icon: NEUTRAL_ICON},
};
export const viewport = {width: 'device-width', initialScale: 1, themeColor: '#ffffff'};

export default function Page() {
  return <CapturePage/>;
}
