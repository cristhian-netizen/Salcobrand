'use client';
import {useState} from 'react';
import {applyBrandClassification} from './catalog.mjs';
import {api, download} from '../../lib/sb';
import {Card, Modal, ErrorBox, Loading, useApi} from '../sb/ui';
import SortableTable from '../tables/SortableTable';

export default function ClassificationTransfer({onSaved, notify}) {
  const [mode,setMode] = useState('');
  return <Card title="Carga y asignación de clasificación" subtitle="Carga el catálogo y asigna categorías y subcategorías a productos existentes por SKU. Las dimensiones, precios y mediciones se conservan.">
    <div className="sb-actions"><button type="button" onClick={()=>setMode('bulk')}>Carga masiva de clasificación</button><button type="button" onClick={()=>setMode('manual')}>Asignar clasificación manualmente</button></div>
    {mode && <Modal wide title={mode==='bulk'?'Carga masiva de clasificación':'Asignar clasificación a producto'} onClose={()=>setMode('')}><Editor bulk={mode==='bulk'} onSaved={()=>{setMode('');notify?.('Clasificación de productos actualizada.');onSaved();}}/></Modal>}
  </Card>;
}

function Editor({bulk,onSaved}) {
  const options = useApi(()=>api('/api/admin/settings/classification'),[]);
  const [selected,setSelected] = useState({sku:'',category:'',subcategory:'',subBrand:''});
  const [file,setFile] = useState(null), [preview,setPreview] = useState(null);
  const [busy,setBusy] = useState(false), [error,setError] = useState('');
  const classification = options.data?.classification;
  async function transfer(chosen, commit=false) {
    if (!chosen) return;
    setBusy(true);setError('');
    try {
      if (!chosen.name.toLowerCase().endsWith('.xlsx') || chosen.size>5*1024*1024) throw Error('Usa un archivo .xlsx de hasta 5 MB.');
      const form=new FormData();form.append('file',chosen);form.append('commit',String(commit));
      if (commit) form.append('version',preview.version);
      const result=await api('/api/admin/settings/classification/import',{method:'POST',form,timeout:120000});
      if (commit) onSaved(); else {setFile(chosen);setPreview(result);}
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }
  async function manual(event) {
    event.preventDefault();setBusy(true);setError('');
    try {await api('/api/admin/settings/classification/assign',{method:'POST',body:{version:options.data.version,assignments:[selected]}});onSaved();}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }
  return <>
    <ErrorBox error={error||options.error} onRetry={options.reload}/>
    {bulk ? <>
      <p>La hoja <b>Catalogo</b> añade marcas, categorías y subcategorías. La hoja <b>Asignaciones</b> actualiza productos existentes por SKU. Puedes completar una o ambas hojas; Referencias muestra las opciones ya creadas. Conserva el SKU como texto.</p>
      <button type="button" disabled={busy} onClick={()=>download('/api/admin/settings/classification/template.xlsx','Clasificacion_Productos.xlsx').catch(e=>setError(e.message))}>Descargar plantilla Excel</button>
      <label className="classification-file">Archivo .xlsx<input type="file" accept=".xlsx" disabled={busy} onChange={event=>{setPreview(null);setFile(null);transfer(event.target.files[0]);}}/></label>
      {busy && <Loading text="Procesando clasificación…"/>}
      {preview && <>
        <p>{preview.catalog_rows} filas de catálogo · {preview.products_updated} asignaciones de productos.</p><ErrorBox error={preview.error}/>
        <div className="sb-table"><SortableTable><thead><tr><th>Hoja</th><th>Fila</th><th>SKU</th><th>Categoría</th><th>Subcategoría</th><th>Resultado</th></tr></thead><tbody>{preview.rows.map(row=><tr key={row.sheet+row.row}><td>{row.sheet}</td><td>{row.row}</td><td>{row.sku||'—'}</td><td>{row.category}</td><td>{row.subcategory}</td><td>{row.error||'Validado'}</td></tr>)}</tbody></SortableTable></div>
        <button type="button" className="action" disabled={busy||preview.has_errors} onClick={()=>transfer(file,true)}>Confirmar carga de clasificación</button>
      </>}
    </> : options.loading ? <Loading/> : classification && <form onSubmit={manual}><fieldset className="settings-fields sb-form" disabled={busy}>
      <label className="full">Producto<select required value={selected.sku} onChange={event=>{const p=options.data.products.find(p=>p.sku===event.target.value);setSelected(p?{sku:p.sku,category:p.category,subcategory:p.subcategory,subBrand:p.subBrand}:{sku:'',category:'',subcategory:'',subBrand:''});}}><option value="">Seleccionar producto</option>{options.data.products.map(p=><option key={p.id} value={p.sku}>{p.name} · {p.sku}</option>)}</select></label>
      <label>Submarca<select required value={selected.subBrand} onChange={e=>setSelected(applyBrandClassification(selected,e.target.value,classification))}><option value="">Seleccionar submarca</option>{[...classification.brands].sort((a,b)=>a.localeCompare(b,'es')).map(name=><option key={name}>{name}</option>)}</select></label>
      <label>Categoría<select required value={selected.category} onChange={e=>setSelected({...selected,category:e.target.value,subcategory:''})}><option value="">Seleccionar categoría</option>{Object.keys(classification.categories).sort((a,b)=>a.localeCompare(b,'es')).map(name=><option key={name}>{name}</option>)}</select></label>
      <label>Subcategoría<select required disabled={!selected.category} value={selected.subcategory} onChange={e=>setSelected({...selected,subcategory:e.target.value})}><option value="">Seleccionar subcategoría</option>{[...(classification.categories[selected.category]||[])].sort((a,b)=>a.localeCompare(b,'es')).map(name=><option key={name}>{name}</option>)}</select></label>
      <button type="submit" className="action" disabled={!selected.sku}>Guardar clasificación del producto</button>
    </fieldset></form>}
  </>;
}
