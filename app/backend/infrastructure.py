"""PDV and infrastructure transactions, validation, history and capture eligibility."""
import base64
import binascii
import io
import json
import math
from pathlib import Path
import re
import unicodedata
import uuid

from PIL import Image
import db

REGIONS = json.loads(Path(__file__).with_name("chile_locations.json").read_text(encoding="utf-8"))
REGION_ORDER = ['15','01','02','03','04','05','13','06','07','16','08','09','14','10','11','12']
REGIONS.sort(key=lambda region: REGION_ORDER.index(region['code']))
for region in REGIONS:
    region['communes'].sort(key=lambda commune: unicodedata.normalize('NFD', commune['name']).encode('ascii','ignore').decode().casefold())
STORE_TYPES = ("Farmacia", "Supermercado", "Tienda de conveniencia", "Minimarket", "Tienda de barrio", "Otro")


class ManagementError(ValueError):
    def __init__(self, detail, status=400):
        super().__init__(detail)
        self.status = status


def _text(value, label, maximum, required=False):
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        raise ManagementError(f"{label}: ingresa un texto válido de hasta {maximum} caracteres.")
    return value.strip()


def _normalize(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFD", str(value)).encode("ascii", "ignore").decode().lower())


def _location(region, commune):
    selected = next((r for r in REGIONS if _normalize(region) in {
        _normalize(r["name"]), _normalize(r["code"]), _normalize(r["abbreviation"]),
        _normalize('Región ' + r['name']), _normalize('Región de ' + r['name']), _normalize('Región del ' + r['name'])
    }), None)
    local = next((c for c in selected["communes"] if _normalize(c["name"]) == _normalize(commune)), None) if selected else None
    if not selected or not local:
        raise ManagementError("Selecciona una región y una comuna perteneciente a esa región.")
    return selected["name"], local["name"]


def _status(value):
    if value not in ("Activo", "Inactivo"):
        raise ManagementError("El estado debe ser Activo o Inactivo.")
    return value


def _photo(value):
    if not value:
        return ""
    if not isinstance(value, str) or len(value) > 750000:
        raise ManagementError("La miniatura de la góndola supera el tamaño permitido.")
    match = re.fullmatch(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)", value)
    if not match:
        raise ManagementError("Usa una fotografía JPG, PNG o WebP válida.")
    try:
        content = base64.b64decode(match[2], validate=True)
        with Image.open(io.BytesIO(content)) as image:
            if image.format != {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[match[1]] or max(image.size) > 640:
                raise ManagementError("La miniatura debe ser una imagen de hasta 640 px.")
            image.verify()
    except (ValueError, OSError, binascii.Error) as exc:
        raise ManagementError("La fotografía no se pudo validar.") from exc
    return value


def _audit(conn, actor, action, resource, before, after):
    def safe(value):
        if value is None:
            return None
        result = dict(value)
        if "photo" in result:
            result["photo"] = bool(result["photo"])
        return json.dumps(result, ensure_ascii=False)
    conn.execute("INSERT INTO management_events (id, actor, action, resource_id, before_json, after_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (uuid.uuid4().hex, actor, action, resource, safe(before), safe(after), db.now_iso()))


def _row(conn, table, key, value, lock=False):
    # Table/key are internal constants, never client-supplied SQL fragments.
    if lock and not db.USE_PG:
        conn.execute(f"UPDATE {table} SET {key} = {key} WHERE {key} = ?", (value,))
    suffix = " FOR UPDATE" if lock and db.USE_PG else ""
    row = conn.execute(f"SELECT * FROM {table} WHERE {key} = ?" + suffix, (value,)).fetchone()
    if row is None:
        raise ManagementError("El registro ya no existe. Actualiza la pantalla.", 404)
    return dict(row)


def _check_version(row, expected):
    if row["version"] != expected:
        raise ManagementError("El registro cambió en otra sesión. Actualiza antes de guardar.", 409)


def _store_public(row):
    result = dict(row)
    result["deleted"] = bool(result["deleted"])
    result["needs_completion"] = any(not result.get(key) for key in ("store_type", "region", "commune", "address", "manager"))
    return result


def bootstrap_legacy_stores():
    """Register known codes without renaming points, guessing locations, or replacing edits."""
    with db.get_conn() as conn:
        names = {}
        for user in conn.execute("SELECT store_id, store_name, store_ids_json FROM users ORDER BY username").fetchall():
            codes = json.loads(user["store_ids_json"] or "[]") or ([user["store_id"]] if user["store_id"] else [])
            for code in codes:
                names.setdefault(code, user["store_name"] if len(codes) == 1 and user["store_name"] else code)
        for point in conn.execute("SELECT store_id FROM points WHERE store_id IS NOT NULL").fetchall():
            if point["store_id"]:
                names.setdefault(point["store_id"], point["store_id"])
        for code, name in names.items():
            now = db.now_iso()
            conn.execute("INSERT INTO management_stores (code, name, created_at, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING", (code, name, now, now))


def list_stores(include_deleted=False):
    bootstrap_legacy_stores()
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM management_stores" + ("" if include_deleted else " WHERE deleted = 0") + " ORDER BY LOWER(name), code").fetchall()
        counts = {r["store_id"]: r["n"] for r in conn.execute("SELECT store_id, COUNT(*) AS n FROM points GROUP BY store_id").fetchall()}
        active = {r["store_code"]: r["n"] for r in conn.execute("SELECT store_code, COUNT(*) AS n FROM management_instances WHERE active = 1 GROUP BY store_code").fetchall()}
        assignments = conn.execute('SELECT a.store_code,a.type_id,a.quantity,t.name FROM management_assignments a '
                                   'JOIN management_shelf_types t ON t.id=a.type_id WHERE a.quantity>0 AND t.deleted=0 ORDER BY t.name').fetchall()
    assigned = {}
    for assignment in assignments:
        assigned.setdefault(assignment['store_code'], []).append({key:assignment[key] for key in ('type_id','name','quantity')})
    return [{**_store_public(r), "gondolas_count": counts.get(r["code"], 0), "active_instances": active.get(r["code"], 0),
             'shelf_types':assigned.get(r['code'], [])} for r in rows]


def store_code(value):
    code = _text(value, "Código PDV", 20, True).upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,19}", code):
        raise ManagementError("Código PDV: usa hasta 20 letras, números, guiones o guiones bajos.")
    return code


def store_data(values, types):
    data = {key: _text(values.get(key, ""), label, maximum, required) for key, label, maximum, required in (
        ("name", "Nombre", 120, True), ("address", "Dirección", 200, True), ("manager", "Encargado de Local", 120, True),
        ("description", "Descripción", 2000, False))}
    data["store_type"] = values.get("store_type", "")
    data["region"], data["commune"] = _location(values.get("region", ""), values.get("commune", ""))
    data["status"] = _status(values.get("status", "Activo"))
    if data['store_type'] not in types:
        raise ManagementError("Selecciona un tipo de PDV del catálogo.")
    return data


def write_store(conn, values, actor, code=None, types=None):
    from settings_service import read
    data = store_data(values, types if types is not None else read(conn)['state']['pdvTypes'])
    if code is None:
        code = store_code(values.get('code', ''))
        if conn.execute("SELECT code FROM management_stores WHERE LOWER(code) = LOWER(?)", (code,)).fetchone():
            raise ManagementError("Ese código PDV ya existe, incluso si está eliminado.", 409)
        now = db.now_iso()
        columns = list(data)
        conn.execute(f"INSERT INTO management_stores (code, {','.join(columns)}, created_at, updated_at) VALUES ({','.join('?' for _ in range(len(columns)+3))})", (code, *data.values(), now, now))
        before = None
    else:
        before = _row(conn, "management_stores", "code", code, lock=True)
        _check_version(before, values['version'])
        if before['deleted']:
            raise ManagementError("Restaura el PDV antes de editarlo.", 409)
        conn.execute(f"UPDATE management_stores SET {','.join(key+' = ?' for key in data)}, version = version + 1, updated_at = ? WHERE code = ?", (*data.values(), db.now_iso(), code))
    after = _row(conn, 'management_stores', 'code', code)
    _audit(conn, actor, 'store.update' if before else 'store.create', code, before, after)
    return _store_public(after)


def save_store(values, actor, code=None):
    with db.get_conn() as conn:
        from catalog_service import lock_catalog
        lock_catalog(conn)
        assignments = values.get('assignments')
        if assignments is not None:
            ids = [item['type_id'] for item in assignments]
            if len(ids) != len(set(ids)):
                raise ManagementError('Hay tipos de góndola repetidos en la asignación.')
        saved = write_store(conn, values, actor, code)
        for item in assignments or []:
            shelf = _row(conn, 'management_shelf_types', 'id', item['type_id'])
            if shelf['deleted']:
                raise ManagementError('El catálogo de góndolas cambió. Actualiza la ficha del PDV.', 409)
            previous = _assignment(conn, saved['code'], item['type_id'], item['version'])
            if item['quantity'] != (previous['quantity'] if previous else 0):
                _set_quantity(conn, saved['code'], item['type_id'], item['quantity'], item['version'], actor)
        return saved


def retire_store(code, version, actor, restore=False):
    with db.get_conn() as conn:
        before = _row(conn, "management_stores", "code", code, lock=True)
        _check_version(before, version)
        conn.execute("UPDATE management_stores SET deleted = ?, status = 'Inactivo', version = version + 1, updated_at = ? WHERE code = ?", (0 if restore else 1, db.now_iso(), code))
        after = _row(conn, "management_stores", "code", code)
        _audit(conn, actor, "store.restore" if restore else "store.retire", code, before, after)
    return _store_public(after)


def store_history(code):
    with db.get_conn() as conn:
        rows = conn.execute("SELECT actor, action, before_json, after_json, created_at FROM management_events WHERE resource_id = ? ORDER BY created_at DESC", (code,)).fetchall()
    return [{"actor": r["actor"], "action": r["action"], "before": json.loads(r["before_json"]) if r["before_json"] else None,
             "after": json.loads(r["after_json"]) if r["after_json"] else None, "created_at": r["created_at"]} for r in rows]


def _type_public(row):
    result = dict(row)
    result["depths"] = json.loads(result.pop("depths_json"))
    result["levels"] = len(result["depths"])
    return result


def list_types():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM management_shelf_types WHERE deleted=0 ORDER BY LOWER(name)").fetchall()
    return [_type_public(row) for row in rows]


def save_type(values, actor, type_id=None):
    name = _text(values.get("name", ""), "Nombre del tipo", 120, True)
    width, depths = values.get("width_cm"), values.get("depths")
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or not 0 < width <= 1000:
        raise ManagementError("El ancho debe ser mayor a 0 y hasta 1000 cm.")
    if not isinstance(depths, list) or not 1 <= len(depths) <= 100 or any(isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d) or not 0 < d <= 1000 for d in depths):
        raise ManagementError("Indica de 1 a 100 niveles con profundidades válidas (hasta 1000 cm).")
    photo, status = _photo(values.get("photo", "")), _status(values.get("status", "Activo"))
    with db.get_conn() as conn:
        from catalog_service import lock_catalog
        lock_catalog(conn)
        before = _row(conn, "management_shelf_types", "id", type_id, lock=True) if type_id else None
        if before:
            _check_version(before, values["version"])
            if before['deleted']:
                raise ManagementError('La góndola fue eliminada. Actualiza el catálogo.', 409)
        kind = values.get('kind', before['kind'] if before else 'Estante')
        supplier = _text(values.get('supplier', before['supplier'] if before else ''), 'Proveedor/fabricante', 160)
        height = values.get('height_cm', before['height_cm'] if before else None)
        if kind not in ('Estante', 'Vin', 'Vitrina'):
            raise ManagementError('Selecciona Estante, Vin o Vitrina.')
        if kind != 'Estante' and len(depths) != 1:
            raise ManagementError('Vin y Vitrina requieren una sola profundidad.')
        if kind == 'Vitrina':
            height = None
        elif height is not None:
            if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height) or not 0 < height <= 1000:
                raise ManagementError('El alto debe ser mayor a 0 y hasta 1000 cm.')
        elif 'kind' in values:
            raise ManagementError('Indica el alto de la góndola en centímetros.')
        other = conn.execute("SELECT id FROM management_shelf_types WHERE LOWER(name) = LOWER(?) AND deleted=0", (name,)).fetchone()
        if other and other["id"] != type_id:
            raise ManagementError("Ya existe un tipo con ese nombre.", 409)
        now = db.now_iso()
        if before:
            conn.execute("UPDATE management_shelf_types SET name = ?, width_cm = ?, depths_json = ?, photo = ?, status = ?, version = version + 1, updated_at = ? WHERE id = ?", (name, width, json.dumps(depths), photo, status, now, type_id))
        else:
            type_id = uuid.uuid4().hex
            conn.execute("INSERT INTO management_shelf_types (id, name, width_cm, depths_json, photo, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (type_id, name, width, json.dumps(depths), photo, status, now, now))
        conn.execute('UPDATE management_shelf_types SET kind=?, supplier=?, height_cm=? WHERE id=?',
                     (kind, supplier, height, type_id))
        after = _row(conn, "management_shelf_types", "id", type_id)
        _audit(conn, actor, "shelf-type.update" if before else "shelf-type.create", type_id, before, after)
    return _type_public(after)


def delete_type(type_id, version, actor):
    from catalog_service import lock_catalog
    with db.get_conn() as conn:
        lock_catalog(conn)
        before = _row(conn, 'management_shelf_types', 'id', type_id, lock=True)
        _check_version(before, version)
        if before['deleted']:
            raise ManagementError('La góndola ya fue eliminada.', 409)
        for assignment in conn.execute('SELECT * FROM management_assignments WHERE type_id=?', (type_id,)).fetchall():
            _audit(conn, actor, 'assignment.type-delete', assignment['store_code'], assignment,
                   {'type_id':type_id, 'quantity':0})
        conn.execute("UPDATE management_shelf_types SET deleted=1,status='Inactivo',version=version+1,updated_at=? WHERE id=?",
                     (db.now_iso(), type_id))
        conn.execute('UPDATE management_instances SET active=0,version=version+1 WHERE type_id=? AND active=1', (type_id,))
        conn.execute('UPDATE management_assignments SET quantity=0,version=version+1,updated_at=? WHERE type_id=?',
                     (db.now_iso(), type_id))
        _audit(conn, actor, 'shelf-type.delete', type_id, before, _row(conn, 'management_shelf_types', 'id', type_id))
    return {'deleted': True, 'id': type_id}


def _assignment(conn, store_code, type_id, version):
    row = conn.execute("SELECT * FROM management_assignments WHERE store_code = ? AND type_id = ?", (store_code, type_id)).fetchone()
    before = dict(row) if row else None
    if (before["version"] if before else 0) != version:
        raise ManagementError("La asignación cambió en otra sesión. Actualiza las cantidades.", 409)
    return before


def _write_assignment(conn, store_code, type_id, quantity, before):
    if before:
        conn.execute("UPDATE management_assignments SET quantity = ?, version = version + 1, updated_at = ? WHERE store_code = ? AND type_id = ?", (quantity, db.now_iso(), store_code, type_id))
    else:
        conn.execute("INSERT INTO management_assignments (store_code, type_id, quantity, updated_at) VALUES (?, ?, ?, ?)", (store_code, type_id, quantity, db.now_iso()))


def _set_quantity(conn, store_code, type_id, quantity, version, actor):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= 10000:
        raise ManagementError("La cantidad debe ser un entero entre 0 y 10000.")
    store = _row(conn, "management_stores", "code", store_code, lock=True)
    shelf = _row(conn, "management_shelf_types", "id", type_id, lock=True)
    before = _assignment(conn, store_code, type_id, version)
    old_quantity = before["quantity"] if before else 0
    if quantity > old_quantity and (store["deleted"] or store["status"] != "Activo" or shelf["status"] != "Activo" or shelf["deleted"]):
        raise ManagementError("Activa el PDV y el tipo de góndola antes de aumentar su cantidad.", 409)
    instances = [dict(r) for r in conn.execute("SELECT * FROM management_instances WHERE store_code = ? AND type_id = ? ORDER BY number", (store_code, type_id)).fetchall()]
    instances.sort(key=lambda item: (not item["active"], item["number"]))
    for index, instance in enumerate(instances):
        active = int(index < quantity)
        if instance["active"] != active:
            conn.execute("UPDATE management_instances SET active = ?, version = version + 1 WHERE id = ?", (active, instance["id"]))
    next_number = max((i["number"] for i in instances), default=0) + 1
    for number in range(next_number, next_number + max(0, quantity - len(instances))):
        instance_id, point_id = uuid.uuid4().hex, "SB-INF-" + uuid.uuid4().hex[:16]
        now = db.now_iso()
        conn.execute("INSERT INTO points (id, name, created_at, store_id, gondola_id) VALUES (?, ?, ?, ?, ?)", (point_id, f'{store["name"]} · {shelf["name"]} #{number}', now, store_code, f'{shelf["name"]} #{number}'))
        conn.execute("INSERT INTO management_instances (id, store_code, type_id, number, point_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (instance_id, store_code, type_id, number, point_id, now))
    _write_assignment(conn, store_code, type_id, quantity, before)
    _audit(conn, actor, "assignment.quantity", store_code, before, {"type_id": type_id, "quantity": quantity})


def set_quantity(store_code, type_id, quantity, version, actor):
    from catalog_service import lock_catalog
    with db.get_conn() as conn:
        lock_catalog(conn)
        _set_quantity(conn, store_code, type_id, quantity, version, actor)
    return infrastructure_state(store_code)


def link_existing(store_code, type_id, point_id, version, actor):
    from catalog_service import lock_catalog
    with db.get_conn() as conn:
        lock_catalog(conn)
        store = _row(conn, "management_stores", "code", store_code, lock=True)
        shelf = _row(conn, "management_shelf_types", "id", type_id, lock=True)
        before = _assignment(conn, store_code, type_id, version)
        if store["deleted"] or store["status"] != "Activo" or shelf["status"] != "Activo" or shelf["deleted"]:
            raise ManagementError("Activa el PDV y el tipo antes de vincular.", 409)
        point = _row(conn, "points", "id", point_id)
        if point["store_id"] != store_code:
            raise ManagementError("La góndola debe pertenecer al PDV seleccionado.")
        if conn.execute("SELECT id FROM management_instances WHERE point_id = ?", (point_id,)).fetchone():
            raise ManagementError("Esa góndola ya está vinculada a un tipo.", 409)
        quantity = (before["quantity"] if before else 0) + 1
        if quantity > 10000:
            raise ManagementError("Máximo 10000 góndolas por tipo y PDV.")
        number = conn.execute("SELECT MAX(number) AS n FROM management_instances WHERE store_code = ? AND type_id = ?", (store_code, type_id)).fetchone()["n"] or 0
        conn.execute("INSERT INTO management_instances (id, store_code, type_id, number, point_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (uuid.uuid4().hex, store_code, type_id, number + 1, point_id, db.now_iso()))
        _write_assignment(conn, store_code, type_id, quantity, before)
        _audit(conn, actor, "instance.link-existing", store_code, None, {"point_id": point_id, "type_id": type_id})
    return infrastructure_state(store_code)


def save_instance(instance_id, values, actor):
    label = _text(values.get("label", ""), "Etiqueta", 120)
    note = _text(values.get("note", ""), "Nota", 1000)
    with db.get_conn() as conn:
        before = _row(conn, "management_instances", "id", instance_id, lock=True)
        _check_version(before, values["version"])
        conn.execute("UPDATE management_instances SET label = ?, note = ?, version = version + 1 WHERE id = ?", (label, note, instance_id))
        _audit(conn, actor, "instance.label", before["store_code"], before, {"id": instance_id, "label": label, "note": note})
    return infrastructure_state(before["store_code"])


def infrastructure_state(store_code=None):
    stores, types = list_stores(include_deleted=True), list_types()
    with db.get_conn() as conn:
        assignments = [dict(r) for r in conn.execute("SELECT * FROM management_assignments ORDER BY store_code, type_id").fetchall()]
        instances = [dict(r) for r in conn.execute("SELECT i.*, t.name AS type_name, p.name AS point_name, p.planogram_id, (SELECT COUNT(*) FROM readings r WHERE r.point_id = i.point_id) AS readings_count FROM management_instances i JOIN points p ON p.id = i.point_id LEFT JOIN management_shelf_types t ON t.id=i.type_id ORDER BY i.store_code, i.type_id, i.number").fetchall()]
        unlinked = [dict(r) for r in conn.execute("SELECT p.id, p.name, p.store_id, p.planogram_id, (SELECT COUNT(*) FROM readings r WHERE r.point_id = p.id) AS readings_count FROM points p LEFT JOIN management_instances i ON p.id = i.point_id WHERE i.id IS NULL AND p.store_id IS NOT NULL AND p.id NOT LIKE 'SB-MANUAL-%' ORDER BY p.store_id, p.id").fetchall()]
    if store_code:
        assignments = [r for r in assignments if r["store_code"] == store_code]
        instances = [r for r in instances if r["store_code"] == store_code]
        unlinked = [r for r in unlinked if r["store_id"] == store_code]
    return {"stores": stores, "types": types, "assignments": assignments, "instances": instances, "unlinked_points": unlinked}


def annotate_points(points):
    with db.get_conn() as conn:
        stores = {r["code"]: dict(r) for r in conn.execute("SELECT code, name, status, deleted FROM management_stores").fetchall()}
        instances = {r["point_id"]: dict(r) for r in conn.execute("SELECT i.*, t.name AS type_name, t.width_cm, t.height_cm, t.kind, t.depths_json, t.status AS type_status FROM management_instances i JOIN management_shelf_types t ON i.type_id = t.id").fetchall()}
        shared_plans={r['plan_id'] for r in conn.execute('SELECT plan_id FROM management_plan_scope_state').fetchall()}
        plans = {}
        for plan_id in {p.get("planogram_id") for p in points if p.get("planogram_id")}:
            row = conn.execute("SELECT data_json FROM management_planograms WHERE id = ?", (plan_id,)).fetchone()
            if row:
                meta = json.loads(row["data_json"])
                plans[plan_id] = {"status": meta.get("status", "Activo"), "store_code": meta.get("store_code"),
                                  "legacy_point_ids": meta.get("legacy_point_ids") or [], "category": meta.get("category", ""), "subcategories": meta.get("subcategories", [])}
    result = []
    for point in points:
        point = dict(point)
        store, instance = stores.get(point.get("store_id")), instances.get(point["id"])
        available = not store or (not store["deleted"] and store["status"] == "Activo")
        if point['id'].startswith('SB-MANUAL-'):
            available = False
        plan = plans.get(point.get("planogram_id"))
        if plan and point.get("planogram_id") not in shared_plans:
            available = available and plan["status"] == "Activo" and (plan["store_code"] == point.get("store_id") or point["id"] in plan.get("legacy_point_ids", []))
        context = None
        if instance:
            available = available and bool(instance["active"]) and instance["type_status"] == "Activo"
            context = {key: instance[key] for key in ("id", "type_id", "type_name", "number", "label", "note", "width_cm", "height_cm", "kind")}
            context["depths"] = json.loads(instance["depths_json"])
        point.update({"can_capture": bool(available), "infrastructure": context})
        if plan and point.get('planogram_id') not in shared_plans:
            point['planogram_classification'] = {key: plan.get(key, '' if key == 'category' else []) for key in ('category', 'subcategories')}
        if store:
            point["store_name"] = store["name"]
        result.append(point)
    return result


def capture_context(point_id):
    with db.get_conn() as conn:
        point = _row(conn, "points", "id", point_id)
    annotated = annotate_points([point])[0]
    with db.get_conn() as conn:
        shared=conn.execute("SELECT 1 FROM management_plan_scope_state WHERE plan_id=?",(point.get("planogram_id"),)).fetchone()
    if point.get("planogram_id") and not shared:
        from catalog_service import validate_assignment
        validate_assignment(point["planogram_id"], point.get("store_id"), point_id)
    if not annotated["can_capture"]:
        raise ManagementError("El PDV, el tipo o esta góndola están inactivos. Consulta el historial o pide al administrador que revise la asignación.", 409)
    return annotated["infrastructure"]
