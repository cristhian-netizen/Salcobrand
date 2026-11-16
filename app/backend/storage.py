"""Fotos de las lecturas: S3 (producción) o disco local (desarrollo y respaldo).

- PHOTOS_BUCKET definido: las fotos nuevas se guardan en s3://PHOTOS_BUCKET/uploads/<punto>/<archivo>.
  Al leer, si la foto no está en S3 se busca en el disco antiguo (DATA_DIR/uploads, EFS) — así las lecturas
  anteriores a la migración siguen viéndose mientras `migrate_local_to_s3()` las copia en segundo plano.
- Sin PHOTOS_BUCKET: todo en DATA_DIR/uploads, como antes.
Las rutas relativas (`<punto>/<archivo>`) no cambian: son las que guarda la base de datos.
"""
import os
import threading
from pathlib import Path
from typing import Iterable, List, Optional

import db

LOCAL_DIR = db.DATA_DIR / "uploads"
LOCAL_DIR.mkdir(parents=True, exist_ok=True)
BUCKET = os.environ.get("PHOTOS_BUCKET", "").strip()
PREFIX = "uploads/"
_client = None
_client_lock = threading.Lock()
MIGRATION = {"running": False, "copied": 0, "skipped": 0, "errors": 0, "done": False}


def using_s3() -> bool:
    return bool(BUCKET)


def _s3():
    global _client
    with _client_lock:
        if _client is None:
            import boto3
            from botocore.config import Config

            _client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                                   config=Config(retries={"max_attempts": 5, "mode": "standard"}, max_pool_connections=32))
        return _client


def _key(rel_path: str) -> str:
    rel = rel_path.lstrip("/")
    if ".." in rel.split("/"):
        raise ValueError("ruta inválida")
    return PREFIX + rel


def _local(rel_path: str) -> Path:
    p = (LOCAL_DIR / rel_path.lstrip("/")).resolve()
    if LOCAL_DIR.resolve() not in p.parents:
        raise ValueError("ruta inválida")
    return p


def put(rel_path: str, data: bytes, content_type: str = "image/jpeg") -> None:
    if using_s3():
        _s3().put_object(Bucket=BUCKET, Key=_key(rel_path), Body=data, ContentType=content_type or "application/octet-stream",
                         ServerSideEncryption="AES256")
        return
    p = _local(rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def get(rel_path: str) -> Optional[bytes]:
    """Bytes de la foto o None si no existe en ningún lado."""
    if using_s3():
        try:
            return _s3().get_object(Bucket=BUCKET, Key=_key(rel_path))["Body"].read()
        except Exception as exc:  # NoSuchKey u otro: se intenta el disco antiguo
            code = ((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code")
            if code not in ("NoSuchKey", "404"):
                print(f"[storage] S3 get {rel_path}: {exc}", flush=True)
    try:
        p = _local(rel_path)
    except ValueError:
        return None
    return p.read_bytes() if p.exists() else None


def exists(rel_path: str) -> bool:
    if using_s3():
        try:
            _s3().head_object(Bucket=BUCKET, Key=_key(rel_path))
            return True
        except Exception:
            pass
    try:
        return _local(rel_path).exists()
    except ValueError:
        return False


def delete(rel_paths: Iterable[str]) -> None:
    for rel in rel_paths or []:
        if using_s3():
            try:
                _s3().delete_object(Bucket=BUCKET, Key=_key(rel))
            except Exception as exc:
                print(f"[storage] S3 delete {rel}: {exc}", flush=True)
        try:
            _local(rel).unlink()
        except (OSError, ValueError):
            pass


def delete_prefix(point_id: str) -> None:
    """Todas las fotos de un punto (al borrar el punto)."""
    if using_s3():
        s3 = _s3()
        token = None
        while True:
            kw = {"Bucket": BUCKET, "Prefix": _key(point_id.strip("/") + "/")}
            if token:
                kw["ContinuationToken"] = token
            res = s3.list_objects_v2(**kw)
            objs = [{"Key": o["Key"]} for o in res.get("Contents", [])]
            if objs:
                s3.delete_objects(Bucket=BUCKET, Delete={"Objects": objs, "Quiet": True})
            if not res.get("IsTruncated"):
                break
            token = res.get("NextContinuationToken")
    import shutil

    try:
        shutil.rmtree(_local(point_id.strip("/")), ignore_errors=True)
    except ValueError:
        pass


def content_type_for(rel_path: str) -> str:
    ext = rel_path.rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "heic": "image/heic"}.get(ext, "application/octet-stream")


def _local_files() -> List[str]:
    out = []
    for p in LOCAL_DIR.rglob("*"):
        if p.is_file():
            out.append(str(p.relative_to(LOCAL_DIR)))
    return out


def migrate_local_to_s3() -> dict:
    """Copia a S3 las fotos que solo están en el disco antiguo (idempotente; no borra nada del disco)."""
    if not using_s3() or MIGRATION["running"]:
        return MIGRATION
    MIGRATION.update({"running": True, "copied": 0, "skipped": 0, "errors": 0, "done": False})
    try:
        existing = set()
        token = None
        s3 = _s3()
        while True:
            kw = {"Bucket": BUCKET, "Prefix": PREFIX}
            if token:
                kw["ContinuationToken"] = token
            res = s3.list_objects_v2(**kw)
            existing.update(o["Key"] for o in res.get("Contents", []))
            if not res.get("IsTruncated"):
                break
            token = res.get("NextContinuationToken")
        for rel in _local_files():
            if _key(rel) in existing:
                MIGRATION["skipped"] += 1
                continue
            try:
                s3.put_object(Bucket=BUCKET, Key=_key(rel), Body=_local(rel).read_bytes(), ContentType=content_type_for(rel),
                              ServerSideEncryption="AES256")
                MIGRATION["copied"] += 1
            except Exception as exc:
                MIGRATION["errors"] += 1
                print(f"[storage] migración {rel}: {exc}", flush=True)
        MIGRATION["done"] = True
        print(f"[storage] migración EFS→S3: {MIGRATION['copied']} copiadas, {MIGRATION['skipped']} ya estaban, "
              f"{MIGRATION['errors']} errores", flush=True)
    finally:
        MIGRATION["running"] = False
    return MIGRATION
