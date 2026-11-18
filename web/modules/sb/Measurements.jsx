"use client";
import SortableTable from '../tables/SortableTable';
import HomeReadingDetail from '../home/HomeReadingDetail';

import { useState } from "react";
import { api, download, fmt } from "../../lib/sb";
import {orderRegions} from '../../lib/locations.mjs';
import { can } from "../../lib/profiles.mjs";
import { useApi, Header, Card, Loading, Empty, ErrorBox, Pill } from "./ui";

const INITIAL = { region: "", commune: "", store: "", from: "", to: "", status: "" };

export default function Measurements({ user, go }) {
  const [filters, setFilters] = useState(INITIAL);
  const [sort, setSort] = useState(null);
  const sortFields = ["id","store_name","date","time","score","status","note","captured_by"];
  const [offset, setOffset] = useState(0);
  const [selectedReading,setSelectedReading] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const invalid = filters.from && filters.to && filters.from > filters.to;
  const query = new URLSearchParams(
    Object.entries({...filters, ...(sort ? {sort:sortFields[sort.column], direction:sort.direction} : {})}).filter(([, value]) => value),
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
      ...(name === "region" ? {commune:"",store:""} : name === "commune" ? {store:""} : {}),
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
        <label>Región<select value={filters.region} onChange={e=>change('region',e.target.value)}><option value="">Todas las regiones</option>{orderRegions([...new Set((data?.stores || []).map(s=>s.region).filter(Boolean))].map(name=>({name}))).map(r=><option key={r.name}>{r.name}</option>)}</select></label>
        <label>Comuna<select value={filters.commune} disabled={!filters.region} onChange={e=>change('commune',e.target.value)}><option value="">Todas las comunas</option>{[...new Set((data?.stores || []).filter(s=>s.region===filters.region).map(s=>s.commune).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'es')).map(name=><option key={name}>{name}</option>)}</select></label>
        <label>
          Punto de venta
          <select
            value={filters.store}
            onChange={(e) => change("store", e.target.value)}
          >
            <option value="">Todos los PDV</option>
            {(data?.stores || []).filter(s=>(!filters.region||s.region===filters.region)&&(!filters.commune||s.commune===filters.commune)).map((s) => (
              <option key={s.code} value={s.code}>
                {s.code} · {s.name}
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
                <SortableTable sort={sort} serverSort onSort={next=>{setSort(next);setOffset(0);}}>
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
                            onClick={() => setSelectedReading(row)}
                          >
                            Ver medición
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </SortableTable>
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
      {selectedReading && <HomeReadingDetail row={selectedReading} user={user} go={go} onClose={()=>{setSelectedReading(null);reload();}}/>}
    </section>
  );
}
