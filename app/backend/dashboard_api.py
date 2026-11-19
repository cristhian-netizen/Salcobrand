import csv
import io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from infrastructure import ManagementError
import dashboard_service as service
import measurement_reports
import measurement_scope
import catalog_service
import db


def csv_bytes(headers, rows):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value for value in row])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def router(require_dashboard, require_report, store_scope):
    api = APIRouter(prefix='/api/dashboard', tags=['Dashboards'])

    def load(region: str = '', commune: str = '', store: str = '', pdv_type: str = '', category: str = '', subcategory: str = '',
             start: str = Query(default='', alias='from'), end: str = Query(default='', alias='to'),
             user=Depends(require_dashboard)):
        return service.summary(store_scope(user), region, commune, store, pdv_type, start, end, category, subcategory)

    @api.get('')
    def dashboard(result=Depends(load)):
        return result

    @api.get('/export/{kind}.csv')
    def export(kind: str, result=Depends(load), user=Depends(require_report)):
        if kind == 'operation':
            headers = ['PDV', 'Nombre PDV', 'Región', 'Comuna', 'Mediciones aprobadas', 'Días con lecturas', 'Última lectura', 'Días desde lectura', 'Intervalo días', 'Puntaje promedio']
            rows = [[item[key] for key in ('code', 'name', 'region', 'commune', 'count', 'days', 'last', 'age', 'gap', 'score')] for item in result['operation']['rows']]
        elif kind == 'locations':
            headers = ['PDV', 'Nombre PDV', 'Región', 'Comuna', 'Encargado de Local', 'Mediciones', 'Rechazos', 'Puntaje promedio aprobado']
            rows = [[item[key] for key in ('code', 'name', 'region', 'commune', 'manager', 'count', 'rejected', 'score')] for item in result['locations']]
        elif kind == 'rejections':
            headers = ['ID', 'Fecha', 'Hora', 'PDV', 'Nombre PDV', 'Región', 'Comuna', 'Medición hecha por', 'Motivo del rechazo']
            rows = [[item[key] for key in ('id', 'date', 'time', 'store_id', 'store_name', 'region', 'commune', 'captured_by', 'note')] for item in result['rejected']]
        elif kind == 'measurements':
            # Full filtered history, including more than the recent activity preview.
            filters = result['filters']
            selected = {item['code'] for item in result['locations']}
            history = measurement_reports.history(tuple(selected), start=filters['from'], end=filters['to'], include_details=True)
            with db.get_conn() as conn:
                products = catalog_service.products(conn)
            rows = measurement_scope.filter_rows(history['rows'], filters['category'], filters['subcategory'], products)
            content = measurement_reports.csv_bytes([row for row in rows if row['date'] <= result['cutoff']])
            return response(kind, content)
        else:
            raise ManagementError('Tipo de exportación no válido.', 404)
        return response(kind, csv_bytes(headers, rows))

    return api


def response(kind, content):
    return Response(content=content, media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="Salcobrand_Dashboard_{kind}.csv"', 'Cache-Control': 'no-store'})
