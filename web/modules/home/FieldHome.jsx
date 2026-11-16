import { fmt } from '../../lib/sb';
import { Metric } from '../sb/ui';
import ReadingTable from './ReadingTable';

export default function FieldHome({ data, role, onOpen }) {
  return <>
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
