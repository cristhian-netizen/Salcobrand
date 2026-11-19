"""Product master → Kilby catalog, confirmed crops → Kilby labels, and trainings launched from "Revisión para entrenamiento".

DEPENDS ON Kilby's Neuravision dataset API (contract 2026-11-18), which is NOT deployed yet. Until it is, every call
answers 404 and the screen says so; analyses (kilby_model) do not depend on it.

- This app pushes; Kilby never calls this app.
- Product changes are recorded in management_kilby_products inside the same transaction that changes the product
  (mark_put / mark_delete, called from catalog_service). A background thread sends them to Kilby, so saving a product
  never waits for Kilby or fails because of it. Failed sends stay pending and are retried.
- Photos are sent only when they change (the product photo is a ≤1200 px data URI in management_products) or when the
  product moves to another catalog (the new catalog starts without it).
- Multi-catalog: each product syncs to the Kilby catalog of ITS category (`route`: subcategory, else category, when
  that slug exists in the workspace; else the configured/default catalog). The outbox records the catalog each row
  was/will be sent to; `drain` re-resolves puts on every round, so category or catalog changes re-route by themselves.
- Labels need the Kilby job id (vjob_…) of the reading, which kilby_model stores in readings.engine_json. Readings
  analyzed before the switch to Kilby cannot be sent (Kilby only takes its own jobs) and are counted as skipped.
- The key needs Kilby's "Manage catalogs and trainings" permission (only a Kilby workspace admin can create it). It can be
  a separate key in Administración → APIs ("Clave para catálogo y entrenamientos"); otherwise the analysis key is used.
"""
import base64
import hashlib
import json
import os
import threading
import time
import uuid

import db
import integrations_service
import kilby_neuravision as kn

INTEGRATION = "neuravision"
RETRY_LIMIT = 8
CATALOGS_TTL_S = 60
_drain_lock = threading.Lock()
_wake = threading.Event()
_thread = {"started": False}
_catalogs_cache = {"at": 0.0, "value": None}


def enabled():
    return os.environ.get("NEURAVISION_ANALYSIS_BACKEND", "").strip().lower() == "kilby"


def dataset_key():
    return integrations_service.secret(INTEGRATION, "dataset_key") or integrations_service.secret(INTEGRATION, "api_key")


def client():
    key = dataset_key()
    if not key:
        raise ValueError(kn.message_es("missing_key"))
    import kilby_model
    return kn.KilbyNeuravision(key, kilby_model.base_url())


def workspace_catalogs(kilby):
    """The workspace's Kilby catalogs, cached for CATALOGS_TTL_S (routing, drain and the overview share one listing)."""
    now = time.monotonic()
    if _catalogs_cache["value"] is not None and now - _catalogs_cache["at"] < CATALOGS_TTL_S:
        return _catalogs_cache["value"]
    catalogs = kilby.catalogs()
    _catalogs_cache.update(at=now, value=catalogs)
    return catalogs


def forget_catalogs():
    _catalogs_cache.update(at=0.0, value=None)


def target_catalog(kilby, catalogs=None):
    """The catalog set in Administración → APIs, or the workspace's only catalog."""
    configured = integrations_service.value(INTEGRATION, "catalog")
    catalogs = workspace_catalogs(kilby) if catalogs is None else catalogs
    if configured:
        found = next((c for c in catalogs if c.get("slug") == configured), None)
        if found is None:
            raise ValueError(kn.message_es("catalog_not_found"))
        return found
    if len(catalogs) == 1:
        return catalogs[0]
    if not catalogs:
        raise ValueError("El espacio de Kilby no tiene catálogos. Créalo en el panel de Kilby (página Neuravision).")
    raise ValueError("El espacio de Kilby tiene varios catálogos: indica cuál usar en Administración → APIs.")


def default_slug(catalogs):
    """Where labels and products without a (routable) category fall back to: the configured catalog, or the
    workspace's only one. None when the workspace has several catalogs and none is configured."""
    configured = integrations_service.value(INTEGRATION, "catalog")
    if configured:
        return configured
    return catalogs[0].get("slug") if len(catalogs) == 1 else None


