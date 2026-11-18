'use client';
import {useEffect,useState} from 'react';
import {api} from '../../lib/sb';
import {orderRegions} from '../../lib/locations.mjs';
import {useApi,Loading,ErrorBox} from '../sb/ui';
import SortableTable from '../tables/SortableTable';
import {INITIAL_FILTERS,eligibleStore,filteredStores,selectStores} from './assignment-selection.mjs';

export default function PlanogramAssignments({plan,catalog,onSaved,onEdit}) {
  const state=useApi(()=>api('/api/admin/catalog/planograms/'+encodeURIComponent(plan.id)+'/assignments'),[plan.id]);
  const [filters,setFilters]=useState(INITIAL_FILTERS);
  const [selected,setSelected]=useState([]),[preview,setPreview]=useState(null),[replace,setReplace]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{
    if(!state.data)return;
    setSelected([...new Set(state.data.assignments.map(r=>r.store_code))]);setPreview(null);setReplace(false);
  },[state.data]);
  const stores=state.data?.stores||[],types=state.data?.types||[];
  const choices=filteredStores(stores,filters);
  const categories=catalog.classification.categories;
  const names=values=>[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'es',{sensitivity:'base'}));
  const name=code=>stores.find(s=>s.code===code)?.name||code;
  const valid=!!plan.category&&plan.subcategories?.length===1;
  function selection(values){setSelected(values);setPreview(null);setReplace(false);setError('');}
  function change(key,value){setFilters(f=>({...f,[key]:value,...(key==='region'?{commune:''}:{}),...(key==='category'?{subcategory:''}:{})}));}
  async function submit(commit=false){
    setBusy(true);setError('');
    try{
      const result=await api('/api/admin/catalog/planograms/'+encodeURIComponent(plan.id)+'/assignments'+(commit?'':'/preview'),{method:commit?'PUT':'POST',body:{stores:selected,version:state.data.version,replace_conflicts:replace}});
      if(commit)onSaved();else setPreview(result);
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }
  if(state.loading&&!state.data)return <Loading text="Cargando PDV y asignaciones…"/>;
  return <>
    <p><b>{plan.name}</b> · {plan.category||'Sin categoría'} · {plan.subcategories?.join(', ')||'Sin subcategoría'}</p>
    <ErrorBox error={error||state.error} onRetry={state.reload}/>
    {!valid&&<div className="sb-error">El planograma necesita una única subcategoría antes de asignarlo. <button type="button" onClick={onEdit}>Editar clasificación</button></div>}
    <fieldset className="settings-fields" disabled={busy||state.loading||!state.data}>
      <div className="sb-toolbar assignment-filters">
        <label>Región<select value={filters.region} onChange={e=>change('region',e.target.value)}><option value="">Todas las regiones</option>{orderRegions(names(stores.map(s=>s.region)).map(name=>({name}))).map(r=><option key={r.name}>{r.name}</option>)}</select></label>
        <label>Comuna<select value={filters.commune} disabled={!filters.region} onChange={e=>change('commune',e.target.value)}><option value="">Todas las comunas</option>{names(stores.filter(s=>s.region===filters.region).map(s=>s.commune)).map(n=><option key={n}>{n}</option>)}</select></label>
        <label>Tipo de PDV<select value={filters.store_type} onChange={e=>change('store_type',e.target.value)}><option value="">Todos los tipos</option>{names(stores.map(s=>s.store_type)).map(n=><option key={n}>{n}</option>)}</select></label>
        <label>Categoría<select value={filters.category} onChange={e=>change('category',e.target.value)}><option value="">Todas las categorías</option>{names(Object.keys(categories)).map(n=><option key={n}>{n}</option>)}</select></label>
        <label>Subcategoría<select value={filters.subcategory} disabled={!filters.category} onChange={e=>change('subcategory',e.target.value)}><option value="">Todas las subcategorías</option>{names(categories[filters.category]||[]).map(n=><option key={n}>{n}</option>)}</select></label>
        <label>Buscar PDV<input value={filters.search} onChange={e=>change('search',e.target.value)} placeholder="Código o nombre"/></label>
        <button type="button" onClick={()=>setFilters(INITIAL_FILTERS)}>Limpiar filtros</button>
      </div>
      <p className="sb-hint">Categoría y subcategoría filtran las referencias actuales de los PDV. Con «Todas» también se muestran los locales sin referencia.</p>
      <div className="sb-actions assignment-selection"><button type="button" onClick={()=>selection(selectStores(selected,choices))}>Seleccionar todos los filtrados</button><button type="button" onClick={()=>selection(selectStores(selected,stores))}>Seleccionar todos los PDV del país</button><button type="button" onClick={()=>selection([])}>Limpiar selección</button><span>{selected.length} PDV seleccionados · {choices.length} visibles</span></div>
      <div className="sb-table assignment-table"><SortableTable><thead><tr><th>Seleccionar</th><th>PDV</th><th>Región / comuna</th><th>Tipo de PDV</th><th>Referencias actuales</th></tr></thead><tbody>{choices.map(s=><tr key={s.code}><td><input type="checkbox" aria-label={'Seleccionar '+s.code} checked={selected.includes(s.code)} disabled={!selected.includes(s.code)&&!eligibleStore(s)} onChange={e=>selection(e.target.checked?[...selected,s.code]:selected.filter(code=>code!==s.code))}/></td><td><b>{s.name}</b><small>{s.code}{s.deleted?' · Eliminado':s.status!=='Activo'?' · Inactivo':''}</small></td><td>{s.region}<small>{s.commune}</small></td><td>{s.store_type}</td><td>{s.references.length?s.references.map(r=><small key={r.plan_id+r.subcategory+r.type_id}>{r.name} · {r.subcategory} · {r.type_id?types.find(t=>t.id===r.type_id)?.name||'Tipo anterior':'General'}</small>):'Sin referencia'}</td></tr>)}</tbody></SortableTable>{!choices.length&&<p className="sb-empty">No hay PDV con estos filtros.</p>}</div>
      <div className="sb-actions assignment-selection"><button type="button" className="action" disabled={!valid} onClick={()=>submit()}>Revisar asignación</button></div>
      {preview&&<section className="assignment-preview" aria-label="Resumen de asignación">
        <h3>Resumen antes de confirmar</h3><p>{preview.selected} PDV · {preview.added.length} nuevas asignaciones · {preview.removed.length} asignaciones que se quitarán.</p>
        <details open={selected.length<=10}><summary>PDV seleccionados ({selected.length})</summary><ul>{selected.map(code=><li key={code}>{name(code)} · {code}</li>)}</ul></details>
        {!!preview.removed.length&&<details open><summary>Se quitará de estos PDV</summary><ul>{preview.removed.map(code=><li key={code}>{name(code)} · {code}</li>)}</ul></details>}
        {!!preview.conflicts.length&&<><h4>Referencias activas que se reemplazarán</h4><ul>{preview.conflicts.map(r=><li key={r.plan_id+r.store_code+r.type_id}>{name(r.store_code)} · {r.name} · {r.subcategory}</li>)}</ul><label className="mg-check"><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)}/>Confirmo el reemplazo de las referencias indicadas.</label></>}
        <div className="sb-actions"><button type="button" className="action" disabled={!!preview.conflicts.length&&!replace} onClick={()=>submit(true)}>Confirmar asignación</button></div>
      </section>}
    </fieldset>
  </>;
}
