'use client';
import { useRef, useState } from 'react';
import { Card } from '../sb/ui';
import { catalogDraft, updateCatalog } from './catalog.mjs';

export default function CatalogSettings({
  state,
  products,
  busy,
  save,
  onError,
}) {
  const [draft, setDraft] = useState(() => catalogDraft(state));
  const sequence = useRef(0);
  const newId = (prefix) => prefix + '-new-' + ++sequence.current;
  const setBrand = (id, values) =>
    setDraft((previous) => ({
      ...previous,
      brands: previous.brands.map((row) =>
        row.id === id ? { ...row, ...values } : row,
      ),
    }));
  const setRow = (id, values) =>
    setDraft((previous) => ({
      ...previous,
      rows: previous.rows.map((row) =>
        row.id === id ? { ...row, ...values } : row,
      ),
    }));
  async function submit(event) {
    event.preventDefault();
    try {
      const next = updateCatalog({ ...state, products }, draft);
      const result = await save('catalog', {
        ...next.catalog,
        ownBrands: next.productParameters.ownBrands,
      });
      if (result) setDraft(catalogDraft(result));
    } catch (error) {
      onError(error.message);
    }
  }
  return (
    <Card
      title="Clasificación de productos"
      subtitle="Marcas y submarcas, categorías y subcategorías. Marca cuáles pertenecen al cliente."
    >
      <form onSubmit={submit}>
        <fieldset className="settings-fields" disabled={busy}>
          <h3>Categorías y subcategorías</h3>
          <p className="sb-hint">
            Una fila por combinación. La submarca exclusiva se aplica a toda la
            categoría.
          </p>
          {draft.rows.map((row, index) => (
            <div className="settings-classification" key={row.id}>
              <label>
                Categoría {index + 1}
                <input
                  list="settings-categories"
                  required
                  maxLength={100}
                  value={row.category}
                  onChange={(e) => setRow(row.id, { category: e.target.value })}
                />
              </label>
              <label>
                Subcategoría
                <input
                  required
                  maxLength={100}
                  value={row.subcategory}
                  onChange={(e) =>
                    setRow(row.id, { subcategory: e.target.value })
                  }
                />
              </label>
              <label>
                Submarca exclusiva
                <select
                  value={row.brandId}
                  onChange={(e) => {
                    const brandId = e.target.value;
                    setDraft((previous) => ({
                      ...previous,
                      rows: previous.rows.map((other) =>
                        other.category.trim() === row.category.trim()
                          ? { ...other, brandId }
                          : other,
                      ),
                    }));
                  }}
                >
                  <option value="">Todas las marcas</option>
                  {draft.brands
                    .filter((brand) => brand.name.trim())
                    .sort((a, b) =>
                      a.name.localeCompare(b.name, 'es', {
                        sensitivity: 'base',
                      }),
                    )
                    .map((brand) => (
                      <option key={brand.id} value={brand.id}>
                        {brand.name}
                      </option>
                    ))}
                  {row.brandId &&
                    !draft.brands.some((brand) => brand.id === row.brandId) && (
                      <option value={row.brandId}>
                        Marca eliminada, selecciona otra
                      </option>
                    )}
                </select>
              </label>
              <button
                type="button"
                onClick={() =>
                  setDraft((previous) => ({
                    ...previous,
                    rows: previous.rows.filter((other) => other.id !== row.id),
                  }))
                }
              >
                Quitar
              </button>
            </div>
          ))}
          <datalist id="settings-categories">
            {[
              ...new Set(draft.rows.map((row) => row.category).filter(Boolean)),
            ].map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          <h3>Marcas y submarcas</h3>
          {draft.brands.map((brand, index) => (
            <div className="settings-brand" key={brand.id}>
              <label>
                Marca / submarca {index + 1}
                <input
                  required
                  maxLength={100}
                  value={brand.name}
                  onChange={(e) => setBrand(brand.id, { name: e.target.value })}
                />
              </label>
              <label className="mg-check">
                <input
                  type="checkbox"
                  checked={brand.own}
                  onChange={(e) =>
                    setBrand(brand.id, { own: e.target.checked })
                  }
                />
                Marca propia
              </label>
              <button
                type="button"
                onClick={() =>
                  setDraft((previous) => ({
                    ...previous,
                    brands: previous.brands.filter(
                      (row) => row.id !== brand.id,
                    ),
                  }))
                }
              >
                Quitar
              </button>
            </div>
          ))}
          <div className="sb-actions">
            <button
              type="button"
              onClick={() =>
                setDraft((previous) => ({
                  ...previous,
                  brands: [
                    ...previous.brands,
                    { id: newId('brand'), name: '', own: false },
                  ],
                }))
              }
            >
              Añadir marca / submarca
            </button>
          </div>
          <div className="sb-actions">
            <button
              type="button"
              onClick={() =>
                setDraft((previous) => ({
                  ...previous,
                  rows: [
                    ...previous.rows,
                    {
                      id: newId('row'),
                      category: '',
                      subcategory: '',
                      brandId: '',
                    },
                  ],
                }))
              }
            >
              Añadir categoría / subcategoría
            </button>
            <button type="submit" className="action">
              Guardar clasificación
            </button>
          </div>
        </fieldset>
      </form>
    </Card>
  );
}
