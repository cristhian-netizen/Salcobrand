import { Card, Metric } from '../sb/ui';
import { fmt } from '../../lib/sb';
import DashboardTable from './DashboardTable';

export default function Vision({ data, months, onOpen }) {
  const cards = [
    ['osa', 'Disponibilidad observada · OSA', `${data.expected} observaciones de productos esperados`],
    ['sos', 'Participación por caras · SOS', `${data.allFaces} caras con cobertura confirmada`],
    ['cp', 'Cumplimiento · CP', `${data.compared} posiciones evaluadas contra referencia`],
    ['oos', 'Ausencias recientes', `Última lectura aprobada por góndola · hasta ${data.freshDays} días`],
  ];
  return <section aria-label="Ejecución y participación" className="dashboard-section">
    <h2>Ejecución y participación</h2>
    <p className="sb-hint">Indicadores calculados con detalles registrados y confirmados por el Analista.</p>
    <div className="sb-metrics">{cards.map(([key, label, hint]) => <Metric key={key} label={label} hint={hint}
      kind={data.indicators[key].band} value={key === 'oos' ? fmt.num(data.indicators[key].value) : fmt.pct(data.indicators[key].value)} />)}</div>
    <Card title="Tendencia mensual de participación y cumplimiento" body={false} subtitle="Porcentajes ponderados por caras o posiciones evaluadas.">
      <DashboardTable rows={months} columns={[
        ['month', 'Mes'], ['sos', 'Participación por caras', row => fmt.pct(row.sos)],
        ['cp', 'Cumplimiento', row => fmt.pct(row.cp)], ['faces', 'Caras registradas', row => fmt.num(row.faces)],
      ]} />
    </Card>
    <Card title="Ausencias en la última lectura reciente" body={false}>
      <DashboardTable rows={data.missing} columns={[
        ['shelf', 'PDV / góndola', row => <>{row.measurement.store_name}<small>{row.shelf}</small></>],
        ['product', 'Producto'], ['date', 'Fecha', row => row.measurement.date],
        ['measurement', 'Evidencia', row => <button type="button" className="link" onClick={() => onOpen(row.measurement)}>Medición #{row.measurement.id}</button>],
      ]} empty="No hay ausencias confirmadas en lecturas recientes con ubicación física identificada." />
    </Card>
  </section>;
}
