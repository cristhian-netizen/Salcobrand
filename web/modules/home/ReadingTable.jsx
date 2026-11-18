import SortableTable from '../tables/SortableTable';
import { fmt } from '../../lib/sb';
import { Card, Empty, Pill } from '../sb/ui';

export default function ReadingTable({ title, rows, onOpen, rejection = false }) {
  return <Card title={title} body={false}>
    {rows.length ? <div className="sb-table"><SortableTable>
      <thead><tr>
        <th>{rejection ? 'PDV' : 'Punto de venta'}</th><th>Fecha</th>
        {rejection ? <th>Motivo del rechazo</th> : <><th>Puntaje</th><th>Estado</th></>}
        <th><span className="home-sr-only">Detalle</span></th>
      </tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        <td><b>{row.store_name}</b><small>{row.store_id} · Medición #{row.id}</small></td>
        <td className="home-date" data-sort-value={row.date+'T'+row.time}>{row.date.split('-').reverse().join('-')}<small>{row.time}</small></td>
        {rejection ? <td className="home-note">{row.note || 'Sin observación registrada'}</td> : <>
          <td><Pill kind={row.score_band}>{fmt.num(row.score)}</Pill></td>
          <td><Pill kind={row.status === 'Aprobado' ? 'ok' : row.status === 'Rechazado' ? 'bad' : 'warn'}>{row.status}</Pill></td>
        </>}
        <td><button className="link home-open" type="button" onClick={() => onOpen(row)} aria-label={`Ver medición #${row.id}`}>Ver medición</button></td>
      </tr>)}</tbody>
    </SortableTable></div> : <Empty>No hay mediciones para mostrar.</Empty>}
  </Card>;
}
