"""Person records and their real account permissions share one transaction."""
from datetime import date
import json
import re
import uuid
import auth
import db
import profiles
from catalog_service import lock_catalog
from infrastructure import ManagementError, _audit, _text

STATUSES = ('Vigente', 'Suspendido', 'De baja')


def account_status(username):
    with db.get_conn() as conn:
        row = conn.execute('SELECT data_json FROM management_people WHERE LOWER(username)=LOWER(?)', (username,)).fetchone()
    return json.loads(row['data_json']).get('status', 'Vigente') if row else 'Vigente'


def list_people(conn=None):
    if conn is None:
        with db.get_conn() as connection:
            return list_people(connection)
    records = {row['username'].casefold():dict(row) for row in conn.execute('SELECT * FROM management_people').fetchall()}
    accounts = [dict(row) for row in conn.execute('SELECT * FROM users').fetchall()]
    hidden = {row['username'].casefold() for row in accounts if row['is_internal'] or not row['portal_access']}
    users = {row['username'].casefold():row for row in accounts if row['username'].casefold() not in hidden}
    records = {key:row for key,row in records.items() if key not in hidden}
    result = []
    for key in records.keys() | users.keys():
        row, user = records.get(key), users.get(key)
        data = json.loads(row['data_json']) if row else {}
        role = profiles.profile_of(user) if user else data.get('role')
        codes = db._user_public(user)['store_ids'] if user else data.get('storeCodes', [])
        username = user['username'] if user else row['username']
        result.append({**data, 'id':row['id'] if row else 'account:' + username, 'username':username,
                       'name':data.get('name') or username, 'role':role, 'storeCodes':codes,
                       'allStores':role == 'analyst' and not codes if user else data.get('allStores', False),
                       'status':data.get('status', 'Vigente'), 'access_enabled':bool(user),
                       'version':row['version'] if row else user['auth_version'] + 1,
                       'needs_completion':not all(data.get(key) for key in ('names','paternal','email','position','startDate'))})
    return sorted(result, key=lambda item:(item['name'].casefold(), item['username']))


def find(conn, person_id):
    person = next((item for item in list_people(conn) if item['id'] == person_id), None)
    if person is None:
        raise ManagementError('La persona ya no está disponible. Actualiza la tabla.', 404)
    return person


def normalize(values):
    data = {key:_text(values.get(key, ''), label, maximum, required) for key,label,maximum,required in (
        ('names','Nombres',100,True), ('paternal','Apellido paterno',80,True), ('maternal','Apellido materno',80,False),
        ('email','Email',180,True), ('position','Cargo',120,True), ('username','Nombre de usuario',80,True))}
    data['username'] = data['username'].lower()
    if not re.fullmatch(r'[\w.@+-]{3,80}', data['username']):
        raise ManagementError('Nombre de usuario: usa entre 3 y 80 letras, números o los caracteres . @ + - _.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', data['email']):
        raise ManagementError('Ingresa un email válido.')
    data['status'] = 'Suspendido' if values.get('status') == 'En revisión' else values.get('status')
    data['role'] = values.get('role')
    if data['role'] not in profiles.PROFILES or data['status'] not in STATUSES:
        raise ManagementError('Selecciona un rol y estado válidos.')
    for key in ('startDate','endDate'):
        value = values.get(key, '')
        if key == 'endDate' and data['status'] != 'De baja':
            value = ''
        if value:
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                    raise ValueError()
                date.fromisoformat(value)
            except (ValueError, TypeError):
                raise ManagementError('Usa fechas válidas en formato AAAA-MM-DD.')
        data[key] = value
    if not data['startDate'] or (data['status'] == 'De baja' and not data['endDate']):
        raise ManagementError('Completa la fecha de alta y, para De baja, la fecha de baja.')
    if data['endDate'] and data['endDate'] < data['startDate']:
        raise ManagementError('La fecha de baja no puede ser anterior a la fecha de alta.')
    data['storeCodes'] = list(dict.fromkeys(str(code).strip().upper() for code in values.get('storeCodes', [])))
    data['allStores'] = bool(values.get('allStores')) and data['role'] == 'analyst'
    if data['role'] not in ('analyst','replenisher'):
        data['storeCodes'] = []
    if data['allStores']:
        data['storeCodes'] = []
    data['name'] = ' '.join(filter(None, (data['names'],data['paternal'],data['maternal'])))
    return data


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 512:
        raise ManagementError('La contraseña debe tener entre 12 y 512 caracteres.')
    return auth.hash_password(password)


