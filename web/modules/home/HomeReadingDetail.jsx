'use client';
import { useEffect, useState } from 'react';
import { api, download } from '../../lib/sb';
import { can } from '../../lib/profiles.mjs';
import { Modal, Loading, ErrorBox, Pill, useApi } from '../sb/ui';
import ReadingView from '../sb/ReadingView';

export default function HomeReadingDetail({ row, user, go, onClose }) {
  const { data, error, loading, reload } = useApi(() => api(`/api/readings/${row.id}`), [row.id]);
  const [review, setReview] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  useEffect(() => {setReview(data?.review || null);}, [row.id, data?.review]);
  const status = review?.status || data?.review?.status || row.status;
  async function exportReading() {
    setExporting(true);setExportError('');
    try {await download(`/api/readings/${row.id}/report.xlsx`, `Salcobrand_Medicion_${row.id}.xlsx`);}
    catch (exception) {setExportError(exception.message);}
    finally {setExporting(false);}
  }
  return <Modal title={`Medición #${row.id} · ${row.store_name}`} onClose={onClose} wide
    titleExtra={status && <span className="measurement-header-status" aria-label="Estado de la medición"><Pill kind={status === 'Aprobado' ? 'ok' : status === 'Rechazado' ? 'bad' : 'warn'}>{status}</Pill></span>}
    actions={data && can(user, 'read') && <button type="button" className="measurement-header-export" disabled={exporting} onClick={exportReading}>{exporting ? 'Descargando…' : 'Descargar Excel de esta medición'}</button>}>
    <ErrorBox error={error || exportError} onRetry={error ? reload : undefined} />
    {loading && !data && <Loading text="Cargando medición…" />}
    {data && <ReadingView key={row.id} reading={data} user={user} showExport={false} onReviewChanged={setReview} onDeleted={onClose} onConfirmGo={() => { onClose(); go('revision'); }} />}
  </Modal>;
}
