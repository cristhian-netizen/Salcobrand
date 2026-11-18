import SortableTable from '../tables/SortableTable';
import { Empty } from '../sb/ui';

export default function DashboardTable({ columns, rows, empty = 'No hay datos para los filtros seleccionados.' }) {
  if (!rows.length) return <Empty>{empty}</Empty>;
  return <div className="sb-table"><SortableTable>
    <thead><tr>{columns.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={row.code || row.month || row.id || index}>
      {columns.map(([key, , render]) => <td key={key} data-sort-value={typeof row[key] === 'number' || typeof row[key] === 'string' ? row[key] : undefined}>{render ? render(row) : row[key] ?? '—'}</td>)}
    </tr>)}</tbody>
  </SortableTable></div>;
}
