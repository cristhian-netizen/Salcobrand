'use client';
// Every image in the portal: a correctly-sized shimmer while it loads, fade-in on load, and a visible error
// state that retries on click. Grid images load lazily and decode off the main thread.
import {useEffect, useRef, useState} from 'react';
import {initial, loaded, failed, retried, sourceFor, wrapperClass} from './img-state.mjs';

export default function Img({src, alt = '', className = '', imgClassName = '', style, eager = false, width, height, onLoad}) {
  const [state, setState] = useState(() => initial(src));
  const ref = useRef(null);
  useEffect(() => { setState(current => current.src === (src || '') ? current : initial(src)); }, [src]);
  useEffect(() => {
    const node = ref.current; // already in the browser cache: no shimmer, no fade
    if (node && node.complete && node.naturalWidth > 0) { setState(loaded); onLoad?.(node); }
  }, [state.src, state.attempt]); // eslint-disable-line react-hooks/exhaustive-deps
  if (state.phase === 'empty') return null;
  return <span className={`${wrapperClass(state)}${className ? ' ' + className : ''}`} style={style}>
    <img ref={ref} src={sourceFor(state)} alt={alt} className={imgClassName || undefined} width={width} height={height}
      loading={eager ? undefined : 'lazy'} decoding="async"
      onLoad={event => { setState(loaded); onLoad?.(event.currentTarget); }} onError={() => setState(failed)}/>
    {state.phase === 'error' && <button type="button" className="sb-img-retry"
      onClick={event => { event.stopPropagation(); setState(retried); }}>
      Imagen no disponible<b>Reintentar</b>
    </button>}
  </span>;
}
