"""Modelos versionados en S3 (fuera de la imagen): s3://NEURAVISION_MODELS_BUCKET/models/unit-detector/<versión>/.

El worker los baja al arrancar, ANTES de cargar el motor:
  NEURAVISION_DETECTOR_VERSION         → NEURAVISION_RTDETR_PATH (detector que produce las lecturas)
  NEURAVISION_SHADOW_DETECTOR_VERSION  → NEURAVISION_SHADOW_RTDETR_PATH (modo sombra: se compara, no afecta resultados)
Si no hay bucket o versión, o la descarga falla, queda el modelo que viene dentro de la imagen (/srv/models/unit-detector).
Cambiar de modelo = cambiar la variable y reiniciar el worker; volver atrás = poner la versión anterior.

Catálogo por apariencia (8-nov-2026): s3://…/models/catalogo/salud_sexual/<versión>/ y un indicador ACTUAL con la versión
activa (o NEURAVISION_CATALOG_VERSION). El worker revisa el indicador antes de cada lectura (como mucho cada 60 s) y, si
cambió, baja esa versión y la usa desde la lectura siguiente, sin reiniciarse. Publicar o volver atrás:
training/catalog/publicar_catalogo.py.
"""
import os
import time
from pathlib import Path

BUCKET = os.environ.get("NEURAVISION_MODELS_BUCKET", "").strip()
CACHE = Path(os.environ.get("NEURAVISION_MODELS_CACHE", "/tmp/models"))
FILES = ("config.json", "model.safetensors", "preprocessor_config.json")


def _download(version: str) -> Path:
    import boto3

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    dst = CACHE / "unit-detector" / version
    dst.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        target = dst / f
        if not target.exists():
            s3.download_file(BUCKET, f"models/unit-detector/{version}/{f}", str(target))
    return dst


CATALOG_PREFIX = "models/catalogo/salud_sexual"
_cat = {"checked": 0.0, "version": None}


def ensure_catalog(min_interval_s: float = 60.0) -> str:
    """Pone NEURAVISION_CATALOG_DIR en la versión activa del catálogo (S3). Devuelve la versión en uso ('' = la de la imagen)."""
    if not BUCKET or time.time() - _cat["checked"] < min_interval_s:
        return _cat["version"] or ""
    _cat["checked"] = time.time()
    try:
        import boto3

        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        version = os.environ.get("NEURAVISION_CATALOG_VERSION", "").strip()
        if not version:
            try:
                version = s3.get_object(Bucket=BUCKET, Key=f"{CATALOG_PREFIX}/ACTUAL")["Body"].read().decode().strip()
            except Exception:
                version = ""
        if not version or version == _cat["version"]:
            return _cat["version"] or ""
        dst = CACHE / "catalogo" / version
        dst.mkdir(parents=True, exist_ok=True)
        keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{CATALOG_PREFIX}/{version}/").get("Contents", [])]
        if not keys:
            raise RuntimeError(f"la versión {version} no tiene archivos")
        for k in keys:
            target = dst / k.rsplit("/", 1)[-1]
            if not target.exists():
                s3.download_file(BUCKET, k, str(target))
        os.environ["NEURAVISION_CATALOG_DIR"] = str(dst)
        print(f"[models] catálogo {_cat['version'] or 'de la imagen'} → {version} ({len(keys)} archivos)", flush=True)
        _cat["version"] = version
    except Exception as exc:
        print(f"[models] no pude revisar/bajar el catálogo ({exc}); sigue el actual", flush=True)
    return _cat["version"] or ""


def prepare() -> dict:
    out = {}
    if not BUCKET:
        return out
    for ver_var, path_var in (("NEURAVISION_DETECTOR_VERSION", "NEURAVISION_RTDETR_PATH"),
                              ("NEURAVISION_SHADOW_DETECTOR_VERSION", "NEURAVISION_SHADOW_RTDETR_PATH")):
        version = os.environ.get(ver_var, "").strip()
        if not version:
            continue
        try:
            os.environ[path_var] = str(_download(version))
            out[ver_var] = version
            print(f"[models] {ver_var}={version} → {os.environ[path_var]}", flush=True)
        except Exception as exc:
            print(f"[models] no pude bajar {version} ({exc}); se usa el modelo de la imagen", flush=True)
            if ver_var == "NEURAVISION_SHADOW_DETECTOR_VERSION":
                os.environ.pop(path_var, None)
    cat = ensure_catalog(min_interval_s=0)
    if cat:
        out["NEURAVISION_CATALOG_VERSION"] = cat
    return out
