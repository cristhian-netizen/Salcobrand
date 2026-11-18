'use client';
import {useState} from 'react';
import {Card} from '../sb/ui';
export default function AlertSettings({state, busy, save}) {
  const [value,setValue] = useState(state.alertParameters || {reviewDays:7,noMeasurementDays:7});
  return <Card title="Plazos de alertas administrativas" subtitle="Se consideran PDV activos. Las alertas aparecen al superar el plazo configurado."><form onSubmit={event=>{event.preventDefault();save('alerts',Object.fromEntries(Object.entries(value).map(([key,value])=>[key,Number(value)])));}}><fieldset className="settings-fields sb-form" disabled={busy}>{[['reviewDays','Mediciones sin revisar (días)'],['noMeasurementDays','PDV sin mediciones (días)']].map(([key,label])=><label key={key}>{label}<input type="number" required min="1" max="365" step="1" value={value[key]} onChange={event=>setValue({...value,[key]:event.target.value})}/></label>)}<button type="submit" className="action">Guardar plazos de alertas</button></fieldset></form></Card>;
}
