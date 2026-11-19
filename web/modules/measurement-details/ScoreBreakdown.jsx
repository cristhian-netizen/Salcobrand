'use client';
import {Card} from '../sb/ui';

const number = value => typeof value === 'number' ? value.toLocaleString('es-CL', {maximumFractionDigits: 4}) : 'Sin evaluar';
const NAMES = {stock: 'Stock observado', space: 'Espacio ocupado', price: 'Rótulos de precio', organization: 'Orden por categoría'};
const MEANINGS = {
  stock: 'Proporción de registros que el modelo no marcó como quiebre de stock. No verifica por sí sola que esté presente todo el surtido esperado.',
  space: 'Penaliza los espacios vacíos: cada punto porcentual de espacio vacío resta dos puntos al componente. El resultado se limita entre 0 y 100.',
  price: 'Proporción de registros evaluados en los que el modelo detectó un rótulo de precio visible. No comprueba que el precio sea correcto.',
  organization: 'Mide el predominio de una categoría en cada nivel, ponderado por sus caras. Un valor alto indica agrupación, no cumplimiento del planograma ni identificación correcta de cada producto.',
};

function formula({key, score, inputs: input}) {
  if (score == null) return key === 'price' ? 'No se evaluó la visibilidad de precios en esta captura. Este componente no participa; no equivale a un puntaje cero.' : 'No hay datos suficientes para evaluar este componente. No participa en el total.';
  if (key === 'stock') return `100 × (1 − ${number(input.missing)} / ${number(input.total)}) = ${number(score)}. Se cuentan registros detectados, no SKU únicos.`;
  if (key === 'space') return `100 − (${number(input.empty_pct)} % × ${number(input.penalty_per_pct)}) = ${number(100 - input.empty_pct * input.penalty_per_pct)} → ${number(score)} puntos, tras limitar a 0–100 y redondear.`;
  if (key === 'price') return `100 × ${number(input.visible)} rótulos visibles / ${number(input.evaluated)} registros evaluados = ${number(score)} puntos, redondeado.`;
  return `100 × ${number(input.dominant_faces)} caras de las categorías predominantes / ${number(input.faces)} caras evaluadas = ${number(score)} puntos, redondeado. Se evaluaron ${input.levels.length} niveles.`;
}

export default function ScoreBreakdown({reading}) {
  const standards = reading.standards || {}, detail = standards.breakdown;
  if (!detail) return null;
  const evaluated = detail.components.filter(item => item.score != null);
  const expression = evaluated.map(item => `${number(item.score)} × ${number(item.base_weight_pct)} %`).join(' + ');
  return <Card className="score-breakdown" title={`Cómo se obtiene el puntaje ${number(standards.overall_score)}`} subtitle="Puntaje de exhibición de 0 a 100. No representa la precisión del reconocimiento ni el porcentaje de cumplimiento del planograma.">
    {evaluated.length ? <div className="score-calculation" aria-label="Cálculo del puntaje">
      <p><strong>({expression}) ÷ {number(detail.available_weight_pct)} % = {number(detail.unrounded_score)} → {number(standards.overall_score)} puntos.</strong></p>
      <p>{detail.available_weight_pct < 100 ? `Hay datos para componentes que suman ${number(detail.available_weight_pct)} % del peso base. Sus pesos se redistribuyen proporcionalmente hasta sumar 100 %.` : 'Se utilizan los cuatro componentes con sus pesos base.'} El resultado se redondea al entero más cercano; si termina exactamente en ,5, se elige el entero par.</p>
    </div> : <p>No hay datos suficientes para calcular un puntaje de exhibición.</p>}
    <div className="score-components">
      {detail.components.map(item => <article key={item.key} className="score-component" data-component={item.key}>
        <h3>{NAMES[item.key]} <span>{item.score == null ? 'Sin evaluar' : `${number(item.score)} / 100`}</span></h3>
        <p>{MEANINGS[item.key]}</p>
        <p className="score-component-formula">{formula(item)}</p>
        <dl><div><dt>Peso base</dt><dd>{number(item.base_weight_pct)} %</dd></div><div><dt>Peso aplicado</dt><dd>{number(item.effective_weight_pct)} %</dd></div><div><dt>Aporte al total</dt><dd>{item.contribution == null ? 'No participa' : `${number(item.contribution)} puntos`}</dd></div></dl>
        {item.key === 'organization' && item.inputs.levels.length > 0 && <details><summary>Ver cálculo por nivel</summary><ul>{item.inputs.levels.map(level => <li key={level.level}>Nivel {level.level}: {number(level.dominant_faces)} de {number(level.faces)} caras pertenecen a la categoría predominante.</li>)}</ul><p>Si todos los productos reciben la misma etiqueta de categoría, este componente puede llegar a 100 aunque su identificación sea incierta.</p></details>}
      </article>)}
    </div>
    <p className="sb-hint score-grade-scale"><strong>Clasificación:</strong> {detail.grade_ranges.map((range, index) => `${range.label}: ${range.minimum}–${index ? detail.grade_ranges[index - 1].minimum - 1 : 100}`).join(' · ')}. El color utiliza el semáforo definido en Configuración.</p>
    <details className="score-other-metrics"><summary>Qué significan las otras métricas</summary><dl>
      <dt>Cumplimiento de planograma</dt><dd>Caras cubiertas frente a caras esperadas de la referencia asociada, expresadas como porcentaje. Requiere posiciones configuradas; se calcula por separado del puntaje de exhibición.</dd>
      <dt>Caras detectadas</dt><dd>Frentes visibles de productos estimados en las fotos. No son unidades totales en profundidad ni cantidad de productos diferentes.</dd>
      <dt>Detecciones inciertas</dt><dd>{number(reading.needs_review)} registros señalados por el motor para verificación. No se descuentan directamente del puntaje: un puntaje alto puede coexistir con muchas detecciones inciertas.</dd>
    </dl></details>
  </Card>;
}
