'use client';
import {useRef} from 'react';

export default function ShelfPhoto({photo, name}) {
  const viewer = useRef(null);
  if (!photo) return <span className="sb-hint">Sin foto</span>;
  return <>
    <button className="shelf-photo-button" type="button" aria-label={'Ampliar foto de ' + name} onClick={() => viewer.current.showModal()}>
      <img src={photo} alt={name}/><span>Ampliar</span>
    </button>
    <dialog ref={viewer} className="shelf-photo-viewer" aria-label={'Foto de ' + name}
      onKeyDown={event => event.stopPropagation()} onCancel={event => event.stopPropagation()}
      onClick={event => {if (event.target === event.currentTarget) viewer.current.close();}}>
      <div className="sb-card-head"><h2>{name}</h2><button type="button" aria-label="Cerrar foto" onClick={() => viewer.current.close()}>Cerrar</button></div>
      <img src={photo} alt={'Foto ampliada de ' + name}/>
    </dialog>
  </>;
}
