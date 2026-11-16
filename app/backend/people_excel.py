"""The previous Personas template imports records without granting new accounts."""
from datetime import date, datetime
import hashlib
import io
import json
import zipfile
from openpyxl import Workbook, load_workbook
from openpyxl.utils.datetime import from_excel
import db
import people_service as service
import profiles
from catalog_service import lock_catalog
from infrastructure import ManagementError
from store_excel import style

COLUMNS = ['Nombres','Apellido paterno','Apellido materno','Email','Fecha alta','Fecha baja','Estado','Nombre de usuario','Rol','Cargo','Código PDV']
FIELDS = ['names','paternal','maternal','email','startDate','endDate','status','username','role','position','storeCode']


def template_bytes():
    book = Workbook()
    sheet = book.active
    sheet.title = 'Personas'
    sheet.append(COLUMNS)
    style(sheet, [24,24,24,36,18,18,20,28,24,30,20])
    sheet.column_dimensions['K'].number_format = '@'
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def read_rows(content):
    if len(content) > 5 * 1024 * 1024:
        raise ManagementError('Usa un archivo .xlsx de hasta 5 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError('Archivo expandido demasiado grande')
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        try:
            if 'Personas' not in book.sheetnames:
                raise ManagementError('Falta la hoja Personas. Usa la plantilla.')
            sheet = book['Personas']
            if (sheet.max_row or 0) > 5001 or (sheet.max_column or 0) > 100:
                raise ManagementError('Máximo 5.000 filas y 100 columnas.')
            rows = list(sheet.iter_rows())
            headers = [str(cell.value or '').strip() for cell in rows[0]] if rows else []
            if any(column not in headers for column in COLUMNS) or len([h for h in headers if h]) != len(set(h for h in headers if h)):
                raise ManagementError('Faltan columnas o hay encabezados repetidos. Usa la plantilla.')
            result = []
            for number,row in enumerate(rows[1:],2):
                cells = [row[headers.index(column)] for column in COLUMNS]
                if all(cell.value in (None,'') for cell in cells):
                    continue
                error = 'No se permiten fórmulas en la ficha.' if any(cell.data_type == 'f' for cell in cells) else ''
                if any(not isinstance(cells[index].value,(str,type(None))) for index in (7,10)):
                    error = 'Nombre de usuario y Código PDV deben ser texto.'
                values = {}
                for field,cell in zip(FIELDS,cells):
                    value = cell.value
                    if field in ('startDate','endDate') and isinstance(value,(int,float)):
                        value = from_excel(value,book.epoch)
                    if isinstance(value,(datetime,date)):
                        value = value.date().isoformat() if isinstance(value,datetime) else value.isoformat()
                    values[field] = str(value).strip() if value is not None else ''
                result.append((number,values,error))
            if not result:
                raise ManagementError('El archivo no contiene personas.')
            return result
        finally:
            book.close()
    except ManagementError:
        raise
    except Exception as exc:
        raise ManagementError('No se pudo leer el Excel. Usa un .xlsx válido.') from exc


def transfer(content, actor, commit=False, version=None):
    from infrastructure import bootstrap_legacy_stores
    bootstrap_legacy_stores()
    with db.get_conn() as conn:
        if commit:
            lock_catalog(conn)
        people = service.list_people(conn)
        stores = [dict(row) for row in conn.execute('SELECT code,deleted FROM management_stores ORDER BY code').fetchall()]
        token = hashlib.sha256(content + json.dumps({'people':people,'stores':stores},sort_keys=True).encode()).hexdigest()
        if commit and token != version:
            raise ManagementError('Las fichas, permisos, PDV o el archivo cambiaron. Vuelve a validar.',409)
        existing = {person['username'].casefold():person for person in people}
        known = {store['code'].casefold():store['code'] for store in stores if not store['deleted']}
        records, errors, usernames, emails = [], [], set(), set()
        for number,values,error in read_rows(content):
            try:
                if error:
                    raise ManagementError(error)
                username = values['username'].lower()
                old = existing.get(username)
                code = values.pop('storeCode')
                if code and code.casefold() not in known:
                    raise ManagementError('Código PDV no registrado.')
                values.update(role={name:key for key,name in profiles.PROFILE_NAMES.items()}.get(values['role'],values['role']),
                              storeCodes=[known[code.casefold()]] if code else [], allStores=not code and values['role'] in ('Analista','analyst'))
                data = service.normalize(values)
                if data['username'] in usernames or data['email'].casefold() in emails:
                    raise ManagementError('Nombre de usuario o email repetido en el archivo.')
                usernames.add(data['username']); emails.add(data['email'].casefold())
                if any((person.get('email') or '').casefold() == data['email'].casefold() and person['username'].casefold() != username for person in people):
                    raise ManagementError('Email asignado a otra persona.')
                if old and old['access_enabled'] and any(data[key] != old[key] for key in ('role','status','storeCodes','allStores','endDate')):
                    raise ManagementError('Cambia el rol, estado o acceso a PDV de una cuenta desde Editar usuario.')
                records.append({'data':data,'id':old['id'] if old else None,'version':old['version'] if old else None})
            except (ValueError,TypeError) as exc:
                errors.append({'sheet':'Personas','row':number,'message':str(exc)})
        creates = sum(item['id'] is None for item in records)
        if len(people) + creates > 5000:
            errors.append({'sheet':'Personas','row':1,'message':'Máximo 5000 personas en el catálogo.'})
        if commit:
            if errors:
                raise ManagementError('Corrige todas las filas antes de importar.')
            for record in records:
                service.save(record['data'], actor, record['id'], record['version'], conn=conn)
        return {'version':token,'creates':creates,'updates':len(records)-creates,'errors':errors,'committed':commit,
                'sample':[{**record['data'],'action':'Actualizar' if record['id'] else 'Crear ficha'} for record in records[:20]]}
