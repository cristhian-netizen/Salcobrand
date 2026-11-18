"""Versioned administrator configuration, shared by master data and presentation."""
import copy
import json
import math
import unicodedata

import db
from infrastructure import ManagementError, STORE_TYPES, _audit, _text

INDICATORS = {
    'coverage': ('Cobertura de PDV (%)', 'higher', 70, 90),
    'osa': ('Disponibilidad observada (%)', 'higher', 85, 95),
    'sos': ('Participación por caras (%)', 'higher', 20, 30),
    'cp': ('Cumplimiento (%)', 'higher', 80, 95),
    'oos': ('Ausencias recientes (cantidad)', 'lower', 3, 0),
}
DEFAULTS = {
    'pdvTypes': list(STORE_TYPES),
    'catalog': {'brands': [], 'categories': {}, 'exclusive': {}},
    'scoreParameters': {'redMax': 50, 'yellowMax': 80},
    'productParameters': {'dimensionMarginPct': 10, 'ownBrands': []},
    'kpiParameters': {**{key: {'warn': warn, 'good': good, 'direction': direction}
                         for key, (_, direction, warn, good) in INDICATORS.items()}, 'freshDays': 7},
    'alertParameters': {'reviewDays': 7, 'noMeasurementDays': 7},
    'catalogConfigured': False,
}


def normalized(value):
    return unicodedata.normalize('NFKC', value).casefold()


def names(values, label, maximum=100, allow_empty=False):
    if not isinstance(values, list) or len(values) > 1000 or (not allow_empty and not values):
        raise ManagementError(f'{label}: agrega entre 1 y 1.000 opciones.')
    cleaned = [_text(value, label, maximum, True) for value in values]
    if len({normalized(value) for value in cleaned}) != len(cleaned):
        raise ManagementError(f'{label}: hay nombres repetidos.')
    return cleaned


def integer(value, label, minimum=0, maximum=100):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ManagementError(f'{label}: usa un entero entre {minimum} y {maximum}.')
    return value


def product_references(conn):
    return [json.loads(r['data_json']) for r in conn.execute('SELECT data_json FROM management_products').fetchall()]


def read(conn=None):
    if conn is None:
        with db.get_conn() as connection:
            return read(connection)
    conn.execute('INSERT INTO management_settings (id, data_json) VALUES (1, ?) ON CONFLICT DO NOTHING',
                 (json.dumps(DEFAULTS),))
    row = conn.execute('SELECT * FROM management_settings WHERE id = 1').fetchone()
    state = json.loads(row['data_json'])
    state.setdefault('alertParameters', copy.deepcopy(DEFAULTS['alertParameters']))
    if not state['catalogConfigured']:
        # Existing API-created products remain editable before classification is configured.
        for product in product_references(conn):
            brand = product.get('subBrand')
            category = product.get('category')
            subcategory = product.get('subcategory')
            if brand and brand not in state['catalog']['brands']:
                state['catalog']['brands'].append(brand)
            if category and subcategory:
                subs = state['catalog']['categories'].setdefault(category, [])
                if subcategory not in subs:
                    subs.append(subcategory)
    used_types = conn.execute("SELECT DISTINCT store_type FROM management_stores WHERE store_type <> ''").fetchall()
    for used in used_types:
        if used['store_type'] not in state['pdvTypes']:
            state['pdvTypes'].append(used['store_type'])
    return {'state': state, 'version': row['version'], 'updated_by': row['updated_by'], 'updated_at': row['updated_at']}


def validate_classification(value, products):
    if not isinstance(value, dict) or set(value) != {'brands', 'categories', 'exclusive', 'ownBrands'}:
        raise ManagementError('La clasificación debe incluir marcas, categorías, exclusividad y marcas propias.')
    brands = names(value['brands'], 'Marcas y submarcas')
    raw_categories = value['categories']
    if not isinstance(raw_categories, dict) or not raw_categories:
        raise ManagementError('Agrega categorías y subcategorías.')
    category_names = names(list(raw_categories), 'Categorías')
    if any(name in ('__proto__', 'prototype', 'constructor') for name in category_names):
        raise ManagementError('Ese nombre de categoría está reservado.')
    categories = {name: names(raw_categories[name], 'Subcategorías de ' + name) for name in category_names}
    exclusive = value['exclusive']
    if not isinstance(exclusive, dict) or any(category not in categories or brand not in brands for category, brand in exclusive.items()):
        raise ManagementError('La submarca exclusiva debe existir y pertenecer a una categoría configurada.')
    own = names(value['ownBrands'], 'Marcas propias', allow_empty=True)
    if any(brand not in brands for brand in own):
        raise ManagementError('Las marcas propias deben estar en el catálogo de marcas.')
    for product in products:
        if product.get('subBrand') not in brands:
            raise ManagementError('No puedes quitar o renombrar una marca con productos asociados.', 409)
        if product.get('subcategory') not in categories.get(product.get('category'), []):
            raise ManagementError('No puedes quitar o renombrar una categoría o subcategoría con productos asociados.', 409)
        restriction = exclusive.get(product['category'])
        if restriction and restriction != product['subBrand']:
            raise ManagementError('La exclusividad de esta categoría dejaría productos de otras marcas fuera del catálogo.', 409)
    return {'brands': brands, 'categories': categories, 'exclusive': exclusive}, own


