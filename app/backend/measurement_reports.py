"""Measurement history exports and approved-only performance, in Chilean local time."""
import csv
from datetime import date, datetime, timezone
import io
import json
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import db
import infrastructure
from infrastructure import ManagementError

STATES = ("En revisión", "Aprobado", "Rechazado")
HEADERS = ["ID", "PDV", "Nombre PDV", "Región", "Comuna", "Fecha", "Hora", "Puntaje", "Estado",
           "Observación", "Considerar en desempeño", "Medición hecha por", "Encargado de Local"]
FIELDS = ("id", "store_id", "store_name", "region", "commune", "date", "time", "score", "status",
          "note", "performance", "captured_by", "manager")
CHILE = ZoneInfo("America/Santiago")


def save_review(reading_id, status, note, version, actor):
    if status not in STATES:
        raise ManagementError("Selecciona un estado válido.")
    note = note.strip()
    if status == "Rechazado" and not note:
        raise ManagementError("Indica el motivo del rechazo.")
    with db.get_conn() as conn:
        if db.USE_PG:
            conn.execute("SELECT id FROM readings WHERE id = ? FOR UPDATE", (reading_id,)).fetchone()
        else:
            conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT id FROM readings WHERE id = ?", (reading_id,)).fetchone():
            raise ManagementError("Medición no encontrada.", 404)
        current = conn.execute("SELECT version FROM management_reading_reviews WHERE reading_id = ?", (reading_id,)).fetchone()
        if (current["version"] if current else 0) != version:
            raise ManagementError("La medición cambió. Actualiza la lectura antes de guardar.", 409)
        conn.execute(
            "INSERT INTO management_reading_reviews (reading_id, status, note, version, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (reading_id) DO UPDATE SET status = excluded.status, note = excluded.note, version = excluded.version, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (reading_id, status, note, version + 1, actor, db.now_iso()),
        )
    return db.measurement_review(reading_id)


