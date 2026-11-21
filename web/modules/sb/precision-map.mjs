// Mapa de precisión de una lectura: cada producto que el motor encontró, pintado sobre la foto según cuánto se puede
// confiar en él, y un resumen al lado. Los productos de las lecturas por Kilby traen `boxes` (una caja por cara, en
// píxeles de la foto `image_index`; un pack trae una caja por lata) e `image_size` ([ancho, alto] de esa foto); las
// lecturas anteriores no las traen y solo muestran el resumen.

export const CLASSES = ['seguro', 'por_confirmar', 'sin_identificar', 'hueco'];
export const LABELS = {
  seguro: 'Identificado seguro',
  por_confirmar: 'Identificado, por confirmar',
  sin_identificar: 'Sin identificar',
  hueco: 'Hueco',
};
export const LEGEND = 'Verde: identificado seguro · Amarillo: identificado, por confirmar · Rojo: sin identificar · Gris: hueco';

const IDENTIFIED = new Set(['match', 'confirmed']);

function validBox(box) {
  if (!Array.isArray(box) || box.length !== 4) return null;
  const [x1, y1, x2, y2] = box.map(Number);
  return [x1, y1, x2, y2].every(Number.isFinite) && x2 > x1 && y2 > y1 ? [x1, y1, x2, y2] : null;
}

export function boxesOf(product) {
  return (Array.isArray(product?.boxes) ? product.boxes : []).map(validBox).filter(Boolean);
}

// Un hueco cuenta si es físico (el motor lo vio en la foto); el faltante que el planograma infiere por secuencia
// (source "prior", sin caja) no es un hueco de la foto.
function isPhysicalGap(product) {
  return product?.match_status === 'gap' && (boxesOf(product).length > 0 || product.source !== 'prior');
}

// count_uncertain no baja la clase: la identidad es segura y solo las caras pueden cambiar cuando se revise un vecino
// dudoso (en la foto real de L128 pintaba de amarillo 39 de los 47 productos seguros); va en el tooltip.
export function precisionClass(product) {
  const status = product?.match_status;
  if (status === 'gap') return isPhysicalGap(product) ? 'hueco' : null;
  if (IDENTIFIED.has(status)) return product.needs_review ? 'por_confirmar' : 'seguro';
  return 'sin_identificar';
}

function displayName(product, cls) {
  if (cls === 'hueco') {
    const named = product.product && product.product !== 'espacio vacío' ? product.product : '';
    return named ? `Hueco · falta ${named}` : 'Hueco';
  }
  if (cls === 'sin_identificar') return 'producto no identificado';
  return product.product || 'producto';
}

function percent(value) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value * 100) : null;
}

export function tooltip(product) {
  const cls = precisionClass(product);
  if (!cls) return '';
  const parts = [displayName(product, cls)];
  if (cls !== 'hueco') {
    parts.push(LABELS[cls]);
    const pct = percent(product.confidence);
    if (pct !== null) parts.push(`confianza ${pct} %`);
    if (cls !== 'sin_identificar' && product.count_uncertain) parts.push('caras por confirmar');
  }
  const units = Number(product.pack_units), perPack = Number(product.units_per_pack);
  if (units > 0 && perPack > 1) parts.push(`pack de ${perPack} (${units} ${units === 1 ? 'lata' : 'latas'})`);
  return parts.join(' · ');
}

// Rectángulos de la foto `index`: uno por caja, con su clase y el texto del tooltip.
export function overlayFor(products, index) {
  const rects = [];
  (products || []).forEach((product, position) => {
    if (product?.image_index !== index) return;
    const cls = precisionClass(product);
    if (!cls) return;
    const title = tooltip(product);
    boxesOf(product).forEach((box, n) => rects.push({key: `${position}-${n}`, box, cls, title}));
  });
  return rects;
}

// [ancho, alto] de la foto `index` según el motor, o null si ningún producto lo trae.
export function imageSizeFor(products, index) {
  for (const product of products || []) {
    const size = product?.image_index === index && Array.isArray(product.image_size) ? product.image_size.map(Number) : null;
    if (size && size.length === 2 && size.every(v => Number.isFinite(v) && v > 0)) return size;
  }
  return null;
}

export function hasPrecisionBoxes(products) {
  return (products || []).some(product => precisionClass(product) && boxesOf(product).length > 0);
}

// Resumen de la lectura: posiciones por clase (caras para los productos, uno por hueco; un pack de 4 latas contado como
// 2 caras son 2) y la confianza media de lo identificado, ponderada por caras.
export function precisionSummary(products) {
  const counts = Object.fromEntries(CLASSES.map(cls => [cls, 0]));
  let confidenceSum = 0, confidenceWeight = 0;
  for (const product of products || []) {
    const cls = precisionClass(product);
    if (!cls) continue;
    const weight = cls === 'hueco' ? 1 : Math.max(1, Number(product.facings) || 0);
    counts[cls] += weight;
    if ((cls === 'seguro' || cls === 'por_confirmar') && typeof product.confidence === 'number' && Number.isFinite(product.confidence)) {
      confidenceSum += product.confidence * weight;
      confidenceWeight += weight;
    }
  }
  const total = CLASSES.reduce((sum, cls) => sum + counts[cls], 0);
  return {
    total,
    classes: CLASSES.map(cls => ({cls, label: LABELS[cls], count: counts[cls], pct: total ? Math.round(counts[cls] / total * 100) : 0})),
    meanConfidence: confidenceWeight ? confidenceSum / confidenceWeight : null,
  };
}
