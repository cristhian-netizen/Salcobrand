"""Additive taxonomy import and atomic classification of existing products by SKU."""
import copy
import io
import json
import zipfile
from openpyxl import Workbook, load_workbook
import catalog_service as catalog
import db
import settings_service as settings
from infrastructure import ManagementError, _audit, _text
from store_excel import style, append_text_row

HEADERS = {'Catalogo': ['Submarca', 'Categoría', 'Subcategoría', 'Marca propia', 'Exclusiva'],
           'Asignaciones': ['SKU', 'Categoría', 'Subcategoría', 'Submarca']}


def snapshot(conn):
    config = settings.read(conn)
    return config, f"{config['version']}:{catalog.lock_catalog(conn)}"


def options():
    with db.get_conn() as conn:
        config, version = snapshot(conn)
        products = [{key: p[key] for key in ('id','sku','name','subBrand','category','subcategory')}
                    for p in catalog.products(conn)]
    return {'version': version, 'classification': config['state']['catalog'], 'products': products}


def workbook_bytes():
    book = Workbook()
    book.remove(book.active)
    for name, headers in HEADERS.items():
        sheet = book.create_sheet(name)
        append_text_row(sheet, headers)
        style(sheet, [30] * len(headers))
    with db.get_conn() as conn:
        state = settings.read(conn)['state']
        refs = book.create_sheet('Referencias')
        append_text_row(refs, ['Tipo', 'Nombre', 'Categoría'])
        for brand in state['catalog']['brands']:
            append_text_row(refs, ['Submarca', brand, ''])
        for category, subs in state['catalog']['categories'].items():
            for sub in subs:
                append_text_row(refs, ['Subcategoría', sub, category])
        style(refs, [24,36,36])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def read_file(content):
    if len(content) > 5 * 1024 * 1024:
        raise ManagementError('Usa un archivo .xlsx de hasta 5 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError('Archivo expandido demasiado grande')
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        try:
            result = []
            for name, headers in HEADERS.items():
                if name not in book.sheetnames:
                    continue
                sheet = book[name]
                if sheet.max_row > 5001 or sheet.max_column > 20:
                    raise ManagementError('Máximo 5.000 filas por hoja.')
                rows = list(sheet.iter_rows())
                names = [str(c.value or '').strip() for c in rows[0]] if rows else []
                if names != headers:
                    raise ManagementError('Revisa los encabezados de la hoja ' + name + '. Usa la plantilla.')
                for number, row in enumerate(rows[1:], 2):
                    if not any(c.value is not None for c in row):
                        continue
                    if any(c.data_type == 'f' for c in row):
                        raise ManagementError(f'{name}, fila {number}: no se permiten fórmulas.')
                    values = dict(zip(headers, (c.value for c in row)))
                    if name == 'Asignaciones' and not isinstance(values['SKU'], str):
                        raise ManagementError(f'Asignaciones, fila {number}: el SKU debe ser texto para conservar ceros iniciales.')
                    result.append({'sheet': name, 'row': number, 'values': values})
            if not result:
                raise ManagementError('Agrega filas en Catalogo o Asignaciones.')
            return result
        finally:
            book.close()
    except ManagementError:
        raise
    except Exception as exc:
        raise ManagementError('No se pudo leer el Excel. Usa la plantilla de clasificación.') from exc


def boolean(value, label):
    normalized = settings.normalized(str(value or '').strip())
    if normalized in ('', 'no', 'false', '0'):
        return False
    if normalized in ('sí', 'si', 'true', '1'):
        return True
    raise ManagementError(label + ': usa Sí o No.')


def transfer(rows, actor, commit=False, version=None):
    with db.get_conn() as conn:
        config, current = snapshot(conn)
        if commit and version != current:
            raise ManagementError('La clasificación o los productos cambiaron. Genera una nueva vista previa.', 409)
        state = copy.deepcopy(config['state'])
        taxonomy = state['catalog']
        products = {p['sku'].casefold(): p for p in catalog.products(conn)}
        projected = copy.deepcopy(products)
        preview, changes, seen = [], [], set()
        for row in sorted(rows, key=lambda r: r['sheet'] != 'Catalogo'):
            values = row['values']
            result = {'sheet': row['sheet'], 'row': row['row'], 'sku': str(values.get('SKU') or ''),
                      'category': str(values.get('Categoría') or ''), 'subcategory': str(values.get('Subcategoría') or ''), 'error': ''}
            try:
                category = _text(values.get('Categoría'), 'Categoría', 100, True)
                sub = _text(values.get('Subcategoría'), 'Subcategoría', 100, True)
                brand = _text(values.get('Submarca') or '', 'Submarca', 100, row['sheet'] == 'Catalogo')
                if row['sheet'] == 'Catalogo':
                    if brand not in taxonomy['brands']:
                        taxonomy['brands'].append(brand)
                    if category not in taxonomy['categories']:
                        taxonomy['categories'][category] = []
                    if sub not in taxonomy['categories'][category]:
                        taxonomy['categories'][category].append(sub)
                    if boolean(values.get('Marca propia'), 'Marca propia') and brand not in state['productParameters']['ownBrands']:
                        state['productParameters']['ownBrands'].append(brand)
                    if boolean(values.get('Exclusiva'), 'Exclusiva'):
                        if taxonomy['exclusive'].get(category, brand) != brand:
                            raise ManagementError('La categoría ya tiene otra submarca exclusiva.')
                        taxonomy['exclusive'][category] = brand
                else:
                    sku = _text(values.get('SKU'), 'SKU', 80, True).casefold()
                    if sku not in products:
                        raise ManagementError('El SKU no existe. Carga primero el producto en Productos.')
                    if sku in seen:
                        raise ManagementError('El SKU está repetido en el archivo.')
                    seen.add(sku)
                    if sub not in taxonomy['categories'].get(category, []):
                        raise ManagementError('Selecciona una categoría y subcategoría creadas en el catálogo.')
                    if brand and brand not in taxonomy['brands']:
                        raise ManagementError('Selecciona una submarca creada en el catálogo.')
                    updated = {**products[sku], 'category': category, 'subcategory': sub,
                               'subBrand': brand or products[sku]['subBrand']}
                    projected[sku] = updated
                    changes.append(updated)
            except ManagementError as exc:
                result['error'] = str(exc)
            preview.append(result)
        validation_error = ''
        try:
            settings.validate_classification({**taxonomy, 'ownBrands':state['productParameters']['ownBrands']}, list(projected.values()))
        except ManagementError as exc:
            validation_error = str(exc)
        errors = bool(validation_error or any(r['error'] for r in preview))
        if commit:
            if errors:
                raise ManagementError(validation_error or 'Corrige las filas con errores antes de importar.')
            state['catalogConfigured'] = True
            conn.execute('UPDATE management_settings SET data_json=?,version=version+1,updated_by=?,updated_at=? WHERE id=1',
                         (json.dumps(state),actor,db.now_iso()))
            for product in changes:
                catalog.write_product(conn, product, actor, product['id'])
            catalog.changed(conn)
            _audit(conn,actor,'settings.classification.bulk','settings',{'version':current},{'products':len(changes),'rows':len(rows)})
        return {'rows': preview, 'version': current, 'has_errors':errors, 'error':validation_error,
                'products_updated':len(changes), 'catalog_rows':sum(r['sheet']=='Catalogo' for r in rows), 'committed':commit}
