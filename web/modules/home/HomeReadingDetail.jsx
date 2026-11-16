'use client';
import { api } from '../../lib/sb';
import { Modal, Loading, ErrorBox, useApi } from '../sb/ui';
import ReadingView from '../sb/ReadingView';

export default function HomeReadingDetail({ row, user, go, onClose }) {
  const { data, error, loading, reload } = useApi(() => api(`/api/readings/${row.id}`), [row.id]);
  return <Modal title={`Medición #${row.id} · ${row.store_name}`} onClose={onClose} wide>
    <ErrorBox error={error} onRetry={reload} />
    {loading && !data && <Loading text="Cargando medición…" />}
    {data && <ReadingView reading={data} user={user} onDeleted={onClose} onConfirmGo={() => { onClose(); go('revision'); }} />}
  </Modal>;
}
