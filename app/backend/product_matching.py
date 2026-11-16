"""Conservative visual catalog matching. Internal codes are never evidence."""
import re
import unicodedata


def norm(value):
    value = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in value if not unicodedata.combining(c))).strip()


# Approved visual equivalence; do not equate PF with all of its sub-brands.
BRANDS = {'listo': 'pf listo', 'list o': 'pf listo', 'pf list o': 'pf listo'}
UNITS = {'g': ('grams', 1), 'gr': ('grams', 1), 'gramos': ('grams', 1), 'grams': ('grams', 1),
         'kg': ('grams', 1000), 'ml': ('ml', 1), 'l': ('ml', 1000), 'litros': ('ml', 1000)}
FORMAT = re.compile(r'(?<!\w)(\d+(?:[.,]\d+)?)\s*(kg|gramos|grams|gr|g|ml|litros|l)\b', re.I)


def brand(value):
    value = norm(value)
    return BRANDS.get(value, value)


def signature(row, catalog=False):
    raw = str(row.get('name' if catalog else 'product') or '')
    formats = [(float(m.group(1).replace(',', '.')) * UNITS[m.group(2).lower()][1],
                UNITS[m.group(2).lower()][0]) for m in FORMAT.finditer(raw)]
    quantity = row.get('quantity')
    if quantity not in (None, ''):
        try:
            unit, factor = UNITS.get(norm(row.get('saleUnit') or row.get('sale_unit')), ('', 1))
            formats.append((float(quantity) * factor, unit))
        except (ValueError, TypeError):
            return None
    if any(q <= 0 or q != q or q == float('inf') for q, _ in formats):
        return None
    if formats and any(q != formats[0][0] or (u and formats[0][1] and u != formats[0][1]) for q, u in formats):
        return None
    # Only presentation-neutral words are ignored. Variety, packs and counts survive.
    words = norm(FORMAT.sub(' ', raw)).split()
    name = ' '.join(w for w in words if w not in {'de', 'del', 'congelada', 'congelado', 'envasada', 'envasado'})
    return name, formats[0] if formats else None


def match_catalog(row, catalog):
    observed = signature(row)
    empty = {'product': None, 'status': 'unmatched', 'reason': 'Sin correspondencia suficientemente clara en el maestro.'}
    if not observed or not observed[0]:
        return {**empty, 'reason': 'Nombre o formato observado insuficiente o contradictorio.'}
    visible_brand = brand(row.get('brand'))
    candidates = []
    conflicting_format = False
    for product in catalog:
        candidate = signature(product, catalog=True)
        if not candidate or observed[0] != candidate[0]:
            continue
        expected_brand = brand(product.get('subBrand') or product.get('brand'))
        if expected_brand != visible_brand:
            continue
        a, b = observed[1], candidate[1]
        if a and (not b or a[0] != b[0] or (a[1] and b[1] and a[1] != b[1])):
            conflicting_format = True
            continue
        candidates.append(product)
    if len(candidates) > 1:
        return {**empty, 'status': 'ambiguous', 'reason': 'Hay varias referencias posibles; falta distinguir el formato o la variedad.'}
    if not candidates:
        return {**empty, 'reason': 'El formato observado contradice el del maestro.' if conflicting_format else empty['reason']}
    product = candidates[0]
    exact = (norm(row.get('product')) == norm(product.get('name'))
             and norm(row.get('brand')) == norm(product.get('subBrand') or product.get('brand'))
             and (observed[1] is not None or signature(product, True)[1] is None))
    reasons = ['Nombre y variedad compatibles; referencia única en el maestro.']
    if norm(row.get('brand')) != norm(product.get('subBrand') or product.get('brand')):
        reasons.append('Se aplicó la equivalencia de marca Listo / PF Listo!.')
    if observed[1] is None and signature(product, True)[1] is not None:
        reasons.append('Formato no visible: se usa el único formato compatible del maestro.')
    return {'product': product, 'status': 'exact' if exact else 'probable', 'reason': ' '.join(reasons)}
