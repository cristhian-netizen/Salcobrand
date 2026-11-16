const normalize = value => String(value ?? '').trim().normalize('NFKC').toLocaleLowerCase('es-CL');

export function catalogDraft(state) {
  const catalog = state.catalog || {};
  const ownBrands = state.productParameters?.ownBrands || [];
  const names = [...new Set([...(catalog.brands || []), ...ownBrands, ...Object.values(catalog.exclusive || {})])];
  const brands = names.map((name, index) => ({id:`b${index}`, name, own:ownBrands.includes(name)}));
  const rows = Object.entries(catalog.categories || {}).flatMap(([category, subcategories]) =>
    (Array.isArray(subcategories) ? subcategories : []).map((subcategory, index) => ({
      id:`${category}-${index}`, category, subcategory,
      brandId:brands.find(brand => brand.name === catalog.exclusive?.[category])?.id || '',
    })));
  return {brands, rows};
}

export function updateCatalog(state, draft) {
  const previous = state.catalog || {};
  const errors = [];
  const brands = [];
  const ownBrands = [];
  const brandById = new Map();
  const brandNames = new Set();

  (draft.brands || []).forEach((row, index) => {
    const name = String(row.name || '').trim();
    if (!name || name.length > 100) errors.push(`Marca ${index + 1}: escribe un nombre de hasta 100 caracteres.`);
    else if (brandNames.has(normalize(name))) errors.push(`Marca ${index + 1}: «${name}» está repetida.`);
    else {
      brandNames.add(normalize(name));
      brands.push(name);
      brandById.set(row.id, name);
      if (row.own) ownBrands.push(name);
    }
  });
  if (!brands.length) errors.push('Agrega al menos una marca o submarca.');

  const categories = Object.create(null);
  const exclusive = Object.create(null);
  const categoryNames = new Map();
  const pairs = new Set();
  (draft.rows || []).forEach((row, index) => {
    const category = String(row.category || '').trim();
    const subcategory = String(row.subcategory || '').trim();
    const label = `Clasificación ${index + 1}: `;
    if (!category || !subcategory) { errors.push(label + 'completa categoría y subcategoría.'); return; }
    if (category.length > 100 || subcategory.length > 100) { errors.push(label + 'usa nombres de hasta 100 caracteres.'); return; }
    if (['__proto__', 'prototype', 'constructor'].includes(category)) { errors.push(label + 'ese nombre de categoría está reservado.'); return; }
    const categoryKey = normalize(category);
    const existingName = categoryNames.get(categoryKey);
    if (existingName && existingName !== category) { errors.push(label + `usa el nombre «${existingName}» de forma consistente.`); return; }
    categoryNames.set(categoryKey, category);
    if (row.brandId && !brandById.has(row.brandId)) { errors.push(label + 'la submarca exclusiva ya no existe.'); return; }
    const pair = `${categoryKey}|${normalize(subcategory)}`;
    if (pairs.has(pair)) { errors.push(label + 'la subcategoría está repetida.'); return; }
    pairs.add(pair);
    const brand = row.brandId ? brandById.get(row.brandId) : '';
    if (categories[category] && (exclusive[category] || '') !== brand) {
      errors.push(label + 'todas las filas de esta categoría deben tener la misma submarca exclusiva.');
      return;
    }
    categories[category] ||= [];
    categories[category].push(subcategory);
    if (brand) exclusive[category] = brand;
  });
  if (!Object.keys(categories).length) errors.push('Agrega al menos una categoría y subcategoría.');

  for (const product of state.products || []) {
    if (previous.brands?.includes(product.subBrand) && !brands.includes(product.subBrand)) {
      errors.push(`No puedes quitar o renombrar «${product.subBrand}»: tiene productos asociados.`);
    }
    if (previous.categories?.[product.category]?.includes(product.subcategory) &&
        !categories[product.category]?.includes(product.subcategory)) {
      errors.push(`No puedes quitar o renombrar «${product.category} / ${product.subcategory}»: tiene productos asociados.`);
    }
    if (exclusive[product.category] && exclusive[product.category] !== product.subBrand) {
      errors.push(`«${product.category}» tiene productos de otras marcas; no se puede restringir a «${exclusive[product.category]}».`);
    }
  }
  if (errors.length) throw Error([...new Set(errors)].join(' '));

  return {
    ...state,
    catalog:{...previous, brands, categories:{...categories}, exclusive:{...exclusive}},
    productParameters:{...state.productParameters, ownBrands},
  };
}
