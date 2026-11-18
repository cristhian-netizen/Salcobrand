const normalize = value => String(value ?? '').trim().normalize('NFKC').toLocaleLowerCase('es-CL');

export function subcategoryOptions(categories = {}) {
  return Object.entries(categories).flatMap(([category, subs]) => subs.map(subcategory => ({category, subcategory, key:JSON.stringify([category,subcategory])})))
    .sort((a,b)=>a.subcategory.localeCompare(b.subcategory,'es',{sensitivity:'base'}) || a.category.localeCompare(b.category,'es',{sensitivity:'base'}));
}

export function catalogDraft(state) {
  const catalog = state.catalog || {};
  const own = state.productParameters?.ownBrands || [];
  const brands = [...new Set([...(catalog.brands || []), ...own])].map((name,index)=>{
    let relation = Object.hasOwn(catalog.brandClassifications || {},name) ? catalog.brandClassifications[name] : null;
    if (!relation) {
      const pairs = [...new Set((state.products || []).filter(p=>p.subBrand===name).map(p=>JSON.stringify([p.category,p.subcategory])))];
      if (pairs.length===1) { const [category,subcategory]=JSON.parse(pairs[0]);relation={category,subcategory}; }
    }
    return {id:'b'+index,name,own:own.includes(name),category:relation?.category || '',subcategory:relation?.subcategory || ''};
  });
  const rows=Object.entries(catalog.categories || {}).flatMap(([category,subs])=>subs.map((subcategory,index)=>({id:category+'-'+index,category,subcategory})));
  return {brands,rows};
}

export function categoryValue(rows) {
  const categories=Object.create(null), pairs=new Set(), names=new Map();
  for (const [index,row] of rows.entries()) {
    const category=String(row.category || '').trim(),subcategory=String(row.subcategory || '').trim();
    if (!category || !subcategory || category.length>100 || subcategory.length>100) throw Error('Clasificación '+(index+1)+': completa categoría y subcategoría con hasta 100 caracteres.');
    if (['__proto__','prototype','constructor'].includes(category)) throw Error('Ese nombre de categoría está reservado.');
    const normalized=normalize(category), pair=normalized+'|'+normalize(subcategory);
    if (names.has(normalized) && names.get(normalized)!==category) throw Error('Usa el nombre «'+names.get(normalized)+'» de forma consistente.');
    if (pairs.has(pair)) throw Error('La subcategoría está repetida en esta categoría.');
    names.set(normalized,category);pairs.add(pair);categories[category] ||= [];categories[category].push(subcategory);
  }
  if (!Object.keys(categories).length) throw Error('Agrega al menos una categoría y subcategoría.');
  return {categories:{...categories}};
}

export function brandValue(rows, categories, previousBrands=[]) {
  const brands=[], ownBrands=[],brandClassifications=Object.create(null),seen=new Set();
  for (const [index,row] of rows.entries()) {
    const name=String(row.name || '').trim();
    if (!name || name.length>100) throw Error('Marca '+(index+1)+': escribe un nombre de hasta 100 caracteres.');
    if (seen.has(normalize(name))) throw Error('La marca «'+name+'» está repetida.');
    seen.add(normalize(name));brands.push(name);if(row.own)ownBrands.push(name);
    if (row.category || row.subcategory) {
      if (!categories[row.category]?.includes(row.subcategory)) throw Error('Selecciona una subcategoría ya creada para «'+name+'».');
      brandClassifications[name]={category:row.category,subcategory:row.subcategory};
    } else if (!previousBrands.includes(name)) throw Error('Selecciona una subcategoría existente para la nueva marca «'+name+'».');
  }
  return {brands,ownBrands,brandClassifications:{...brandClassifications}};
}

export function applyBrandClassification(form, brand, catalog) {
  const relation=Object.hasOwn(catalog.brandClassifications || {},brand) ? catalog.brandClassifications[brand] : null;
  const category=relation?.category || (catalog.categories[form.category] ? form.category : '');
  const subcategory=relation?.subcategory || (catalog.categories[category]?.includes(form.subcategory) ? form.subcategory : '');
  return {...form,subBrand:brand,category,subcategory};
}

export function updateCatalog(state, draft) {
  const {categories}=categoryValue(draft.rows);
  const {brands,ownBrands,brandClassifications}=brandValue(draft.brands,categories,state.catalog?.brands || []);
  for (const p of state.products || []) {
    if (!brands.includes(p.subBrand) || !categories[p.category]?.includes(p.subcategory)) throw Error('No puedes quitar o renombrar clasificaciones con productos asociados.');
  }
  return {...state,catalog:{brands,categories,exclusive:{},brandClassifications},productParameters:{...state.productParameters,ownBrands}};
}
