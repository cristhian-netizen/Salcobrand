'use client';
import { useState } from 'react';
import { Card, Pill } from '../sb/ui';

const FACTORS = [
  ['stock', 'Disponibilidad (quiebres de stock)'],
  ['space', 'Espacio en góndola'],
  ['price', 'Rótulos de precio'],
  ['organization', 'Organización por categoría'],
];
// Historical weights of the shelf score (same defaults as the backend).
const DEFAULT_WEIGHTS = { stock: 35, space: 25, price: 20, organization: 20 };

export default function MeasurementSettings({ state, busy, save }) {
  const [weights, setWeights] = useState({
    ...DEFAULT_WEIGHTS,
    ...(state.standardsWeights || {}),
  });
  const total = FACTORS.reduce(
    (sum, [key]) => sum + (Number(weights[key]) || 0),
    0,
  );
  return (
    <Card
      title="Parámetros de medición"
      subtitle="Pesos de los cuatro factores del puntaje de góndola de Mediciones."
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          await save(
            'standards',
            Object.fromEntries(
              FACTORS.map(([key]) => [key, Number(weights[key])]),
            ),
          );
        }}
      >
        <fieldset className="settings-fields sb-form" disabled={busy}>
          {FACTORS.map(([key, label]) => (
            <label key={key}>
              {label} (%)
              <input
                required
                type="number"
                min="0"
                max="100"
                step="1"
                value={weights[key]}
                onChange={(e) =>
                  setWeights((previous) => ({
                    ...previous,
                    [key]: e.target.value,
                  }))
                }
              />
            </label>
          ))}
          <div className="sb-actions full" aria-label="Suma de los pesos">
            <Pill kind={total === 100 ? 'ok' : 'bad'}>Suma · {total} %</Pill>
            {total !== 100 && <small>Ajusta los pesos hasta sumar 100 %.</small>}
          </div>
          <p className="full sb-hint">
            El puntaje se calcula cada vez que se muestra o exporta una
            medición, así que un cambio de pesos también re-puntúa las
            mediciones anteriores.
          </p>
          <div className="sb-actions full">
            <button className="action" type="submit" disabled={total !== 100}>
              Guardar pesos
            </button>
            <button
              type="button"
              onClick={() => setWeights({ ...DEFAULT_WEIGHTS })}
            >
              Restaurar valores por defecto
            </button>
          </div>
        </fieldset>
      </form>
    </Card>
  );
}
