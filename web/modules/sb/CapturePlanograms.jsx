'use client';
import {useEffect, useState} from 'react';
import {api} from '../../lib/sb';
import {useApi, Loading, ErrorBox} from './ui';
import PdfPreview from '../catalog/PdfPreview';
import ShelfPhoto from '../management/ShelfPhoto';

export default function CapturePlanograms({store, classification, preferredPlan}) {
  const params = new URLSearchParams({store,category:classification.category});
  for (const sub of classification.subcategories || []) params.append('subcategories', sub);
  const query = params.toString();
  const ready = !!store && !!classification.category && !!classification.subcategories?.length;
  const result = useApi(async () => ({plans:ready ? await api('/api/capture/planograms?'+query) : [],query}),[query,ready]);
  const [selected,setSelected] = useState('');
  const current = result.data?.query === query ? result.data.plans : [];
  useEffect(() => {
    setSelected(current.some(plan => plan.id === preferredPlan) ? preferredPlan : current[0]?.id || '');
  },[result.data,query,preferredPlan]);
  if (!ready) return null;
  if (result.loading && !current.length) return <div className="full"><Loading text="Buscando planograma asociado…"/></div>;
  if (result.error) return <div className="full"><ErrorBox error={result.error} onRetry={result.reload}/></div>;
  if (!current.length) return null;
  return <section className="full capture-planograms" aria-label="Planograma asociado">
    <div className="sb-actions"><h3>{current.length === 1 ? 'Planograma asociado' : 'Planogramas asociados'}</h3></div>
    {current.length > 1 && <div className="sb-actions">{current.map(plan => <button type="button" key={plan.id} aria-pressed={plan.id === selected} onClick={() => setSelected(plan.id)}>Ver {plan.name}</button>)}</div>}
    {current.some(plan => plan.id === selected) && <Reference key={store+':'+selected} store={store} id={selected}/>}
  </section>;
}

function Reference({store,id}) {
  const {data,error,loading,reload} = useApi(() => api('/api/capture/planograms/'+encodeURIComponent(id)+'?'+new URLSearchParams({store})),[store,id]);
  const [page,setPage] = useState(1);
  const [expanded,setExpanded] = useState(true);
  const [url,setUrl] = useState('');
  useEffect(() => {
    if (!data?.document) return;
    const bytes = Uint8Array.from(atob(data.document.split(',')[1]),char=>char.charCodeAt(0));
    const objectUrl = URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  },[data?.document]);
  if (loading) return <Loading text="Cargando referencia…"/>;
  if (error) return <ErrorBox error={error} onRetry={reload}/>;
  return <>
    <div className="sb-actions"><strong>{data.name}</strong><button type="button" aria-expanded={expanded} onClick={() => setExpanded(value=>!value)}>{expanded ? 'Ocultar referencia' : 'Mostrar referencia'}</button></div>
    {expanded && <>
      {data.document ? <>
        <div className="sb-actions"><button type="button" disabled={page<=1} onClick={()=>setPage(page-1)}>Anterior</button><span>Página {page} de {data.document_pages || 1}</span><button type="button" disabled={page>=(data.document_pages || 1)} onClick={()=>setPage(page+1)}>Siguiente</button>{url && <a href={url} download={data.document_name || 'planograma.pdf'}>Descargar PDF</a>}</div>
        <PdfPreview document={data.document} page={page}/>
      </> : data.photo ? <ShelfPhoto photo={data.photo} name={data.name}/> : <p className="sb-hint">El planograma tiene posiciones registradas y aún no cuenta con una imagen o PDF de referencia.</p>}
    </>}
  </>;
}
