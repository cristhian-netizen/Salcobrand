"""Product classification of captures, including uniquely classified older records."""
from collections import defaultdict
from product_matching import norm


def classification(row, products):
    context = row.get('_capture_context') or {}
    if context.get('category'):
        return context['category'], context.get('subcategories', [context['subcategory']] if context.get('subcategory') else [])
    by_id = {product['id']: product for product in products}
    by_name = defaultdict(list)
    for product in products:
        by_name[norm(product['name'])].append(product)
    found = set()
    observations = (row.get('_manual') or {}).get('details', []) or row.get('_products', [])
    for observation in observations:
        product = by_id.get(observation.get('productId'))
        candidates = by_name[norm(observation.get('product') or observation.get('name'))]
        if product is None and len(candidates) == 1:
            product = candidates[0]
        if product and product.get('category'):
            found.add((product['category'], product.get('subcategory', '')))
        elif observation.get('category') and observation.get('subcategory'):
            found.add((observation['category'], observation['subcategory']))
    categories = {category for category, _ in found}
    return (next(iter(categories)), sorted({sub for _, sub in found})) if len(categories) == 1 else ('', [])


def filter_rows(rows, category='', subcategory='', products=()):
    if not category:
        return rows
    result = []
    for row in rows:
        actual_category, actual_subcategory = classification(row, products)
        if actual_category == category and (not subcategory or subcategory in actual_subcategory):
            result.append(row)
    return result
