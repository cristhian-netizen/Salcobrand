from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import analysis_usage
import profiles


def router(require_user):
    api = APIRouter(tags=['Uso de análisis'])

    @api.get('/api/reports/analysis-usage')
    def usage(date_from: str = '',date_to: str = '',user=Depends(require_user)):
        if profiles.profile_of(user) != 'viewer':
            raise HTTPException(status_code=403,detail='Estas métricas están disponibles para el Superusuario.')
        return JSONResponse(analysis_usage.report(date_from,date_to),headers={'Cache-Control':'no-store'})

    return api
