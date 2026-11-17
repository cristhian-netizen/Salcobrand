'use client';
import {useId} from 'react';

const sorted = values => [...values].sort((a,b) => a.localeCompare(b,'es'));
export default function CategorySelection({categories = {}, value, onChange, disabled = false, required = false}) {
  const id = useId();
  const options = sorted(categories[value.category] || []);
  const selected = value.subcategories || [];
  function toggle(subcategory) {
    onChange({...value, subcategories: selected.includes(subcategory) ? selected.filter(item => item !== subcategory) : [...selected, subcategory]});
  }
  return <>
    <label>Categoría<select value={value.category} disabled={disabled || !Object.keys(categories).length} required={required && !!Object.keys(categories).length} onChange={event => onChange({category:event.target.value, subcategories:[]})}>
      <option value="">{Object.keys(categories).length ? 'Selecciona una categoría' : 'Sin categorías configuradas'}</option>
      {sorted(Object.keys(categories)).map(category => <option key={category}>{category}</option>)}
    </select></label>
    <fieldset className="full ct-subcategories" disabled={disabled || !value.category} aria-describedby={id}>
      <legend>Subcategorías de producto</legend>
      <p id={id} className="sb-hint">{!value.category ? 'Selecciona primero una categoría.' : options.length ? 'Marca una o varias subcategorías presentes en la góndola.' : 'Esta categoría no tiene subcategorías configuradas.'}</p>
      {!!options.length && <>
        <div className="sb-actions ct-subcategory-actions">
          <button type="button" disabled={disabled || selected.length === options.length} onClick={() => onChange({...value,subcategories:options})}>Seleccionar todas</button>
          <button type="button" disabled={disabled || !selected.length} onClick={() => onChange({...value,subcategories:[]})}>Limpiar selección</button>
          <span className="sb-hint" role="status">{selected.length} seleccionada{selected.length === 1 ? '' : 's'}</span>
        </div>
        <div className="ct-subcategory-options">{options.map(option => <label key={option}><input type="checkbox" checked={selected.includes(option)} onChange={() => toggle(option)}/><span>{option}</span></label>)}</div>
      </>}
    </fieldset>
  </>;
}
