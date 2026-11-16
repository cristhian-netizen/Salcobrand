'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import Icon from '../navigation/icons';

export function useApi(loader, deps = []) {
  const [state, setState] = useState({data: null, error: '', loading: true});
  const seq = useRef(0);
  const run = useCallback(async () => {
    const id = ++seq.current;
    setState(s => ({...s, loading: true, error: ''}));
    try {
      const data = await loader();
      if (id === seq.current) setState({data, error: '', loading: false});
    } catch (e) {
      if (id === seq.current) setState(s => ({...s, error: e.message || 'Error', loading: false}));
    }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, [run]);
  return {...state, reload: run, setData: data => setState(s => ({...s, data}))};
}

export const Header = ({eyebrow, title, subtitle, children}) => <div className="sb-head">
  <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
  {children && <div className="sb-actions">{children}</div>}
</div>;

export const Card = ({title, subtitle, actions, children, body = true, className = ''}) => <section className={'sb-card nv-plain ' + className}>
  {(title || actions) && <div className="sb-card-head"><div>{title && <h2>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div>{actions && <div className="sb-actions">{actions}</div>}</div>}
  {body ? <div className="sb-card-body">{children}</div> : children}
</section>;

export const Metric = ({label, value, hint, icon, kind}) => <article className="sb-metric" data-kind={kind}>
  <span>{label}</span><strong>{value}</strong>{hint && <small>{hint}</small>}
  {icon && <i className="chip" aria-hidden="true"><Icon name={icon} size={17}/></i>}
</article>;

export const Loading = ({text = 'Cargando…'}) => <div className="sb-loading" role="status"><span className="nv-spinner" style={{width: 18, height: 18, borderWidth: 2}} aria-hidden="true"/>{text}</div>;
export const Empty = ({children}) => <div className="sb-empty">{children}</div>;
export const ErrorBox = ({error, onRetry}) => error ? <div className="sb-error" role="alert">{error} {onRetry && <button className="link" type="button" onClick={onRetry}>Reintentar</button>}</div> : null;

export function Pill({kind = '', children}) { return <span className={'sb-pill ' + kind}>{children}</span>; }

export function complianceKind(pct) {
  if (typeof pct !== 'number') return '';
  return pct >= 85 ? 'ok' : pct >= 60 ? 'warn' : 'bad';
}

export function ComplianceBar({pct}) {
  if (typeof pct !== 'number') return <span className="sb-hint">Sin planograma</span>;
  const kind = complianceKind(pct);
  return <div className="sb-bar"><i><b className={kind === 'ok' ? '' : kind} style={{width: `${Math.max(2, Math.min(100, pct))}%`}}/></i><span>{pct.toLocaleString('es-CL', {maximumFractionDigits: 1})} %</span></div>;
}

const STATUS = {
  ok: ['ok', 'En planograma'], low: ['warn', 'Bajo lo esperado'], missing: ['bad', 'Falta'], foreign: ['info', 'Fuera de planograma'],
  match: ['ok', 'Identificado'], confirmed: ['ok', 'Confirmado'], unmatched: ['warn', 'Sin identificar'], unreadable: ['warn', 'Ilegible'], gap: ['bad', 'Espacio vacío'],
  quiebre: ['bad', 'Quiebre'], baja: ['warn', 'A la baja'], bajo: ['warn', 'Bajo esperado'], sube: ['ok', 'Sube'], estable: ['', 'Estable'], none: ['', 'Sin datos'],
};
export function StatusPill({status, label}) {
  const [kind, text] = STATUS[status] || ['', status || '—'];
  return <Pill kind={kind}>{label || text}</Pill>;
}

export function Modal({title, onClose, children, wide = false}) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return <div className="sb-modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className={'sb-modal' + (wide ? ' sb-modal-wide' : '')} role="dialog" aria-modal="true" aria-label={title}>
      <div className="sb-card-head"><h2>{title}</h2><button className="nv-icon-button" type="button" onClick={onClose} aria-label="Cerrar"><Icon name="close"/></button></div>
      <div className="sb-card-body">{children}</div>
    </div>
  </div>;
}

export const Back = ({onClick, children = 'Volver'}) => <button className="sb-back link" type="button" onClick={onClick}>← {children}</button>;

export function storeLabel(p) { return p?.store_name || p?.store || p?.store_id || 'Sin local'; }
