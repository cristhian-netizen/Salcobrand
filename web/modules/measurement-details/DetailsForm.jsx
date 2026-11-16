'use client';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/sb';
import { ErrorBox } from '../sb/ui';
import ObservationFields from './ObservationFields';

const FLAGS = [
  ['scopeConfirmed', 'Registré todas las caras observadas, incluidas las de competencia.'],
  ['expectedConfirmed', 'Verifiqué el surtido esperado completo de la ubicación evaluada.'],
  ['comparisonConfirmed', 'Evalué todas las posiciones aplicables del planograma seleccionado.'],
];
const blank = () => ({ productId: '', position: '', ownership: 'Sin clasificar', expected: null,
  present: null, faces: null, match: 'N/A', observedPrice: null, confidence: null });
const FIELDS = Object.keys(blank());

export default function DetailsForm({ readingId, initial, options, onSaved, onCancel, onReload }) {
  const [draft, setDraft] = useState(() => ({ ...initial, details: initial.details.map(row => ({ ...row })) }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const feedback = useRef(null);
  useEffect(() => {
    if (error) {
      feedback.current?.focus();
      feedback.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [error]);
  function change(index, field, value) {
    setDraft(previous => ({ ...previous, details: previous.details.map((row, rowIndex) =>
      rowIndex === index ? { ...row, [field]: value } : row) }));
  }
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const payload = {
      version: draft.version, reviewVersion: draft.reviewVersion, shelfInstanceId: draft.shelfInstanceId,
      details: draft.details.map(row => Object.fromEntries(FIELDS.map(field => [field, row[field]]))),
      ...Object.fromEntries(FLAGS.map(([field]) => [field, draft[field]])),
    };
    try {
      const result = await api(`/api/readings/${readingId}/product-details`, { method: 'PATCH', body: payload });
      onSaved(result);
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }
  return <form onSubmit={save} className="manual-details-form">
    <p>Registra el detalle observado y confirma cada alcance cuando la evidencia lo permita. Guardar requiere una nueva revisión de la medición.</p>
    <div ref={feedback} tabIndex={-1}><ErrorBox error={error} /></div>
    <fieldset disabled={busy} className="manual-editor-fields">
      <label className="manual-instance">Góndola física<select required value={draft.shelfInstanceId || ''} onChange={event => setDraft({ ...draft, shelfInstanceId: event.target.value })}>
        <option value="">Seleccionar góndola</option>
        {options.instances.map(instance => <option key={instance.id} value={instance.id}>
          {instance.label || `${instance.type_name} · ${instance.number}`}{instance.active ? '' : ' (archivada)'}
        </option>)}
      </select></label>
      {!options.instances.length && <p role="status">Solicita al Administrador que vincule una góndola física desde Puntos de venta (PDV).</p>}
      {draft.details.map((row, index) => <ObservationFields key={index} row={row} index={index} products={options.products}
        hasPlanogram={initial.hasPlanogram} change={(field, value) => change(index, field, value)}
        remove={() => setDraft(previous => ({ ...previous, details: previous.details.filter((_, rowIndex) => rowIndex !== index) }))} />)}
      <button type="button" disabled={draft.details.length >= 500} onClick={() => setDraft(previous => ({ ...previous, details: [...previous.details, blank()] }))}>Añadir producto / posición</button>
      <div className="manual-confirmations">
        {FLAGS.map(([field, label]) => <label key={field}><input type="checkbox" checked={draft[field]}
          disabled={field === 'comparisonConfirmed' && !initial.hasPlanogram}
          onChange={event => setDraft({ ...draft, [field]: event.target.checked })} /><span>{label}</span></label>)}
      </div>
      <div className="sb-actions">
        <button type="submit" className="action" disabled={!options.instances.length}>{busy ? 'Guardando…' : 'Guardar detalle'}</button>
        <button type="button" onClick={onCancel}>Cancelar</button>
        {error && <button type="button" onClick={onReload}>Recargar valores guardados</button>}
      </div>
    </fieldset>
  </form>;
}
