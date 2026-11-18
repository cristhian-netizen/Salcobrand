"""Observed findings and rejection follow-up with persisted, scoped alert states."""
import db
import infrastructure
from infrastructure import ManagementError, _row, _audit
import measurement_reports
import profiles
from alert_findings import findings, source_from_reading


def public(row):
    return {key: value for key, value in row.items() if not key.startswith('_')}


def summary(user, point='', store='', start='', end='', status='Pendiente'):
    if status not in ('', 'Pendiente', 'Resuelta'):
        raise ManagementError('Selecciona un estado de alerta válido.')
    if profiles.profile_of(user) == 'admin':
        return administrative_summary(store)
    scope = profiles.store_scope(user)
    author = profiles.reading_author(user)
    history = measurement_reports.history(scope, store=store, point=point, start=start, end=end,
                                         captured_by=author, include_alerts=True)
    where, params = db._scope_where(scope, 'p.store_id')
    if author is not None:
        where += ' AND r.captured_by = ?'
        params = (*params, author)
    with db.get_conn() as conn:
        stored = conn.execute('SELECT a.* FROM management_reading_alerts a JOIN readings r ON r.id = a.reading_id '
                              f'JOIN points p ON p.id = r.point_id WHERE {where}', params).fetchall()
    states = {(row['reading_id'], row['kind']): dict(row) for row in stored}
    alerts = []
    for reading in history['rows']:
        for item in findings(reading['_alert_source']):
            state = states.get((reading['id'], item['kind']))
            effective = state['status'] if state and state['fingerprint'] == item['fingerprint'] else 'Pendiente'
            if not status or status == effective:
                alerts.append({**item, 'status': effective, 'version': state['version'] if state else 0,
                               'updated_by': state['updated_by'] if state else None, 'updated_at': state['updated_at'] if state else None,
                               'reading': public(reading)})
    rejected = [public(row) for row in history['rows'] if row['status'] == 'Rechazado']
    own = [row for row in rejected if row['captured_by'] == user['username']]
    other = [row for row in rejected if row['captured_by'] != user['username']]
    gaps = db.panel_summary(30, store_id=scope, captured_by=author)['points']
    gaps = infrastructure.annotate_points(gaps)
    gaps = [item for item in gaps if item.get('can_capture') is not False and item.get('performance')
            and (item['performance']['missing'] or item['performance']['low'])
            and (not point or item['id'] == point) and (not store or item['store_id'] == store)]
    gaps = [item for item in gaps if in_period(item['performance']['created_at'], start, end)]
    gaps.sort(key=lambda item: (-(item['performance'].get('impact_clp') or 0), -(item['performance'].get('missing') or 0)))
    suppliers = [] if profiles.profile_of(user) == 'replenisher' else db.list_supplier_stockouts(store_id=scope)
    suppliers = [item for item in suppliers if (not point or item['point_id'] == point)
                 and in_period(item['created_at'], start, end)]
    allowed_points = {item['id'] for item in history['points'] if not store or item['store_id'] == store}
    suppliers = [item for item in suppliers if item['point_id'] in allowed_points]
    return {'findings': alerts, 'rejected': rejected, 'own_rejected': own, 'other_rejected': other,
            'points': history['points'], 'stores': history['stores'], 'gaps': gaps, 'suppliers': suppliers}


def in_period(created_at, start, end):
    day = measurement_reports.local_datetime(created_at).date().isoformat()
    return (not start or day >= start) and (not end or day <= end)


