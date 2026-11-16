'use client';
import { useState } from 'react';
import { api, download } from '../../lib/sb';
import { ErrorBox } from '../sb/ui';
import DashboardTable from '../dashboard/DashboardTable';

export default function StoreExcel({ onSaved, onClose, endpoint = '/api/admin/store-transfer', templatePath = '/api/admin/store-transfer/workbook.xlsx?template=true', templateName = 'Plantilla_PDV.xlsx', columns = [
  ['code','Código PDV'],['name','Nombre local'],['store_type','Tipo PDV'],['region','Región'],['commune','Comuna'],['manager','Encargado de Local'],['action','Acción'],
], children }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function transfer(chosen, commit = false) {
    if (!chosen) return;
    setBusy(true);
    setError('');
    if (!commit) setPreview(null);
    try {
      if (!chosen.name.toLowerCase().endsWith('.xlsx') || chosen.size > 5 * 1024 * 1024) throw Error('Usa un archivo .xlsx de hasta 5 MB.');
      const form = new FormData();
      form.append('file', chosen);
      form.append('commit', String(commit));
      if (commit) form.append('version', preview.version);
      const result = await api(endpoint + '/import', { method: 'POST', form, timeout: 120000 });
      if (commit) onSaved(result);
      else setPreview(result);
    } catch (exception) {
      setError(exception.message);
      if (commit) setPreview(null);
    } finally { setBusy(false); }
  }
  async function template() {
    setBusy(true);
    setError('');
    try { await download(templatePath, templateName); }
    catch (exception) { setError(exception.message); }
    finally { setBusy(false); }
  }
  return <div>
    {children || <p>El código identifica al PDV. El encargado se ingresa como texto libre. Se procesa la hoja PDV y las asignaciones de góndolas se gestionan desde la ficha del punto de venta.</p>}
    <p className="sb-hint">Máximo 5 MB y 5.000 filas. Revisa la vista previa antes de confirmar.</p>
    <button type="button" disabled={busy} onClick={template}>Descargar plantilla</button>
    <label className="ct-upload">Importar archivo .xlsx<input type="file" accept=".xlsx" disabled={busy} onChange={event => {
      const chosen = event.target.files[0];
      setFile(chosen || null);
      setPreview(null);
      setError('');
      if (chosen) transfer(chosen);
      event.target.value = '';
    }} /></label>
    <ErrorBox error={error} />
    {busy && <p role="status">Procesando Excel…</p>}
    {preview && <>
      <p role="status">{preview.creates} nuevos · {preview.updates} actualizaciones · {preview.errors.length} errores</p>
      {!preview.errors.length && <p className="sb-hint">Vista previa de {preview.sample.length} de {preview.creates + preview.updates} filas válidas.</p>}
      {preview.errors.length ? <DashboardTable rows={preview.errors} columns={[
        ['sheet','Hoja'],['row','Fila'],['message','Error'],
      ]} /> : <DashboardTable rows={preview.sample} columns={columns} />}
    </>}
    <div className="sb-actions store-transfer-actions">
      <button type="button" className="action" disabled={busy || !preview || preview.errors.length > 0} onClick={() => transfer(file, true)}>Confirmar importación</button>
      {file && <button type="button" disabled={busy} onClick={() => transfer(file)}>Volver a validar</button>}
      <button type="button" disabled={busy} onClick={onClose}>Cancelar</button>
    </div>
  </div>;
}