def route(data, slugs, default):
    """Catalog for one product: the slug of its subcategory (or, without one, its category) when that catalog exists
    in the Kilby workspace (`slugs`); else `default`. Same precedence as kilby_model._catalog_choice for analyses."""
    import kilby_model
    for candidate in ((data or {}).get("subcategory"), (data or {}).get("category")):
        derived = kilby_model.catalog_slug(candidate)
        if derived:
            return derived if derived in slugs else default
    return default


def _chosen_catalog(catalog, catalogs):
    """The explicitly chosen catalog (it must exist in Kilby), or the workspace's only one. With several catalogs
    the caller must name one."""
    chosen = (catalog or "").strip() or None
    if chosen:
        if not any(c.get("slug") == chosen for c in catalogs):
            raise ValueError(f"El catálogo «{chosen}» no existe en Kilby. Actualiza la página e inténtalo nuevamente.")
        return chosen
    if len(catalogs) == 1:
        return catalogs[0].get("slug")
    if not catalogs:
        raise ValueError("El espacio de Kilby no tiene catálogos. Créalo en el panel de Kilby (página Neuravision).")
    raise ValueError("El espacio de Kilby tiene varios catálogos: indica cuál entrenar.")


# ---------------------------------------------------------------------------- outbox (called inside product transactions)

def _mark(conn, sku, product_id, pending):
    conn.execute("INSERT INTO management_kilby_products (sku, product_id, pending, revision, attempts, updated_at) VALUES (?, ?, ?, ?, 0, ?) "
                 "ON CONFLICT (sku) DO UPDATE SET product_id = EXCLUDED.product_id, pending = EXCLUDED.pending, revision = EXCLUDED.revision, "
                 "attempts = 0, last_error = NULL, updated_at = EXCLUDED.updated_at", (sku, product_id, pending, uuid.uuid4().hex, db.now_iso()))


def mark_put(conn, product_id, sku, previous_sku=None):
    if not enabled():
        return
    if previous_sku and previous_sku.lower() != sku.lower():
        _mark(conn, previous_sku, None, "delete")
    _mark(conn, sku, product_id, "put")


def mark_delete(conn, sku):
    if enabled():
        _mark(conn, sku, None, "delete")


# ---------------------------------------------------------------------------- sending

def _product_fields(data):
    category = " / ".join(part for part in (data.get("category"), data.get("subcategory")) if part)
    return {"name": data.get("name") or data.get("sku"), "brand": data.get("subBrand") or None, "category": category or None}


def _product_photo(data):
    value = data.get("photo") or ""
    if not value.startswith("data:image/") or "," not in value:
        return None
    header, encoded = value.split(",", 1)
    mime = header[5:].split(";", 1)[0]
    content = base64.b64decode(encoded)
    extension = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
    return kn.Photo(content, mime, "product." + extension)


