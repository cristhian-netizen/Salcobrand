import { can } from '../../lib/profiles.mjs';
import { fmt } from '../../lib/sb';
import { Card, ComplianceBar, Pill } from '../sb/ui';
import DashboardTable from '../dashboard/DashboardTable';

const clp = value => typeof value === 'number' ? '$' + Math.round(value).toLocaleString('es-CL') : '—';

export default function OperationalAlerts({ data, user, go, onResolve, busy }) {
  return <>
    <Card title="Góndolas con faltantes" subtitle="Góndolas activas según su última medición aprobada de los últimos 30 días. Ordenadas por impacto estimado." body={false}>
      <DashboardTable rows={data.gaps} empty="Ninguna góndola tiene faltantes en su última lectura aprobada del período." columns={[
        ['name', 'Góndola', point => <><b>{point.gondola || point.name}</b><small>{point.store_name || point.store || point.store_id}</small></>],
        ['date', 'Última lectura', point => <span data-sort-value={point.performance.created_at}>{fmt.dateTime(point.performance.created_at)}</span>],
        ['compliance', 'Cumplimiento', point => <ComplianceBar pct={point.performance.compliance_pct} />],
        ['missing', 'Faltan', point => <Pill kind="bad">{point.performance.missing}</Pill>],
        ['low', 'Bajo esperado', point => point.performance.low || 0],
        ['impact', 'Impacto', point => clp(point.performance.impact_clp)],
        ['detail', 'Detalle', point => <button type="button" className="link" onClick={() => go(`gondolas/${encodeURIComponent(point.id)}/lectura/${point.performance.id}`)}>Ver medición</button>],
      ]} />
    </Card>
    <Card title="Quiebres de proveedor abiertos" body={false}>
      <DashboardTable rows={data.suppliers} empty="No hay quiebres de proveedor abiertos para estos filtros." columns={[
        ['product_title', 'Producto', row => <><b>{row.product_title}</b>{row.note && <small>{row.note}</small>}</>],
        ['point_name', 'Góndola', row => row.point_name || row.point_id],
        ['created_at', 'Registrado', row => <>{fmt.dateTime(row.created_at)}<small>{row.created_by}</small></>],
        ['actions', 'Acción', row => can(user, 'resolve')
          ? <button type="button" disabled={busy} onClick={() => onResolve(row.id)}>Resolver</button>
          : <span className="sb-hint">Solo lectura</span>],
      ]} />
    </Card>
  </>;
}
