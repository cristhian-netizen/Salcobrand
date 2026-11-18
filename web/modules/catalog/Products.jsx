'use client';
import SortableTable from '../tables/SortableTable';

import { useState } from 'react';
import { api } from '../../lib/sb';
import {
  useApi,
  Header,
  Card,
  Loading,
  Empty,
  ErrorBox,
  Modal,
} from '../sb/ui';
import ProductForm from './ProductForm';
import {unitPrice,priceUnit} from './product-format.mjs';
import ProductExcel from './ProductExcel';
import { alphabetical } from '../management/shared';

export default function Products({ notify }) {
  const catalog = useApi(() => api('/api/admin/catalog'), []);
  const [search, setSearch] = useState('');
  const [brand, setBrand] = useState('');
  const [category, setCategory] = useState('');
  const [subcategory, setSubcategory] = useState('');
  const [selected, setSelected] = useState([]);
  const [importing, setImporting] = useState(false);
  const [edit, setEdit] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const products = catalog.data?.products || [];
  const rows = products.filter(
    (p) =>
      (!brand || p.subBrand === brand) &&
      (!category || p.category === category) &&
      (!subcategory || p.subcategory === subcategory) &&
      `${p.name} ${p.sku} ${p.description}`
        .toLocaleLowerCase('es')
        .includes(search.toLocaleLowerCase('es')),
  );
  const visibleSelection = rows.filter((p) => selected.includes(p.id));
  const allSelected =
    rows.length > 0 && visibleSelection.length === rows.length;
  async function remove() {
    setBusy(true);
    setError('');
    try {
      await api('/api/admin/catalog/products/delete', {
        method: 'POST',
        body: {
          products: deleting.map((p) => ({ id: p.id, version: p.version })),
        },
      });
      setDeleting(null);
      setSelected([]);
      setEdit(null);
      catalog.reload();
      notify('Productos eliminados.');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <Header eyebrow="Administración" title="Productos">
        <button type="button" onClick={() => setImporting(true)}>Carga masiva</button>
        <button className="action" disabled={!catalog.data} onClick={() => setEdit({})}>
          Crear producto
        </button>
      </Header>
      <ErrorBox error={catalog.error} onRetry={catalog.reload} />
      <div className="sb-toolbar" aria-label="Filtros de productos">
        <label>
          Buscar
          <input
            value={search}
            placeholder="Nombre, SKU o descripción"
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label>
          Submarca
          <select
            value={brand}
            onChange={(e) => {
              setBrand(e.target.value);
              setCategory('');
              setSubcategory('');
            }}
          >
            <option value="">Todas las submarcas</option>
            {alphabetical(catalog.data?.classification?.brands || products.map((p) => p.subBrand)).map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </label>
        <label>
          Categoría
          <select
            value={category}
            onChange={(e) => {setCategory(e.target.value);setSubcategory('');}}
          >
            <option value="">Todas las categorías</option>
            {alphabetical(
              catalog.data?.classification ? Object.keys(catalog.data.classification.categories) : products.filter((p) => !brand || p.subBrand === brand).map((p) => p.category),
            ).map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Subcategoría
          <select value={subcategory} onChange={(e) => setSubcategory(e.target.value)}>
            <option value="">Todas las subcategorías</option>
            {alphabetical([
              ...(category ? catalog.data?.classification?.categories?.[category] || [] : Object.values(catalog.data?.classification?.categories || {}).flat()),
              ...products.filter(p => (!category || p.category === category) && (!brand || p.subBrand === brand)).map(p => p.subcategory),
            ]).map(name => <option key={name}>{name}</option>)}
          </select>
        </label>
        <button
          onClick={() => {
            setSearch('');
            setBrand('');
            setCategory('');
            setSubcategory('');
          }}
        >
          Limpiar filtros
        </button>
      </div>
      <div className="sb-actions ct-selection">
        <button
          disabled={!rows.length}
          onClick={() => setSelected(allSelected ? [] : rows.map((p) => p.id))}
        >
          {allSelected ? 'Deseleccionar todo' : 'Seleccionar todo'}
        </button>
        {visibleSelection.length > 0 && (
          <>
            <span>{visibleSelection.length} seleccionado(s)</span>
            <button
              className="remove"
              onClick={() => {
                setError('');
                setDeleting(visibleSelection);
              }}
            >
              Eliminar producto(s)
            </button>
          </>
        )}
      </div>
      <Card body={false}>
        {catalog.loading ? (
          <Loading />
        ) : !rows.length ? (
          <Empty>No hay productos con estos filtros.</Empty>
        ) : (
          <div className="sb-table">
            <SortableTable>
              <thead>
                <tr>
                  <th>Seleccionar</th>
                  <th>SKU / producto</th>
                  <th>Submarca</th>
                  <th>Categoría / subcategoría</th>
                  <th>Formato</th>
                  <th>Volumen</th>
                  <th>Precio CLP</th>
                  <th>Precio por kg/litro/unidad</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <input
                        className="ct-select"
                        type="checkbox"
                        aria-label={'Seleccionar ' + p.name}
                        checked={selected.includes(p.id)}
                        onChange={(e) =>
                          setSelected((current) =>
                            e.target.checked
                              ? [...new Set([...current, p.id])]
                              : current.filter((id) => id !== p.id),
                          )
                        }
                      />
                    </td>
                    <td>
                      <b>{p.name}</b>
                      <small>{p.sku}</small>
                    </td>
                    <td>{p.subBrand}</td>
                    <td>
                      {p.category}
                      <small>{p.subcategory}</small>
                    </td>
                    <td data-sort-value={p.quantity}>
                      {p.quantity} {p.saleUnit}
                      <small>{p.productType}</small>
                    </td>
                    <td data-sort-value={p.volume}>{p.volume.toLocaleString('es-CL')} cm³</td>
                    <td data-sort-value={p.price}>
                      {p.price == null ? '—' : p.price.toLocaleString('es-CL')}
                    </td>
                    <td data-sort-value={unitPrice(p) ?? ''}>
                      {p.price == null
                        ? '—'
                        : unitPrice(p).toLocaleString(
                            'es-CL',
                            { maximumFractionDigits: 2 },
                          ) +
                          ' CLP/' +
                          priceUnit(p.saleUnit)}
                    </td>
                    <td>
                      <button onClick={() => setEdit(p)}>Editar</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </SortableTable>
          </div>
        )}
      </Card>
      {importing && <Modal title="Carga masiva de productos" wide onClose={() => setImporting(false)}><ProductExcel onSaved={catalog.reload}/></Modal>}
      {edit && (
        <Modal
          title={edit.id ? 'Editar producto' : 'Crear producto'}
          onClose={() => setEdit(null)}
        >
          <ProductForm
            product={edit}
            products={products}
            classification={catalog.data?.classification}
            onClose={() => setEdit(null)}
            onSaved={() => {
              setEdit(null);
              catalog.reload();
              notify('Producto guardado.');
            }}
            onDelete={(product) => {
              setError('');
              setDeleting([product]);
              setEdit(null);
            }}
          />
        </Modal>
      )}
      {deleting && (
        <Modal
          title="Eliminar producto(s)"
          onClose={() => !busy && setDeleting(null)}
        >
          <p>¿Eliminar {deleting.length} producto(s)?</p>
          <ul>
            {deleting.slice(0, 10).map((p) => (
              <li key={p.id}>
                {p.name} · {p.sku}
              </li>
            ))}
          </ul>
          <ErrorBox error={error} />
          <div className="sb-actions">
            <button disabled={busy} onClick={() => setDeleting(null)}>
              Cancelar
            </button>
            <button className="remove" disabled={busy} onClick={remove}>
              {busy ? 'Eliminando…' : 'Confirmar eliminación'}
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
