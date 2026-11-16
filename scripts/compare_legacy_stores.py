"""Prepare a read-only comparison of the old workspace and local Salcobrand PDV."""
import csv
import json
from pathlib import Path
import sqlite3
import sys
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
from infrastructure import store_code, store_data
from store_excel import COLUMNS, FIELDS, append_text_row, style


def main():
    source_path = ROOT.parents[1] / 'backend/db.sqlite3'
    target_path = ROOT / '.local/capture-dev/data.db'
    with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as conn:
        workspaces = conn.execute('SELECT state FROM api_portalworkspace').fetchall()
    if len(workspaces) != 1:
        raise ValueError('Selecciona explícitamente el workspace de origen para comparar.')
    source = json.loads(workspaces[0][0])
    tenant = source.get('tenant', {}).get('name', 'Copia local anterior')
    with sqlite3.connect(target_path.as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        current = {row['code'].casefold():dict(row) for row in conn.execute('SELECT * FROM management_stores')}
        settings = json.loads(conn.execute('SELECT data_json FROM management_settings WHERE id=1').fetchone()[0])
    book = Workbook()
    sheet = book.active
    sheet.title = 'PDV'
    sheet.append(COLUMNS)
    comparisons, seen = [], set()
    counts = {'source':len(source.get('stores', [])), 'local':len(current), 'matched':0, 'source_only':0, 'local_only':0, 'invalid':0}
    for store in source.get('stores', []):
        values = {'code':str(store.get('code') or '').strip(), 'name':store.get('name',''), 'store_type':store.get('type',''),
                  'description':store.get('description',''), 'region':store.get('region',''), 'commune':store.get('comuna',''),
                  'address':store.get('address',''), 'manager':store.get('manager',''), 'status':store.get('status','')}
        validation = ''
        normalized = values
        try:
            normalized = {**store_data(values,settings['pdvTypes']), 'code':store_code(values['code'])}
            if normalized['code'].casefold() in seen:
                raise ValueError('Código duplicado en la copia anterior.')
        except ValueError as exc:
            validation = str(exc)
            counts['invalid'] += 1
        key = values['code'].casefold()
        seen.add(key)
        existing = current.get(key)
        if existing:
            counts['matched'] += 1
            differences = [field for field in FIELDS if field != 'code' and existing.get(field,'') != normalized.get(field,'')]
            situation = 'Diferencias' if differences else 'Coincide'
        else:
            counts['source_only'] += 1
            differences = []
            situation = 'Solo copia anterior'
            append_text_row(sheet,[values[field] for field in FIELDS])
            sheet.cell(sheet.max_row,1).number_format = '@'
        comparisons.append([tenant,values['code'],situation,values['name'],existing['name'] if existing else '',
                            ', '.join(differences),validation,store.get('id',''),store.get('remoteId',''),
                            store.get('lat',''),store.get('lng','')])
    for key, existing in current.items():
        if key not in seen:
            counts['local_only'] += 1
            comparisons.append([tenant,existing['code'],'Solo localhost','',existing['name'],'','','','','',''])
    output = ROOT / '.local/pdv-reconciliation'
    output.mkdir(parents=True,exist_ok=True)
    style(sheet,[20,34,26,44,36,26,44,30,18])
    book.save(output / 'Productos_PF_PDV_pendientes.xlsx')
    with (output / 'Comparacion_PDV.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.writer(stream,delimiter=';')
        writer.writerow(['Origen','Código PDV','Comparación','Nombre anterior','Nombre localhost','Campos diferentes','Validación',
                         'ID anterior','Referencia del modelo anterior','Latitud anterior','Longitud anterior'])
        for row in comparisons:
            writer.writerow(["'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value for value in row])
    (output / 'summary.json').write_text(json.dumps({'source_workspace':tenant,**counts},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'source_workspace':tenant,**counts},ensure_ascii=False))


if __name__ == '__main__':
    main()
