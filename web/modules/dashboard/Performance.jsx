import { Card, Metric, Pill } from '../sb/ui';
import { fmt } from '../../lib/sb';
import ReadingTable from '../home/ReadingTable';
import TrendChart from './TrendChart';
import DashboardTable from './DashboardTable';

function Ranking({ title, rows }) {
  return <Card title={title} body={false}><DashboardTable rows={rows} empty="Aún no hay puntajes de mediciones aprobadas." columns={[
    ['name', 'PDV'], ['region', 'Región / comuna', row => [row.region, row.commune].filter(Boolean).join(' / ') || '—'],
    ['manager', 'Encargado de Local', row => row.manager || 'Sin encargado registrado'],
    ['score', 'Puntaje promedio', row => <Pill kind={row.score_band}>{fmt.num(row.score)}</Pill>], ['eligible', 'Mediciones válidas'],
  ]} /></Card>;
}

export default function Performance({ data, exportFile, onOpen, busy }) {
  const ranked = data.locations.filter(row => row.score !== null).sort((a, b) => a.score - b.score || a.name.localeCompare(b.name, 'es'));
  const totals = data.totals;
  return <>
    <p className="sb-hint">Solo las mediciones aprobadas aportan a los indicadores de desempeño. Las mediciones en revisión y rechazadas se contabilizan por separado.</p>
    <div className="sb-metrics">
      <Metric label="Análisis de góndolas" value={fmt.num(totals.measurements)} hint="Incluye todos los estados" />
      <Metric label="Puntaje promedio" value={fmt.num(totals.average_score)} hint="Solo mediciones aprobadas" kind={totals.score_band} />
      <Metric label="En revisión" value={fmt.num(totals.in_review)} hint="Pendientes de decisión" />
      <Metric label="Rechazadas" value={fmt.num(totals.rejected)} hint={totals.measurements ? `${fmt.pct(100 * totals.rejected / totals.measurements)} del total` : 'Sin mediciones'} />
    </div>
    <div className="dashboard-grid">
      <TrendChart title="Análisis de góndolas por mes" rows={data.months} field="count" color="var(--nv-primary)" />
      <TrendChart title="Puntaje promedio por mes" rows={data.months} field="score" color="#168252" percent />
      <TrendChart title="Mediciones rechazadas por mes" rows={data.months} field="rejected" color="#c73737" />
      <TrendChart title="Tasa de rechazo mensual (%)" rows={data.months} field="rejectionRate" color="#a66b00" percent />
      <Ranking title="PDV con menor puntaje" rows={ranked.slice(0, 10)} />
      <Ranking title="PDV con mejor puntaje" rows={[...ranked].reverse().slice(0, 10)} />
    </div>
    <Card title="Rechazos por ubicación" body={false} actions={<button type="button" disabled={busy} onClick={() => exportFile('locations')}>Descargar resumen</button>}>
      <DashboardTable rows={data.locations.filter(row => row.count).sort((a, b) => b.rejected - a.rejected)} columns={[
        ['region', 'Región'], ['commune', 'Comuna'], ['name', 'PDV'], ['manager', 'Encargado de Local'],
        ['count', 'Mediciones'], ['rejected', 'Rechazos'], ['rejectionRate', 'Tasa de rechazo', row => fmt.pct(row.rejectionRate)],
      ]} />
    </Card>
    <Card title="Rechazos por persona que realizó la medición" body={false} actions={<button type="button" disabled={busy} onClick={() => exportFile('rejections')}>Descargar rechazos</button>}>
      <DashboardTable rows={data.authors} columns={[
        ['name', 'Persona'], ['count', 'Mediciones realizadas'], ['rejected', 'Rechazos'], ['rejectionRate', 'Tasa de rechazo', row => fmt.pct(row.rejectionRate)],
      ]} />
    </Card>
    <ReadingTable title="Actividad reciente" rows={data.recent.slice(0, 10)} onOpen={onOpen} />
  </>;
}