def save(reading_id, kind, payload, actor):
    with db.get_conn() as conn:
        reading = _row(conn, 'readings', 'id', reading_id, lock=True)
        item = next((item for item in findings(source_from_reading(reading)) if item['kind'] == kind), None)
        stored = conn.execute('SELECT * FROM management_reading_alerts WHERE reading_id = ? AND kind = ?', (reading_id, kind)).fetchone()
        version = stored['version'] if stored else 0
        if not item or item['fingerprint'] != payload['fingerprint'] or version != payload['version']:
            raise ManagementError('El hallazgo cambió o fue actualizado por otra persona. Actualiza las alertas antes de guardar.', 409)
        updated = {**item, 'reading_id': reading_id, 'status': payload['status'], 'version': version + 1,
                   'updated_by': actor, 'updated_at': db.now_iso()}
        conn.execute('INSERT INTO management_reading_alerts (reading_id, kind, fingerprint, status, version, updated_by, updated_at) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (reading_id, kind) DO UPDATE SET fingerprint=excluded.fingerprint, '
                     'status=excluded.status, version=excluded.version, updated_by=excluded.updated_by, updated_at=excluded.updated_at',
                     (reading_id, kind, item['fingerprint'], updated['status'], updated['version'], actor, updated['updated_at']))
        _audit(conn, actor, 'alert.status', f'{reading_id}:{kind}', dict(stored) if stored else None, updated)
    return updated


def administrative_summary(store=''):
    from datetime import datetime, timezone
    import people_service
    import settings_service
    parameters = settings_service.read()['state']['alertParameters']
    now = datetime.fromisoformat(db.now_iso().replace('Z', '+00:00'))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    stores = [s for s in infrastructure.list_stores() if s['status'] == 'Activo']
    if store and store not in {s['code'] for s in stores}:
        raise ManagementError('El punto de venta no está disponible.', 404)
    people = [p for p in people_service.list_people() if p['access_enabled'] and p['status'] == 'Vigente'
              and (not p.get('startDate') or p['startDate'] <= now.date().isoformat())]
    def assigned(code, role):
        return [p['name'] for p in people if p['role'] == role and (p.get('allStores') or code in p['storeCodes'])]
    def elapsed(value):
        return (now - measurement_reports.local_datetime(value)).total_seconds() / 86400
    unassigned, stale, pending = [], [], []
    with db.get_conn() as conn:
        rows = conn.execute("SELECT r.id, r.created_at, r.captured_by, p.store_id, v.status FROM readings r JOIN points p ON p.id=r.point_id LEFT JOIN management_reading_reviews v ON v.reading_id=r.id").fetchall()
    for local in stores:
        if store and local['code'] != store:
            continue
        code = local['code']
        analysts, replenishers = assigned(code, 'analyst'), assigned(code, 'replenisher')
        base = {'store_id': code, 'store_name': local['name'], 'region': local['region'], 'commune': local['commune']}
        missing = [label for label, values in [('Analista', analysts), ('Reponedor', replenishers)] if not values]
        if missing:
            unassigned.append({**base, 'missing': missing, 'analysts': analysts, 'replenishers': replenishers})
        readings = [r for r in rows if r['store_id'] == code]
        latest = max((r['created_at'] for r in readings), key=measurement_reports.local_datetime, default=None)
        age = elapsed(latest or local['created_at'])
        if age > parameters['noMeasurementDays']:
            stale.append({**base, 'last_measurement': latest, 'days_elapsed': int(age)})
        for reading in readings:
            age = elapsed(reading['created_at'])
            if (reading['status'] or 'En revisión') == 'En revisión' and age > parameters['reviewDays']:
                pending.append({**base, 'id': reading['id'], 'created_at': reading['created_at'],
                                'captured_by': reading['captured_by'] or 'Sin autor registrado', 'days_elapsed': int(age)})
    pending.sort(key=lambda r: (-r['days_elapsed'], r['id']))
    stale.sort(key=lambda r: (-r['days_elapsed'], r['store_name']))
    return {'mode': 'administrative', 'parameters': parameters, 'unassigned_stores': unassigned,
            'overdue_reviews': pending, 'inactive_stores': stale, 'stores': stores,
            'findings': [], 'rejected': [], 'own_rejected': [], 'other_rejected': [], 'points': [], 'gaps': [], 'suppliers': []}
