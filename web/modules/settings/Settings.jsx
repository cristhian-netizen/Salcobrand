'use client';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/sb';
import { useApi, Header, Loading, ErrorBox } from '../sb/ui';
import CatalogSettings from './CatalogSettings';
import PdvTypesSettings from './PdvTypesSettings';
import AnalysisSettings from './AnalysisSettings';
import AlertSettings from './AlertSettings';
import ClassificationTransfer from './ClassificationTransfer';

export default function Settings({ notify, rest=[] }) {
  const { data, error, loading, setData } = useApi(
    () => api('/api/admin/settings'),
    [],
  );
  const [tab, setTab] = useState(rest[0] === 'alertas' ? 'alerts' : 'catalogs');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [failure, setFailure] = useState('');
  const [revision, setRevision] = useState(0);
  const alert = useRef(null);
  useEffect(() => {
    if (failure) {
      alert.current?.focus();
      alert.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [failure]);
  async function refresh() {
    setBusy(true);
    setFailure('');
    setMessage('');
    try {
      setData(await api('/api/admin/settings'));
      setRevision((value) => value + 1);
    } catch (exception) {
      setFailure(exception.message);
    } finally {
      setBusy(false);
    }
  }
  async function save(section, value) {
    setBusy(true);
    setFailure('');
    setMessage('');
    try {
      const result = await api('/api/admin/settings/' + section, {
        method: 'PATCH',
        body: { version: data.version, value },
      });
      setData({ ...data, ...result });
      setMessage('Configuración guardada.');
      notify?.('Configuración guardada.');
      return result.state;
    } catch (exception) {
      setFailure(exception.message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <Header
        eyebrow="Administración"
        title="Configuración"
        subtitle="Catálogos de la operación y parámetros de análisis."
      >
        <button type="button" disabled={busy} onClick={refresh}>
          Recargar valores guardados
        </button>
      </Header>
      <div ref={alert} tabIndex={-1}>
        <ErrorBox error={failure || error} onRetry={refresh} />
      </div>
      {message && (
        <p className="sb-hint" role="status">
          {message}
        </p>
      )}
      <div
        className="sb-tabs"
        role="group"
        aria-label="Secciones de configuración"
      >
        <button
          type="button"
          aria-pressed={tab === 'catalogs'}
          onClick={() => setTab('catalogs')}
        >
          Catálogos
        </button>
        <button
          type="button"
          aria-pressed={tab === 'analysis'}
          onClick={() => setTab('analysis')}
        >
          Parámetros de análisis
        </button>
        <button type="button" aria-pressed={tab === 'alerts'} onClick={()=>setTab('alerts')}>Alertas administrativas</button>
      </div>
      {loading && !data ? (
        <Loading text="Cargando configuración…" />
      ) : (
        data && (
          <div key={revision}>
            <div style={{ display: tab === 'catalogs' ? 'block' : 'none' }}>
              <PdvTypesSettings state={data.state} busy={busy} save={save} />
              <CatalogSettings
                state={data.state}
                products={data.products}
                busy={busy}
                save={save}
                onError={setFailure}
              />
              <ClassificationTransfer onSaved={refresh} notify={notify}/>
            </div>
            <div style={{ display: tab === 'alerts' ? 'block' : 'none' }}><AlertSettings state={data.state} busy={busy} save={save}/></div>
            <div style={{ display: tab === 'analysis'  ? 'block' : 'none' }}>
              <AnalysisSettings state={data.state} busy={busy} save={save} />
            </div>
          </div>
        )
      )}
    </section>
  );
}
