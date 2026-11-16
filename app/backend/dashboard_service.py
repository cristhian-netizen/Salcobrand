"""Dashboard aggregation with the original review, geography and cutoff rules."""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import calendar
import infrastructure
from infrastructure import ManagementError
import measurement_reports
from dashboard_vision import summarize as vision_summary, brand_share, public_reading
import settings_service


def average(rows):
    values = [row['score'] for row in rows if row['status'] == 'Aprobado' and row['score'] is not None]
    return sum(values) / len(values) if values else None


def months_between(start, end):
    year, month = map(int, start[:7].split('-'))
    end_year, end_month = map(int, end[:7].split('-'))
    count = (end_year - year) * 12 + end_month - month + 1
    if count > 1200:
        raise ManagementError('Elige un período de hasta 100 años.')
    return [f'{(year * 12 + month - 1 + offset) // 12:04d}-{(month - 1 + offset) % 12 + 1:02d}' for offset in range(max(0, count))]


def summary(scope, region='', commune='', store='', pdv_type='', start='', end=''):
    # Reuse date validation, Chilean local time and the authorized measurement history.
    history = measurement_reports.history(scope, start=start, end=end, include_details=True)
    cutoff = end or datetime.now(timezone.utc).astimezone(measurement_reports.CHILE).date().isoformat()
    if commune and not region:
        raise ManagementError('Selecciona una región antes de filtrar por comuna.')
    stores = [item for item in infrastructure.list_stores(include_deleted=True) if scope is None or item['code'] in scope]
    if store and store not in {item['code'] for item in stores}:
        raise ManagementError('El PDV está fuera de tu ámbito.', 403)
    selected = [item for item in stores if (not region or item['region'] == region)
                and (not commune or item['commune'] == commune) and (not store or item['code'] == store)
                and (not pdv_type or item['store_type'] == pdv_type)]
    ids = {item['code'] for item in selected}
    rows = [row for row in history['rows'] if row['store_id'] in ids and row['date'] <= cutoff]
    approved = [row for row in rows if row['status'] == 'Aprobado']
    rejected = [row for row in rows if row['status'] == 'Rechazado']
    state = settings_service.read()['state']
    kpis, score_parameters = state['kpiParameters'], state['scoreParameters']
    by_store = defaultdict(list)
    for row in rows:
        by_store[row['store_id']].append(row)
    locations = []
    for master in selected:
        measurements = by_store[master['code']]
        score = average(measurements)
        rejected_count = sum(row['status'] == 'Rechazado' for row in measurements)
        locations.append({'code': master['code'], 'name': master['name'], 'region': master['region'],
                          'commune': master['commune'], 'manager': master['manager'], 'count': len(measurements),
                          'eligible': sum(row['status'] == 'Aprobado' for row in measurements), 'rejected': rejected_count,
                          'rejectionRate': round(100 * rejected_count / len(measurements), 1) if measurements else None,
                          'score': round(score, 1) if score is not None else None, 'score_band': settings_service.score_band(score, score_parameters)})
    authors = defaultdict(lambda: {'count': 0, 'rejected': 0})
    for row in rows:
        author = authors[row['captured_by']]
        author['count'] += 1
        author['rejected'] += row['status'] == 'Rechazado'
    author_rows = [{'name': name, **counts, 'rejectionRate': round(100 * counts['rejected'] / counts['count'], 1)}
                   for name, counts in authors.items()]
    author_rows.sort(key=lambda item: (-item['rejected'], item['name'].casefold()))
    operation = coverage(selected, approved, history['rows'], cutoff, start, kpis)
    monthly_rows = defaultdict(list)
    for row in rows:
        monthly_rows[row['date'][:7]].append(row)
    first = start or (rows[-1]['date'] if rows else cutoff)
    last = end or (rows[0]['date'] if rows else cutoff)
    months = []
    daily = Counter(row['date'] for row in approved)
    for month in months_between(first, last):
        measurements = monthly_rows[month]
        valid = [row for row in measurements if row['status'] == 'Aprobado']
        bad = sum(row['status'] == 'Rechazado' for row in measurements)
        vision = vision_summary(valid, cutoff, kpis)
        monthly_score = average(valid)
        months.append({'month': month, 'count': len(measurements), 'approved': len(valid), 'score': round(monthly_score, 1) if monthly_score is not None else None,
                       'rejected': bad, 'rejectionRate': round(100 * bad / len(measurements), 1) if measurements else None,
                       'sos': vision['indicators']['sos']['value'], 'cp': vision['indicators']['cp']['value'], 'faces': vision['faces']})
    calendar_rows = []
    calendar_months = months_between(f'{first[:4]}-01-01', f'{last[:4]}-12-01') if first <= last else []
    for month in calendar_months:
        year, number = map(int, month.split('-'))
        days = []
        for day in range(1, 32):
            key = f'{month}-{day:02d}'
            value = None if day > calendar.monthrange(year, number)[1] else -1 if (start and key < start) or key > cutoff else daily[key]
            days.append(value)
        calendar_rows.append({'month': month, 'days': days})
    score = average(approved)
    return {'cutoff': cutoff, 'geography': infrastructure.REGIONS, 'pdvTypes': state['pdvTypes'],
            'filters': {'region': region, 'commune': commune, 'store': store, 'pdv_type': pdv_type, 'from': start, 'to': end},
            'options': [{'code': item['code'], 'name': item['name'], 'region': item['region'], 'commune': item['commune'],
                         'pdv_type': item['store_type']} for item in stores],
            'totals': {'measurements': len(rows), 'approved': len(approved), 'in_review': sum(row['status'] == 'En revisión' for row in rows),
                       'rejected': len(rejected), 'average_score': round(score, 1) if score is not None else None, 'score_band': settings_service.score_band(score, score_parameters)},
            'months': months, 'calendar': calendar_rows, 'locations': locations, 'authors': author_rows,
            'operation': operation, 'vision': vision_summary(approved, cutoff, kpis),
            'brands': brand_share(approved, state['productParameters']['ownBrands']),
            'recent': [public_reading(row) for row in rows[:20]], 'rejected': [public_reading(row) for row in rejected]}


