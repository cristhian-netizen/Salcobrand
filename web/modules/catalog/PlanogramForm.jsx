'use client';
import SortableTable from '../tables/SortableTable';

import { useState } from 'react';
import { SaveForm, StatusField, enc, sortByName } from '../management/shared';
import ReferenceField from './ReferenceField';
import {subcategoryOptions} from '../settings/catalog.mjs';
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
  const subcategoryChoices=subcategoryOptions(catalog.classification.categories);
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
    if (!form.category || form.subcategories.length!==1) throw Error('Selecciona una única subcategoría.');
    const result = Object.fromEntries(
      [
        'category',
        'subcategories',
        'name',
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
      <StatusField
        value={form.status}
        onChange={(status) => setForm({ ...form, status })}
      />
      <label>Subcategoría del planograma<select required value={form.subcategories.length===1?JSON.stringify([form.category,form.subcategories[0]]):''} onChange={e=>{const choice=subcategoryChoices.find(c=>c.key===e.target.value);setForm({...form,category:choice?.category||'',subcategories:choice?[choice.subcategory]:[]});}}><option value="">Seleccionar subcategoría</option>{subcategoryChoices.map(c=><option key={c.key} value={c.key}>{c.subcategory} · {c.category}</option>)}</select></label>
      <label>Categoría<input readOnly value={form.subcategories.length===1?form.category:''} placeholder="Se completa al elegir subcategoría"/></label>
      {plan.subcategories?.length>1&&<p className="full sb-hint">Este registro anterior tiene varias subcategorías. Selecciona una para utilizar la asignación compartida.</p>}
      {!!plan.assigned_count&&<p className="full sb-hint">Los cambios se aplicarán a las próximas mediciones de los {plan.assigned_count} PDV asignados. Las mediciones anteriores se conservan.</p>}
      <p className="full sb-hint">Guarda el planograma y usa «Asignar a PDV» para seleccionar uno o varios locales.</p>
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
