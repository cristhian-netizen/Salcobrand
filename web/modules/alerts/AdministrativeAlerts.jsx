'use client';
import {useState} from 'react';
import {api, fmt} from '../../lib/sb';
import {useApi, Header, Card, Metric, Loading, Empty, ErrorBox} from '../sb/ui';
import SortableTable from '../tables/SortableTable';

export default function AdministrativeAlerts({go}) {
  const [store, setStore] = useState('');
  const {data, loading, error, reload} = useApi(()=>api('/api/alerts?'+new URLSearchParams({store})),[store]);
  return <section>
    <Header eyebrow="General" title="Alertas" subtitle="Asignación de responsables, revisiones pendientes y continuidad de las mediciones."><button type="button" disabled={loading} onClick={reload}>Actualizar</button><button type="button" onClick={()=>go('configuracion/alertas')}>Configurar plazos</button></Header>
    <div className="sb-toolbar"><label>Punto de venta<select value={store} onChange={e=>setStore(e.target.value)}><option value="">Todos los PDV activos</option>{data?.stores?.map(s=><option key={s.code} value={s.code}>{s.name} · {s.code}</option>)}</select></label></div>
    <ErrorBox error={error} onRetry={reload}/>
    {loading ? <Loading text="Consultando alertas administrativas…"/> : data && <>
      <div className="sb-metrics dashboard-three"><Metric label="PDV sin responsables completos" value={data.unassigned_stores.length}/><Metric label="Mediciones con revisión atrasada" value={data.overdue_reviews.length} hint={'Más de '+data.parameters.reviewDays+' días'}/><Metric label="PDV sin mediciones recientes" value={data.inactive_stores.length} hint={'Más de '+data.parameters.noMeasurementDays+' días'}/></div>
      <Card title="PDV pendientes de asignación" subtitle="Un PDV necesita al menos un Analista y un Reponedor vigentes." body={false}>
        {!data.unassigned_stores.length ? <Empty>Todos los PDV activos tienen ambos perfiles asignados.</Empty> : <div className="sb-table"><SortableTable><thead><tr><th>PDV</th><th>Región / comuna</th><th>Perfil pendiente</th><th>Analistas</th><th>Reponedores</th><th>Acciones</th></tr></thead><tbody>{data.unassigned_stores.map(s=><tr key={s.store_id}><td>{s.store_name}<small>{s.store_id}</small></td><td>{s.region}<small>{s.commune}</small></td><td>{s.missing.join(' y ')}</td><td>{s.analysts.join(', ')||'Sin asignar'}</td><td>{s.replenishers.join(', ')||'Sin asignar'}</td><td><button type="button" onClick={()=>go('usuarios')}>Asignar responsables</button></td></tr>)}</tbody></SortableTable></div>}
      </Card>
      <Card title="Mediciones pendientes de revisión" subtitle={'Mediciones en revisión desde hace más de '+data.parameters.reviewDays+' días.'} body={false}>
        {!data.overdue_reviews.length ? <Empty>No hay revisiones fuera de plazo.</Empty> : <div className="sb-table"><SortableTable><thead><tr><th>Medición</th><th>PDV</th><th>Fecha</th><th>Días pendientes</th><th>Medición hecha por</th><th>Acciones</th></tr></thead><tbody>{data.overdue_reviews.map(r=><tr key={r.id}><td>#{r.id}</td><td>{r.store_name}<small>{r.store_id}</small></td><td data-sort-value={r.created_at}>{fmt.dateTime(r.created_at)}</td><td>{r.days_elapsed}</td><td>{r.captured_by}</td><td><button type="button" onClick={()=>go('mediciones')}>Ver mediciones</button></td></tr>)}</tbody></SortableTable></div>}
      </Card>
      <Card title="PDV sin mediciones recientes" subtitle={'PDV activos cuya última medición supera '+data.parameters.noMeasurementDays+' días; si nunca midieron, se cuenta desde su creación.'} body={false}>
        {!data.inactive_stores.length ? <Empty>Todos los PDV activos están dentro del plazo.</Empty> : <div className="sb-table"><SortableTable><thead><tr><th>PDV</th><th>Región / comuna</th><th>Última medición</th><th>Días sin medición</th></tr></thead><tbody>{data.inactive_stores.map(s=><tr key={s.store_id}><td>{s.store_name}<small>{s.store_id}</small></td><td>{s.region}<small>{s.commune}</small></td><td data-sort-value={s.last_measurement||''}>{s.last_measurement ? fmt.dateTime(s.last_measurement) : 'Sin mediciones'}</td><td>{s.days_elapsed}</td></tr>)}</tbody></SortableTable></div>}
      </Card>
    </>}
  </section>;
}
