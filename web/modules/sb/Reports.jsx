"use client";
import SortableTable from '../tables/SortableTable';

import { useState } from "react";
import { api, download, fmt } from "../../lib/sb";
import { profileOf } from '../../lib/profiles.mjs';
import Icon from "../navigation/icons";
import {
  useApi,
  Header,
  Card,
  ErrorBox,
  Metric,
  Loading,
  Empty,
  Pill,
} from "./ui";

const INITIAL = { store: "", from: "", to: "", status: "" };
const STATUSES = ["En revisión", "Aprobado", "Rechazado"];

export default function Reports({ user, go }) {
  const [sort,setSort] = useState(null);
  const sortFields=["id","store_id","store_name","region","commune","date","time","score","status","note","performance","captured_by","manager"];
  const [filters, setFilters] = useState(INITIAL);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const invalid = filters.from && filters.to && filters.from > filters.to;
  const query = new URLSearchParams(
    Object.entries({...filters,...(sort?{sort:sortFields[sort.column],direction:sort.direction}:{})}).filter(([, value]) => value),
  ).toString();
  const {
    data,
    error: loadError,
    loading,
    reload,
  } = useApi(async () => {
    if (invalid) return null;
    return { ...(await api("/api/reports/measurements?" + query)), query };
  }, [query, invalid]);
  const current = data?.query === query ? data : null;
  const totals = current?.totals;
  const rows = current?.rows || [];
  function change(key, value) {
    setFilters((previous) => ({ ...previous, [key]: value }));
    setError("");
  }
  async function exportFile(extension) {
    setBusy(true);
    setError("");
    try {
      await download(
        "/api/reports/measurements." + extension + "?" + query,
        "Salcobrand_Mediciones." + extension,
      );
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }
  async function exportCatalog(kind) {
    setBusy(true);
    setError('');
    try {
      await download('/api/reports/catalog/' + kind + '.xlsx', kind === 'products' ? 'Salcobrand_Productos.xlsx' : 'Salcobrand_PDV.xlsx');
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <Header
        eyebrow="Análisis"
        title="Reportes y exportaciones"
        subtitle="Historial de mediciones por PDV, con fecha y hora separadas. Los indicadores de desempeño consideran únicamente mediciones aprobadas."
      >
        <button
          type="button"
          className="action"
          disabled={busy || loading || invalid || !current}
          onClick={() => exportFile("xlsx")}
        >
          <Icon name="download" size={16} />
          {busy ? "Preparando descarga…" : "Descargar Excel"}
        </button>
      </Header>
      <div className="sb-toolbar" aria-label="Filtros de reportes">
        <label>
          Punto de venta
          <select
            value={filters.store}
            onChange={(e) => change("store", e.target.value)}
          >
            <option value="">Todos los PDV</option>
            {(data?.stores || []).map((store) => (
              <option key={store.code} value={store.code}>
                {store.code} · {store.name}
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
            {STATUSES.map((status) => (
              <option key={status}>{status}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setFilters(INITIAL);
            setError("");
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
      {loading || (!current && !invalid && !loadError) ? (
        <Loading text="Cargando mediciones…" />
      ) : (
        current && (
          <>
            <div className="sb-metrics">
              <Metric
                label="Mediciones registradas"
                value={fmt.num(totals.measurements)}
                hint="Todos los estados del filtro"
              />
              <Metric
                label="Mediciones aprobadas"
                value={fmt.num(totals.approved)}
                hint="Incluidas en desempeño"
              />
              <Metric
                label="Puntaje promedio aprobado"
                value={fmt.num(totals.average_score)}
                kind={totals.average_score_band}
                hint="Escala de 0 a 100"
              />
              <Metric
                label="En revisión / rechazadas"
                value={`${totals.in_review} / ${totals.rejected}`}
                hint="Excluidas del desempeño"
              />
            </div>
            <Card
              title="Mediciones"
              body={false}
              subtitle={`Vista previa de ${rows.length} de ${totals.measurements}. La descarga incluye todas las coincidencias. Horario de Chile continental.${rows.length ? ' Desplaza la tabla horizontalmente para ver todas las columnas.' : ''}`}
            >
              {rows.length ? (
                <div className="sb-table reports-table" role="region" aria-label="Tabla de reportes de mediciones" tabIndex={0}>
                  <SortableTable sort={sort} serverSort onSort={setSort}>
                    <thead>
                      <tr>
                        {[
                          "ID",
                          "PDV",
                          "Nombre PDV",
                          "Región",
                          "Comuna",
                          "Fecha",
                          "Hora",
                          "Puntaje",
                          "Estado",
                          "Observación",
                          "Considerar en desempeño",
                          "Medición hecha por",
                          "Encargado de Local",
                        ].map((label) => (
                          <th key={label}>{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.id}>
                          <td>
                            <button
                              type="button"
                              className="link"
                              onClick={() =>
                                go(
                                  `gondolas/${encodeURIComponent(row.point_id)}/lectura/${row.id}`,
                                )
                              }
                            >
                              #{row.id}
                            </button>
                          </td>
                          <td>{row.store_id || "—"}</td>
                          <td>{row.store_name}</td>
                          <td>{row.region || "—"}</td>
                          <td>{row.commune || "—"}</td>
                          <td>{row.date}</td>
                          <td style={{ whiteSpace: "nowrap" }}>{row.time}</td>
                          <td className="sb-num"><Pill kind={row.score_band}>{fmt.num(row.score)}</Pill></td>
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
                          <td>{row.performance}</td>
                          <td>{row.captured_by}</td>
                          <td>{row.manager || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </SortableTable>
                </div>
              ) : (
                <Empty>No hay mediciones para los filtros seleccionados.</Empty>
              )}
            </Card>
          </>
        )
      )}
      {profileOf(user) === 'viewer' && <Card title="Reportes de catálogos" subtitle="Descarga todos los productos o puntos de venta sin acceder a su administración.">
        <div className="sb-actions">
          <button type="button" disabled={busy} onClick={() => exportCatalog('products')}>Productos · Excel</button>
          <button type="button" disabled={busy} onClick={() => exportCatalog('stores')}>Puntos de venta · Excel</button>
        </div>
      </Card>}
    </section>
  );
}
