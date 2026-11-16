'use client';
import {useState} from 'react';
import {api,saveBlob} from '../../lib/sb';
import {useApi,Header,Card,Metric,Loading,ErrorBox} from '../sb/ui';
import DashboardTable from '../dashboard/DashboardTable';

const MONTHS = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
const dollars = value => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return '$ ' + Number(value).toLocaleString('es-CL',{minimumFractionDigits:4,maximumFractionDigits:4});
};
const monthLabel = value => {const [year,month] = value.split('-');return `${MONTHS[Number(month)-1]} ${year}`;};
function defaultPeriod() {
  const parts = new Intl.DateTimeFormat('en-CA',{timeZone:'America/Santiago',year:'numeric',month:'2-digit'}).formatToParts(new Date());
  const year = Number(parts.find(item => item.type === 'year').value);
  const month = Number(parts.find(item => item.type === 'month').value);
  const index = year*12+month-1-5;
  return {from:`${Math.floor(index/12)}-${String(index%12+1).padStart(2,'0')}`,to:`${year}-${String(month).padStart(2,'0')}`};
}

export default function AnalysisUsage() {
  const [filters,setFilters] = useState(defaultPeriod);
  const [query,setQuery] = useState(filters);
  const state = useApi(() => api('/api/reports/analysis-usage?' + new URLSearchParams({date_from:query.from+'-01',date_to:query.to+'-01'}),{timeout:120000}),[query.from,query.to]);
  const [error,setError] = useState('');
  const dirty = filters.from !== query.from || filters.to !== query.to;
  const validMonths = [filters.from,filters.to].every(value => /^[0-9]{4}-(0[1-9]|1[0-2])$/.test(value));
  const monthIndex = value => {const [year,month] = value.split('-').map(Number);return year*12+month;};
  const length = validMonths ? monthIndex(filters.to)-monthIndex(filters.from)+1 : 0;
  const invalid = !validMonths || length < 1 || length > 120;
  const data = !state.loading && !state.error && state.data?.date_from === query.from+'-01' && state.data?.date_to === query.to+'-01' ? state.data : null;
  function consult(event) {
    event?.preventDefault();
    if (invalid) {setError('Selecciona un período válido de hasta 120 meses.');return;}
    setError('');
    if (!dirty) state.reload();
    else setQuery({...filters});
  }
  function exportCsv() {
    if (!data || dirty) return;
    const rows = [['Mes','Período','Costo estimado (USD)'],...data.months.map(row => [monthLabel(row.month),row.month,row.cost_usd ?? ''])];
    const content = '\ufeff' + rows.map(row => row.map(value => '"'+String(value).replace(/"/g,'""')+'"').join(';')).join('\r\n')+'\r\n';
    saveBlob(new Blob([content],{type:'text/csv;charset=utf-8'}),'Neuravision_Uso_Analisis.csv');
  }
  return <section>
    <Header eyebrow="Análisis" title="Uso de análisis" subtitle="Costo mensual estimado de análisis de góndolas en la organización."/>
    <form className="sb-toolbar usage-filters" onSubmit={consult}>
      <label>Desde<input aria-label="Desde" type="month" required value={filters.from} max={filters.to || undefined} disabled={state.loading} onChange={event => {setError('');setFilters({...filters,from:event.target.value});}}/></label>
      <label>Hasta<input aria-label="Hasta" type="month" required value={filters.to} min={filters.from || undefined} disabled={state.loading} onChange={event => {setError('');setFilters({...filters,to:event.target.value});}}/></label>
      <div className="sb-actions"><button className="action" type="submit" disabled={state.loading || invalid}>{state.loading ? 'Consultando…' : 'Consultar'}</button><button type="button" disabled={!data || dirty || invalid} onClick={exportCsv}>Descargar CSV</button></div>
    </form>
    {invalid && <p className="sb-error" role="alert">Selecciona un período válido de hasta 120 meses.</p>}
    <ErrorBox error={error || state.error} onRetry={() => consult()}/>
    {state.loading && <Loading text="Consultando datos de uso…"/>}
    {data && <>
      <p className="sb-hint">Período consultado {monthLabel(query.from)} a {monthLabel(query.to)}.</p>
      <div className="sb-metrics usage-metrics">
        <Metric label="Meses consultados" value={data.months.length} hint="En el período seleccionado" icon="dashboards"/>
        <Metric label="Meses con información" value={data.known_months} hint="Con un costo informado por el proveedor" icon="scan"/>
        <Metric label="Total estimado (USD)" value={dollars(data.total_cost_usd)} hint={`${data.known_months} de ${data.months.length} meses con información`} icon="reports"/>
      </div>
      <Card className="usage-costs"><p className="sb-hint">Cifras estimadas a partir de la actividad del proveedor del modelo. Se contabilizan los análisis de góndola.</p>
        <DashboardTable rows={data.months} columns={ [['label','Mes',row => monthLabel(row.month)],['month','Período'],['cost_usd','Costo estimado (USD)',row => dollars(row.cost_usd)]] }/>
      </Card>
    </>}
  </section>;
}
