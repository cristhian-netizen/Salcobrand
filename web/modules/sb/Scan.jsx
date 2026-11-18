"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/sb";
import Icon from "../navigation/icons";
import ShelfPhoto from "../management/ShelfPhoto";
import {orderRegions} from "../../lib/locations.mjs";
import { useApi, Header, Card, ErrorBox, Loading } from "./ui";
import ReadingView from "./ReadingView";
import CapturePlanograms from "./CapturePlanograms";
import CategorySelection from "../catalog/CategorySelection";
import {enabled} from '../identity/identity.mjs';
import {byLocationName, captureStores, filterCaptureStores, pointStoreCode, regionFor, capturePointForType} from './scan-locations.mjs';

const MAX_PHOTOS = 6;
const TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
];

const isHeic = (file) =>
  ["image/heic", "image/heif"].includes(file.type) ||
  /\.hei[cf]$/i.test(file.name);

function newRequestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return [...crypto.getRandomValues(new Uint8Array(16))]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function prepare(file) {
  if (
    (!TYPES.includes(file.type) && !/\.hei[cf]$/i.test(file.name)) ||
    !file.size
  )
    throw Error("Usa fotos JPG, PNG, WebP o HEIC válidas.");
  if (file.size > 25 * 1024 * 1024)
    throw Error("Cada foto admite hasta 25 MB.");
  if (isHeic(file)) return file;
  let bitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, 3000 / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size < 1.5 * 1024 * 1024) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas
      .getContext("2d")
      .drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.85),
    );
    if (!blob) throw Error("No se pudo preparar la fotografía.");
    return new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", {
      type: "image/jpeg",
    });
  } catch {
    throw Error(
      "No se pudo abrir " +
        file.name +
        ". Revisa el archivo antes de cargarlo.",
    );
  } finally {
    bitmap?.close();
  }
}

function remember(key, jobId) {
  try {
    if (jobId) localStorage.setItem(key, jobId);
    else localStorage.removeItem(key);
  } catch {}
}

