'use client';
import SortableTable from '../tables/SortableTable';

import { useState } from 'react';
import { Card, Pill } from '../sb/ui';

const INDICATORS = [
  ['coverage', 'Cobertura de PDV (%)', 'higher'],
  ['osa', 'Disponibilidad observada (%)', 'higher'],
  ['sos', 'Participación por caras (%)', 'higher'],
  ['cp', 'Cumplimiento (%)', 'higher'],
];

export default function AnalysisSettings({ state, busy, save }) {
  const [score, setScore] = useState(state.scoreParameters);
  const [margin, setMargin] = useState(
    state.productParameters.dimensionMarginPct,
  );
  const [kpis, setKpis] = useState(state.kpiParameters);
  function threshold(key, field, value) {
    setKpis((previous) => ({
      ...previous,
      [key]: { ...previous[key], [field]: value },
    }));
  }
  async function saveScore(event) {
    event.preventDefault();
    await save('score', {
      redMax: Number(score.redMax),
      yellowMax: Number(score.yellowMax),
    });
  }
  async function saveKpis(event) {
    event.preventDefault();
    const value = Object.fromEntries(
      INDICATORS.map(([key, , direction]) => [
        key,
        {
          warn: Number(kpis[key].warn),
          good: Number(kpis[key].good),
          direction,
        },
      ]),
    );
    await save('kpi', value);
  }
  return (
    <>
      <Card
        title="Semáforo del puntaje"
        subtitle="Define los colores de los puntajes y sus promedios."
      >
        <form onSubmit={saveScore}>
          <fieldset className="settings-fields sb-form" disabled={busy}>
            <label>
              Límite superior rojo
              <input
                required
                type="number"
                min="0"
                max="98"
                step="1"
                value={score.redMax}
                onChange={(e) =>
                  setScore((previous) => ({
                    ...previous,
                    redMax: e.target.value,
                  }))
                }
              />
            </label>
            <label>
              Límite superior amarillo
              <input
                required
                type="number"
                min="1"
                max="99"
                step="1"
                value={score.yellowMax}
                onChange={(e) =>
                  setScore((previous) => ({
                    ...previous,
                    yellowMax: e.target.value,
                  }))
                }
              />
            </label>
            <div
              className="sb-actions full"
              aria-label="Vista previa del semáforo"
            >
              <Pill kind="bad">Rojo · 0–{score.redMax}</Pill>
              <Pill kind="warn">
                Amarillo · &gt;{score.redMax}–{score.yellowMax}
              </Pill>
              <Pill kind="ok">Verde · &gt;{score.yellowMax}–100</Pill>
            </div>
            <div className="full">
              <button className="action" type="submit">
                Guardar semáforo
              </button>
            </div>
          </fieldset>
        </form>
      </Card>
      <Card
        title="Estimación de profundidad"
        subtitle="El margen añade separación al espesor del producto para estimar su capacidad máxima en la góndola."
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            save('product', { dimensionMarginPct: Number(margin) });
          }}
        >
          <fieldset className="settings-fields" disabled={busy}>
            <label>
              Margen adicional de profundidad (%)
              <input
                required
                type="number"
                min="0"
                max="50"
                step="0.5"
                value={margin}
                onChange={(e) => setMargin(e.target.value)}
              />
            </label>
            <button type="submit" className="action">
              Guardar estimación
            </button>
          </fieldset>
        </form>
      </Card>
      <Card
        title="Objetivos por indicador"
        subtitle="Umbrales amarillo y verde según la dirección de mejora de cada indicador."
      >
        <form onSubmit={saveKpis}>
          <fieldset className="settings-fields" disabled={busy}>
            <div className="sb-table">
              <SortableTable>
                <thead>
                  <tr>
                    <th>Indicador</th>
                    <th>Mejora cuando</th>
                    <th>Amarillo</th>
                    <th>Verde</th>
                  </tr>
                </thead>
                <tbody>
                  {INDICATORS.map(([key, label, direction]) => (
                    <tr key={key}>
                      <td>{label}</td>
                      <td>{direction === 'lower' ? 'Disminuye' : 'Aumenta'}</td>
                      {['warn', 'good'].map((field) => (
                        <td key={field}>
                          <input
                            required
                            aria-label={`${label} ${field === 'warn' ? 'amarillo' : 'verde'}`}
                            type="number"
                            min="0"
                            max={direction === 'lower' ? undefined : 100}
                            step="1"
                            value={kpis[key][field]}
                            onChange={(e) =>
                              threshold(key, field, e.target.value)
                            }
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </SortableTable>
            </div>
            <button type="submit" className="action">
              Guardar objetivos
            </button>
          </fieldset>
        </form>
      </Card>
    </>
  );
}
