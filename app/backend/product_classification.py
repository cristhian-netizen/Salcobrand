"""Classification shared by planograms and capture snapshots."""
from infrastructure import ManagementError, _text


def selection(category='', subcategory='', subcategories=None):
    category = _text(category, 'Categoría', 150)
    subcategory = _text(subcategory, 'Subcategoría', 150)
    if subcategories is not None:
        if not isinstance(subcategories, list) or len(subcategories) > 1000:
            raise ManagementError('Selecciona hasta 1.000 subcategorías.')
        cleaned = [_text(value, 'Subcategoría', 150, True) for value in subcategories]
        if len(set(cleaned)) != len(cleaned):
            raise ManagementError('Hay subcategorías repetidas.')
        if subcategory and subcategory not in cleaned:
            raise ManagementError('La subcategoría individual no coincide con la selección múltiple.')
        if cleaned and not category:
            raise ManagementError('Selecciona primero una categoría.')
        return {'category': category, 'subcategories': sorted(cleaned, key=str.casefold)} if category or cleaned else {}
    if subcategory and not category:
        raise ManagementError('Selecciona primero una categoría.')
    return {'category': category, 'subcategory': subcategory} if category or subcategory else {}


def validate(values, conn=None):
    import settings_service
    categories = settings_service.read(conn)['state']['catalog']['categories']
    category = values.get('category', '')
    subs = values.get('subcategories', [values['subcategory']] if values.get('subcategory') else [])
    if category and (category not in categories or any(sub not in categories[category] for sub in subs)):
        raise ManagementError('Selecciona una categoría y subcategorías configuradas por el administrador.')
    if category and 'subcategories' in values and categories[category] and not subs:
        raise ManagementError('Selecciona al menos una subcategoría.')