export default function Scan({ user, rest, go, notify }) {
  const points = useApi(async () => {
    const [summary, stores, locations, captureOptions] = await Promise.all([
      api('/api/summary?days=30'), api('/api/stores'), api('/api/location-catalog'), api('/api/capture/options'),
    ]);
    return {...summary, captureStores: stores, regions: locations.regions, captureOptions};
  }, []);
  const availability = useApi(() => api("/api/capture/status"), []);
  const [pointId, setPointId] = useState(rest[0] || "");
  const [location, setLocation] = useState({region: '', commune: '', query: ''});
  const [storeCode, setStoreCode] = useState('');
  const [reference,setReference]=useState({query:'',id:'',loading:false,error:''});
  const [classification, setClassification] = useState({category: '', subcategories: []});
  const [shelfType, setShelfType] = useState('');
  const [manualOverride, setManualOverride] = useState(false);
  const [manualDepths, setManualDepths] = useState(['']);
  const [photos, setPhotos] = useState([]);
  const [meters, setMeters] = useState("");
  const [preparing, setPreparing] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState(null);
  const [jobId, setJobId] = useState("");
  const [pollVersion, setPollVersion] = useState(0);
  const [recovering, setRecovering] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);
  const requestId = useRef(null);
  const urls = useRef(new Set());
  const preparingRef = useRef(false);
  const mounted = useRef(true);
  const storageKey = "nv-capture-job:" + user.username;
  const active = job && ["queued", "running"].includes(job.status);
  const busy = uploading || active || restoring;
  const list = useMemo(() => (points.data?.points || []).filter(
    (p) => p.can_capture !== false,
  ), [points.data]);
  const regions = points.data?.regions || [];
  const stores = useMemo(() => captureStores(points.data?.captureStores || [], list), [points.data, list]);
  const visibleStores = useMemo(() => filterCaptureStores(stores, regions, location), [stores, regions, location]);
  const currentPoint = points.data?.points.find(point => point.id === pointId);
  const selectedStore = busy && currentPoint ? pointStoreCode(currentPoint) : storeCode;
  const storePoints = visibleStores.some(store => store.code === selectedStore)
    ? list.filter(point => pointStoreCode(point) === selectedStore) : [];
  const types = (points.data?.captureOptions.types || []).filter(type => type.store_code === selectedStore).sort(byLocationName);
  const hasAssigned = !points.data?.captureOptions.manual_stores.includes(selectedStore);
  const manualMode = !hasAssigned || manualOverride;
  const selectedType = shelfType;
  const selectedShelf = types.find(type => type.id === selectedType);
  const resolution = capturePointForType(storePoints, selectedType, classification, enabled(user, 'planograms')&&!points.data?.captureOptions.shared_plan_assignments);
  const selected = manualMode ? null : resolution.point;
  const categories = points.data?.captureOptions.categories || {};
  const referencePoint = selected || (manualOverride ? resolution.point : null);
  const planClassification = enabled(user, 'planograms')&&!points.data?.captureOptions.shared_plan_assignments ? referencePoint?.planogram_classification : null;
  const captureClassification = planClassification?.category ? planClassification : classification;
  const subcategories = categories[classification.category] || [];
  const classificationReady = (!Object.keys(categories).length || classification.category)
    && (!subcategories.length || classification.subcategories.length);
  const displayedMeters = manualMode ? meters : selectedShelf ? String(selectedShelf.width_cm / 100) : '';
  const manualReady = manualDepths.length > 0 && manualDepths.every(value => value !== '' && Number(value) > 0 && Number(value) <= 1000);
  const captureReady = classificationReady && (manualMode ? selectedStore && manualReady : selected && selectedShelf) && !reference.loading && !reference.error;
  const communes = [...(regionFor(regions, location.region)?.communes || [])].sort(byLocationName);

  useEffect(() => {
    if (!points.data || busy || result || job?.status === 'done') return;
    const preferredStore = storeCode || (currentPoint && pointStoreCode(currentPoint));
    const nextStore = visibleStores.find(store => store.code === preferredStore)?.code || visibleStores[0]?.code || '';
    if (nextStore !== storeCode) { setStoreCode(nextStore); setShelfType(''); setMeters(''); setManualOverride(false); setManualDepths(['']); }
    const storePoints = list.filter(point => pointStoreCode(point) === nextStore);
    if (pointId && !storePoints.some(point => point.id === pointId)) {
      setPointId('');
      requestId.current = null;
    }
  }, [points.data, busy, result, job?.status, visibleStores, list, storeCode, pointId, currentPoint]);

  useEffect(() => {
    if (busy || result) return;
    const nextPoint = selected?.id || '';
    if (nextPoint !== pointId) {setPointId(nextPoint);requestId.current = null;}
  }, [selected?.id, busy, result, pointId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      urls.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);
  useEffect(() => {
    let disposed = false;
    async function restore() {
      let saved;
      let pendingRequest;
      try {
        saved = localStorage.getItem(storageKey);
        pendingRequest = localStorage.getItem(storageKey + ":request");
      } catch {}
      requestId.current = pendingRequest;
      try {
        const prior = saved
          ? await api("/api/analysis-jobs/" + encodeURIComponent(saved))
          : pendingRequest
            ? await api(
                "/api/analysis-requests/" + encodeURIComponent(pendingRequest),
              )
            : (await api("/api/analysis-jobs"))[0];
        if (!disposed && prior) {
          setLocation({region: '', commune: '', query: ''});
          setStoreCode('');
          setJob(prior);
          setJobId(prior.job_id);
          setPointId(prior.point_id);
          remember(storageKey, prior.job_id);
        }
      } catch (exception) {
        if (!disposed && [404, 410].includes(exception.status))
          remember(storageKey, null);
        else if (!disposed) setError(exception.message);
      } finally {
        if (!disposed) setRestoring(false);
      }
    }
    restore();
    return () => {
      disposed = true;
    };
  }, [storageKey]);

  useEffect(() => {
    if (!jobId) return;
    let disposed = false;
    let timer;
    async function poll() {
      try {
        const current = await api(
          "/api/analysis-jobs/" + encodeURIComponent(jobId),
        );
        if (disposed) return;
        setJob(current);
        setPointId(current.point_id);
        setError("");
        if (current.status === "done") {
          if (!current.reading?.id) {
            setError("La solicitud terminó sin una medición disponible.");
            return;
          }
          setResult(current.reading);
          for (const url of urls.current) URL.revokeObjectURL(url);
          urls.current.clear();
          setPhotos([]);
          return;
        }
        if (current.status === "failed") {
          setError(current.detail || "No se pudo completar la medición.");
          return;
        }
      } catch (exception) {
        if (disposed) return;
        setError(
          exception.message + " Se volverá a consultar la misma solicitud.",
        );
        if ([401, 403, 404, 410].includes(exception.status)) return;
      }
      timer = setTimeout(poll, 2000);
    }
    poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [jobId, pollVersion]);

  useEffect(() => {
    if (!active) return;
    const started = new Date(job.created_at).valueOf();
    const update = () =>
      setElapsed(Math.max(0, Math.round((Date.now() - started) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [job?.job_id, active]);

  async function addFiles(fileList) {
    if (preparingRef.current || busy || !fileList?.length) return;
    preparingRef.current = true;
    setPreparing(true);
    setError("");
    const files = [...fileList];
    try {
      if (files.length + photos.length > MAX_PHOTOS)
        throw Error(`Máximo ${MAX_PHOTOS} fotos por lectura.`);
      const prepared = await Promise.all(files.map(prepare));
      if (!mounted.current) return;
      if (
        [...prepared, ...photos.map((p) => p.file)].reduce(
          (sum, file) => sum + file.size,
          0,
        ) >
        100 * 1024 * 1024
      )
        throw Error("El conjunto de fotos admite hasta 100 MB.");
      const ready = prepared.map((file) => {
        const url = URL.createObjectURL(file);
        urls.current.add(url);
        return { file, url };
      });
      setPhotos((current) => [...current, ...ready]);
      if (photos.length) requestId.current = null;
    } catch (exception) {
      setError(exception.message);
    } finally {
      setPreparing(false);
      preparingRef.current = false;
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function move(index, offset) {
    requestId.current = null;
    setPhotos((current) => {
      const next = [...current];
      const target = index + offset;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function removePhoto(index) {
    requestId.current = null;
    const url = photos[index].url;
    URL.revokeObjectURL(url);
    urls.current.delete(url);
    setPhotos((current) => current.filter((_, i) => i !== index));
  }

  async function analyze() {
    if (uploading || active || preparing || !captureReady || !photos.length) return;
    const width = displayedMeters === "" ? null : Number(displayedMeters);
    if (
      width !== null &&
      (!Number.isFinite(width) || width <= 0 || width > 30)
    ) {
      setError("El ancho debe ser mayor a cero y hasta 30 metros.");
      return;
    }
    setUploading(true);
    setError("");
    setResult(null);
    requestId.current ||= newRequestId();
    remember(storageKey + ":request", requestId.current);
    const form = new FormData();
    photos.forEach((p) => form.append("images", p.file, p.file.name));
    if (width !== null) form.append("linear_meters", String(width));
    if (manualMode) {
      form.append('manual_override', String(manualOverride));
      if (manualOverride && referencePoint) form.append('reference_point_id', referencePoint.id);
      form.append('levels', String(manualDepths.length));
      manualDepths.forEach(depth => form.append('depths', String(Number(depth))));
    } else form.append('by_type', 'true');
    if (captureClassification.category) form.append('category', captureClassification.category);
    for (const subcategory of captureClassification.subcategories) form.append('subcategories', subcategory);
    const referenceParams=new URLSearchParams({store:selectedStore,category:classification.category,type_id:selectedType||''});
    for(const sub of classification.subcategories||[])referenceParams.append('subcategories',sub);
    if(reference.query===referenceParams.toString()&&reference.id)form.append('reference_plan_id',reference.id);
    try {
      const current = await api(
        manualMode ? '/api/stores/' + encodeURIComponent(selectedStore) + '/analysis-jobs'
          : "/api/points/" + encodeURIComponent(selected.id) + "/analysis-jobs",
        {
          method: "POST",
          form,
          headers: { "Idempotency-Key": requestId.current },
          timeout: 120000,
        },
      );
      remember(storageKey, current.job_id);
      setJob(current);
      setPointId(current.point_id);
      setJobId(current.job_id);
      notify(
        "Captura recibida. Puedes recuperar esta solicitud al volver a Escanear.",
      );
    } catch (exception) {
      setError(exception.message);
    } finally {
      setUploading(false);
    }
  }

  async function recover() {
    setRecovering(true);
    setError("");
    try {
      const current = await api(
        "/api/analysis-jobs/" + encodeURIComponent(jobId) + "/resume",
        { method: "POST" },
      );
      setJob(current);
      setPointId(current.point_id);
      setLocation({region: '', commune: '', query: ''});
      setStoreCode('');
      setPollVersion((version) => version + 1);
    } catch (exception) {
      setError(exception.message);
    } finally {
      setRecovering(false);
    }
  }

  function another() {
    remember(storageKey, null);
    remember(storageKey + ":request", null);
    setJobId("");
    setJob(null);
    setResult(null);
    setError("");
    requestId.current = null;
  }

  if (result)
    return (
      <section>
        <Header
          eyebrow={selected?.name || pointId}
          title={`Lectura #${result.id}`}
          subtitle="Análisis terminado."
        >
          <button type="button" onClick={another}>
            <Icon name="scan" size={16} />
            Otra lectura
          </button>
          <button
            className="action"
            type="button"
            onClick={() => go("mediciones")}
          >
            Ver historial
          </button>
        </Header>
        <ReadingView
          reading={result}
          user={user}
          onDeleted={another}
          onConfirmGo={() => go("revision")}
        />
      </section>
    );

  return (
    <section>
      <Header
        eyebrow="Operación"
        title="Escanear góndola"
        subtitle="Carga las fotos de izquierda a derecha, con la góndola completa y nítida."
      />
      <ErrorBox error={error || points.error || availability.error} onRetry={() => {points.reload(); availability.reload();}} />
      {availability.data && !availability.data.available && (
        <ErrorBox
          error={
            availability.data.detail ||
            "El análisis no está disponible en este entorno."
          }
          onRetry={availability.reload}
        />
      )}
      {jobId && (
        <Card title="Solicitud de medición">
          <p className="sb-hint">{jobId}</p>
          {active && (
            <div className="sb-progress" role="status">
              <span className="nv-spinner" aria-hidden="true" />
              {job.status === "queued" ? "En cola" : "Analizando fotos"} ·{" "}
              {elapsed} s
            </div>
          )}
          {active && (
            <p className="sb-hint">
              El primer análisis puede tardar varios minutos mientras se inicia
              el motor. La solicitud se conserva al recargar.
            </p>
          )}
          {job?.status === "failed" && (
            <div className="sb-actions">
              {job.can_recover && (
                <button disabled={recovering} onClick={recover}>
                  {recovering ? "Recuperando…" : "Recuperar resultado"}
                </button>
              )}
              <button onClick={another}>Nueva captura</button>
            </div>
          )}
        </Card>
      )}
      <Card title="Góndola">
        {points.loading && !points.data ? (
          <Loading />
        ) : (
          <div className="sb-form scan-location-form">
            <label>
              Región
              <select value={location.region} disabled={busy} onChange={event => {
                setLocation({...location, region: event.target.value, commune: ''});
                setStoreCode(''); setShelfType(''); setMeters(''); setManualOverride(false); setManualDepths(['']); setPointId(''); requestId.current = null;
              }}>
                <option value="">Todas las regiones</option>
                {orderRegions(regions).map(region => <option key={region.code} value={region.name}>{region.name}</option>)}
              </select>
            </label>
            <label>
              Comuna
              <select value={location.commune} disabled={busy || !location.region} aria-describedby="scan-commune-note" onChange={event => {
                setLocation({...location, commune: event.target.value});
                setStoreCode(''); setShelfType(''); setMeters(''); setManualOverride(false); setManualDepths(['']); setPointId(''); requestId.current = null;
              }}>
                <option value="">{location.region ? 'Todas las comunas' : 'Selecciona primero una región'}</option>
                {communes.map(commune => <option key={commune.code} value={commune.name}>{commune.name}</option>)}
              </select>
            </label>
            <p id="scan-commune-note" className="sb-hint full">
              {location.region ? `${communes.length} comunas disponibles en la región para tu cuenta.` : 'Selecciona una región para ver sus comunas.'}
            </p>
            <label>
              Buscar PDV
              <input type="search" value={location.query} placeholder="Nombre o código" disabled={busy} onChange={event => {
                setLocation({...location, query: event.target.value});
              }}/>
            </label>
            <label>
              Punto de venta
              <select value={selectedStore} disabled={busy || !visibleStores.length} aria-describedby="scan-pdv-note" onChange={event => {
                setStoreCode(event.target.value); setShelfType(''); setMeters(''); setManualOverride(false); setManualDepths(['']); setPointId(''); requestId.current = null;
              }}>
                {!visibleStores.length && <option value="">Sin PDV con esos filtros</option>}
                {visibleStores.map(store => <option key={store.code} value={store.code}>{store.name} ({store.code}) · {store.commune || 'Comuna sin dato'}</option>)}
              </select>
            </label>
            <p id="scan-pdv-note" className="sb-hint full" role="status">
              {visibleStores.length ? `${visibleStores.length} PDV ${visibleStores.length === 1 ? 'activo disponible' : 'activos disponibles'} para tu cuenta con estos filtros.` : stores.length ? 'No hay PDV activos que coincidan. Limpia región, comuna o búsqueda para ampliar los resultados.' : 'Tu cuenta no tiene PDV activos disponibles. Revisa su asignación en Personas y roles.'}
            </p>
            <CategorySelection categories={categories} value={classification} disabled={busy} onChange={value => {
              setClassification(value); requestId.current = null;
            }}/>
            {enabled(user,'planograms') && <CapturePlanograms store={selectedStore} classification={classification} typeId={selectedType||''} onReference={setReference} preferredPlan={referencePoint?.planogram_id}/>}
            {planClassification?.category && <p className="sb-hint full">La comparación del tipo seleccionado utiliza el planograma completo.</p>}
            <div className="full scan-type-picker">
              <label>Tipo de góndola<select value={selectedType} disabled={busy || !selectedStore || manualMode || !types.length} onChange={event => {
                const next = capturePointForType(storePoints,event.target.value,classification,enabled(user,'planograms')&&!points.data?.captureOptions.shared_plan_assignments).point;
                if (!points.data?.captureOptions.shared_plan_assignments && !classification.category && next?.planogram_classification?.category) setClassification(next.planogram_classification);
                setShelfType(event.target.value); setPointId(''); setMeters(''); requestId.current = null;
              }}>
                <option value="">{hasAssigned ? 'Selecciona un tipo de góndola' : 'Sin tipos asociados a este PDV'}</option>
                {types.map(type => <option key={type.id} value={type.id}>{type.name}</option>)}
              </select></label>
              <button type="button" disabled={busy || !selectedStore || !hasAssigned} aria-pressed={manualOverride} onClick={() => {
                setClassification(captureClassification); setManualOverride(value => !value); setMeters(''); setManualDepths(['']); setPointId(''); requestId.current = null;
              }}>{manualOverride ? 'Usar tipo precargado' : 'Ingresar medidas manualmente'}</button>
            </div>
            {!manualMode && selectedShelf && <div className="full scan-shelf-details">
              <ShelfPhoto photo={selectedShelf.photo} name={selectedShelf.name}/>
              <div><strong>{selectedShelf.name}</strong><p>Ancho {selectedShelf.width_cm} cm · Alto {selectedShelf.height_cm ?? 'sin especificar'}{selectedShelf.height_cm ? ' cm' : ''} · {selectedShelf.levels} {selectedShelf.levels === 1 ? 'nivel' : 'niveles'}</p>
                <ul>{selectedShelf.depths.map((depth,index) => <li key={index}>Nivel {index + 1} · Profundidad {depth} cm</li>)}</ul>
              </div>
            </div>}
            {!manualMode && resolution.ambiguous && <p className="message full" role="alert">Hay varios planogramas para este tipo. Selecciona la categoría y subcategorías correspondientes. Si la ambigüedad continúa, el Administrador debe revisar las referencias asignadas.</p>}
            {!manualMode && selectedShelf && !selected && !resolution.ambiguous && <p className="sb-hint full">No hay una referencia disponible para esta categoría en el tipo elegido. Revisa las asignaciones o utiliza las medidas manuales.</p>}
            <label>Ancho de la góndola en metros (opcional)<input type="number" min="0.1" max="30" step="any" value={displayedMeters} disabled={busy || !manualMode} onChange={event => {setMeters(event.target.value);requestId.current = null;}} placeholder="Ej.: 1.2"/></label>
            {manualMode && <>
              <label>Cantidad de niveles<input type="number" min="1" max="100" step="1" required value={manualDepths.length} disabled={busy} onChange={event => {
                const count = Number(event.target.value);
                if (Number.isInteger(count) && count >= 1 && count <= 100) {setManualDepths(values => Array.from({length:count},(_,index) => values[index] ?? ''));requestId.current = null;}
              }}/></label>
              {manualDepths.map((depth,index) => <label key={index}>Profundidad nivel {index+1} (cm)<input type="number" min="0.1" max="1000" step="any" required value={depth} disabled={busy} onChange={event => {setManualDepths(values => values.map((value,i) => i === index ? event.target.value : value));requestId.current = null;}}/></label>)}
              {referencePoint?.planogram_name && <p className="sb-hint full">Se conserva la comparación con {referencePoint.planogram_name}.</p>}
              <p className="sb-hint full">Estas medidas se guardan con la captura. {hasAssigned ? 'Puedes volver al tipo precargado con el botón superior.' : 'Este PDV permite capturar con medidas manuales.'}</p>
            </>}
            {!manualMode && <p className="sb-hint full">{enabled(user, 'planograms') && selected?.planogram_name ? `Se compara con ${selected.planogram_name}.` : 'Se identifican productos y caras. La comparación se aplica cuando hay un planograma asociado.'}</p>}

          </div>
        )}
      </Card>
      <Card title={`Fotos (${photos.length}/${MAX_PHOTOS})`}>
        <div className="sb-dropzone">
          <Icon name="upload" size={28} />
          <p>Toma o elige hasta {MAX_PHOTOS} fotos</p>
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
            capture="environment"
            multiple
            disabled={busy || preparing || photos.length >= MAX_PHOTOS}
            onChange={(e) => addFiles(e.target.files)}
            aria-label="Agregar fotos"
          />
        </div>
        {preparing && <Loading text="Preparando fotos…" />}
        {photos.length > 0 && (
          <div className="sb-previews">
            {photos.map((p, i) => (
              <figure key={p.url}>
                {isHeic(p.file) ? (
                  <div className="sb-empty">Foto HEIC {i + 1}</div>
                ) : (
                  <img src={p.url} alt={`Foto ${i + 1}`} />
                )}
                <figcaption>
                  <span>{i + 1}</span>
                  <span className="sb-actions">
                    <button
                      type="button"
                      disabled={busy || i === 0}
                      onClick={() => move(i, -1)}
                      aria-label="Mover a la izquierda"
                    >
                      ←
                    </button>
                    <button
                      type="button"
                      disabled={busy || i === photos.length - 1}
                      onClick={() => move(i, 1)}
                      aria-label="Mover a la derecha"
                    >
                      →
                    </button>
                    <button
                      className="remove"
                      type="button"
                      disabled={busy}
                      onClick={() => removePhoto(i)}
                      aria-label="Quitar foto"
                    >
                      ✕
                    </button>
                  </span>
                </figcaption>
              </figure>
            ))}
          </div>
        )}
      </Card>
      <div className="sb-actions" style={{ justifyContent: "flex-end" }}>
        <button
          className="action"
          type="button"
          onClick={analyze}
          disabled={
            busy ||
            preparing ||
            !photos.length ||
            !captureReady ||
            availability.data?.available === false
          }
        >
          {uploading ? "Enviando fotos…" : "Analizar góndola"}
        </button>
      </div>
    </section>
  );
}
