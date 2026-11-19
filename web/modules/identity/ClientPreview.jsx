import Img from '../common/Img';
import {identityStyle} from './identity.mjs';

export default function ClientPreview({tenant}) {
  return <section className="client-preview" style={identityStyle(tenant)} aria-label="Vista previa de identidad">
    <h2>Vista previa</h2>
    <div className="client-preview-layout">
      <aside><div className="client-preview-brand">{tenant.logo ? <Img src={tenant.logo} alt="Logo del cliente" eager/> : <b>{tenant.name?.slice(0, 1) || 'C'}</b>}<strong>{tenant.name || 'Cliente'}</strong></div><p>Inicio</p><p>Mediciones</p>{tenant.modules.planograms && <p>Planogramas</p>}<p>Mi cuenta</p></aside>
      <div className="client-preview-content"><span>ESPACIO DE TRABAJO</span><h3>{tenant.name || 'Cliente'}</h3><p>Tu operación, en un solo lugar.</p><button type="button" disabled>Acción principal</button><small>Los colores de estado de las mediciones se conservan.</small></div>
    </div>
  </section>;
}
