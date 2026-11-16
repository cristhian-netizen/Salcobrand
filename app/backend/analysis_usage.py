"""Organization monthly gondola costs from the provider's original usage contract."""
import calendar
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, DecimalException, localcontext
import re
from zoneinfo import ZoneInfo
import httpx
import remote_model
from infrastructure import ManagementError


def month_range(date_from='', date_to=''):
    today = datetime.now(ZoneInfo('America/Santiago')).date()
    try:
        values = [date_from or today.replace(day=1).isoformat(), date_to or today.isoformat()]
        if any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) for value in values):
            raise ValueError()
        start, end = [date.fromisoformat(value).replace(day=1) for value in values]
    except (ValueError,TypeError):
        raise ManagementError('Usa fechas válidas con formato AAAA-MM-DD.')
    length = (end.year-start.year)*12 + end.month-start.month + 1
    if not 1 <= length <= 120:
        raise ManagementError('Selecciona un período de hasta 120 meses, con inicio anterior al término.')
    return start, end, length


@contextmanager
def provider_client():
    try:
        origin = remote_model.base_url()
    except ValueError:
        raise ManagementError('Falta configurar la conexión al resumen de costos del proveedor.',503) from None
    try:
        with httpx.Client(base_url=origin, timeout=15, follow_redirects=False, trust_env=False) as client:
            try:
                remote_model.authenticate(client)
            except ValueError:
                raise ManagementError('El proveedor no autorizó la consulta de costos con el acceso configurado.',503) from None
            yield client
    except httpx.HTTPError:
        raise ManagementError('No se pudo consultar el resumen de costos del proveedor. Reintenta la consulta.',503) from None


def gondola_cost(summary):
    endpoints = summary.get('by_endpoint') if isinstance(summary,dict) else None
    if not isinstance(endpoints,list) or any(not isinstance(row,dict) for row in endpoints):
        return None
    try:
        values = [Decimal(str(row['cost_usd'])) for row in endpoints if row.get('endpoint') == 'vision_gondola']
        if any(not value.is_finite() or value < 0 for value in values):
            return None
        with localcontext() as context:
            context.prec = max(28, sum(len(value.as_tuple().digits) for value in values) + 8)
            return str(sum(values,Decimal('0')))
    except (KeyError,TypeError,DecimalException):
        return None


def report(date_from='', date_to=''):
    start, end, length = month_range(date_from,date_to)
    months = []
    with provider_client() as client:
        for offset in range(length):
            year, month = divmod(start.year*12+start.month-1+offset,12)
            month += 1
            params = {'date_from':date(year,month,1).isoformat(),
                      'date_to':date(year,month,calendar.monthrange(year,month)[1]).isoformat()}
            try:
                with client.stream('GET','/api/usage/summary',params=params) as response:
                    if response.status_code == 404:
                        raise ManagementError('El proveedor de análisis no tiene disponible el resumen de costos para esta conexión.',503)
                    if response.status_code != 200:
                        raise ManagementError('El proveedor no pudo entregar el resumen de costos. Reintenta la consulta.',503)
                    summary = remote_model.json_response(response)
            except ManagementError:
                raise
            except ValueError:
                raise ManagementError('El proveedor devolvió un resumen de costos no válido.',502) from None
            months.append({'month':f'{year:04d}-{month:02d}','cost_usd':gondola_cost(summary)})
    known = [Decimal(row['cost_usd']) for row in months if row['cost_usd'] is not None]
    with localcontext() as context:
        context.prec = max(28,sum(len(value.as_tuple().digits) for value in known)+8)
        total = str(sum(known,Decimal('0'))) if known else None
    return {'currency':'USD','estimated':True,'scope':'organization','date_from':start.isoformat(),
            'date_to':end.isoformat(),'months':months,'known_months':len(known),'total_cost_usd':total}