def save(section, value, version, actor):
    from catalog_service import lock_catalog, changed
    with db.get_conn() as conn:
        lock_catalog(conn)
        current = read(conn)
        if current['version'] != version:
            raise ManagementError('La configuración cambió en otra sesión. Actualízala antes de guardar.', 409)
        state = copy.deepcopy(current['state'])
        if section == 'catalog':
            catalog, own = validate_classification(value, product_references(conn))
            state['catalog'] = catalog
            state['productParameters']['ownBrands'] = own
            state['catalogConfigured'] = True
        elif section == 'pdv-types':
            types = names(value, 'Tipos de PDV', 80)
            used = conn.execute("SELECT DISTINCT store_type FROM management_stores WHERE store_type <> ''").fetchall()
            if any(row['store_type'] not in types for row in used):
                raise ManagementError('No puedes quitar o renombrar un tipo asignado a un PDV.', 409)
            state['pdvTypes'] = types
        elif section == 'alerts':
            if not isinstance(value, dict) or set(value) != {'reviewDays', 'noMeasurementDays'}:
                raise ManagementError('Completa los dos plazos de alertas.')
            state['alertParameters'] = {key: integer(value[key], 'Plazo de alertas (días)', 1, 365) for key in ('reviewDays', 'noMeasurementDays')}
        elif section == 'score':
            if not isinstance(value, dict) or set(value) != {'redMax', 'yellowMax'}:
                raise ManagementError('Indica los límites rojo y amarillo.')
            red = integer(value['redMax'], 'Límite rojo', 0, 98)
            yellow = integer(value['yellowMax'], 'Límite amarillo', 1, 99)
            if red >= yellow:
                raise ManagementError('El límite rojo debe ser menor que el amarillo.')
            state['scoreParameters'] = {'redMax': red, 'yellowMax': yellow}
        elif section == 'product':
            if not isinstance(value, dict) or set(value) != {'dimensionMarginPct'}:
                raise ManagementError('Indica el margen de profundidad.')
            margin = value['dimensionMarginPct']
            if isinstance(margin, bool) or not isinstance(margin, (float, int)) or not math.isfinite(margin) or not 0 <= margin <= 50:
                raise ManagementError('El margen debe estar entre 0 y 50 %.')
            state['productParameters']['dimensionMarginPct'] = margin
        elif section == 'kpi':
            if not isinstance(value, dict) or set(value) not in ({*INDICATORS, 'freshDays'}, set(INDICATORS) - {'oos'}):
                raise ManagementError('Completa los objetivos de todos los indicadores.')
            kpis = {'freshDays': integer(value.get('freshDays', state['kpiParameters']['freshDays']), 'Antigüedad de ausencias', 1, 365)}
            for key, (label, direction, _, _) in INDICATORS.items():
                thresholds = value.get(key, state['kpiParameters'][key])
                if not isinstance(thresholds, dict) or set(thresholds) != {'warn', 'good', 'direction'} or thresholds['direction'] != direction:
                    raise ManagementError('Revisa los umbrales y la dirección de ' + label)
                maximum = 9007199254740991 if direction == 'lower' else 100
                warn = integer(thresholds['warn'], label, 0, maximum)
                good = integer(thresholds['good'], label, 0, maximum)
                if (direction == 'lower' and good > warn) or (direction == 'higher' and good < warn):
                    raise ManagementError('Revisa el orden de los umbrales de ' + label)
                kpis[key] = {'warn': warn, 'good': good, 'direction': direction}
            state['kpiParameters'] = kpis
        else:
            raise ManagementError('Sección de configuración no encontrada.', 404)
        conn.execute('UPDATE management_settings SET data_json = ?, version = version + 1, updated_by = ?, updated_at = ? WHERE id = 1',
                     (json.dumps(state), actor, db.now_iso()))
        _audit(conn, actor, 'settings.' + section, 'settings', {'version': version}, {'version': version + 1, 'section': section})
        changed(conn)
        return read(conn)


def validate_product(conn, product):
    row = conn.execute('SELECT data_json FROM management_settings WHERE id = 1').fetchone()
    state = json.loads(row['data_json']) if row else read(conn)['state']
    if not state['catalogConfigured']:
        return
    catalog = state['catalog']
    if product['subBrand'] not in catalog['brands'] or product['subcategory'] not in catalog['categories'].get(product['category'], []):
        raise ManagementError('Selecciona una marca, categoría y subcategoría configuradas.')
    exclusive = catalog['exclusive'].get(product['category'])
    if exclusive and exclusive != product['subBrand']:
        raise ManagementError('Esta categoría está reservada para otra submarca.')


def display_parameters():
    with db.get_conn() as conn:
        row = conn.execute('SELECT data_json FROM management_settings WHERE id = 1').fetchone()
    state = json.loads(row['data_json']) if row else DEFAULTS
    return {key: state[key] for key in ('scoreParameters', 'kpiParameters', 'productParameters')}


def score_band(score, parameters=None):
    if score is None:
        return None
    parameters = parameters or display_parameters()['scoreParameters']
    return 'bad' if score <= parameters['redMax'] else 'warn' if score <= parameters['yellowMax'] else 'ok'


def indicator(key, value, parameters):
    rule = parameters[key]
    band = None
    if value is not None:
        if rule['direction'] == 'higher':
            band = 'ok' if value >= rule['good'] else 'warn' if value >= rule['warn'] else 'bad'
        else:
            band = 'ok' if value <= rule['good'] else 'warn' if value <= rule['warn'] else 'bad'
    return {'value': value, 'band': band, **rule}
