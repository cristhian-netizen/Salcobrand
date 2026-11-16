import { profileOf } from '../../lib/profiles.mjs';
import { Card } from '../sb/ui';
import DashboardTable from '../dashboard/DashboardTable';

function RejectedTable({ title, rows, onOpen }) {
  return <Card title={title} body={false} className="alerts-rejections"><DashboardTable rows={rows} empty="No hay mediciones rechazadas para estos filtros." columns={[
    ['id', 'Medición', row => <><b>#{row.id}</b><small>{row.date} · {row.time}</small></>],
    ['store_name', 'PDV'], ['captured_by', 'Medición hecha por'], ['note', 'Motivo del rechazo'],
    ['reviewed_by', 'Revisado por'],
    ['detail', 'Detalle', row => <button type="button" className="link" onClick={() => onOpen(row)}>Ver medición</button>],
  ]} /></Card>;
}

export default function Rejections({ data, user, onOpen }) {
  const role = profileOf(user);
  if (role === 'admin' || role === 'viewer') return <RejectedTable title="Mediciones rechazadas" rows={data.rejected} onOpen={onOpen} />;
  return <>
    <RejectedTable title="Mis mediciones rechazadas" rows={data.own_rejected} onOpen={onOpen} />
    {role === 'analyst' && <RejectedTable title="Otras mediciones rechazadas en los PDV accesibles" rows={data.other_rejected} onOpen={onOpen} />}
  </>;
}