def drain(limit=200):
    """Sends pending product changes, grouped by catalog: each put goes to the catalog of its product's category
    (`route`, resolved fresh on every round), each delete to the catalog the product was last sent to. Returns
    counts; never raises for a single product."""
    if not _drain_lock.acquire(blocking=False):
        return {"busy": True}
    sent = deleted = failed = 0
    try:
        with db.get_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM management_kilby_products WHERE pending IS NOT NULL AND attempts < ? "
                                                  "ORDER BY updated_at LIMIT ?", (RETRY_LIMIT, limit)).fetchall()]
        if not rows:
            return {"sent": 0, "deleted": 0, "failed": 0}
        with client() as kilby:
            catalogs = workspace_catalogs(kilby)
            default = target_catalog(kilby, catalogs)["slug"]
            slugs = {c.get("slug") for c in catalogs}
            groups = {}
            for row in rows:
                row["product"] = None
                slug = row["catalog"] if row["catalog"] in slugs else default
                if row["pending"] != "delete":
                    with db.get_conn() as conn:
                        product = conn.execute("SELECT sku, name, data_json FROM management_products WHERE id = ?", (row["product_id"],)).fetchone()
                    if product is not None and product["sku"] == row["sku"]:  # else deleted/renamed: its own row handles it
                        row["product"] = product
                        slug = route(json.loads(product["data_json"]), slugs, default)
                groups.setdefault(slug, []).append(row)
            for slug in sorted(groups):  # one catalog at a time
                for row in groups[slug]:
                    try:
                        done = {}
                        if row["pending"] == "delete":
                            kilby.delete_product(slug, row["sku"])
                            deleted += 1
                        elif row["product"] is not None:
                            product = row["product"]
                            data = {**json.loads(product["data_json"]), "sku": product["sku"], "name": product["name"]}
                            if len(product["sku"]) > kn.SKU_MAX:
                                raise kn.InvalidRequestError("sku too long", code="sku_too_long")
                            fields = _product_fields(data)
                            photo = _product_photo(data)
                            photo_hash = hashlib.sha256(photo.data).hexdigest() if photo else ""
                            moved = (row.get("catalog") or default) != slug  # another catalog: it starts without the photo
                            send_photo = photo is not None and (moved or photo_hash != (row.get("synced_photo") or ""))
                            kilby.put_product(slug, product["sku"], fields["name"], brand=fields["brand"], category=fields["category"],
                                              photos=[photo] if send_photo else None)
                            done = {"synced_fingerprint": hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest(),
                                    "synced_photo": photo_hash if (send_photo or not photo) else row.get("synced_photo")}
                            sent += 1
                        with db.get_conn() as conn:  # only if nobody changed the product meanwhile
                            conn.execute("UPDATE management_kilby_products SET pending = NULL, attempts = 0, last_error = NULL, catalog = ?, "
                                         "synced_fingerprint = COALESCE(?, synced_fingerprint), synced_photo = COALESCE(?, synced_photo) "
                                         "WHERE sku = ? AND revision = ?",
                                         (slug, done.get("synced_fingerprint"), done.get("synced_photo"), row["sku"], row["revision"]))
                    except (kn.AuthError, kn.NotEnabledError):
                        raise
                    except kn.NeuravisionError as exc:
                        failed += 1
                        message = "El SKU supera 64 caracteres; Kilby no lo acepta." if exc.code == "sku_too_long" else exc.message_es
                        with db.get_conn() as conn:
                            conn.execute("UPDATE management_kilby_products SET attempts = ?, last_error = ?, catalog = ? WHERE sku = ? AND revision = ?",
                                         (RETRY_LIMIT if exc.code == "sku_too_long" else row["attempts"] + 1, message, slug, row["sku"], row["revision"]))
    finally:
        _drain_lock.release()
    return {"sent": sent, "deleted": deleted, "failed": failed}


def mark_all():
    """Full resync with fresh routing: every local product is marked again and the next drain re-resolves its catalog
    against a fresh Kilby listing (photos are re-sent only when they changed or the product changed catalog).
    Products that exist only in Kilby are not deleted (the Kilby catalog may hold products loaded from its own
    panel); they are counted."""
    with db.get_conn() as conn:
        products = conn.execute("SELECT id, sku FROM management_products").fetchall()
        for product in products:
            _mark(conn, product["sku"], product["id"], "put")
    forget_catalogs()  # "Reenviar todo" must see catalogs created since the last listing
    return len(products)


def _counts_by_catalog(conn, slugs, default):
    """Outbox rows per target catalog: {slug: {synced, pending, stuck}}. Puts re-resolve from the product's current
    category (same rule as drain); deletes and already-synced rows keep the catalog they were last sent to
    (NULL = synced before multi-catalog = the default)."""
    counts = {}
    rows = conn.execute("SELECT k.pending, k.attempts, k.catalog, p.data_json FROM management_kilby_products k "
                        "LEFT JOIN management_products p ON p.id = k.product_id").fetchall()
    for row in rows:
        if row["pending"] is not None and row["pending"] != "delete" and row["data_json"]:
            slug = route(json.loads(row["data_json"]), slugs, default)
        else:
            slug = row["catalog"] if row["catalog"] in slugs else default
        state = "synced" if row["pending"] is None else ("stuck" if row["attempts"] >= RETRY_LIMIT else "pending")
        counts.setdefault(slug, {"synced": 0, "pending": 0, "stuck": 0})[state] += 1
    return counts


def _loop():
    while True:
        _wake.wait(60)
        _wake.clear()
        try:
            drain()
        except Exception as exc:  # Kilby down, key missing or not allowed: retried on the next round
            print(f"[kilby-catalog] sincronización pendiente: {type(exc).__name__}", flush=True)


