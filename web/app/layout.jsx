import {Inter} from 'next/font/google';
import './theme.css';
import './sb.css';
import './identity.css';
import '../modules/help/help.css';

const inter = Inter({subsets:['latin'], display:'swap', variable:'--nv-font-inter'});

export const metadata = {title:'NeuraVision', description:'Portal de control de exhibición e inventario'};
export const viewport = {width:'device-width', initialScale:1, themeColor:'#f5f6f8'};

export default function Layout({children}) {
  return <html lang="es" className={inter.variable}><body>{children}</body></html>;
}
