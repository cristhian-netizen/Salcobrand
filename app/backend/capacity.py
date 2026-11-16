"""The legacy capacity formula uses captured geometry and the current product catalog."""
import math
import db
from product_matching import match_catalog
from settings_service import display_parameters, product_references


def positive(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        return None
    return value


def estimate(reading):
    margin = display_parameters()['productParameters']['dimensionMarginPct']
    result = {'dimensionMarginPct': margin, 'maximumOnly': True, 'products': [], 'calculatedPositions': 0}
    depths = (reading.get('infrastructure') or {}).get('depths') or []
    if not depths:
        return result
    with db.get_conn() as conn:
        catalog = product_references(conn)
    for observed in reading.get('products', []):
        match = match_catalog(observed, catalog)
        product = match['product'] or {}
        level = observed.get('shelf_level')
        facings = observed.get('facings')
        depth = positive(depths[level - 1]) if type(level) is int and 1 <= level <= len(depths) else None
        thickness = positive(product.get('thickness'))
        per_face = math.floor(depth / (thickness * (1 + margin / 100))) if depth and thickness else None
        maximum = per_face * facings if per_face is not None and type(facings) is int and facings >= 0 else None
        result['products'].append({'product': observed.get('product'), 'level': level, 'position': observed.get('position_index'),
            'depthCm': depth, 'thicknessCm': thickness, 'facings': facings, 'unitsPerFacing': per_face,
            'maximumUnits': maximum, 'matchStatus': match['status'], 'matchReason': match['reason']})
        result['calculatedPositions'] += int(maximum is not None)
    return result