def coverage(stores, approved, history, cutoff, start, parameters):
    active = [store for store in stores if store['status'] == 'Activo' and not store['deleted']]
    periods, historical = defaultdict(list), defaultdict(list)
    for row in approved:
        periods[row['store_id']].append(row)
    for row in history:
        if row['status'] == 'Aprobado' and row['date'] <= cutoff:
            historical[row['store_id']].append(row)
    # The period query already applies Desde. Earlier approved history is needed for last-at-cutoff.
    if start:
        earlier = measurement_reports.history(tuple(store['code'] for store in active), end=cutoff, status='Aprobado')['rows']
        historical = defaultdict(list)
        for row in earlier:
            historical[row['store_id']].append(row)
    result = []
    for store in active:
        period = periods[store['code']]
        dates = sorted({row['date'] for row in period})
        last = max((row['date'] for row in historical[store['code']]), default=None)
        gap = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / (len(dates) - 1) if len(dates) > 1 else None
        score = average(period)
        result.append({'code': store['code'], 'name': store['name'], 'region': store['region'], 'commune': store['commune'],
                       'count': len(period), 'days': len(dates), 'last': last,
                       'age': (date.fromisoformat(cutoff) - date.fromisoformat(last)).days if last else None,
                       'gap': round(gap, 1) if gap is not None else None, 'score': round(score, 1) if score is not None else None})
    measured = sum(row['count'] > 0 for row in result)
    value = 100 * measured / len(active) if active else None
    coverage_indicator = settings_service.indicator('coverage', value, parameters)
    coverage_indicator['value'] = round(value, 1) if value is not None else None
    return {'rows': result, 'total': len(active), 'measured': measured, 'unmeasured': len(active) - measured,
            'count': sum(row['count'] for row in result),
            'indicator': coverage_indicator}
