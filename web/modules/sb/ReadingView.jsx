'use client';
import SortableTable from '../tables/SortableTable';

import Img from '../common/Img';
import {useState} from 'react';
import {api, fmt, download} from '../../lib/sb';
import {can} from '../../lib/profiles.mjs';
import {Card, Metric, StatusPill, Pill, Empty} from './ui';
import MeasurementReview from './MeasurementReview';
import ScoreBreakdown from '../measurement-details/ScoreBreakdown';

const clp = v => typeof v === 'number' ? '$' + Math.round(v).toLocaleString('es-CL') : '—';
const BOX = {ok: '#12b76a', match: '#12b76a', confirmed: '#12b76a', low: '#f79009', unmatched: '#f79009', unreadable: '#f79009', missing: '#f04438', gap: '#f04438', foreign: '#6172f3'};

function Photo({url, index, engineImage, products}) {
  const size = engineImage?.size;
  const statusByItem = new Map(products.filter(p => p.image_index === index && p.item_index != null).map(p => [p.item_index, p.planogram_status || p.match_status]));
  return <figure className="sb-photo">
    <Img src={url} alt={`Foto ${index + 1} de la góndola`} style={size ? {aspectRatio: `${size[0]} / ${size[1]}`} : undefined}/>
    {size && engineImage.items?.length > 0 && <svg viewBox={`0 0 ${size[0]} ${size[1]}`} preserveAspectRatio="none" aria-hidden="true">
      {engineImage.items.map(item => { const [x1, y1, x2, y2] = item.box; const color = BOX[statusByItem.get(item.index) || item.status] || '#98a2b3';
        return <rect key={item.index} x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke={color} strokeWidth={Math.max(3, size[0] / 400)} rx="4"/>; })}
    </svg>}
    <figcaption>Foto {index + 1}{engineImage ? ` · ${engineImage.boxes ?? engineImage.items?.length ?? 0} detecciones` : ''}</figcaption>
  </figure>;
}

