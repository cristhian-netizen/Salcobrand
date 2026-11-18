import SortableTable from '../tables/SortableTable';
import { Card } from '../sb/ui';

function monthLabel(month) {
  return new Intl.DateTimeFormat('es-CL', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(month + '-01T12:00:00Z'));
}

export default function NetworkCalendar({ data, filters, onSelect }) {
  const stores = data.options.filter(store => (!filters.region || store.region === filters.region)
    && (!filters.commune || store.commune === filters.commune) && (!filters.pdv_type || store.pdv_type === filters.pdv_type));
  return <>
    <Card title="Red de puntos de venta">
      <p className="sb-hint">Mapa pendiente de proveedor cartográfico. Selecciona un PDV para filtrar sus resultados.</p>
      <div className="dashboard-network" aria-label="Seleccionar PDV de la red">
        {stores.map(store => <button type="button" key={store.code} aria-pressed={filters.store === store.code} onClick={() => onSelect(store.code)}>
          {store.name}<small>{[store.region, store.commune].filter(Boolean).join(' · ') || store.code}</small>
        </button>)}
        {!stores.length && <p>No hay PDV para los filtros seleccionados.</p>}
      </div>
    </Card>
    <Card title="Mediciones por día" subtitle="Mediciones aprobadas según los filtros seleccionados." body={false}>
      <div className="sb-table" tabIndex={0} role="region" aria-label="Mediciones por día: tabla con desplazamiento horizontal"><SortableTable className="dashboard-calendar">
        <thead><tr><th>Mes</th>{Array.from({ length: 31 }, (_, index) => <th key={index}>{index + 1}</th>)}</tr></thead>
        <tbody>{data.calendar.map(month => <tr key={month.month}>
          <th data-sort-value={month.month}>{monthLabel(month.month)}</th>{month.days.map((count, index) => <td key={index}
            className={count === null ? 'invalid' : count < 0 ? 'outside' : count > 0 ? 'measured' : ''}
            title={`${month.month}-${String(index + 1).padStart(2, '0')} · ${count === null ? 'fecha inexistente' : count < 0 ? 'fuera del rango' : `${count} mediciones aprobadas`}`}>
            {count === null ? '' : count < 0 ? '—' : count}
          </td>)}
        </tr>)}</tbody>
      </SortableTable></div>
      <p className="dashboard-legend">0 = sin mediciones · — = fuera del rango seleccionado · celda gris = fecha inexistente.</p>
    </Card>
  </>;
}
