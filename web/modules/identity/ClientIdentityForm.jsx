import {useRef} from 'react';
import {FONTS} from './identity.mjs';

export default function ClientIdentityForm({tenant, model, linked, disabled, onTenant, onModel, onError, onProcessing}) {
  const logoInput = useRef(null);
  function typography(area, key, value) {
    const next = {...(tenant.typography[area] || {})};
    if (value === '') delete next[key]; else next[key] = key === 'fontSize' ? Number(value) : value;
    onTenant({...tenant, typography: {...tenant.typography, [area]: next}});
  }
  async function logo(file) {
    if (!file) return;
    onProcessing(true); onError('');
    let bitmap;
    try {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || !file.size || file.size > 5 * 1024 * 1024) throw Error('Usa un logo PNG, JPG o WebP de hasta 5 MB.');
      bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 500 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const value = canvas.toDataURL('image/webp', .85);
      if (value.length > 800000) throw Error('El logo sigue siendo demasiado grande. Usa una imagen más pequeña.');
      onTenant({...tenant, logo: value});
    } catch (error) { onError(error.message || 'No se pudo abrir el logo.'); }
    finally { bitmap?.close(); onProcessing(false); if (logoInput.current) logoInput.current.value = ''; }
  }
  return <fieldset disabled={disabled} className="client-fields">
    <section><h2>Identidad del cliente</h2><div className="client-form-grid">
      <label>Nombre del cliente<input required maxLength={100} value={tenant.name} onChange={e => onTenant({...tenant, name: e.target.value})}/></label>
      <label>Identificador<input required pattern="[a-z][a-z0-9-]{2,49}" maxLength={50} readOnly={linked} value={tenant.id} onChange={e => onTenant({...tenant, id: e.target.value})}/><small>{linked ? 'Identificador del cliente registrado.' : 'Solo para este borrador; no registra un cliente.'}</small></label>
      <label>Color principal<input type="color" value={tenant.primaryColor} onChange={e => onTenant({...tenant, primaryColor: e.target.value})}/></label>
      <label>Color de la barra lateral<input type="color" value={tenant.sidebarColor} onChange={e => onTenant({...tenant, sidebarColor: e.target.value})}/></label>
      <label className="client-full">Logo del cliente<input ref={logoInput} type="file" accept="image/png,image/jpeg,image/webp" onChange={e => logo(e.target.files[0])}/><small>PNG, JPG o WebP · hasta 5 MB. Se optimiza a 500 px.</small></label>
    </div>{tenant.logo && <button type="button" onClick={() => onTenant({...tenant, logo: ''})}>Quitar logo</button>}</section>
    <section><h2>Tipografía</h2><div className="client-form-grid">{[['sidebar', 'Barra lateral'], ['content', 'Contenido']].map(([area, name]) => <div key={area} className="client-font-group"><h3>{name}</h3><label>Fuente de {name.toLowerCase()}<select value={tenant.typography[area]?.fontFamily || ''} onChange={e => typography(area, 'fontFamily', e.target.value)}><option value="">Predeterminada</option>{FONTS.map(font => <option key={font}>{font}</option>)}</select></label><label>Color de texto de {name.toLowerCase()}<input type="color" value={tenant.typography[area]?.color || (area === 'sidebar' ? '#ffffff' : '#101828')} onChange={e => typography(area, 'color', e.target.value)}/></label>{area === 'sidebar' && <label>Tamaño de la barra lateral (px)<input type="number" min="10" max="24" step="1" value={tenant.typography.sidebar?.fontSize ?? ''} placeholder="13,5" onChange={e => typography(area, 'fontSize', e.target.value)}/></label>}<button type="button" onClick={() => onTenant({...tenant, typography: {...tenant.typography, [area]: {}}})}>Restablecer {name.toLowerCase()}</button></div>)}</div></section>
    <section><h2>Módulos</h2><div className="client-checks">{[['vision', 'Indicadores de ejecución y participación'], ['planograms', 'Planogramas'], ['sales', 'Ventas e inventario · requiere integración']].map(([key, label]) => <label key={key}><input type="checkbox" checked={tenant.modules[key]} onChange={e => onTenant({...tenant, modules: {...tenant.modules, [key]: e.target.checked}})}/>{label}</label>)}</div><p className="client-hint">La identidad conserva los permisos de cada perfil. Ventas e inventario se muestra como integración pendiente.</p></section>
    <section><h2>Conexión con el modelo</h2><p className="client-hint">Solo referencias de servidor. La clave de API se configura fuera del navegador.</p><div className="client-form-grid"><label>ID de organización del modelo<input maxLength={100} pattern="[A-Za-z0-9_-]{1,100}" value={model.remoteOrgId} onChange={e => onModel({...model, remoteOrgId: e.target.value})}/><small>Vacío conserva el acceso de servidor configurado actualmente.</small></label><label>Variable de credencial<input required maxLength={100} pattern="INTEGRATION_[A-Z0-9_]{1,88}" value={model.credentialEnv} onChange={e => onModel({...model, credentialEnv: e.target.value})}/><small>Nombre de variable; nunca pegues una clave aquí.</small></label></div></section>
  </fieldset>;
}
