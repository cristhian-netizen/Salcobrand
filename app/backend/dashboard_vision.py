"""Weighted confirmed retail indicators and observed brand facings."""
from collections import defaultdict
from datetime import date
from manual_metrics import observations, ratios
from settings_service import indicator


def summarize(rows, cutoff, parameters):
    counts = dict.fromkeys(('expected', 'present', 'allFaces', 'ownFaces', 'compared', 'matching', 'detailCount'), 0)
    faces = []
    latest = {}
    for row in rows:
        data = row['_manual']
        observation = None
        if data:
            observation = observations(data, row['_has_planogram'])
            for key in counts:
                counts[key] += observation[key]
            if observation['faces'] is not None:
                faces.append(observation['faces'])
        instance = data.get('shelfInstanceId') if data else row['_instance_id']
        if instance and instance not in latest:
            # An unconfirmed newer reading also supersedes older observations.
            latest[instance] = (row, observation)
    missing = []
    fresh = 0
    for row, observation in latest.values():
        age = (date.fromisoformat(cutoff) - date.fromisoformat(row['date'])).days
        if 0 <= age <= parameters['freshDays'] and observation and observation['expected']:
            fresh += 1
            for product in observation['missing']:
                missing.append({'measurement': public_reading(row), 'product': product['name'],
                                'sku': product.get('sku', ''), 'shelf': row['_manual'].get('shelfLabel', '')})
    values = {**ratios(counts), 'oos': len(missing) if fresh else None}
    indicators = {}
    for key, value in values.items():
        indicators[key] = indicator(key, value, parameters)
        indicators[key]['value'] = round(value, 1) if value is not None else None
    return {**counts, 'faces': sum(faces) if faces else None, 'missing': missing,
            'freshDays': parameters['freshDays'],
            'indicators': indicators}


def public_reading(row):
    return {key: value for key, value in row.items() if not key.startswith('_')}


def brand_share(rows, own_brands):
    own = {brand.strip().casefold() for brand in own_brands}
    totals = defaultdict(int)
    scans = 0
    for reading in rows:
        counted = False
        captured = reading.get('_brand_share')
        if captured and captured.get('brands'):
            for item in captured['brands']:
                faces = item.get('facings')
                kind = item.get('classification')
                if type(faces) is int and faces >= 0 and kind in ('client', 'other', 'unknown'):
                    totals[(item.get('brand') or 'Marca no identificada', kind)] += faces
                    counted = counted or faces > 0
            scans += counted
            continue
        for product in reading['_products']:
            faces = product.get('facings')
            if type(faces) is not int or faces < 0:
                continue
            brand = str(product.get('brand') or '').strip()
            if brand.casefold() in ('sin marca', 'sin marca visible', 'marca no identificada', 'desconocida'):
                brand = ''
            is_own = product.get('is_own_brand')
            if is_own is True or (brand and brand.casefold() in own):
                classification = 'client'
            elif brand and (is_own is False or own):
                classification = 'other'
            else:
                classification = 'unknown'
            totals[(brand or 'Marca no identificada', classification)] += faces
            counted = counted or faces > 0
        scans += counted
    total = sum(totals.values())
    brands = [{'brand': brand, 'classification': kind, 'facings': faces,
               'sharePct': round(100 * faces / total, 1) if total else None}
              for (brand, kind), faces in sorted(totals.items(), key=lambda item: (-item[1], item[0][0].casefold()))]
    return {'scans': scans, 'totalFacings': total, 'brands': brands,
            'groups': [{'classification': kind, 'facings': sum(item['facings'] for item in brands if item['classification'] == kind),
                        'sharePct': round(100 * sum(item['facings'] for item in brands if item['classification'] == kind) / total, 1) if total else None}
                       for kind in ('client', 'other', 'unknown')]}
