"""Confirmed OSA/SOS/CP semantics from the original retail.js visionSummary."""
from settings_service import display_parameters, indicator


def observations(data, has_planogram):
    rows = data['details']
    groups = {}
    if data['expectedConfirmed']:
        for row in rows:
            if row['expected']:
                groups.setdefault(row['productId'], []).append(row)
    expected = [group for group in groups.values() if all(isinstance(row['present'], bool) for row in group)]
    present = sum(any(row['present'] for row in group) for group in expected)
    compared = [row for row in rows if row['match'] in ('Sí', 'No')] if has_planogram and data['comparisonConfirmed'] else []
    matching = sum(row['match'] == 'Sí' for row in compared)
    classified = rows if data['scopeConfirmed'] and rows and all(
        isinstance(row['faces'], int) and row['ownership'] in ('Propio', 'Competencia') for row in rows
    ) else []
    all_faces = sum(row['faces'] for row in classified)
    own_faces = sum(row['faces'] for row in classified if row['ownership'] == 'Propio')
    face_rows = [row['faces'] for row in rows if isinstance(row['faces'], int)]
    return {'expected': len(expected), 'present': present, 'allFaces': all_faces, 'ownFaces': own_faces,
            'compared': len(compared), 'matching': matching, 'faces': sum(face_rows) if face_rows else None,
            'detailCount': len(rows), 'missing': [group[0] for group in expected if not any(row['present'] for row in group)]}


def ratios(counts):
    return {'osa': 100 * counts['present'] / counts['expected'] if counts['expected'] else None,
            'sos': 100 * counts['ownFaces'] / counts['allFaces'] if counts['allFaces'] else None,
            'cp': 100 * counts['matching'] / counts['compared'] if counts['compared'] else None}


def calculate(data, has_planogram, approved):
    counts = observations(data, has_planogram)
    values = ratios(counts)
    parameters = display_parameters()['kpiParameters']
    indicators = {}
    for key, value in values.items():
        indicators[key] = indicator(key, value if approved else None, parameters)
        indicators[key]['value'] = round(value, 1) if approved and value is not None else None
    return {'eligible': approved, **counts,
            'indicators': indicators}
