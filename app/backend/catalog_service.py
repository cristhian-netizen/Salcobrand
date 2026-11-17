"""Product master and planogram editing backed by the existing planograms engine tables."""
import base64
import io
import json
import math
import uuid

from PIL import Image
import db
from infrastructure import ManagementError, _audit, _check_version, _row, _status, _text


def lock_catalog(conn, expected=None):
    state = _row(conn, "management_catalog_state", "id", 1, lock=True)
    if expected is not None:
        _check_version(state, expected)
    return state["version"]


def changed(conn):
    conn.execute("UPDATE management_catalog_state SET version = version + 1 WHERE id = 1")


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= 1000000:
        raise ManagementError(f"{label}: ingresa un número mayor a cero y hasta 1.000.000.")
    return value


def image_reference(value):
    if not value:
        return ""
    try:
        header, encoded = value.split(",", 1)
        formats = {"data:image/jpeg;base64": "JPEG", "data:image/png;base64": "PNG", "data:image/webp;base64": "WEBP"}
        if header not in formats or len(value) > 7000000:
            raise ValueError()
        with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as photo:
            if photo.format != formats[header] or max(photo.size) > 1200:
                raise ValueError()
            photo.verify()
    except (ValueError, OSError, TypeError, Image.DecompressionBombError) as exc:
        raise ManagementError("Carga una imagen JPG, PNG o WebP válida, de hasta 1200 px.") from exc
    return value


def product_data(values):
    result = {}
    for key, label, limit, required in (
        ("sku", "SKU", 80, True), ("name", "Nombre", 180, True),
        ("subBrand", "Submarca", 100, True), ("category", "Categoría", 100, True),
        ("subcategory", "Subcategoría", 100, True), ("description", "Descripción", 2000, False),
        ("barcode", "Código de barras", 80, False),
    ):
        result[key] = _text(values.get(key, ""), label, limit, required)
    for key, label in (("quantity", "Cantidad"), ("height", "Alto"), ("width", "Ancho"), ("thickness", "Espesor")):
        result[key] = positive(values.get(key), label)
    if values.get("saleUnit") not in ("gramos", "ml") or values.get("productType") not in ("Envasado", "a granel"):
        raise ManagementError("Selecciona un formato de venta y un tipo de producto válidos.")
    result.update({key: values[key] for key in ("saleUnit", "productType")})
    price = values.get("price")
    if price is not None and (isinstance(price, bool) or not isinstance(price, (float, int)) or not math.isfinite(price) or not 0 <= price <= 1000000000):
        raise ManagementError("El precio debe ser un número entre 0 y 1.000.000.000 CLP.")
    result["price"] = price
    result["photo"] = image_reference(values.get("photo", ""))
    result["volume"] = result["height"] * result["width"] * result["thickness"]
    return result


def product_public(row):
    data = json.loads(row["data_json"])
    data.pop("previous_identifiers", None)
    return {**data, "id": row["id"], "sku": row["sku"], "name": row["name"], "version": row["version"]}


def products(conn):
    return [product_public(r) for r in conn.execute("SELECT * FROM management_products ORDER BY LOWER(name), sku").fetchall()]


