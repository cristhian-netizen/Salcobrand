'use client';
import { useState } from 'react';
import { Card } from '../sb/ui';

export default function PdvTypesSettings({ state, busy, save }) {
  const [types, setTypes] = useState(state.pdvTypes);
  async function submit(event) {
    event.preventDefault();
    const result = await save('pdv-types', types);
    if (result) setTypes(result.pdvTypes);
  }
  return (
    <Card
      title="Tipos de punto de venta"
      subtitle="Estas opciones aparecen al crear o editar un PDV. Los tipos en uso deben conservarse."
    >
      <form onSubmit={submit}>
        <fieldset className="settings-fields" disabled={busy}>
          {types.map((name, index) => (
            <div className="settings-type" key={index}>
              <label>
                Tipo de PDV {index + 1}
                <input
                  required
                  maxLength={80}
                  value={name}
                  onChange={(e) =>
                    setTypes((previous) =>
                      previous.map((type, position) =>
                        position === index ? e.target.value : type,
                      ),
                    )
                  }
                />
              </label>
              <button
                type="button"
                disabled={types.length === 1}
                onClick={() =>
                  setTypes((previous) =>
                    previous.filter((_, position) => position !== index),
                  )
                }
              >
                Quitar
              </button>
            </div>
          ))}
          <div className="sb-actions">
            <button
              type="button"
              onClick={() => setTypes((previous) => [...previous, ''])}
            >
              Añadir tipo de PDV
            </button>
            <button type="submit" className="action">
              Guardar tipos de PDV
            </button>
          </div>
        </fieldset>
      </form>
    </Card>
  );
}
