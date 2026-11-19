'use client';
import Img from '../common/Img';
import { useEffect, useState } from 'react';
import { api } from '../../lib/sb';
import { ErrorBox } from '../sb/ui';
import PdfPreview from './PdfPreview';

export default function ReferenceField({
  value,
  onChange,
  onBusy,
  pdf = false,
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [url, setUrl] = useState('');
  useEffect(() => {
    if (!value.document) {
      setUrl('');
      return;
    }
    const bytes = Uint8Array.from(atob(value.document.split(',')[1]), (c) =>
      c.charCodeAt(0),
    );
    const objectUrl = URL.createObjectURL(
      new Blob([bytes], { type: 'application/pdf' }),
    );
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [value.document]);

  async function choose(file) {
    if (!file) return;
    setBusy(true);
    onBusy(true);
    setError('');
    let bitmap;
    try {
      if (file.size > 5 * 1024 * 1024)
        throw Error('Usa un archivo de hasta 5 MB.');
      if (pdf && file.type === 'application/pdf') {
        const form = new FormData();
        form.append('file', file);
        onChange(
          await api('/api/admin/catalog/reference', { method: 'POST', form }),
        );
      } else {
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
          throw Error(
            pdf ? 'Usa JPG, PNG, WebP o PDF.' : 'Usa JPG, PNG o WebP.',
          );
        bitmap = await createImageBitmap(file);
        const ratio = Math.min(1, 1200 / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(bitmap.width * ratio));
        canvas.height = Math.max(1, Math.round(bitmap.height * ratio));
        canvas
          .getContext('2d')
          .drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        onChange({
          photo: canvas.toDataURL('image/jpeg', 0.8),
          document: '',
          document_name: '',
          document_page: 1,
          document_pages: 0,
          detected: null,
        });
      }
    } catch (e) {
      setError(e.message);
    } finally {
      bitmap?.close();
      setBusy(false);
      onBusy(false);
    }
  }
  const page = value.document_page || 1;
  const pages = value.document_pages || 1;
  return (
    <div className="full ct-reference">
      <label>
        {pdf ? 'Imagen o PDF del planograma' : 'Fotografía del producto'}
        <input
          type="file"
          disabled={busy}
          accept={
            pdf
              ? 'image/jpeg,image/png,image/webp,application/pdf'
              : 'image/jpeg,image/png,image/webp'
          }
          onChange={(e) => {
            choose(e.target.files[0]);
            e.target.value = '';
          }}
        />
      </label>
      <ErrorBox error={error} />
      {busy && <p role="status">Procesando archivo…</p>}
      {value.photo && (
        <Img src={value.photo} alt="Vista previa de referencia" />
      )}
      {url && (
        <>
          <div className="sb-actions">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => onChange({ document_page: page - 1 })}
            >
              Anterior
            </button>
            <span>
              Página {page} de {pages}
            </span>
            <button
              type="button"
              disabled={page >= pages}
              onClick={() => onChange({ document_page: page + 1 })}
            >
              Siguiente
            </button>
            <a href={url} download={value.document_name || 'planograma.pdf'}>
              Descargar PDF
            </a>
          </div>
          <PdfPreview document={value.document} page={page} />
        </>
      )}
      {(value.photo || value.document) && (
        <button
          type="button"
          onClick={() =>
            onChange({
              photo: '',
              document: '',
              document_name: '',
              document_page: 1,
              document_pages: 0,
              detected: null,
            })
          }
        >
          Quitar archivo
        </button>
      )}
    </div>
  );
}
