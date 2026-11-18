"""PDV-only XLSX imports and the original PDV/Gondolas export contract."""
import csv
import hashlib
import io
import json
import zipfile
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
import db
import infrastructure as service
from infrastructure import ManagementError
from catalog_service import lock_catalog
from settings_service import read as read_settings

COLUMNS = ['Código PDV', 'Nombre local', 'Tipo PDV', 'Descripción', 'Región', 'Comuna', 'Dirección', 'Encargado de Local', 'Estado']
FIELDS = ['code', 'name', 'store_type', 'description', 'region', 'commune', 'address', 'manager', 'status']
REL_COLUMNS = ['Código PDV', 'Nombre/código góndola', 'Cantidad']


def append_text_row(sheet, values):
    sheet.append(values)
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = 's'
        cell.alignment = Alignment(vertical='top', wrap_text=True)


def style(sheet, widths):
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    for cell in sheet[1]:
        cell.font = Font(name='Calibri', bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='143445')
        cell.alignment = Alignment(vertical='center', wrap_text=True)
    sheet.row_dimensions[1].height = 32
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    sheet.column_dimensions['A'].number_format = '@'


def workbook_bytes(template=False, search="", region="", commune="", status="", include_deleted=False):
    service.bootstrap_legacy_stores()
    book = Workbook()
    sheet = book.active
    sheet.title = 'PDV'
    sheet.append(COLUMNS)
    with db.get_conn() as conn:
        stores = [] if template else conn.execute('SELECT * FROM management_stores' + ('' if include_deleted else ' WHERE deleted=0') + ' ORDER BY LOWER(name),code').fetchall()
        stores = [s for s in stores if (not region or s['region'] == region) and (not commune or s['commune'] == commune) and (not status or s['status'] == status) and search.casefold() in ' '.join(str(s[k]) for k in ('code','name','commune','address','description')).casefold()]
        for store in stores:
            append_text_row(sheet, [store[field] for field in FIELDS])
            sheet.cell(sheet.max_row, 1).number_format = '@'
        if not template:
            relations = book.create_sheet('Gondolas')
            relations.append(REL_COLUMNS)
            for row in conn.execute('SELECT a.store_code,t.name,a.quantity FROM management_assignments a '
                                    'JOIN management_shelf_types t ON t.id=a.type_id '
                                    'JOIN management_stores s ON s.code=a.store_code WHERE s.deleted=0 '
                                    'ORDER BY a.store_code,t.name').fetchall():
                if row['store_code'] in {s['code'] for s in stores}:
                    append_text_row(relations, [row['store_code'],row['name'],row['quantity']])
            style(relations, [20,42,16])
    style(sheet, [20,34,26,44,36,26,44,30,18])
    states = DataValidation(type='list', formula1='"Activo,Inactivo"')
    sheet.add_data_validation(states)
    states.add('I2:I5001')
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def read_rows(content):
    if len(content) > 5 * 1024 * 1024:
        raise ManagementError('Usa un archivo .xlsx de hasta 5 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError('Archivo expandido demasiado grande')
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        try:
            if 'PDV' not in book.sheetnames:
                raise ManagementError('Falta la hoja PDV. Usa la plantilla estándar.')
            sheet = book['PDV']
            if sheet.max_row > 5001 or sheet.max_column > 100:
                raise ManagementError('Máximo 5.000 filas y 100 columnas en la hoja PDV.')
            cells = list(sheet.iter_rows())
            aliases = {'Responsable':'Encargado de Local','Responsable de local':'Encargado de Local'}
            headers = [aliases.get(str(cell.value or '').strip(), str(cell.value or '').strip()) for cell in cells[0]] if cells else []
            names = [header for header in headers if header]
            if any(column not in headers for column in COLUMNS) or len(names) != len(set(names)):
                raise ManagementError('Faltan columnas o hay encabezados repetidos en PDV. Usa la plantilla.')
            result = []
            for number, row in enumerate(cells[1:], 2):
                selected = [row[headers.index(column)] for column in COLUMNS]
                if all(cell.value in (None,'') for cell in selected):
                    continue
                error = 'No se permiten fórmulas en los datos del PDV.' if any(cell.data_type == 'f' for cell in selected) else ''
                if not isinstance(selected[0].value, (str, type(None))):
                    error = 'Código PDV debe ser texto para conservar ceros iniciales.'
                values = {field:str(cell.value).strip() if cell.value is not None else '' for field,cell in zip(FIELDS,selected)}
                result.append((number,values,error))
            if not result:
                raise ManagementError('El archivo no contiene PDV.')
            return result
        finally:
            book.close()
    except ManagementError:
        raise
    except Exception as exc:
        raise ManagementError('No se pudo leer el Excel. Usa un archivo .xlsx válido.') from exc


def prepare(content, stores, types):
    current = {store['code'].casefold():store for store in stores}
    seen, records, errors = set(), [], []
    for number, values, error in read_rows(content):
        try:
            if error:
                raise ManagementError(error)
            code = service.store_code(values['code'])
            if code.casefold() in seen:
                raise ManagementError('Código PDV repetido en el archivo.')
            seen.add(code.casefold())
            previous = current.get(code.casefold())
            if previous and previous['deleted']:
                raise ManagementError('Restaura el PDV eliminado antes de actualizarlo.')
            record = {**service.store_data(values, types), 'code':previous['code'] if previous else code,
                      'version':previous['version'] if previous else None}
            records.append(record)
        except (ValueError,TypeError) as exc:
            errors.append({'sheet':'PDV','row':number,'message':str(exc)})
    return records, errors


def transfer(content, actor, commit=False, version=None):
    service.bootstrap_legacy_stores()
    with db.get_conn() as conn:
        if commit:
            lock_catalog(conn)
        stores = [dict(row) for row in conn.execute('SELECT * FROM management_stores ORDER BY code').fetchall()]
        types = read_settings(conn)['state']['pdvTypes']
        snapshot = json.dumps({'stores':stores,'types':types}, sort_keys=True).encode()
        token = hashlib.sha256(content + snapshot).hexdigest()
        if commit and version != token:
            raise ManagementError('Los PDV, sus tipos o el archivo cambiaron desde la vista previa. Vuelve a cargar el Excel.',409)
        records, errors = prepare(content, stores, types)
        if commit:
            if errors:
                raise ManagementError('Corrige todas las filas antes de confirmar la importación.')
            for record in records:
                service.write_store(conn, record, actor, record['code'] if record['version'] is not None else None, types)
    return {'version':token,'creates':sum(record['version'] is None for record in records),
            'updates':sum(record['version'] is not None for record in records),'errors':errors,'committed':commit,
            'sample':[{**record,'action':'Actualizar' if record['version'] is not None else 'Crear'} for record in records[:20]]}


def csv_bytes(search='', region='', commune='', status='', include_deleted=False):
    stores = [store for store in service.list_stores(include_deleted) if (not region or store['region']==region)
              and (not commune or store['commune']==commune) and (not status or store['status']==status)
              and search.casefold() in ' '.join(str(store[key]) for key in ('code','name','commune','address','description')).casefold()]
    with db.get_conn() as conn:
        assignments = conn.execute('SELECT a.store_code,t.name,a.quantity FROM management_assignments a '
                                   'JOIN management_shelf_types t ON t.id=a.type_id ORDER BY t.name').fetchall()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([*COLUMNS,'Tipos de góndola'])
    for store in stores:
        labels = ', '.join(f"{row['quantity']} × {row['name']}" for row in assignments if row['store_code']==store['code'])
        values = [store[field] for field in FIELDS]
        if store['deleted']:
            values[-1] = 'Eliminado'
        writer.writerow(["'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value for value in [*values,labels]])
    return ('\ufeff'+output.getvalue()).encode('utf-8')
