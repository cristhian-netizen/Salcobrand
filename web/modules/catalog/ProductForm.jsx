'use client';
import {DISPLAY_TYPES} from './product-format.mjs';
import {applyBrandClassification} from '../settings/catalog.mjs';
import { useState } from 'react';
import { SaveForm, enc, alphabetical } from '../management/shared';
import ReferenceField from './ReferenceField';
import { api } from '../../lib/sb';
import { useApi, Loading, ErrorBox } from '../sb/ui';

export default function ProductEditor(props) {
  const record = useApi(
    () =>
      props.product.id
        ? api('/api/admin/catalog/products/' + enc(props.product.id))
        : Promise.resolve(props.product),
    [props.product.id],
  );
  if (record.loading) return <Loading />;
  if (record.error)
    return <ErrorBox error={record.error} onRetry={record.reload} />;
  return <ProductForm {...props} product={record.data} />;
}

function ProductForm({
  product,
  products,
  classification,
  onSaved,
  onClose,
  onDelete,
}) {
  const [form, setForm] = useState({
    name: '',
    sku: '',
    barcode: '',
    subBrand: '',
    category: '',
    subcategory: '',
    description: '',
    productType: 'Individual',
    saleUnit: 'gramos',
    quantity: '',
    height: '',
    width: '',
    thickness: '',
    price: '',
    photo: '',
    ...product,
    productType: product.id && !DISPLAY_TYPES.includes(product.productType) ? '' : product.productType || 'Individual',
  });
  const [processing, setProcessing] = useState(false);
  const catalog = classification || {
    brands: alphabetical(products.map((p) => p.subBrand)),
    categories: Object.fromEntries(
      alphabetical(products.map((p) => p.category)).map((category) => [
        category,
        alphabetical(
          products
            .filter((p) => p.category === category)
            .map((p) => p.subcategory),
        ),
      ]),
    ),
    exclusive: {},
  };
  const categories = alphabetical(Object.keys(catalog.categories));
  const field = (key) => ({
    value: form[key] ?? '',
    onChange: (e) => setForm({ ...form, [key]: e.target.value }),
  });
  function payload() {
    if (processing)
      throw Error('Espera a que termine de cargar la fotografía.');
    if (!DISPLAY_TYPES.includes(form.productType)) throw Error('Selecciona un tipo de display.');
    const result = Object.fromEntries(
      [
        'name',
        'sku',
        'barcode',
        'subBrand',
        'category',
        'subcategory',
        'description',
        'productType',
        'saleUnit',
        'photo',
      ].map((k) => [k, form[k]]),
    );
    for (const key of ['quantity', 'height', 'width', 'thickness'])
      result[key] = Number(form[key]);
    result.price =
      form.price === '' || form.price == null ? null : Number(form.price);
    if (product.id) result.version = product.version;
    return result;
  }
  return (
    <SaveForm
      path={
        '/api/admin/catalog/products' +
        (product.id ? '/' + enc(product.id) : '')
      }
      method={product.id ? 'PATCH' : 'POST'}
      payload={payload}
      onSaved={onSaved}
      onClose={onClose}
    >
      <label className="full">
        Nombre del producto
        <input required maxLength={180} {...field('name')} />
      </label>
      <label>
        SKU
        <input required maxLength={80} {...field('sku')} />
      </label>
      <label>
        Código de barras
        <input maxLength={80} {...field('barcode')} />
      </label>
      {!catalog.brands.length && (
        <p className="sb-hint full">
          Configura las marcas y categorías desde Configuración para crear
          productos.
        </p>
      )}
      <label>
        Marca / submarca
        <select
          required
          value={form.subBrand}
          onChange={(e) => {
            setForm(applyBrandClassification(form,e.target.value,catalog));
          }}
        >
          <option value="">Seleccionar marca / submarca</option>
          {alphabetical(catalog.brands).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label>
        Categoría
        <select
          required
          value={form.category}
          onChange={(e) =>
            setForm({ ...form, category: e.target.value, subcategory: '' })
          }
        >
          <option value="">Seleccionar categoría</option>
          {categories.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label>
        Subcategoría
        <select required disabled={!form.category} {...field('subcategory')}>
          <option value="">Seleccionar subcategoría</option>
          {alphabetical(catalog.categories[form.category] || []).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label>
        Tipo de display
        <select required {...field('productType')}>
          {!form.productType && <option value="">Seleccionar tipo de display</option>}
          {DISPLAY_TYPES.map(name => <option key={name}>{name}</option>)}
        </select>
      </label>
      {product.id && !DISPLAY_TYPES.includes(product.productType) && <p className="full sb-hint">Tipo anterior registrado: {product.productType}. Selecciona el tipo de display para guardar la actualización.</p>}
      <label>
        Formato de venta
        <select {...field('saleUnit')}>
          <option value="gramos">gramos</option>
          <option value="ml">ml</option>
          <option value="unidad">unidad</option>
        </select>
      </label>
      {[
        ['quantity', 'Cantidad'],
        ['height', 'Alto (cm)'],
        ['width', 'Ancho (cm)'],
        ['thickness', 'Espesor (cm)'],
      ].map(([key, label]) => (
        <label key={key}>
          {label}
          <input
            required
            type="number"
            min={key === 'quantity' && form.saleUnit === 'unidad' ? '1' : '0.001'}
            max="1000000"
            step={key === 'quantity' && form.saleUnit === 'unidad' ? '1' : 'any'}
            {...field(key)}
          />
        </label>
      ))}
      <label>
        Precio CLP (opcional)
        <input
          type="number"
          min="0"
          max="1000000000"
          step="any"
          {...field('price')}
        />
      </label>
      <label className="full">
        Descripción
        <textarea maxLength={2000} {...field('description')} />
      </label>
      <ReferenceField
        value={form}
        onChange={(value) =>
          setForm((current) => ({ ...current, photo: value.photo }))
        }
        onBusy={setProcessing}
      />
      {product.id && (
        <div className="full">
          <button
            className="remove"
            type="button"
            onClick={() => onDelete(product)}
          >
            Eliminar producto
          </button>
        </div>
      )}
    </SaveForm>
  );
}
