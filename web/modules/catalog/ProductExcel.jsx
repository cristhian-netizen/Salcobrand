'use client';
import { useState } from 'react';
import { api, download } from '../../lib/sb';
import { Card, ErrorBox } from '../sb/ui';

export default function ProductExcel({ onSaved }) {
  const [preview, setPreview] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function transfer(chosen, commit = false) {
    if (!chosen) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      if (
        !chosen.name.toLowerCase().endsWith('.xlsx') ||
        chosen.size > 5 * 1024 * 1024
      )
        throw Error('Usa un archivo .xlsx de hasta 5 MB.');
      const form = new FormData();
      form.append('file', chosen);
      form.append('commit', String(commit));
      if (commit) form.append('version', String(preview.version));
      const result = await api('/api/admin/catalog/products/import', {
        method: 'POST',
        form,
        timeout: 120000,
      });
      if (commit) {
        setPreview(null);
        setFile(null);
        onSaved();
        setNotice(
          `${result.creates} productos creados y ${result.updates} actualizados.`,
        );
      } else {
        setPreview(result);
        setFile(chosen);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function exportFile(template) {
    setBusy(true);
    setError('');
    try {
      await download(
        '/api/admin/catalog/products.xlsx?template=' + template,
        template ? 'Plantilla_Productos.xlsx' : 'Productos.xlsx',
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="Excel de productos">
      <p>
        Revisa la vista previa antes de confirmar la importación. Las
        fotografías se cargan en el producto.
      </p>
      <div className="sb-actions">
        <button disabled={busy} onClick={() => exportFile(true)}>
          Descargar plantilla
        </button>
        <button disabled={busy} onClick={() => exportFile(false)}>
          Exportar Excel
        </button>
      </div>
      <label className="ct-upload">
        Importar archivo .xlsx
        <input
          type="file"
          accept=".xlsx"
          disabled={busy}
          onChange={(e) => {
            setPreview(null);
            setFile(null);
            transfer(e.target.files[0]);
            e.target.value = '';
          }}
        />
      </label>
      <ErrorBox error={error} />
      {busy && <p role="status">Procesando Excel…</p>}
      {notice && (
        <p className="sb-ok" role="status">
          {notice}
        </p>
      )}
      {preview && (
        <>
          <p>
            {preview.creates} nuevos · {preview.updates} actualizaciones ·{' '}
            {preview.errors.length} errores
          </p>
          {preview.errors.length ? (
            <ul>
              {preview.errors.slice(0, 30).map((e) => (
                <li key={e.row}>
                  Fila {e.row} · {e.message}
                </li>
              ))}
            </ul>
          ) : (
            <>
              <div className="sb-table">
                <table>
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Producto</th>
                      <th>Acción</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample.map((p) => (
                      <tr key={p.sku}>
                        <td>{p.sku}</td>
                        <td>{p.name}</td>
                        <td>{p.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                className="action"
                disabled={busy}
                onClick={() => transfer(file, true)}
              >
                Confirmar importación
              </button>
            </>
          )}
        </>
      )}
    </Card>
  );
}
