import { fmt } from '../../lib/sb';
import { Card, Empty, Pill } from '../sb/ui';
import ReadingTable from './ReadingTable';

export default function ViewerHome({ data, go, onOpen }) {
  return <>
    <nav className="home-shortcuts" aria-label="Accesos de seguimiento">
      {[['mediciones', 'Mediciones'], ['alertas', 'Alertas'], ['reportes', 'Reportes y exportaciones']].map(([route, label]) =>
        <button key={route} type="button" onClick={() => go(route)}>{label}</button>)}
    </nav>
    <Card title="PDV que requieren atención" body={false}>
      {data.attention.length ? <div className="sb-table"><table>
        <thead><tr><th>Punto de venta</th><th>Región / comuna</th><th>Encargado de Local</th><th>Puntaje promedio</th></tr></thead>
        <tbody>{data.attention.map(store => <tr key={store.code}>
          <td><b>{store.name}</b><small>{store.code}</small></td>
          <td>{[store.region, store.commune].filter(Boolean).join(' / ') || 'Sin ubicación registrada'}</td>
          <td>{store.manager || 'Sin encargado registrado'}</td>
          <td><Pill kind={store.score_band}>{fmt.num(store.score)}</Pill></td>
        </tr>)}</tbody>
      </table></div> : <Empty>Aún no hay mediciones aprobadas para calcular el puntaje de los PDV.</Empty>}
    </Card>
    <ReadingTable title="Mediciones rechazadas para seguimiento" rows={data.rejected} onOpen={onOpen} />
  </>;
}
