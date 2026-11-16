import { can } from '../../lib/profiles.mjs';
import { Card, Pill } from '../sb/ui';
import DashboardTable from '../dashboard/DashboardTable';

export default function Findings({ rows, user, busy, onToggle, onOpen }) {
  return <Card title="Hallazgos para revisar" body={false} className="alerts-findings">
    <DashboardTable rows={rows} empty="No hay hallazgos para estos filtros." columns={[
      ['title', 'Hallazgo'],
      ['reading', 'Local / lectura', row => <><b>{row.reading.store_name}</b><small>{row.reading.store_id} · Medición #{row.reading.id}</small></>],
      ['date', 'Fecha', row => <>{row.reading.date}<small>{row.reading.time}</small></>],
      ['priority', 'Prioridad', row => <Pill kind={row.priority === 'Alta' ? 'bad' : 'warn'}>{row.priority}</Pill>],
      ['owner', 'Responsable'],
      ['status', 'Estado', row => <Pill kind={row.status === 'Resuelta' ? 'ok' : 'warn'}>{row.status}</Pill>],
      ['actions', 'Acción', row => <div className="sb-actions alerts-actions">
        <button type="button" className="link" onClick={() => onOpen(row.reading)} aria-label={`Ver medición #${row.reading.id}`}>Ver medición</button>
        {can(user, 'resolve') ? <button type="button" disabled={busy} onClick={() => onToggle(row)}>
          {row.status === 'Resuelta' ? 'Reabrir' : 'Marcar resuelta'}
        </button> : <span className="sb-hint">Solo lectura</span>}
      </div>],
    ]} />
  </Card>;
}
