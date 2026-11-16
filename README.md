# Salcobrand · NeuraVision

Portal migrado a Next.js, API FastAPI y PostgreSQL 18, alojado en Kilby.

Portal de validación desplegado en
https://salcobrand-web-qo18.apps.kilby.neuramorphic.ai

El código se mantiene en el repositorio privado
https://github.com/cristhian-netizen/Salcobrand, rama `main`.
Los despliegues de Kilby se inician manualmente después de validar cada cambio.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `web/` | Frontend principal Next.js y React, compilado con Node 20 |
| `app/backend/` | API, permisos, catálogos, infraestructura, mediciones, revisión y reportes |
| `app/frontend/` | Páginas y recursos del piloto de farmacia |
| `deploy/kilby/` | Contenedores, proxy, aprovisionamiento y transferencia inicial de datos |
| `scripts/` | Herramientas de migración y validación local |

## Servicios de Kilby

`salcobrand-web` sirve la exportación estática de Next.js y envía las solicitudes
de API al servicio privado `salcobrand-api`, bajo el mismo origen HTTPS.
La base `salcobrand` utiliza PostgreSQL 18. La API conserva las fotografías en
su disco persistente de 5 GB, montado en `/data`.

El análisis de imágenes usa actualmente la API de desarrollo de Salcobrand.
La conexión al proveedor productivo y el dominio definitivo requieren completar
su configuración y validación. Los datos importados proceden del entorno local
de migración, con sus mediciones de prueba.

Las cuentas y sus permisos se conservan en PostgreSQL. Las contraseñas generadas
para Kilby se entregan en el archivo privado del operador. El almacenamiento de
claves externas de la API v1 sigue configurado en memoria, según el entorno local
de origen. Su persistencia se configura antes de incorporar consumidores externos.

## Desarrollo

```powershell
git clone https://github.com/cristhian-netizen/Salcobrand.git
cd Salcobrand/web
npm ci
$env:SALCOBRAND_BACKEND_URL = 'http://127.0.0.1:8012'
npm run dev
```

Usar Node 20 y un backend local configurado con los datos privados de desarrollo.
La URL `SALCOBRAND_BACKEND_URL` selecciona el backend del proxy de Next.js.

Las variables, los respaldos, las fotografías y los archivos de contraseñas del
operador se guardan fuera del código versionado. El procedimiento de despliegue,
transferencia inicial y respaldo está en [deploy/kilby/README.md](deploy/kilby/README.md).

Los documentos `PROFILE-MIGRATION.md` y `MIGRATION-PARITY.md` registran el recorrido
y las comprobaciones de la migración anterior.