export default function ReadingView({reading, user, onDeleted, onConfirmGo, showExport = true, onReviewChanged}) {
  const [review, setReview] = useState(reading.review);
  const [tab, setTab] = useState('productos');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const c = reading.compliance, s = reading.standards || {};
  const reference = reading.planogram_reference;
  const hasPlan = !!reading.planogram_id;
  const missingPositions = reference?.status === 'missing_positions';
  const planHint = c ? `${c.total_filled_facings} de ${c.total_expected_facings} caras esperadas`
    : hasPlan ? `${reference?.name || 'Planograma asociado'} · ${missingPositions ? 'Sin posiciones configuradas' : 'Comparación no disponible'}` : 'Sin planograma asociado';
  const planMessage = hasPlan
    ? missingPositions ? 'El planograma está asociado a esta medición, pero no tiene posiciones de productos ni caras esperadas configuradas. Para calcular cumplimiento y reposición, el Administrador debe completar los productos, niveles, posiciones y caras en el módulo Planogramas.'
      : 'Esta medición tiene un planograma asociado, pero no hay una comparación disponible con su referencia de captura.'
    : 'Esta medición no tiene un planograma asociado. Las referencias para nuevas capturas se asignan desde el módulo Planogramas.';
  const products = reading.products || [];
  const images = reading.engine?.images || [];
  async function remove() {
    if (!window.confirm(`¿Eliminar la lectura #${reading.id}? Las fotos se conservan.`)) return;
    setBusy(true); setError('');
    try { await api(`/api/readings/${reading.id}`, {method: 'DELETE'}); onDeleted?.(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <>
    <div className="sb-metrics reading-summary" aria-label="Métricas de la medición">
      <article className="sb-metric"><span>Puntaje de exhibición</span>
        <div className="sb-score" style={{marginTop: 8}}><div className="ring" style={{'--p': s.overall_score ?? 0, '--c': s.grade_color || 'var(--nv-primary)'}}><span>{s.overall_score ?? '—'}</span></div>
          <div className="reading-score-text"><strong style={{fontSize: 20, margin: 0}}>{s.grade || 'Sin dato'}</strong>
            <dl className="reading-score-components">{[['Stock',s.stock_score],['Espacio',s.space_score],['Precios',s.price_score],['Orden',s.organization_score]].map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value ?? 'Sin evaluar'}</dd></div>)}</dl>
          </div></div>
      </article>
      <Metric label="Cumplimiento de planograma" value={c ? fmt.pct(c.compliance_pct) : '—'} hint={planHint}/>
      <Metric label="Caras detectadas" value={fmt.num(reading.total_facings)} hint={`${reading.shelf_levels_detected ?? '—'} niveles · espacio vacío ${fmt.pct(reading.empty_space_pct)}`}/>
      <Metric label="Detecciones inciertas" value={fmt.num(reading.needs_review)} hint={c ? `Impacto estimado ${clp(c.impact_clp)}` : 'Recortes dudosos del motor'}/>
    </div>
    <ScoreBreakdown reading={reading}/>
    {s.findings?.length > 0 && <Card title="Hallazgos"><ul className="sb-findings">{s.findings.map((f, i) => <li key={i}>{f}</li>)}</ul></Card>}
    <Card className="measurement-photos" title={`Fotos (${reading.image_urls?.length || 0})`} subtitle="Verde: correcto · Naranjo: bajo lo esperado o sin identificar · Rojo: falta · Azul: fuera de planograma.">
      <div className="sb-photos">{(reading.image_urls || []).map((url, i) => <Photo key={url} url={url} index={i} engineImage={images[i]} products={products}/>)}</div>
    </Card>
    <div className="sb-tabs" role="group" aria-label="Detalle">
      {[['productos', `Productos (${products.length})`], ['planograma', 'Planograma'], ['reposicion', 'Reposición']].map(([id, label]) =>
        <button key={id} type="button" aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    {tab === 'productos' && <Card body={false} title="Productos detectados" actions={can(user, 'train') && reading.needs_review > 0 && <button type="button" onClick={onConfirmGo}>Revisar {reading.needs_review} recortes</button>}>
      {products.length ? <div className="sb-table"><SortableTable><thead><tr><th>Producto</th><th>Nivel / pos.</th><th className="sb-num">Caras</th><th>Estado</th><th className="sb-num">Confianza</th></tr></thead><tbody>
        {products.map((p, i) => <tr key={i}><td><b>{p.product}</b><small>{[p.brand, p.category].filter(Boolean).join(' · ')}</small></td>
          <td>{p.shelf_level} / {p.position_index}</td><td className="sb-num">{p.facings}</td>
          <td><StatusPill status={p.planogram_status || p.match_status}/>{p.needs_review && <> <Pill kind="warn">Confianza limitada</Pill></>}</td>
          <td className="sb-num">{typeof p.confidence === 'number' ? Math.round(p.confidence * 100) + ' %' : '—'}</td></tr>)}
      </tbody></SortableTable></div> : <Empty>El motor no detectó productos en esta lectura.</Empty>}
    </Card>}
    {tab === 'planograma' && (c ? <Card body={false} title={c.planogram_name} subtitle={`${c.items?.length || 0} posiciones · ${c.items_missing_price || 0} sin precio`}>
      <div className="sb-table"><SortableTable><thead><tr><th>Posición</th><th>Producto</th><th className="sb-num">Esperadas</th><th className="sb-num">Detectadas</th><th>Estado</th><th className="sb-num">Precio</th></tr></thead><tbody>
        {(c.items || []).map(item => <tr key={item.planogram_item_id}><td>{item.section_label} · banda {item.band} · {item.position_in_section}</td>
          <td><b>{item.title}</b>{item.tag && <small>{item.tag}</small>}</td><td className="sb-num">{item.expected_facings}</td><td className="sb-num">{item.detected_facings}</td>
          <td><StatusPill status={item.status}/></td><td className="sb-num">{clp(item.price_clp)}</td></tr>)}
      </tbody></SortableTable></div>
      {c.foreign_products?.length > 0 && <div className="sb-card-body"><h3>Productos fuera de planograma</h3><p>{c.foreign_products.map(f => f.product).join(' · ')}</p></div>}
    </Card> : <Card className="measurement-planogram-state" title={hasPlan ? `Planograma asociado${reference?.name ? ' · '+reference.name : ''}` : 'Sin planograma asociado'}><p>{planMessage}</p>{missingPositions && <p className="sb-hint">{reference.position_count} posiciones · {reference.expected_facings} caras esperadas en la referencia de captura.</p>}</Card>)}
    {tab === 'reposicion' && <Card body={false} title="Reposición sugerida" subtitle="Posiciones faltantes o bajo lo esperado, prioridad TOP y lanzamientos primero.">
      {c?.replenishment?.length ? <div className="sb-table"><SortableTable><thead><tr><th>Producto</th><th>Posición</th><th className="sb-num">Faltan</th><th className="sb-num">Valor</th><th>Estado</th></tr></thead><tbody>
        {c.replenishment.map(item => <tr key={item.planogram_item_id}><td><b>{item.title}</b>{item.tag && <small>{item.tag}</small>}</td><td>{item.section_label} · {item.position_in_section}</td>
          <td className="sb-num">{item.deficit}</td><td className="sb-num">{clp(item.deficit_value_clp)}</td><td><StatusPill status={item.status}/></td></tr>)}
      </tbody></SortableTable></div> : <Empty>{c ? 'No hay posiciones por reponer en esta lectura.' : planMessage}</Empty>}
    </Card>}
    {reading.infrastructure?.category && <p className="sb-hint">{reading.infrastructure.category} · {reading.infrastructure.subcategories?.join(', ') || reading.infrastructure.subcategory || 'Todas las subcategorías'}{reading.infrastructure.captureMode === 'manual' ? ` · ${reading.linear_meters == null ? 'Ancho no informado' : 'Ancho manual '+reading.linear_meters+' m'}` : ''}</p>}
    {reading.infrastructure?.captureMode === 'manual' && reading.infrastructure.depths?.length > 0 && <p className="sb-hint">{reading.infrastructure.depths.length} niveles · {reading.infrastructure.depths.map((depth,index) => `Nivel ${index+1}: ${depth} cm de profundidad`).join(' · ')}</p>}
    <Card title="Capacidad máxima por dimensiones" subtitle={`Margen adicional de profundidad ${reading.capacity?.dimensionMarginPct ?? '—'} %. La capacidad teórica no confirma existencias ni unidades ocultas.`}>
      {reading.capacity?.products?.length ? <div className="sb-table"><SortableTable><thead><tr><th>Producto</th><th>Nivel / posición</th><th>Profundidad cm</th><th>Espesor cm</th><th>Máximo por cara</th><th>Máximo total</th></tr></thead><tbody>
        {reading.capacity.products.map((item,index) => <tr key={index}><td>{item.product}<small>{item.matchReason}</small></td><td>{item.level} / {item.position}</td><td>{item.depthCm ?? '—'}</td><td>{item.thicknessCm ?? '—'}</td><td>{item.unitsPerFacing ?? '—'}</td><td>{item.maximumUnits ?? '—'}</td></tr>)}
      </tbody></SortableTable></div> : <p className="sb-hint">Esta captura no tiene profundidades por nivel registradas.</p>}
    </Card>
    <div className="reading-actions">
    {error && <div className="sb-error" role="alert">{error}</div>}
    {showExport && can(user, 'read') && <div className="sb-actions"><button type="button" disabled={busy} onClick={async () => {
      setBusy(true); setError('');
      try { await download(`/api/readings/${reading.id}/report.xlsx`, `Neuravision_Medicion_${reading.id}.xlsx`); }
      catch (exception) { setError(exception.message); } finally { setBusy(false); }
    }}>Descargar Excel de esta medición</button></div>}
    <div className="sb-actions" style={{justifyContent: 'space-between'}}>
      <span className="sb-hint">Lectura #{reading.id} · {fmt.dateTime(reading.created_at)}{reading.engine ? ` · motor ${reading.engine.version} (${Math.round((reading.engine.elapsed_ms || 0) / 1000)} s)` : ''}</span>
      {can(user, 'manage') && <button className="remove" type="button" disabled={busy} onClick={remove}>Eliminar lectura</button>}
    </div>
    </div>
    <MeasurementReview key={reading.id} reading={{...reading, review}} user={user} onSaved={updated => {setReview(updated); onReviewChanged?.(updated);}}/>
  </>;
}
