"""HTTP caching and lazy thumbnails for authenticated images (photos, crops).

- Every image answer carries a strong ETag (hash of the served bytes) and Cache-Control: private with a one-week
  max-age; `immutable` is added only where the bytes can never change for that URL (the photos and crops of a
  stored reading). If-None-Match answers 304 without a body, so second visits cost headers only.
- `private` keeps shared proxies out: authorization runs on this server on every request that reaches it. The
  speedup lives in the browser cache, never in a cache that skips auth.
- `?w=` serves a downscaled JPEG (grids ask for 256), generated once per width bucket and kept on disk under
  DATA_DIR/thumbs; later requests read the file and never re-encode. Originals are served untouched when they are
  already small or not decodable.
"""
import hashlib
import io
import os

from fastapi import Response

import db

CACHE_SECONDS = 7 * 24 * 3600
WIDTHS = (128, 256, 512)  # buckets keep the disk cache to a few variants per image
JPEG_QUALITY = 80


def pick_width(w):
    """The smallest allowed bucket that covers the requested width, or None for a nonsense value."""
    try:
        w = int(w)
    except (TypeError, ValueError):
        return None
    if w <= 0:
        return None
    for width in WIDTHS:
        if w <= width:
            return width
    return WIDTHS[-1]


def etag_for(data: bytes) -> str:
    return '"' + hashlib.sha256(data).hexdigest()[:32] + '"'


def matches(request, etag: str) -> bool:
    header = request.headers.get("if-none-match") or ""
    return etag in [value.strip()[2:] if value.strip().startswith("W/") else value.strip() for value in header.split(",")]


def response(request, data: bytes, media_type: str, immutable: bool = True) -> Response:
    etag = etag_for(data)
    headers = {"Cache-Control": f"private, max-age={CACHE_SECONDS}" + (", immutable" if immutable else ""),
               "ETag": etag, "Vary": "Cookie"}
    if matches(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=media_type, headers=headers)


def thumbnail(kind: str, name: str, data: bytes, w):
    """(bytes, media_type or None) for the `?w=` variant: the cached thumbnail, or the original bytes when no
    resize applies (no/invalid w, image already small, bytes not decodable). media_type is set only for a thumb."""
    width = pick_width(w)
    if width is None or not data:
        return data, None
    digest = hashlib.sha256(f"{kind}/{name}".encode()).hexdigest()[:40]
    path = db.DATA_DIR / "thumbs" / kind / f"{digest}-w{width}.jpg"
    try:
        return path.read_bytes(), "image/jpeg"
    except OSError:
        pass
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        if max(image.size) <= width:
            return data, None  # the original already fits the grid
        image.thumbnail((width, width))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=JPEG_QUALITY)
        small = buffer.getvalue()
    except Exception:
        return data, None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + f".{os.getpid()}.tmp")
        temp.write_bytes(small)
        temp.replace(path)  # atomic: a concurrent request never reads a half-written file
    except OSError:
        pass
    return small, "image/jpeg"
