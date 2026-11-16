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