def write_product(conn, values, actor, product_id=None):
    data = product_data(values)
    from settings_service import validate_product
    validate_product(conn, data)
    before = _row(conn, "management_products", "id", product_id) if product_id else None
    if before:
        _check_version(before, values.get("version"))
        previous = json.loads(before["data_json"])
        identifiers = {key: previous.get(key, "") for key in ("sku", "name", "barcode")}
        history = previous.get("previous_identifiers", [])
        if identifiers not in history:
            history.append(identifiers)
        data["previous_identifiers"] = history
    duplicate = conn.execute("SELECT id FROM management_products WHERE LOWER(sku) = LOWER(?)", (data["sku"],)).fetchone()
    if duplicate and duplicate["id"] != product_id:
        raise ManagementError("El SKU ya existe en el catálogo.", 409)
    product_id = product_id or uuid.uuid4().hex
    now = db.now_iso()
    if before:
        conn.execute("UPDATE management_products SET sku = ?, name = ?, data_json = ?, version = version + 1, updated_at = ? WHERE id = ?",
                     (data["sku"], data["name"], json.dumps(data), now, product_id))
    else:
        conn.execute("INSERT INTO management_products (id, sku, name, data_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (product_id, data["sku"], data["name"], json.dumps(data), now, now))
    # Photos are excluded from audit payloads.
    _audit(conn, actor, "product.update" if before else "product.create", product_id,
           {"sku": before["sku"], "version": before["version"]} if before else None,
           {"sku": data["sku"], "name": data["name"]})
    return product_public(_row(conn, "management_products", "id", product_id))


def save_product(values, actor, product_id=None):
    with db.get_conn() as conn:
        lock_catalog(conn)
        result = write_product(conn, values, actor, product_id)
        changed(conn)
    return result


def delete_products(selected, actor):
    if not selected or len(selected) > 5000 or len({r["id"] for r in selected}) != len(selected):
        raise ManagementError("Selecciona entre 1 y 5.000 productos distintos.")
    with db.get_conn() as conn:
        lock_catalog(conn)
        rows = []
        for item in selected:
            row = _row(conn, "management_products", "id", item["id"])
            _check_version(row, item["version"])
            rows.append({**product_public(row), "previous_identifiers": json.loads(row["data_json"]).get("previous_identifiers", [])})
        blocked = set()
        plans = conn.execute("SELECT p.name, p.id, m.data_json FROM planograms p LEFT JOIN management_planograms m ON m.id = p.id").fetchall()
        selected_ids = {p["id"] for p in rows}
        for detail in conn.execute('SELECT reading_id, data_json FROM management_reading_details').fetchall():
            if any(row.get('productId') in selected_ids for row in json.loads(detail['data_json']).get('details', [])):
                blocked.add(f"Medición #{detail['reading_id']}")
        for plan in plans:
            meta = json.loads(plan["data_json"]) if plan["data_json"] else {}
            if any(r.get("productId") in selected_ids for r in meta.get("positionRows", [])):
                blocked.add(plan["name"])
        for product in rows:
            for identity in [product, *product["previous_identifiers"]]:
                refs = conn.execute("SELECT DISTINCT p.name FROM planogram_items i JOIN planograms p ON p.id = i.planogram_id WHERE LOWER(i.internal_code) = LOWER(?) OR LOWER(i.title) = LOWER(?) OR (i.barcode = ? AND i.barcode <> '')",
                                    (identity["sku"], identity["name"], identity["barcode"])).fetchall()
                blocked.update(r["name"] for r in refs)
        if blocked:
            raise ManagementError("Los productos están referenciados en estos registros: " + ", ".join(sorted(blocked)) + ".", 409)
        for product in rows:
            conn.execute("DELETE FROM management_products WHERE id = ?", (product["id"],))
            _audit(conn, actor, "product.delete", product["id"], {"sku": product["sku"], "name": product["name"]}, None)
        changed(conn)
    return {"deleted": [r["id"] for r in rows]}


def plan_public(plan):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM management_planograms WHERE id = ?", (plan["id"],)).fetchone()
    if row:
        return {**plan, "category": "", "subcategories": [], "position_mode": "faces", **json.loads(row["data_json"]), "version": row["version"], "managed": True}
    return {**plan, "category": "", "subcategories": [], "version": 0, "managed": False, "position_mode": "products", "store_code": "", "status": "Activo", "description": "", "photo": "", "document": "", "document_name": "", "document_page": 1,
            "positionRows": [{"level": i["band"] or 1, "position": i["position_in_section"] or index + 1,
                              "faces": i["expected_facings"] or 1, "productId": "", "legacy_item_id": i["id"],
                              "sku": i["internal_code"] or "", "barcode": i["barcode"] or "", "legacy_title": i["title"]}
                             for index, i in enumerate(plan.get("items", []))]}


def state():
    with db.get_conn() as conn:
        items = [{key: value for key, value in p.items() if key != "photo"} for p in products(conn)]
        version = conn.execute("SELECT version FROM management_catalog_state WHERE id = 1").fetchone()["version"]
    plans = []
    for source in db.list_planograms():
        plan = plan_public(db.get_planogram(source["id"]))
        summary = {key: value for key, value in plan.items() if key not in ("photo", "document", "items", "positionRows", "legacy_point_ids")}
        summary["item_count"] = len(plan["items"])
        summary["face_count"] = sum(i["expected_facings"] or 0 for i in plan["items"])
        plans.append(summary)
    from settings_service import read
    configuration = read()['state']
    return {"products": items, "planograms": plans, "version": version, "classification": {
        **configuration['catalog'], 'ownBrands': configuration['productParameters']['ownBrands']}}


def product_detail(product_id):
    with db.get_conn() as conn:
        return product_public(_row(conn, "management_products", "id", product_id))


def plan_detail(plan_id):
    plan = db.get_planogram(plan_id)
    if not plan:
        raise ManagementError("El planograma ya no existe. Actualiza la pantalla.", 404)
    return plan_public(plan)


def plan_options():
    result = []
    with db.get_conn() as conn:
        for plan in db.list_planograms():
            row = conn.execute("SELECT data_json FROM management_planograms WHERE id = ?", (plan["id"],)).fetchone()
            meta = json.loads(row["data_json"]) if row else {}
            result.append({**plan, "store_code": meta.get("store_code"), "status": meta.get("status", "Activo")})
    return result


def legacy_items(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 5000:
        raise ManagementError("El JSON debe contener entre 1 y 5.000 posiciones.")
    result = []
    for index, row in enumerate(raw, 1):
        if not isinstance(row, dict):
            raise ManagementError(f"Fila {index}: posición no válida.")
        title = _text(row.get("title", ""), "Producto", 180, True)
        item = {}
        for field, default in (("order_seq", index), ("module", 1), ("band", 1), ("segment", 0), ("position_in_section", index), ("expected_facings", 1)):
            value = row.get(field, default)
            try:
                number = int(value)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ManagementError(f"Fila {index}: {field} debe ser un entero.") from exc
            if isinstance(value, bool) or (isinstance(value, float) and value != number) or not (0 if field == "segment" else 1) <= number <= 5000:
                raise ManagementError(f"Fila {index}: {field} no es válido.")
            item[field] = number
        price = row.get("price_clp")
        if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or not 0 <= price <= 1000000000):
            raise ManagementError(f"Fila {index}: precio no válido.")
        price_source = row.get("price_source")
        if price_source not in (None, "manual", "ocr"):
            raise ManagementError(f"Fila {index}: origen del precio no válido.")
        result.append({**item, "title": title, "section_label": str(row.get("section_label") or f'1/{item["band"]}')[:100],
                       "internal_code": _text(row.get("internal_code") or "", "SKU", 80),
                       "barcode": _text(row.get("barcode") or "", "Código de barras", 80),
                       "tag": _text(row.get("tag") or "", "Etiqueta", 100), "price_clp": price, "price_source": price_source})
    return result


def document_reference(value, page):
    if not value:
        return {"content": "", "pages": 0}
    try:
        from pypdf import PdfReader
        if not value.startswith("data:application/pdf;base64,") or len(value) > 7000000:
            raise ValueError()
        content = base64.b64decode(value.split(",", 1)[1], validate=True)
        pdf = PdfReader(io.BytesIO(content))
        if pdf.is_encrypted or not 1 <= page <= len(pdf.pages) or len(pdf.pages) > 1000:
            raise ValueError()
    except Exception as exc:
        raise ManagementError("Carga un PDF válido sin contraseña y selecciona una página existente.") from exc
    return {"content": value, "pages": len(pdf.pages)}


def position_items(rows, master, old_items, position_mode="faces"):
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ManagementError("Máximo 5.000 filas de posiciones.")
    occupied, items, clean = set(), [], []
    total_faces = 0
    for index, row in enumerate(rows, 1):
        level, start, faces = (row.get(k) for k in ("level", "position", "faces"))
        if any(type(n) is not int or not 1 <= n <= 5000 for n in (level, start, faces)) or (position_mode == "faces" and start + faces - 1 > 5000) or total_faces + faces > 5000:
            raise ManagementError(f"Fila {index}: nivel, posición y caras deben ser enteros positivos, hasta 5.000 caras en total.")
        product = master.get(row.get("productId"))
        legacy = old_items.get(row.get("legacy_item_id")) if not product else None
        if not product and not legacy:
            raise ManagementError(f"Fila {index}: selecciona un producto existente.")
        sku = _text(row.get("sku", ""), "SKU", 80)
        barcode = _text(row.get("barcode", ""), "Código de barras", 80)
        if product:
            if (sku and sku.casefold() != product["sku"].casefold()) or (barcode and product["barcode"] and barcode != product["barcode"]):
                raise ManagementError(f"Fila {index}: SKU o código de barras no corresponde al producto seleccionado.")
            if barcode and any(p["barcode"] == barcode and p["id"] != product["id"] for p in master.values()):
                raise ManagementError(f"Fila {index}: el código de barras corresponde a otro producto.")
            sku, barcode = sku or product["sku"], barcode or product["barcode"]
        else:
            if sku != (legacy["internal_code"] or "") or barcode != (legacy["barcode"] or ""):
                raise ManagementError("Para cambiar la identidad de un producto anterior, selecciónalo en el maestro.")
        total_faces += faces
        occupied_positions = range(start, start + faces) if position_mode == "faces" else (start,)
        for position in occupied_positions:
            if (level, position) in occupied:
                raise ManagementError(f"Fila {index}: se superponen caras en nivel {level}, posición {position}.")
            occupied.add((level, position))
        clean.append({"level": level, "position": start, "faces": faces, "productId": product["id"] if product else "",
                      "legacy_item_id": legacy["id"] if legacy else None, "legacy_title": legacy["title"] if legacy else "", "sku": sku, "barcode": barcode})
        price_source = legacy.get("price_source") if legacy else None
        if product and product["price"] is not None:
            price_source = "manual"
        items.append({"order_seq": index, "section_label": f"1/{level}", "module": 1, "band": level, "segment": 0,
                      "position_in_section": start, "title": product["name"] if product else legacy["title"], "internal_code": sku,
                      "barcode": barcode, "expected_facings": faces, "tag": product["subBrand"] if product else legacy["tag"],
                      "price_clp": product["price"] if product else legacy.get("price_clp"),
                      "price_source": price_source})
    return clean, items


def freeze_readings(conn, plan):
    # Existing measurements keep the reference used before an edit or deletion.
    suffix = " FOR UPDATE" if db.USE_PG else ""
    jobs = conn.execute("SELECT job_id, status, payload_json FROM api_jobs WHERE status IN ('queued', 'running')" + suffix).fetchall()
    for job in jobs:
        payload = json.loads(job["payload_json"] or "{}")
        if payload.get("planogram_id") != plan["id"] or payload.get("plan_snapshot"):
            continue
        if job["status"] == "running":
            raise ManagementError("Hay un análisis anterior en curso con este planograma. Espera a que termine para editar su referencia.", 409)
        payload["plan_snapshot"] = plan
        conn.execute("UPDATE api_jobs SET payload_json = ? WHERE job_id = ?", (json.dumps(payload), job["job_id"]))
    conn.execute("UPDATE readings SET plan_snapshot_json = ? WHERE planogram_id = ? AND plan_snapshot_json IS NULL",
                 (json.dumps(plan), plan["id"]))


def job_snapshot(plan_id):
    if not plan_id:
        return None
    with db.get_conn() as conn:
        lock_catalog(conn)
        return db.get_planogram(plan_id)


def validate_assignment(plan_id, store_code, point_id=None):
    with db.get_conn() as conn:
        row = conn.execute("SELECT data_json FROM management_planograms WHERE id = ?", (plan_id,)).fetchone()
    if row:
        meta = json.loads(row["data_json"])
        allowed_legacy = point_id in meta.get("legacy_point_ids", [])
        if meta["status"] != "Activo" or (meta["store_code"] != store_code and not allowed_legacy):
            raise ManagementError("Selecciona un planograma activo del mismo PDV que la góndola.", 409)


def save_plan(values, actor, plan_id=None):
    name = _text(values.get("name"), "Nombre", 150, True)
    with db.get_conn() as conn:
        lock_catalog(conn)
        before = _row(conn, "planograms", "id", plan_id) if plan_id else None
        metadata = conn.execute("SELECT * FROM management_planograms WHERE id = ?", (plan_id,)).fetchone() if plan_id else None
        version = metadata["version"] if metadata else 0
        if before and values.get("version") != version:
            raise ManagementError("El planograma cambió en otra sesión. Actualiza antes de guardar.", 409)
        store = _row(conn, "management_stores", "code", values.get("store_code"))
        if store["deleted"]:
            raise ManagementError("Selecciona un PDV disponible.")
        assignments = conn.execute("SELECT id, store_id FROM points WHERE planogram_id = ?", (plan_id,)).fetchall() if before else []
        if metadata:
            legacy_points = json.loads(metadata["data_json"]).get("legacy_point_ids", [])
            if any(p["store_id"] != store["code"] and p["id"] not in legacy_points for p in assignments):
                raise ManagementError("Este planograma sigue asignado a góndolas de su PDV anterior. Desasígnalo de esas góndolas antes de cambiar el PDV.", 409)
        else:
            # Imported Salcobrand references may already be shared by several stores.
            legacy_points = [p["id"] for p in assignments if p["store_id"] != store["code"]]
        from product_classification import selection, validate
        previous = json.loads(metadata['data_json']) if metadata else {}
        category = values.get('category')
        category = previous.get('category', '') if category is None else category
        subcategories = values.get('subcategories')
        subcategories = previous.get('subcategories', []) if subcategories is None else subcategories
        classification = selection(category, subcategories=subcategories)
        validate(classification, conn)
        status = _status(values.get("status", "Activo"))
        description = _text(values.get("description", ""), "Descripción", 2000)
        photo = image_reference(values.get("photo", ""))
        page = values.get("document_page", 1)
        if type(page) is not int or page < 1:
            raise ManagementError("Selecciona una página válida del PDF.")
        reference = document_reference(values.get("document", ""), page)
        document = reference["content"]
        if not photo and not document:
            raise ManagementError("Carga una imagen o PDF del planograma.")
        document_name = _text(values.get("document_name", ""), "Archivo", 200)
        duplicate = conn.execute("SELECT m.id, p.name, m.data_json FROM management_planograms m JOIN planograms p ON p.id = m.id WHERE LOWER(p.name) = LOWER(?)", (name,)).fetchall()
        if any(r["id"] != plan_id and json.loads(r["data_json"])["store_code"] == store["code"] for r in duplicate):
            raise ManagementError("Ya existe un planograma con ese nombre en el PDV.", 409)
        old_plan = db.get_planogram(plan_id) if before else None
        old_items = {i["id"]: i for i in old_plan["items"]} if old_plan else {}
        position_mode = values.get("position_mode", "faces")
        if position_mode not in ("faces", "products"):
            raise ManagementError("La numeración de posiciones no es válida.")
        rows, items = position_items(values.get("positionRows", []), {p["id"]: p for p in products(conn)}, old_items, position_mode)
        plan_id = plan_id or "catalog-" + uuid.uuid4().hex
        meta = {"category": category, "subcategories": classification.get("subcategories", []), "store_code": store["code"], "status": status, "description": description, "photo": photo,
                "document": document, "document_name": document_name, "document_page": page, "document_pages": reference["pages"], "positionRows": rows,
                "legacy_point_ids": legacy_points, "position_mode": position_mode}
        if old_plan:
            freeze_readings(conn, old_plan)
            conn.execute("UPDATE planograms SET name = ?, bands = ? WHERE id = ?", (name, max((i["band"] for i in items), default=0), plan_id))
            existing = {(i["band"], i["position_in_section"]): i["id"] for i in old_plan["items"]}
        else:
            conn.execute("INSERT INTO planograms (id, name, bands, created_at) VALUES (?, ?, ?, ?)", (plan_id, name, max((i["band"] for i in items), default=0), db.now_iso()))
            existing = {}
        retained = set()
        for row, item in zip(rows, items):
            item_id = existing.get((item["band"], item["position_in_section"]))
            keys = list(item)
            if item_id:
                conn.execute("UPDATE planogram_items SET " + ", ".join(k + " = ?" for k in keys) + " WHERE id = ?", (*item.values(), item_id))
                retained.add(item_id)
            else:
                inserted = conn.execute("INSERT INTO planogram_items (planogram_id, " + ", ".join(keys) + ") VALUES (" + ", ".join("?" for _ in range(len(keys) + 1)) + ")", (plan_id, *item.values()))
                item_id = inserted.lastrowid
            if not row["productId"]:
                row["legacy_item_id"] = item_id
        for item_id in old_items:
            if item_id not in retained:
                conn.execute("DELETE FROM planogram_items WHERE id = ?", (item_id,))
        if metadata:
            conn.execute("UPDATE management_planograms SET data_json = ?, version = version + 1, updated_at = ? WHERE id = ?", (json.dumps(meta), db.now_iso(), plan_id))
        else:
            conn.execute("INSERT INTO management_planograms (id, data_json, updated_at) VALUES (?, ?, ?)", (plan_id, json.dumps(meta), db.now_iso()))
        _audit(conn, actor, "planogram.update" if before else "planogram.create", plan_id, {"version": version}, {"version": version + 1, "name": name})
        changed(conn)
    return plan_public(db.get_planogram(plan_id))


def delete_plan(plan_id, version, actor):
    with db.get_conn() as conn:
        lock_catalog(conn)
        _row(conn, "planograms", "id", plan_id)
        meta = conn.execute("SELECT version FROM management_planograms WHERE id = ?", (plan_id,)).fetchone()
        if version != (meta["version"] if meta else 0):
            raise ManagementError("El planograma cambió. Actualiza antes de eliminarlo.", 409)
        freeze_readings(conn, db.get_planogram(plan_id))
        conn.execute("UPDATE points SET planogram_id = NULL WHERE planogram_id = ?", (plan_id,))
        conn.execute("DELETE FROM planogram_items WHERE planogram_id = ?", (plan_id,))
        conn.execute("DELETE FROM planograms WHERE id = ?", (plan_id,))
        conn.execute("DELETE FROM management_planograms WHERE id = ?", (plan_id,))
        changed(conn)
        _audit(conn, actor, "planogram.delete", plan_id, {"version": version}, None)
    return {"deleted": plan_id}