def start():
    if enabled() and not _thread["started"]:
        _thread["started"] = True
        threading.Thread(target=_loop, name="kilby-catalog-sync", daemon=True).start()
        _wake.set()


def drain_soon():
    if enabled():
        _wake.set()


# ---------------------------------------------------------------------------- labels

def labels(default=None):
    """(labels for Kilby, skipped counts). A label needs the reading's Kilby job id and the verified product's SKU.
    Each label carries the catalog its reading was analyzed with (stored by kilby_model in engine_json); readings
    that did not record one (analyzed before multi-catalog) count as `default`."""
    skipped = {"sin_job_kilby": 0, "sin_sku": 0, "ajeno": 0, "no_identificable": 0}
    with db.get_conn() as conn:
        rows = conn.execute("SELECT reading_id, image_index, item_index, data_json FROM management_training_labels ORDER BY created_at, id").fetchall()
        by_name = {}
        for product in conn.execute("SELECT sku, name FROM management_products").fetchall():
            by_name.setdefault(product["name"].strip().lower(), product["sku"])
        result = []
        for row in rows:
            data = json.loads(row["data_json"])
            title = (data.get("title") or "").strip()
            if data.get("verdict") == "no_identificable":
                skipped["no_identificable"] += 1
                continue
            if not title:
                skipped["ajeno"] += 1
                continue
            sku = by_name.get(title.lower())
            if sku is None and data.get("planogram_id"):
                item = conn.execute("SELECT internal_code FROM planogram_items WHERE planogram_id = ? AND LOWER(title) = LOWER(?) "
                                    "AND internal_code IS NOT NULL AND internal_code <> '' LIMIT 1", (data["planogram_id"], title)).fetchone()
                sku = item["internal_code"] if item else None
            if not sku:
                skipped["sin_sku"] += 1
                continue
            reading = conn.execute("SELECT engine_json FROM readings WHERE id = ?", (row["reading_id"],)).fetchone()
            engine = json.loads(reading["engine_json"]) if reading and reading["engine_json"] else {}
            job = engine.get("kilby") or {}
            if not job.get("job_id"):
                skipped["sin_job_kilby"] += 1
                continue
            result.append({"job_id": job["job_id"], "image_index": row["image_index"], "item_index": row["item_index"],
                           "sku": sku, "catalog": job.get("catalog") or default})
    return result, skipped


# ---------------------------------------------------------------------------- trainings

def _save_training(conn, training_id, slug, status, data, actor=None):
    now = db.now_iso()
    conn.execute("INSERT INTO management_kilby_trainings (id, catalog, status, data_json, started_by, started_at, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, data_json = EXCLUDED.data_json, "
                 "updated_at = EXCLUDED.updated_at", (training_id, slug, status, json.dumps(data), actor or "", now, now))


def start_training(actor, catalog=None):
    with client() as kilby:
        catalogs = workspace_catalogs(kilby)
        slug = _chosen_catalog(catalog, catalogs)
        drained = drain()
        if drained.get("busy"):
            raise ValueError("Se están enviando productos a Kilby. Espera unos segundos y vuelve a intentar.")
        default = default_slug(catalogs)
        with db.get_conn() as conn:
            unsent = _counts_by_catalog(conn, {c.get("slug") for c in catalogs}, default).get(slug, {})
        pending = unsent.get("pending", 0) + unsent.get("stuck", 0)
        if pending:
            raise ValueError(f"Hay {pending} productos sin enviar al catálogo «{slug}» de Kilby. Revisa los errores de sincronización antes de entrenar.")
        ready, skipped = labels(default=default)
        to_send = [label for label in ready if label["catalog"] == slug]  # only crops analyzed with this catalog
        skipped["otro_catalogo"] = len(ready) - len(to_send)
        uploaded = kilby.upload_labels(slug, to_send) if to_send else None  # no labels: keep the ones Kilby has
        started = kilby.start_training(slug)
    data = {"id": started["id"], "status": started.get("status", "queued"), "labels": {"sent": len(to_send), "skipped_here": skipped,
            "accepted": (uploaded or {}).get("accepted"), "skipped_by_kilby": (uploaded or {}).get("skipped")}, "products": drained}
    with db.get_conn() as conn:
        _save_training(conn, started["id"], slug, data["status"], data, actor)
    return training_status(started["id"])


