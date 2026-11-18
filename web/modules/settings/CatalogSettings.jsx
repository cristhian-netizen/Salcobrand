'use client';
import {useRef,useState} from 'react';
import {Card} from '../sb/ui';
import {catalogDraft,categoryValue,brandValue,subcategoryOptions} from './catalog.mjs';

export default function CatalogSettings(props) {
  return <><CategoriesSettings {...props}/><BrandsSettings {...props}/></>;
}

function CategoriesSettings({state,busy,save,onError}) {
  const [rows,setRows]=useState(()=>catalogDraft(state).rows);
  const sequence=useRef(0);
  const change=(id,value)=>setRows(rows=>rows.map(row=>row.id===id?{...row,...value}:row));
  async function submit(event) {
    event.preventDefault();
    try {const saved=await save('categories',categoryValue(rows));if(saved)setRows(catalogDraft(saved).rows);}
    catch(error){onError(error.message);}
  }
  return <Card title="Clasificación de productos" subtitle="Configura y guarda las categorías y subcategorías de los productos.">
    <form onSubmit={submit}><fieldset className="settings-fields" aria-label="Categorías y subcategorías" disabled={busy}>
      {rows.map((row,index)=><div className="settings-classification" key={row.id}>
        <label>Categoría {index+1}<input required maxLength={100} list="settings-categories" value={row.category} onChange={e=>change(row.id,{category:e.target.value})}/></label>
        <label>Subcategoría<input required maxLength={100} value={row.subcategory} onChange={e=>change(row.id,{subcategory:e.target.value})}/></label>
        <button type="button" onClick={()=>setRows(rows=>rows.filter(r=>r.id!==row.id))}>Quitar</button>
      </div>)}
      <datalist id="settings-categories">{[...new Set(rows.map(r=>r.category).filter(Boolean))].map(name=><option key={name} value={name}/>)}</datalist>
      <div className="sb-actions"><button type="button" onClick={()=>setRows(rows=>[...rows,{id:'category-new-'+ ++sequence.current,category:'',subcategory:''}])}>Añadir categoría / subcategoría</button><button type="submit" className="action">Guardar clasificación</button></div>
    </fieldset></form>
  </Card>;
}

function BrandsSettings({state,busy,save,onError}) {
  const [rows,setRows]=useState(()=>catalogDraft(state).brands);
  const sequence=useRef(0);
  const categories=state.catalog.categories;
  const options=subcategoryOptions(categories);
  const change=(id,value)=>setRows(rows=>rows.map(row=>row.id===id?{...row,...value}:row));
  async function submit(event) {
    event.preventDefault();
    try {const saved=await save('brands',brandValue(rows,categories,state.catalog.brands));if(saved)setRows(catalogDraft(saved).brands);}
    catch(error){onError(error.message);}
  }
  return <Card title="Marcas y submarcas" subtitle="Asigna una subcategoría existente a cada nueva marca o submarca; su categoría se completa automáticamente.">
    <form onSubmit={submit}><fieldset className="settings-fields" aria-label="Marcas y submarcas" disabled={busy}>
      {!options.length&&<p className="sb-hint">Crea y guarda primero una categoría y subcategoría.</p>}
      {rows.map((row,index)=><div className="settings-brand" key={row.id}>
        <label>Marca / submarca {index+1}<input required maxLength={100} value={row.name} onChange={e=>change(row.id,{name:e.target.value})}/></label>
        <label>Subcategoría<select required={!state.catalog.brands.includes(row.name.trim())} value={row.subcategory?JSON.stringify([row.category,row.subcategory]):''} onChange={e=>{const selected=options.find(option=>option.key===e.target.value);change(row.id,{category:selected?.category||'',subcategory:selected?.subcategory||''});}}><option value="">Seleccionar subcategoría</option>{options.map(option=><option key={option.key} value={option.key}>{option.subcategory} · {option.category}</option>)}</select></label>
        <label>Categoría<input readOnly value={row.category} placeholder="Se completa al elegir subcategoría"/></label>
        <label className="mg-check"><input type="checkbox" checked={row.own} onChange={e=>change(row.id,{own:e.target.checked})}/>Marca propia</label>
        <button type="button" onClick={()=>setRows(rows=>rows.filter(r=>r.id!==row.id))}>Quitar</button>
      </div>)}
      <div className="sb-actions"><button type="button" disabled={!options.length} onClick={()=>setRows(rows=>[...rows,{id:'brand-new-'+ ++sequence.current,name:'',own:false,category:'',subcategory:''}])}>Añadir marca / submarca</button><button type="submit" className="action">Guardar marcas y submarcas</button></div>
    </fieldset></form>
  </Card>;
}
