"""Copy the previous local configuration through the authorized local settings API."""
import hashlib
import json
from pathlib import Path
import sqlite3
import unicodedata

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.local' / 'settings-migration'


def checked(response):
    response.raise_for_status()
    return response.json()


def merged_names(current, incoming):
    values = {unicodedata.normalize('NFKC', value).casefold(): value for value in current}
    for value in incoming:
        values.setdefault(unicodedata.normalize('NFKC', value).casefold(), value)
    return list(values.values())


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    marker = OUTPUT / 'proof.json'
    proof = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {'completed_sections': []}
    if len(proof['completed_sections']) == 5:
        print('La configuración anterior ya está importada. Se conservan las ediciones posteriores.')
        return
    source_path = ROOT.parents[1] / 'backend' / 'db.sqlite3'
    with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as conn:
        rows = conn.execute('SELECT state FROM api_portalworkspace').fetchall()
    if len(rows) != 1:
        raise ValueError('Selecciona explícitamente la organización de origen antes de importar.')
    source = json.loads(rows[0][0])
    backup = OUTPUT / 'before-settings.sqlite3'
    if not backup.exists():
        with sqlite3.connect((ROOT / '.local/capture-dev/data.db').as_uri() + '?mode=ro', uri=True) as conn:
            with sqlite3.connect(backup) as destination:
                conn.backup(destination)
    with httpx.Client(base_url='http://localhost:3001', timeout=120) as client:
        checked(client.post('/api/auth/login', json={'username': 'local-admin', 'password': 'Isolated-local-password-2026!'}))
        current = checked(client.get('/api/admin/settings'))
        state = current['state']
        original = source.get('catalog', {})
        catalog = {'brands': merged_names(state['catalog']['brands'], original.get('brands', [])),
                   'categories': dict(state['catalog']['categories']), 'exclusive': dict(state['catalog']['exclusive']),
                   'ownBrands': merged_names(state['productParameters']['ownBrands'], source.get('productParameters', {}).get('ownBrands', []))}
        for category, subcategories in original.get('categories', {}).items():
            catalog['categories'][category] = merged_names(catalog['categories'].get(category, []), subcategories)
        catalog['exclusive'].update(original.get('exclusive', {}))
        values = {
            'pdv-types': merged_names(state['pdvTypes'], source.get('pdvTypes') or sorted({s['type'] for s in source.get('stores', []) if s.get('type')})),
            'catalog': catalog,
            'score': source.get('scoreParameters', state['scoreParameters']),
            'product': {'dimensionMarginPct': source.get('productParameters', {}).get('dimensionMarginPct', state['productParameters']['dimensionMarginPct'])},
            'kpi': source.get('kpiParameters', state['kpiParameters']),
        }
        for section, value in values.items():
            if section in proof['completed_sections']:
                continue
            current = checked(client.get('/api/admin/settings'))
            saved = checked(client.patch('/api/admin/settings/' + section, json={'version': current['version'], 'value': value}))
            proof['completed_sections'].append(section)
            proof['version'] = saved['version']
            proof['source_sha256'] = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
            marker.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
        final = checked(client.get('/api/admin/settings'))
        print(json.dumps({'version': final['version'], 'pdv_types': len(final['state']['pdvTypes']),
                          'brands': len(final['state']['catalog']['brands']), 'categories': len(final['state']['catalog']['categories'])}))


if __name__ == '__main__':
    main()