def training_status(training_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM management_kilby_trainings WHERE id = ?", (training_id,)).fetchone()
    if row is None:
        raise LookupError("Entrenamiento no encontrado.")
    data = json.loads(row["data_json"])
    if row["status"] not in ("done", "failed"):
        with client() as kilby:
            remote = kilby.training(row["catalog"], training_id)
        data.update({key: remote.get(key) for key in ("status", "metrics", "baseline", "version", "published", "error")})
        with db.get_conn() as conn:
            _save_training(conn, training_id, row["catalog"], data["status"], data)
    error = data.get("error")
    code = error.get("code") if isinstance(error, dict) else error
    return {**data, "catalog": row["catalog"], "started_by": row["started_by"], "started_at": row["started_at"],
            "error_es": kn.message_es(code) if code else None}


def overview():
    with db.get_conn() as conn:
        counts = {r["state"]: r["n"] for r in conn.execute(
            "SELECT CASE WHEN pending IS NULL THEN 'synced' WHEN attempts >= ? THEN 'stuck' ELSE 'pending' END AS state, COUNT(*) AS n "
            "FROM management_kilby_products GROUP BY 1", (RETRY_LIMIT,)).fetchall()}
        errors = [dict(r) for r in conn.execute("SELECT sku, last_error, catalog FROM management_kilby_products WHERE last_error IS NOT NULL "
                                                "ORDER BY updated_at DESC LIMIT 20").fetchall()]
        local = conn.execute("SELECT COUNT(*) AS n FROM management_products").fetchone()["n"]
        trainings = [r["id"] for r in conn.execute("SELECT id FROM management_kilby_trainings ORDER BY started_at DESC LIMIT 5").fetchall()]
    to_send, skipped = labels()
    import gemini_prelabel
    result = {"enabled": enabled(), "products": {"local": local, "synced": counts.get("synced", 0), "pending": counts.get("pending", 0),
              "stuck": counts.get("stuck", 0), "errors": errors}, "labels": {"ready": len(to_send), "skipped": skipped},
              "gemini": {"configured": gemini_prelabel.configured(), "model": gemini_prelabel.MODEL},
              "catalog": None, "default_catalog": None, "catalogs": [], "versions": [], "trainings": [], "error": None}
    try:
        with client() as kilby:
            catalogs = workspace_catalogs(kilby)
            default = default_slug(catalogs)
            slugs = {c.get("slug") for c in catalogs}
            with db.get_conn() as conn:
                by_catalog = _counts_by_catalog(conn, slugs, default)
            ready = {}
            for label in to_send:  # labels() ran without a default: None = analyzed with the configured catalog
                slug = label["catalog"] or default
                ready[slug] = ready.get(slug, 0) + 1
            result["default_catalog"] = default
            result["catalogs"] = [{**c, **by_catalog.get(c.get("slug"), {"synced": 0, "pending": 0, "stuck": 0}),
                                   "labels_ready": ready.get(c.get("slug"), 0)} for c in catalogs]
            catalog = target_catalog(kilby, catalogs)
            result["catalog"] = catalog
            result["versions"] = kilby.versions(catalog["slug"])
        result["trainings"] = [training_status(t) for t in trainings]
    except kn.NeuravisionError as exc:
        result["error"] = ("Kilby todavía no ofrece la API de catálogos y entrenamientos." if exc.status == 404 else exc.message_es)
    except (ValueError, LookupError) as exc:
        result["error"] = str(exc)
    return result


def publish(version, actor, catalog=None):
    with client() as kilby:
        catalogs = workspace_catalogs(kilby)
        slug = _chosen_catalog(catalog, catalogs) if catalog else target_catalog(kilby, catalogs)["slug"]
        kilby.publish(slug, version)
    with db.get_conn() as conn:
        from infrastructure import _audit
        _audit(conn, actor, "kilby.publish", slug, None, {"version": version})
    return {"catalog": slug, "version": version, "published": True}