def save(values, actor, person_id=None, version=None, enable_access=False, password='', conn=None):
    if conn is None:
        from infrastructure import bootstrap_legacy_stores
        bootstrap_legacy_stores()
        with db.get_conn() as connection:
            lock_catalog(connection)
            return save(values, actor, person_id, version, enable_access, password, connection)
    data = normalize(values)
    people = list_people(conn)
    before = find(conn, person_id) if person_id else None
    if before and before['version'] != version:
        raise ManagementError('La ficha o sus permisos cambiaron. Cierra y vuelve a abrir para actualizar.', 409)
    if before and before['access_enabled'] and before['username'] != data['username']:
        raise ManagementError('El nombre de usuario de una cuenta existente se conserva.')
    for other in people:
        if before and other['id'] == before['id']:
            continue
        if other['username'].casefold() == data['username'].casefold() or (other.get('email') or '').casefold() == data['email'].casefold():
            raise ManagementError('Ya existe una persona con ese usuario o email.', 409)
    if not before and len(people) >= 5000:
        raise ManagementError('Máximo 5000 personas.')
    user_row = conn.execute('SELECT * FROM users WHERE LOWER(username)=LOWER(?)', (data['username'],)).fetchone()
    user = dict(user_row) if user_row else None
    if user and (user.get('is_internal') or not user.get('portal_access',1)):
        raise ManagementError('Esta cuenta pertenece al equipo interno.',403)
    enabled = bool(user or enable_access)
    if data['username'] == actor.casefold() and before and (data['role'] != before['role'] or data['status'] != before['status']):
        raise ManagementError('No puedes cambiar tu propio rol ni desactivar o suspender tu acceso.', 403)
    preserve_scope = bool(user and before and data['role'] == before['role'] and data['status'] != 'Vigente')
    if preserve_scope:
        data['storeCodes'], data['allStores'] = before['storeCodes'], before['allStores']
    else:
        known = {row['code'].casefold():row['code'] for row in conn.execute('SELECT code FROM management_stores WHERE deleted=0').fetchall()}
        if any(code.casefold() not in known for code in data['storeCodes']):
            raise ManagementError('Selecciona PDV registrados en el catálogo.')
        data['storeCodes'] = [known[code.casefold()] for code in data['storeCodes']]
        if enabled and data['status'] == 'Vigente' and data['role'] in ('analyst','replenisher') and not data['storeCodes'] and not data['allStores']:
            raise ManagementError('Asigna al menos un PDV al analista o reponedor.')
    if user:
        kwargs = {}
        public = db._user_public(user)
        if profiles.profile_of(user) != data['role']:
            kwargs['role'] = data['role']
        if public['store_ids'] != data['storeCodes']:
            kwargs.update(set_store=True, store_ids=data['storeCodes'], store_id=data['storeCodes'][0] if len(data['storeCodes']) == 1 else None)
        if password:
            kwargs['password_hash'], kwargs['salt'] = password_hash(password)
        if kwargs:
            db.update_user(user['username'], conn=conn, **kwargs)
        if before and data['status'] != before['status']:
            conn.execute('UPDATE users SET auth_version=auth_version+1 WHERE username=?', (user['username'],))
    elif enabled:
        hashed, salt = password_hash(password)
        db.create_user(data['username'], hashed, salt, role=data['role'], store_ids=data['storeCodes'],
                       store_id=data['storeCodes'][0] if len(data['storeCodes']) == 1 else None, conn=conn)
    person_id = before['id'] if before else uuid.uuid4().hex
    next_version = before['version'] + 1 if before else 1
    conn.execute('INSERT INTO management_people (id,username,email,data_json,version,updated_at) VALUES(?,?,?,?,?,?) '
                 'ON CONFLICT(id) DO UPDATE SET username=excluded.username,email=excluded.email,data_json=excluded.data_json,version=excluded.version,updated_at=excluded.updated_at',
                 (person_id,data['username'],data['email'],json.dumps(data,ensure_ascii=False),next_version,db.now_iso()))
    after = find(conn, person_id)
    _audit(conn, actor, 'person.update' if before else 'person.create', person_id, before, after)
    return after


def delete(person_id, version, actor):
    with db.get_conn() as conn:
        lock_catalog(conn)
        before = find(conn, person_id)
        if before['version'] != version:
            raise ManagementError('La ficha cambió. Actualiza antes de eliminar.',409)
        if before['username'].casefold() == actor.casefold():
            raise ManagementError('No puedes eliminar tu propio usuario.',403)
        db.delete_user(before['username'], conn=conn)
        conn.execute('DELETE FROM management_people WHERE id=?', (person_id,))
        _audit(conn, actor, 'person.delete', person_id, before, None)
    return {'deleted':person_id}


def reset_password(person_id, version, password, actor):
    hashed, salt = password_hash(password)
    with db.get_conn() as conn:
        lock_catalog(conn)
        person = find(conn, person_id)
        if person['version'] != version:
            raise ManagementError('La cuenta cambió. Actualiza la ficha.',409)
        if not person['access_enabled']:
            raise ManagementError('Habilita primero el acceso desde Editar usuario.')
        db.update_user(person['username'], password_hash=hashed, salt=salt, conn=conn)
        _audit(conn, actor, 'person.password-reset', person_id, None, {'username':person['username']})
    return {'ok':True,'reauthenticate':person['username'] == actor}
