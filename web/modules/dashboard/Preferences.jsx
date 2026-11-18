import { useState } from 'react';
import { Modal } from '../sb/ui';

export const DEFAULT_PANELS = { operation: true, vision: true, business: true };
const LABELS = { operation: 'Cobertura, frecuencia y ranking', vision: 'Participación por marca', business: 'Indicadores pendientes de conexión' };

export function loadPreferences(key) {
  try {
    const stored = JSON.parse(localStorage.getItem(key));
    return Object.fromEntries(Object.entries(DEFAULT_PANELS).map(([panel, value]) => [panel, typeof stored?.[panel] === 'boolean' ? stored[panel] : value]));
  } catch { return DEFAULT_PANELS; }
}

export default function Preferences({ value, onSave, onClose }) {
  const [draft, setDraft] = useState(value);
  return <Modal title="Personalizar indicadores" onClose={onClose}>
    <form onSubmit={event => { event.preventDefault(); onSave(draft); }}>
      <div className="manual-confirmations">{Object.entries(LABELS).map(([key, label]) => <label key={key}>
        <input type="checkbox" checked={draft[key]} onChange={event => setDraft({ ...draft, [key]: event.target.checked })} /><span>{label}</span>
      </label>)}</div>
      <div className="sb-actions"><button className="action" type="submit">Guardar preferencias</button><button type="button" onClick={onClose}>Cancelar</button></div>
    </form>
  </Modal>;
}