def local_datetime(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(CHILE)


def history(scope, store="", point="", start="", end="", status="", captured_by=None, include_details=False, include_alerts=False):
    try:
        for value in (start, end):
            if value:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError("Usa fechas YYYY-MM-DD")
    except ValueError as exc:
        raise ManagementError("Selecciona fechas válidas.") from exc
    if start and end and start > end:
        raise ManagementError("La fecha Desde debe ser anterior o igual a Hasta.")
    if status and status not in STATES:
        raise ManagementError("Selecciona un estado válido.")
    stores = infrastructure.list_stores(include_deleted=True)
    by_store = {s["code"]: s for s in stores}
    where, params = db._scope_where(scope, "p.store_id")
    with db.get_conn() as conn:
        points = conn.execute(f"SELECT p.id, p.name, p.store_id FROM points p WHERE {where}", params).fetchall()
        allowed_stores = {p["store_id"] for p in points} | {s['code'] for s in stores if scope is None or s['code'] in scope}
        allowed_points = {p["id"] for p in points}
        if (store and store not in allowed_stores) or (point and point not in allowed_points):
            raise ManagementError("El PDV o la góndola está fuera de tu ámbito.", 403)
        if store:
            where += " AND p.store_id = ?"
            params = (*params, store)
        if point:
            where += " AND p.id = ?"
            params = (*params, point)
        if captured_by is not None:
            where += " AND r.captured_by = ?"
            params = (*params, captured_by)
        detail_fields = ', d.data_json AS manual_details, i.id AS instance_id' if include_details else ''
        detail_join = ' LEFT JOIN management_reading_details d ON d.reading_id = r.id LEFT JOIN management_instances i ON i.point_id = p.id ' if include_details else ''
        plan_ids = {row['id'] for row in conn.execute('SELECT id FROM planograms').fetchall()} if include_details else set()
        readings = conn.execute(
            "SELECT r.*, p.store_id, v.status AS review_status, v.note AS review_note, v.updated_by AS reviewed_by, v.updated_at AS reviewed_at " + detail_fields + " "
            "FROM readings r JOIN points p ON p.id = r.point_id "
            f"LEFT JOIN management_reading_reviews v ON v.reading_id = r.id {detail_join} WHERE {where} ORDER BY r.created_at DESC, r.id DESC",
            params,
        ).fetchall()
    rows = []
    for reading in readings:
        local = local_datetime(reading["created_at"])
        day = local.date().isoformat()
        state = reading["review_status"] or "En revisión"
        if (start and day < start) or (end and day > end) or (status and state != status):
            continue
        master = by_store.get(reading["store_id"], {})
        score = db.compute_shelf_standards(json.loads(reading["products_json"] or "[]"), reading["empty_space_pct"])
        paths = json.loads(reading["image_paths_json"] or "[]")
        if not paths and reading["image_path"]:
            paths = [reading["image_path"]]
        rows.append({"id": reading["id"], "point_id": reading["point_id"], "store_id": reading["store_id"] or "",
                     "image_url": "/uploads/" + paths[0] if paths else None, "facings": reading["total_facings"],
                     "store_name": master.get("name") or reading["store_id"] or "Sin PDV registrado",
                     "region": master.get("region", ""), "commune": master.get("commune", ""),
                     "date": day, "time": local.strftime("%H:%M hrs."), "score": score.get("overall_score"), "score_band": score.get('score_band'),
                     "status": state, "note": reading["review_note"] or "", "performance": "Sí" if state == "Aprobado" else "No",
                     "reviewed_at": reading['reviewed_at'],
                     "reviewed_by": reading['reviewed_by'] or '',
                     "captured_by": reading["captured_by"] or "Sin autor registrado", "manager": master.get("manager", "")})
        if include_alerts:
            rows[-1].update(reviewed_by=reading['reviewed_by'] or 'Sin dato', _alert_source={
                'empty_space_pct': reading['empty_space_pct'], 'products': json.loads(reading['products_json'] or '[]'),
                'context': json.loads(reading['capture_context_json']) if reading['capture_context_json'] else {}})
        if include_details:
            context = json.loads(reading['capture_context_json']) if reading['capture_context_json'] else {}
            rows[-1].update(_manual=json.loads(reading['manual_details']) if reading['manual_details'] else None,
                            _capture_context=context,
                            _products=json.loads(reading['products_json'] or '[]'), _created_at=reading['created_at'],
                            _instance_id=reading['instance_id'],
                            _brand_share=(json.loads(reading['capture_context_json']) if reading['capture_context_json'] else {}).get('brandShare'),
                            _has_planogram=bool(reading['plan_snapshot_json']) or reading['planogram_id'] in plan_ids)
    approved = [r for r in rows if r["status"] == "Aprobado"]
    scores = [r["score"] for r in approved if r["score"] is not None]
    average = round(sum(scores) / len(scores), 1) if scores else None
    from settings_service import score_band
    return {"rows": rows, "totals": {"measurements": len(rows), "approved": len(approved),
            "in_review": sum(r["status"] == "En revisión" for r in rows),
            "rejected": sum(r["status"] == "Rechazado" for r in rows),
            "average_score": average, "average_score_band": score_band(average)},
            "stores": sorted([{"code": code, "name": by_store.get(code, {}).get("name") or code}
                              for code in allowed_stores if code], key=lambda s: s["name"].casefold()),
            "points": sorted([dict(p) for p in points], key=lambda p: p["name"].casefold())}


def csv_bytes(rows):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(HEADERS)
    for row in rows:
        values = []
        for field in FIELDS:
            value = row[field]
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def xlsx_bytes(rows):
    book = Workbook()
    sheet = book.active
    sheet.title = "Mediciones"
    sheet.append(HEADERS)
    for row in rows:
        values = [row[field] for field in FIELDS]
        values[5] = date.fromisoformat(row["date"])
        values[6] = datetime.strptime(row["time"], "%H:%M hrs.").time()
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.cell(sheet.max_row, 6).number_format = "yyyy-mm-dd"
        sheet.cell(sheet.max_row, 7).number_format = 'hh:mm "hrs."'
        sheet.cell(sheet.max_row, 8).number_format = "0.0"
    for cell in sheet[1]:
        cell.font = Font(name="Calibri", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="143445")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for index, width in enumerate((12, 18, 32, 30, 24, 16, 16, 14, 18, 48, 25, 28, 28), 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[1].height = 32
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def reading_xlsx_bytes(reading, row):
    book = load_workbook(io.BytesIO(xlsx_bytes([row])))
    context = reading.get('infrastructure') or {}
    comparison = reading.get('compliance') or {}
    summary = book.active
    summary.title = 'Medición'
    capture = book.create_sheet('Captura')
    capture.append(['Campo', 'Valor'])
    for label, value in [('Categoría de captura', context.get('category', '')),
                         ('Subcategoría de captura', context.get('subcategory', '')),
                         ('Ancho metro-góndola (m)', reading.get('linear_meters')),
                         ('Planograma', comparison.get('planogram_name', 'Sin planograma')),
                         ('Coincidencia (%)', comparison.get('compliance_pct'))]:
        capture.append([label, value])
    products = book.create_sheet('Productos detectados')
    products.append(['Producto', 'Marca', 'Categoría detectada', 'Nivel', 'Posición', 'Caras', 'Estado', 'Confianza (%)'])
    for product in reading.get('products', []):
        confidence = product.get('confidence')
        products.append([product.get('product'), product.get('brand'), product.get('category'), product.get('shelf_level'),
                         product.get('position_index'), product.get('facings'), product.get('planogram_status') or product.get('match_status'),
                         round(confidence * 100, 2) if isinstance(confidence, (float, int)) else None])
    if comparison:
        plan = book.create_sheet('Comparación planograma')
        plan.append(['Producto esperado', 'Nivel', 'Posición', 'Caras esperadas', 'Caras detectadas', 'Estado'])
        for item in comparison.get('items', []):
            plan.append([item.get('title'), item.get('band'), item.get('position_in_section'), item.get('expected_facings'),
                         item.get('detected_facings'), item.get('status')])
    for sheet in book:
        for cells in sheet:
            for cell in cells:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
                if isinstance(cell.value, str):
                    cell.data_type = 's'
        if sheet is summary:
            continue
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='143445')
        for index in range(1, sheet.max_column + 1):
            sheet.column_dimensions[get_column_letter(index)].width = 52 if index == 1 or sheet is capture else 23
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()
