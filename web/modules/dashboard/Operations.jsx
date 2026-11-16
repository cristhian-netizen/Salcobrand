import { Card, Metric } from '../sb/ui';
import { fmt } from '../../lib/sb';
import DashboardTable from './DashboardTable';

export default function Operations({ data, cutoff }) {
  return <section aria-label="Cobertura y frecuencia" className="dashboard-section">
    <h2>Cobertura y frecuencia</h2>
    <div className="sb-metrics">
      <Metric label="Cobertura de PDV" value={fmt.pct(data.indicator.value)} hint={`${data.measured} de ${data.total} locales activos medidos`} kind={data.indicator.band} />
      <Metric label="PDV sin mediciones" value={fmt.num(data.unmeasured)} hint="En el período seleccionado" />
      <Metric label="Lecturas por PDV" value={data.total ? fmt.num(Math.round(10 * data.count / data.total) / 10) : '—'} hint="Incluye locales sin lecturas" />
      <Metric label="Mediciones aprobadas" value={fmt.num(data.count)} hint="Registros válidos en locales activos" />
    </div>
    <Card title="Frecuencia de mediciones" body={false} subtitle={`Corte ${cutoff}. La última lectura considera el historial aprobado hasta ese día.`}>
      <DashboardTable rows={data.rows} columns={[
        ['name', 'PDV', row => <><b>{row.name}</b>{!row.count && <small>Sin mediciones en el período</small>}</>],
        ['count', 'Lecturas / días', row => `${row.count} / ${row.days}`], ['last', 'Última lectura al corte', row => row.last || 'Nunca medido'],
        ['age', 'Días sin lectura'], ['gap', 'Intervalo promedio', row => row.gap === null ? 'No hay 2 días de lectura' : `${fmt.num(row.gap)} días`],
      ]} />
    </Card>
  </section>;
}
