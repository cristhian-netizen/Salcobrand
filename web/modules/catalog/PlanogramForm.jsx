'use client';
import SortableTable from '../tables/SortableTable';

import {orderRegions} from '../../lib/locations.mjs';
import { useState } from 'react';
import { SaveForm, StatusField, enc, sortByName } from '../management/shared';
import ReferenceField from './ReferenceField';
import CategorySelection from './CategorySelection';
import { api } from '../../lib/sb';
import { useApi, Loading, ErrorBox } from '../sb/ui';

const productLabel = (p) =>
  `${p.name} · ${p.subBrand} · ${p.quantity} ${p.saleUnit}`;
export default function PlanogramEditor(props) {
  const record = useApi(
    () =>
      props.plan.id
        ? api('/api/admin/catalog/planograms/' + enc(props.plan.id))
        : Promise.resolve(props.plan),
    [props.plan.id],
  );
  if (record.loading) return <Loading />;
  if (record.error)
    return <ErrorBox error={record.error} onRetry={record.reload} />;
  return <PlanogramForm {...props} plan={record.data} />;
}

function PlanogramForm({ plan, catalog, onSaved, onClose }) {
  const local = catalog.stores.find((s) => s.code === plan.store_code);
  const [region, setRegion] = useState(local?.region || '');
  const [commune, setCommune] = useState(local?.commune || '');
  const [processing, setProcessing] = useState(false);
  const [form, setForm] = useState({
    category: '',
    subcategories: [],
    name: '',
    store_code: '',
    status: 'Activo',
    description: '',
    photo: '',
    document: '',
    document_name: '',
    document_page: 1,
    document_pages: 0,
    position_mode: 'faces',
    positionRows: [],
    ...plan,
  });
  const products = sortByName(catalog.products);
  const communes =
    catalog.locations.regions.find((r) => r.name === region)?.communes || [];
  const stores = sortByName(
    catalog.stores.filter((s) => s.region === region && s.commune === commune),
  );
  const field = (key) => ({
    value: form[key],
    onChange: (e) => setForm({ ...form, [key]: e.target.value }),
  });
  function updateRow(index, values) {
    setForm((current) => ({
      ...current,
      positionRows: current.positionRows.map((r, i) =>
        i === index ? { ...r, ...values } : r,
      ),
    }));
  }
  function selectProduct(index, value) {
    const product = products.find((p) => p.id === value);
    if (product)
      updateRow(index, {
        productId: product.id,
        sku: product.sku,
        barcode: product.barcode,
        legacy_item_id: null,
        legacy_title: '',
      });
    else if (!value.startsWith('legacy:'))
      updateRow(index, {
        productId: '',
        sku: '',
        barcode: '',
        legacy_item_id: null,
        legacy_title: '',
      });
  }
  function payload() {
    if (processing) throw Error('Espera a que termine de cargar el archivo.');
    if (Object.keys(catalog.classification.categories).length && !form.category) throw Error('Selecciona una categoría.');
    if (catalog.classification.categories[form.category]?.length && !form.subcategories.length) throw Error('Selecciona al menos una subcategoría.');
    const result = Object.fromEntries(
      [
        'category',
        'subcategories',
        'name',
        'store_code',
        'status',
        'description',
        'photo',
        'document',
        'document_name',
        'document_page',
        'position_mode',
      ].map((k) => [k, form[k]]),
    );
    result.positionRows = form.positionRows.map((r) => ({
      ...r,
      level: Number(r.level),
      position: Number(r.position),
      faces: Number(r.faces),
    }));
    if (plan.id) result.version = plan.version;
    return result;
  }
  return (
    <SaveForm
      path={
        '/api/admin/catalog/planograms' + (plan.id ? '/' + enc(plan.id) : '')
      }
      method={plan.id ? 'PATCH' : 'POST'}
      payload={payload}
      onSaved={onSaved}
      onClose={onClose}
    >
      <label>
        Nombre del planograma
        <input required maxLength={150} {...field('name')} />
      </label>
      <label>
        Región
        <select
          required
          value={region}
          onChange={(e) => {
            setRegion(e.target.value);
            setCommune('');
            setForm({ ...form, store_code: '' });
          }}
        >
          <option value="">Seleccionar región</option>
          {orderRegions(catalog.locations.regions).map((r) => (
            <option key={r.code}>{r.name}</option>
          ))}
        </select>
      </label>
      <label>
        Comuna
        <select
          required
          value={commune}
          disabled={!region}
          onChange={(e) => {
            setCommune(e.target.value);
            setForm({ ...form, store_code: '' });
          }}
        >
          <option value="">Seleccionar comuna</option>
          {sortByName(communes).map((c) => (
            <option key={c.name}>{c.name}</option>
          ))}
        </select>
      </label>
      <label>
        Punto de venta
        <select required disabled={!commune} {...field('store_code')}>
          <option value="">Seleccionar PDV</option>
          {stores.map((s) => (
            <option key={s.code} value={s.code}>
              {s.name} ({s.code})
            </option>
          ))}
        </select>
      </label>
      <StatusField
        value={form.status}
        onChange={(status) => setForm({ ...form, status })}
      />
      <CategorySelection categories={catalog.classification.categories} value={form} required onChange={value => setForm(current => ({...current, category:value.category, subcategories:value.subcategories}))}/>
      {form.legacy_point_ids?.length > 0 && (
        <p className="full sb-hint">
          Se conservan {form.legacy_point_ids.length} asignaciones anteriores de
          este planograma compartido en góndolas de otros locales.
        </p>
      )}
      <label className="full">
        Descripción
        <textarea maxLength={2000} {...field('description')} />
      </label>
      <ReferenceField
        pdf
        value={form}
        onChange={(value) => setForm((current) => ({ ...current, ...value }))}
        onBusy={setProcessing}
      />
      <fieldset className="full ct-distribution">
        <legend>Posiciones de productos</legend>
        <p className="sb-hint">
          {form.position_mode === 'products'
            ? 'Se conserva la numeración por producto del planograma importado. Las caras indican la cantidad esperada en cada posición.'
            : 'Nivel 1 arriba, posición 1 a la izquierda. Cada cara ocupa una posición.'}{' '}
          Un pack es una presentación.
        </p>
        <div className="sb-actions">
          <button
            type="button"
            onClick={() =>
              setForm({
                ...form,
                positionRows: [
                  ...form.positionRows,
                  {
                    level: 1,
                    position: 1,
                    faces: 1,
                    productId: '',
                    sku: '',
                    barcode: '',
                  },
                ],
              })
            }
          >
            Añadir producto
          </button>
        </div>
        <div className="sb-table ct-positions">
          <SortableTable>
            <thead>
              <tr>
                <th>Nivel ↓</th>
                <th>Producto</th>
                <th>
                  {form.position_mode === 'products'
                    ? 'Posición de producto →'
                    : 'Posición inicial →'}
                </th>
                <th>Código/SKU</th>
                <th>Código de barras</th>
                <th>Caras</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {form.positionRows.map((row, index) => (
                <tr key={index}>
                  <td>
                    <input
                      aria-label={'Nivel fila ' + (index + 1)}
                      type="number"
                      min="1"
                      max="5000"
                      step="1"
                      required
                      value={row.level}
                      onChange={(e) =>
                        updateRow(index, { level: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <select
                      aria-label={'Producto fila ' + (index + 1)}
                      required
                      value={
                        row.productId ||
                        (row.legacy_item_id
                          ? 'legacy:' + row.legacy_item_id
                          : '')
                      }
                      onChange={(e) => selectProduct(index, e.target.value)}
                    >
                      <option value="">Seleccionar producto</option>
                      {row.legacy_item_id && (
                        <option value={'legacy:' + row.legacy_item_id}>
                          {row.legacy_title} · Referencia anterior
                        </option>
                      )}
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>
                          {productLabel(p)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      aria-label={'Posición fila ' + (index + 1)}
                      type="number"
                      min="1"
                      max="5000"
                      step="1"
                      required
                      value={row.position}
                      onChange={(e) =>
                        updateRow(index, { position: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={'Código/SKU fila ' + (index + 1)}
                      maxLength={80}
                      value={row.sku || ''}
                      onChange={(e) =>
                        updateRow(index, { sku: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={'Código de barras fila ' + (index + 1)}
                      maxLength={80}
                      value={row.barcode || ''}
                      onChange={(e) =>
                        updateRow(index, { barcode: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={'Caras fila ' + (index + 1)}
                      type="number"
                      min="1"
                      max="5000"
                      step="1"
                      required
                      value={row.faces}
                      onChange={(e) =>
                        updateRow(index, { faces: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      onClick={() =>
                        setForm({
                          ...form,
                          positionRows: form.positionRows.filter(
                            (_, i) => i !== index,
                          ),
                        })
                      }
                    >
                      Quitar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </SortableTable>
        </div>
      </fieldset>
    </SaveForm>
  );
}
