const booleanValue = value => value === null ? '' : String(value);
const booleanOf = value => value === '' ? null : value === 'true';

export default function ObservationFields({ row, index, products, hasPlanogram, change, remove }) {
  const choices = products.some(product => product.id === row.productId) || !row.productId
    ? products : [...products, { id: row.productId, name: row.name, sku: row.sku }];
  function number(field, value) {
    change(field, value === '' ? null : Number(value));
  }
  return <fieldset className="manual-observation">
    <legend>Producto / posición {index + 1}</legend>
    <div className="sb-form">
      <label>Producto<select required value={row.productId} onChange={event => change('productId', event.target.value)}>
        <option value="">Seleccionar producto</option>
        {choices.map(product => <option value={product.id} key={product.id}>{product.name} · {product.sku}</option>)}
      </select></label>
      <label>Posición / nivel<input required maxLength={80} value={row.position} onChange={event => change('position', event.target.value)} /></label>
      <label>Participación<select value={row.ownership} onChange={event => change('ownership', event.target.value)}>
        {['Sin clasificar', 'Propio', 'Competencia'].map(value => <option key={value}>{value}</option>)}
      </select></label>
      {[['expected', '¿Se esperaba aquí?'], ['present', '¿Está presente?']].map(([field, label]) => <label key={field}>{label}
        <select value={booleanValue(row[field])} onChange={event => change(field, booleanOf(event.target.value))}>
          <option value="">Sin evaluar</option><option value="true">Sí</option><option value="false">No</option>
        </select>
      </label>)}
      <label>Caras visibles<input type="number" min={0} max={10000} step={1} value={row.faces ?? ''} onChange={event => number('faces', event.target.value)} /></label>
      <label>Coincide con planograma<select disabled={!hasPlanogram} value={row.match} onChange={event => change('match', event.target.value)}>
        {['N/A', 'Sí', 'No'].map(value => <option key={value}>{value}</option>)}
      </select></label>
      <label>Precio observado (opcional)<input type="number" min={0} step="any" value={row.observedPrice ?? ''} onChange={event => number('observedPrice', event.target.value)} /></label>
      <label>Confianza del motor % (opcional)<input type="number" min={0} max={100} step="any" value={row.confidence ?? ''} onChange={event => number('confidence', event.target.value)} /></label>
    </div>
    <button type="button" className="link" onClick={remove}>Quitar fila</button>
  </fieldset>;
}
