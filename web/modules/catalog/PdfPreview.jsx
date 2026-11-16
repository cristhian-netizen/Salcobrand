'use client';
import { useEffect, useRef, useState } from 'react';
import { ErrorBox } from '../sb/ui';

export default function PdfPreview({ document, page }) {
  const canvas = useRef(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let disposed = false;
    let task;
    let rendering;
    setLoading(true);
    setError('');
    async function draw() {
      try {
        const library = await import(
          /* webpackIgnore: true */ '/vendor/pdfjs/build/pdf.min.mjs'
        );
        if (disposed) return;
        library.GlobalWorkerOptions.workerSrc =
          '/vendor/pdfjs/build/pdf.worker.min.mjs';
        const bytes = Uint8Array.from(
          atob(document.split(',')[1]),
          (character) => character.charCodeAt(0),
        );
        task = library.getDocument({
          data: bytes,
          isEvalSupported: false,
          cMapUrl: '/vendor/pdfjs/cmaps/',
          cMapPacked: true,
          standardFontDataUrl: '/vendor/pdfjs/standard_fonts/',
          wasmUrl: '/vendor/pdfjs/wasm/',
        });
        const pdf = await task.promise;
        if (disposed) return;
        const selected = await pdf.getPage(page);
        if (disposed) return;
        const original = selected.getViewport({ scale: 1 });
        const viewport = selected.getViewport({
          scale: Math.min(1.6, 1000 / original.width),
        });
        canvas.current.width = Math.ceil(viewport.width);
        canvas.current.height = Math.ceil(viewport.height);
        rendering = selected.render({
          canvasContext: canvas.current.getContext('2d'),
          viewport,
        });
        await rendering.promise;
        if (!disposed) {
          canvas.current.dataset.renderedPage = String(page);
          setLoading(false);
        }
      } catch (exception) {
        if (!disposed) {
          setError(
            'No se pudo mostrar esta página. Puedes descargar el PDF para revisarlo.',
          );
          setLoading(false);
        }
      }
    }
    draw();
    return () => {
      disposed = true;
      rendering?.cancel();
      task?.destroy();
    };
  }, [document, page]);

  return (
    <div className="ct-pdf-preview">
      {loading && <p role="status">Cargando página…</p>}
      <ErrorBox error={error} />
      <canvas
        key={page}
        ref={canvas}
        aria-label={'Referencia del planograma, página ' + page}
      />
    </div>
  );
}
