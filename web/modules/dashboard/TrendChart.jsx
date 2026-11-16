import { Card } from '../sb/ui';
import { fmt } from '../../lib/sb';
import DashboardTable from './DashboardTable';

export default function TrendChart({ title, rows, field, color, percent = false }) {
  const width = 600, height = 220, left = 44, top = 20, plotHeight = 156, plotWidth = 538;
  const ceiling = percent ? 100 : Math.max(4, Math.ceil(Math.max(0, ...rows.map(row => row[field] ?? 0)) / 4) * 4);
  const x = index => left + (rows.length > 1 ? index / (rows.length - 1) : 0.5) * plotWidth;
  const y = value => top + plotHeight * (1 - value / ceiling);
  const segments = [];
  let segment = [];
  rows.forEach((row, index) => {
    if (row[field] === null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else segment.push(`${x(index)},${y(row[field])}`);
  });
  if (segment.length) segments.push(segment);
  return <Card title={title}>
    <svg viewBox={`0 0 ${width} ${height}`} className="dashboard-chart" role="img" aria-label={title}>
      {[0, 1, 2, 3, 4].map(tick => <g key={tick}>
        <line x1={left} y1={y(ceiling * tick / 4)} x2={582} y2={y(ceiling * tick / 4)} stroke="var(--nv-border)" />
        <text x={left - 8} y={y(ceiling * tick / 4) + 4} textAnchor="end">{fmt.num(ceiling * tick / 4)}</text>
      </g>)}
      {segments.map((points, index) => <polyline key={index} points={points.join(' ')} fill="none" stroke={color} strokeWidth={2.5} />)}
      {rows.map((row, index) => <g key={row.month}>
        {row[field] !== null && <circle tabIndex={0} cx={x(index)} cy={y(row[field])} r={4} fill={color}
          aria-label={`${row.month} · ${fmt.num(row[field])}`}><title>{row.month} · {fmt.num(row[field])}</title></circle>}
        {(index % Math.max(1, Math.ceil(rows.length / 6)) === 0 || index === rows.length - 1) && <text x={x(index)} y={height - 14} textAnchor="middle">{row.month}</text>}
      </g>)}
    </svg>
    <details><summary>Ver datos del gráfico</summary><DashboardTable rows={rows} columns={[
      ['month', 'Mes'], [field, title, row => row[field] === null ? 'Sin datos' : fmt.num(row[field])],
    ]} /></details>
  </Card>;
}
