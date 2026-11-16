"""Modo sombra: un detector candidato (p. ej. v5) corre sobre las MISMAS fotos de cada lectura real, sin tocar el
resultado que ve el cliente. Se guarda la comparación con el detector en producción (shadow_runs) para decidir el cambio
con datos reales: cajas de cada uno, cuántas coinciden (IoU ≥ 0,5), cuántas solo ve cada uno y el tiempo.
"""
import io
import os
import time

import db

_shadow = None


def enabled() -> bool:
    return bool(os.environ.get("NEURAVISION_SHADOW_RTDETR_PATH"))


def _detector():
    global _shadow
    if _shadow is None:
        from neuravision.detector import RTDetrUnitDetector

        _shadow = RTDetrUnitDetector(os.environ["NEURAVISION_SHADOW_RTDETR_PATH"],
                                     threshold=float(os.environ.get("NEURAVISION_RTDETR_THRESHOLD", "0.4")))
    return _shadow


def compare(main_boxes, shadow_boxes) -> dict:
    from neuravision.detector import _iou

    used, matched = set(), 0
    for b in sorted(shadow_boxes, key=lambda z: -z.conf):
        best, best_i = 0.0, None
        for i, m in enumerate(main_boxes):
            if i in used:
                continue
            v = _iou(b, m)
            if v > best:
                best, best_i = v, i
        if best_i is not None and best >= 0.5:
            used.add(best_i)
            matched += 1
    return {"main": len(main_boxes), "shadow": len(shadow_boxes), "both": matched,
            "only_main": len(main_boxes) - matched, "only_shadow": len(shadow_boxes) - matched}


def run(job: dict, reading_id) -> None:
    if not enabled():
        return
    import core
    from PIL import Image, ImageOps
    from neuravision.engine import shared_components

    try:
        main_det = shared_components()[0]
        sh = _detector()
        per_image = []
        t_main = t_sh = 0.0
        for data, _ct in core.load_images_from_disk((job.get("payload") or {}).get("image_paths") or []):
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            t0 = time.perf_counter(); mb = main_det.detect(img); t_main += time.perf_counter() - t0
            t0 = time.perf_counter(); sb = sh.detect(img); t_sh += time.perf_counter() - t0
            per_image.append(compare(mb, sb))
        tot = {k: sum(p[k] for p in per_image) for k in ("main", "shadow", "both", "only_main", "only_shadow")}
        tot.update({"images": per_image, "ms_main": round(t_main * 1000), "ms_shadow": round(t_sh * 1000)})
        db.add_shadow_run(job["job_id"], reading_id, os.environ.get("NEURAVISION_DETECTOR_VERSION", "imagen"),
                          os.environ.get("NEURAVISION_SHADOW_DETECTOR_VERSION", "?"), tot)
        print(f"[sombra] {job['job_id']}: producción {tot['main']} cajas, sombra {tot['shadow']} "
              f"(coinciden {tot['both']}, solo sombra {tot['only_shadow']})", flush=True)
    except Exception as exc:  # la sombra nunca afecta la lectura
        print(f"[sombra] falló en {job.get('job_id')}: {exc}", flush=True)


def summary(limit: int = 200) -> dict:
    runs = db.shadow_runs(limit)
    keys = ("main", "shadow", "both", "only_main", "only_shadow", "ms_main", "ms_shadow")
    tot = {k: sum((r["result"].get(k) or 0) for r in runs) for k in keys}
    return {"runs": len(runs), "totals": tot,
            "versions": sorted({(r["main_version"], r["shadow_version"]) for r in runs}),
            "recent": [{"job_id": r["job_id"], "reading_id": r["reading_id"], "created_at": r["created_at"],
                        **{k: r["result"].get(k) for k in keys}} for r in runs[:30]]}
