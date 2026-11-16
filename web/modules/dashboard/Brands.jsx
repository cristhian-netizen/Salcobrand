import { Card, Metric } from '../sb/ui';
import { fmt } from '../../lib/sb';
import DashboardTable from './DashboardTable';

const LABELS = { client: 'Marcas del cliente', other: 'Otras marcas', unknown: 'Sin clasificar' };

export default function Brands({ data }) {
  return <Card title="Participación por marca" subtitle={`${data.scans} escaneos aprobados con frentes detectados. Cada escaneo se cuenta como una captura independiente.`}>
    <div className="sb-metrics dashboard-three">{data.groups.map(group => <Metric key={group.classification}
      label={LABELS[group.classification]} value={fmt.pct(group.sharePct)} hint={`${group.facings} frentes detectados`} />)}</div>
    <DashboardTable rows={data.brands} columns={[
      ['brand', 'Marca'], ['classification', 'Clasificación', row => LABELS[row.classification]], ['facings', 'Frentes detectados'],
      ['sharePct', 'Participación', row => fmt.pct(row.sharePct)],
    ]} />
  </Card>;
}
