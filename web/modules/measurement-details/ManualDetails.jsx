'use client';
import { useEffect, useState } from 'react';
import { api, fmt } from '../../lib/sb';
import { can } from '../../lib/profiles.mjs';
import { useApi, Card, Metric, Loading, ErrorBox, Empty } from '../sb/ui';
import DetailsForm from './DetailsForm';

export default function ManualDetails({ reading, user, reviewVersion, onReviewChanged }) {
  const { data, loading, error, reload, setData } = useApi(() => api(`/api/readings/${reading.id}/product-details`), [reading.id, reviewVersion]);
  const [options, setOptions] = useState(null);
  const [editing, setEditing] = useState(false);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => {
    if (data?.review && data.review.version > reviewVersion) onReviewChanged(data.review);
  }, [data, reviewVersion, onReviewChanged]);
  async function edit() {
    setOpening(true);
    setOpenError('');
    setMessage('');
    try {
      setOptions(await api(`/api/readings/${reading.id}/product-detail-options`));
      setEditing(true);
    } catch (exception) {
      setOpenError(exception.message);
    } finally {
      setOpening(false);
    }
  }
  function saved(result) {
    setData(result);
    setEditing(false);
    setMessage('Detalle manual guardado. Revisa la medición para aprobar sus indicadores.');
    onReviewChanged(result.review);
  }
  return <Card title="Detalle por producto" actions={can(user, 'review') && !editing &&
    <button type="button" disabled={opening || !data || loading} onClick={edit}>{opening ? 'Cargando…' : 'Registrar / editar detalle'}</button>}>
    <ErrorBox error={error || openError} onRetry={reload} />
    {message && data?.reviewStatus === 'En revisión' && <p role="status">{message}</p>}
    {loading && !data && <Loading text="Cargando detalle manual…" />}
    {data && <>
      {editing ? <DetailsForm readingId={reading.id} initial={data} options={options} onSaved={saved}
        onCancel={() => setEditing(false)} onReload={() => { setEditing(false); reload(); }} /> : <>
        <p>{data.shelfLabel || 'Registro histórico sin ubicación física identificada.'}</p>
        {data.details.length ? <div className="sb-table"><table>
          <thead><tr><th>Producto / SKU</th><th>Posición</th><th>Participación</th><th>Esperado</th><th>Caras</th><th>Presente</th><th>Planograma</th><th>Precio observado</th><th>Confianza %</th><th>Origen</th></tr></thead>
          <tbody>{data.details.map((row, index) => <tr key={index}>
            <td><b>{row.name}</b><small>{row.sku}</small></td><td>{row.position}</td><td>{row.ownership}</td>
            <td>{answer(row.expected)}</td><td>{row.faces ?? '—'}</td><td>{answer(row.present)}</td><td>{row.match}</td>
            <td>{row.observedPrice ?? '—'}</td><td>{row.confidence ?? '—'}</td><td>Manual</td>
          </tr>)}</tbody>
        </table></div> : <Empty>Aún no hay detalle manual registrado.</Empty>}
        <div className="manual-confirmations-summary">
          <span>Cobertura completa · {answer(data.scopeConfirmed)}</span>
          <span>Surtido esperado · {answer(data.expectedConfirmed)}</span>
          <span>Comparación con planograma · {answer(data.comparisonConfirmed)}</span>
        </div>
        {!data.metrics.eligible && <p>Los indicadores estarán disponibles cuando la medición esté aprobada. Estado actual · {data.reviewStatus}.</p>}
        <div className="sb-metrics manual-metrics">
          {[
            ['osa', 'Disponibilidad observada · OSA', `${data.metrics.expected} productos esperados evaluados`],
            ['sos', 'Participación por caras · SOS', `${data.metrics.allFaces} caras con cobertura confirmada`],
            ['cp', 'Cumplimiento · CP', `${data.metrics.compared} posiciones evaluadas contra referencia`],
          ].map(([key, label, hint]) => <Metric key={key} label={label} value={fmt.pct(data.metrics.indicators[key].value)} hint={hint} kind={data.metrics.indicators[key].band} />)}
        </div>
        {data.updatedAt && <p className="sb-hint">Actualizado por {data.updatedBy} · {fmt.dateTime(data.updatedAt)}</p>}
      </>}
    </>}
  </Card>;
}

function answer(value) {
  return value === null ? 'Sin evaluar' : value ? 'Sí' : 'No';
}
