"use client";
import { useState } from "react";
import { api, download, fmt } from "../../lib/sb";
import { can } from "../../lib/profiles.mjs";
import { useApi, Header, Card, Loading, Empty, ErrorBox, Pill } from "./ui";

const INITIAL = { store: "", point: "", from: "", to: "", status: "" };

export default function Measurements({ user, go }) {
  const [filters, setFilters] = useState(INITIAL);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const invalid = filters.from && filters.to && filters.from > filters.to;
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value),
  ).toString();
  const key = query + "&offset=" + offset;
  const {
    data,
    loading,
    error: loadError,
    reload,
  } = useApi(
    async () =>
      invalid ? null : { ...(await api("/api/measurements?" + key)), key },
    [key, invalid],
  );
  const current = data?.key === key ? data : null;
  function change(name, value) {
    setFilters((previous) => ({
      ...previous,
      [name]: value,
      ...(name === "store" ? { point: "" } : {}),
    }));
    setOffset(0);
  }
  async function exportFile() {
    setBusy(true);
    setError("");
    try {
      await download(
        "/api/reports/measurements.xlsx?" + query,
        "Neuravision_Mediciones.xlsx",
      );
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <Header
        eyebrow="Operación"
        title="Mediciones"
        subtitle="Consulta las capturas, su evidencia y las observaciones del analista."
      >
        {can(user, "scan") && (
          <button
            type="button"
            className="action"
            onClick={() => go("escanear")}
          >
            Nueva medición
          </button>
        )}
        {can(user, "report") && (
          <button
            type="button"
            disabled={busy || !current || invalid}
            onClick={exportFile}
          >
            Descargar Excel
          </button>
        )}
      </Header>
      <div className="sb-toolbar" aria-label="Filtros de mediciones">
        <label>
          Punto de venta
          <select
            value={filters.store}
            onChange={(e) => change("store", e.target.value)}
          >
            <option value="">Todos los PDV</option>
            {(data?.stores || []).map((s) => (
              <option key={s.code} value={s.code}>
                {s.code} · {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Góndola
          <select
            value={filters.point}
            onChange={(e) => change("point", e.target.value)}
          >
            <option value="">Todas las góndolas</option>
            {(data?.points || [])
              .filter((p) => !filters.store || p.store_id === filters.store)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Desde
          <input
            type="date"
            value={filters.from}
            onChange={(e) => change("from", e.target.value)}
          />
        </label>
        <label>
          Hasta
          <input
            type="date"
            value={filters.to}
            onChange={(e) => change("to", e.target.value)}
          />
        </label>
        <label>
          Estado
          <select
            value={filters.status}
            onChange={(e) => change("status", e.target.value)}
          >
            <option value="">Todos los estados</option>
            {["En revisión", "Aprobado", "Rechazado"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setFilters(INITIAL);
            setOffset(0);
          }}
        >
          Limpiar filtros
        </button>
      </div>
      <ErrorBox
        error={
          invalid
            ? "La fecha Desde debe ser anterior o igual a Hasta."
            : error || loadError
        }
        onRetry={invalid ? undefined : reload}
      />
      {loading && !current ? (
        <Loading text="Cargando mediciones…" />
      ) : (
        current && (
          <Card body={false} title={`${current.count} mediciones`}>
            {current.rows.length ? (
              <div className="sb-table">
                <table>
                  <thead>
                    <tr>
                      <th>Lectura</th>
                      <th>PDV</th>
                      <th>Fecha</th>
                      <th>Hora</th>
                      <th>Puntaje</th>
                      <th>Estado</th>
                      <th>Observación</th>
                      <th>Medición hecha por</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {current.rows.map((row) => (
                      <tr key={row.id}>
                        <td>
                          <b>#{row.id}</b>
                        </td>
                        <td>
                          {row.store_name}
                          <small>{row.store_id}</small>
                        </td>
                        <td style={{ whiteSpace: "nowrap" }}>{row.date}</td>
                        <td style={{ whiteSpace: "nowrap" }}>{row.time}</td>
                        <td><Pill kind={row.score_band}>{fmt.num(row.score)}</Pill></td>
                        <td>
                          <Pill
                            kind={
                              row.status === "Aprobado"
                                ? "ok"
                                : row.status === "Rechazado"
                                  ? "bad"
                                  : "warn"
                            }
                          >
                            {row.status}
                          </Pill>
                        </td>
                        <td>{row.note || "—"}</td>
                        <td>{row.captured_by}</td>
                        <td>
                          <button
                            type="button"
                            onClick={() =>
                              go(
                                `gondolas/${encodeURIComponent(row.point_id)}/lectura/${row.id}`,
                              )
                            }
                          >
                            Ver medición
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>No hay mediciones para estos filtros.</Empty>
            )}
            <div className="sb-card-body sb-actions">
              <span>
                {current.count ? offset + 1 : 0}–{offset + current.rows.length}{" "}
                de {current.count}
              </span>
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((value) => Math.max(0, value - 50))}
              >
                Anterior
              </button>
              <button
                type="button"
                disabled={offset + current.rows.length >= current.count}
                onClick={() => setOffset((value) => value + 50)}
              >
                Siguiente
              </button>
            </div>
          </Card>
        )
      )}
    </section>
  );
}
