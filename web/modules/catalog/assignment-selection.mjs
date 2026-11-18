export const INITIAL_FILTERS={region:'',commune:'',store_type:'',category:'',subcategory:'',search:''};
export const eligibleStore=(store,typeId='')=>!store.deleted&&store.status==='Activo'&&(!typeId||store.type_ids.includes(typeId));
export function filteredStores(stores,filters) {
  return stores.filter(s=>(!filters.region||s.region===filters.region)&&(!filters.commune||s.commune===filters.commune)&&(!filters.store_type||s.store_type===filters.store_type)
    &&(!filters.category||s.references.some(r=>r.category===filters.category&&(!filters.subcategory||r.subcategory===filters.subcategory)))
    &&`${s.name} ${s.code}`.toLocaleLowerCase('es').includes(filters.search.toLocaleLowerCase('es')));
}
export const selectStores=(selected,stores,typeId='')=>[...new Set([...selected,...stores.filter(s=>eligibleStore(s,typeId)).map(s=>s.code)])];
