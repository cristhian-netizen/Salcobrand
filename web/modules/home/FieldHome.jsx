import { fmt } from '../../lib/sb';
import { Metric, Card, StatusPill } from '../sb/ui';
import ReadingTable from './ReadingTable';

export default function FieldHome({ data, role, onOpen }) {
  return <>
    {role === 'replenisher' && <Card title="Notificaciones de revisión">
      <div aria-live="polite" aria-relevant="additions text">
        {data.notifications?.length ? data.notifications.map(row => <article className="home-review-notification" key={row.id}>
          <div><strong>Medición #{row.id} · {row.store_name}</strong> <StatusPill status={row.status}/></div>
          <p>{row.reviewed_by} {row.status === 'Aprobado' ? 'aprobó' : 'rechazó'} tu medición · {fmt.dateTime(row.reviewed_at)}</p>
          {row.note && <p>{row.note}</p>}
          <button type="button" onClick={() => onOpen(row)}>Ver resultado</button>
        </article>) : <p className="sb-hint">Aquí aparecerán las aprobaciones y rechazos de tus mediciones.</p>}
      </div>
    </Card>}
    <div className="sb-metrics home-metrics">
      <Metric label="Mis mediciones" value={fmt.num(data.totals.own)} hint="Realizadas con tu cuenta" icon="scan" />
      <Metric label="Mis mediciones rechazadas" value={fmt.num(data.totals.rejected)} hint="Revisa la observación del analista" icon="alerts" />
      <Metric label={role === 'analyst' ? 'Pendientes de revisión' : 'Mis mediciones en revisión'} value={fmt.num(data.totals.pending)} hint="Estado En revisión" icon="review" />
    </div>
    {role === 'analyst' && <ReadingTable title="Pendientes de revisión en tus PDV" rows={data.pending} onOpen={onOpen} />}
    <ReadingTable title="Mis mediciones rechazadas" rows={data.rejected} onOpen={onOpen} rejection />
    <ReadingTable title="Mis mediciones recientes" rows={data.recent} onOpen={onOpen} />
  </>;
}
