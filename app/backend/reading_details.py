"""Versioned manual SKU observations, independent of the image model results."""
import json
import catalog_service
import db
from infrastructure import ManagementError, _audit, _row
from manual_metrics import calculate

FLAGS = ('scopeConfirmed', 'expectedConfirmed', 'comparisonConfirmed')


def empty(instance=None):
    return {'details': [], 'shelfInstanceId': instance, 'shelfLabel': '',
            **dict.fromkeys(FLAGS, False), 'source': 'manual'}


def read(reading_id):
    with db.get_conn() as conn:
        # A single statement observes details and approval at the same committed version.
        reading = conn.execute(
            'SELECT r.planogram_id, r.plan_snapshot_json, d.data_json, d.version AS detail_version, '
            'd.updated_by AS detail_author, d.updated_at AS detail_date, i.id AS instance_id, i.label AS instance_label, p.name AS point_name, '
            'v.status, v.note, v.version AS review_version, v.updated_by AS reviewer, v.updated_at AS review_date '
            'FROM readings r JOIN points p ON p.id = r.point_id LEFT JOIN management_reading_details d ON d.reading_id = r.id '
            'LEFT JOIN management_reading_reviews v ON v.reading_id = r.id '
            'LEFT JOIN management_instances i ON i.point_id = r.point_id WHERE r.id = ?', (reading_id,)).fetchone()
    if not reading:
        raise ManagementError('Medición no encontrada.', 404)
    data = json.loads(reading['data_json']) if reading['data_json'] else empty(reading['instance_id'])
    if not reading['data_json'] and reading['instance_id']:
        data['shelfLabel'] = reading['instance_label'] or reading['point_name']
    review = {'reading_id': reading_id, 'status': reading['status'] or 'En revisión', 'note': reading['note'] or '',
              'version': reading['review_version'] or 0, 'updated_by': reading['reviewer'], 'updated_at': reading['review_date']}
    snapshot = json.loads(reading['plan_snapshot_json']) if reading['plan_snapshot_json'] else db.get_planogram(reading['planogram_id'])
    has_planogram = bool(snapshot)
    return {**data, 'version': reading['detail_version'] or 0, 'reviewVersion': review['version'],
            'updatedBy': reading['detail_author'], 'updatedAt': reading['detail_date'],
            'hasPlanogram': has_planogram, 'reviewStatus': review['status'], 'review': review,
            'metrics': calculate(data, has_planogram, review['status'] == 'Aprobado')}


def options(reading_id):
    with db.get_conn() as conn:
        reading = conn.execute('SELECT p.store_id FROM readings r JOIN points p ON p.id = r.point_id WHERE r.id = ?', (reading_id,)).fetchone()
        products = [{key: product.get(key, '') for key in ('id', 'sku', 'name', 'category', 'subBrand')}
                    for product in catalog_service.products(conn)]
        instances = [dict(row) for row in conn.execute(
            'SELECT i.id, i.label, i.active, i.number, p.name AS point_name, t.name AS type_name '
            'FROM management_instances i JOIN points p ON p.id = i.point_id '
            'JOIN management_shelf_types t ON t.id = i.type_id WHERE i.store_code = ? ORDER BY t.name, i.number',
            (reading['store_id'],)).fetchall()]
    products.sort(key=lambda product: (product['name'].casefold(), product['sku']))
    return {'products': products, 'instances': instances}


def validate(rows, flags, has_planogram):
    seen = set()
    for row in rows:
        key = (row['productId'], row['position'].casefold())
        if key in seen:
            raise ManagementError('Producto y posición duplicados.')
        seen.add(key)
        if row['present'] is False and row['faces'] is not None and row['faces'] > 0:
            raise ManagementError('Un producto ausente no puede tener caras visibles.')
        if row['present'] is True and row['faces'] == 0:
            raise ManagementError('Un producto presente debe tener al menos una cara o dejar el conteo sin evaluar.')
        if row['match'] != 'N/A' and not has_planogram:
            raise ManagementError('No hay planograma seleccionado para esta medición.')
    if flags['scopeConfirmed'] and (not rows or any(
        row['faces'] is None or row['present'] is None or row['ownership'] == 'Sin clasificar' for row in rows
    )):
        raise ManagementError('Para confirmar la cobertura completa, clasifica presencia, caras y propiedad de todos los productos observados.')
    if flags['expectedConfirmed'] and (not any(row['expected'] for row in rows) or any(
        row['expected'] and row['present'] is None for row in rows
    )):
        raise ManagementError('Completa la presencia de todos los productos esperados.')
    if flags['comparisonConfirmed'] and (not has_planogram or not any(row['match'] != 'N/A' for row in rows)):
        raise ManagementError('El cumplimiento requiere una referencia y posiciones evaluadas.')


def save(reading_id, payload, actor):
    with db.get_conn() as conn:
        catalog_service.lock_catalog(conn)
        reading = _row(conn, 'readings', 'id', reading_id, lock=True)
        stored = conn.execute('SELECT * FROM management_reading_details WHERE reading_id = ?', (reading_id,)).fetchone()
        review = conn.execute('SELECT version FROM management_reading_reviews WHERE reading_id = ?', (reading_id,)).fetchone()
        if payload['version'] != (stored['version'] if stored else 0) or payload['reviewVersion'] != (review['version'] if review else 0):
            raise ManagementError('La medición o su detalle cambió. Recarga los valores guardados antes de editar.', 409)
        point = _row(conn, 'points', 'id', reading['point_id'])
        instance = _row(conn, 'management_instances', 'id', payload['shelfInstanceId'])
        if not point['store_id'] or instance['store_code'] != point['store_id']:
            raise ManagementError('Selecciona una góndola física del PDV de esta medición.')
        products = {product['id']: product for product in catalog_service.products(conn)}
        previous = json.loads(stored['data_json']) if stored else empty()
        historical = {row['productId']: row for row in previous['details']}
        rows = []
        for value in payload['details']:
            product = products.get(value['productId']) or historical.get(value['productId'])
            if not product:
                raise ManagementError('Selecciona un producto del catálogo.')
            rows.append({**value, 'name': product['name'], 'sku': product.get('sku', ''),
                         'category': product.get('category', ''), 'source': 'manual'})
        flags = {key: payload[key] for key in FLAGS}
        snapshot = json.loads(reading['plan_snapshot_json']) if reading['plan_snapshot_json'] else db.get_planogram(reading['planogram_id'])
        validate(rows, flags, bool(snapshot))
        data = {'details': rows, **flags, 'shelfInstanceId': instance['id'],
                'shelfLabel': instance['label'] or f"{point['store_id']} · góndola {instance['number']}", 'source': 'manual'}
        conn.execute('INSERT INTO management_reading_details (reading_id, data_json, version, updated_by, updated_at) '
                     'VALUES (?, ?, ?, ?, ?) ON CONFLICT (reading_id) DO UPDATE SET data_json = excluded.data_json, '
                     'version = excluded.version, updated_by = excluded.updated_by, updated_at = excluded.updated_at',
                     (reading_id, json.dumps(data), payload['version'] + 1, actor, db.now_iso()))
        if snapshot and not reading['plan_snapshot_json']:
            conn.execute('UPDATE readings SET plan_snapshot_json = ? WHERE id = ?', (json.dumps(snapshot), reading_id))
        db.invalidate_measurement_review(conn, reading_id, invalidate_details=False)
        _audit(conn, actor, 'measurement.product-details', str(reading_id), previous, data)
    return read(reading_id)
