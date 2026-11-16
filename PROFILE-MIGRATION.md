# Migración local de los cuatro perfiles

Rama: `migration/four-client-profiles`, basada en `develop` (`beb181d`).
La copia de trabajo principal permanece en `develop`. No se hizo push.

| Capacidad | Administrador | Analista | Reponedor | Superusuario |
| --- | --- | --- | --- | --- |
| Consultar lecturas y alertas | Sí | Sí, en su ámbito | Solo propias, en PDV asignados | Sí |
| Capturar | No | Sí | Sí, en PDV asignados | No |
| Confirmar recortes/revisar | No | Sí | No | No |
| Resolver alertas/solicitudes | No | Sí | No | No |
| Reportes y tendencias | Sí | Sí, en su ámbito | No | Sí |
| Usuarios, góndolas, planogramas y enlaces | Sí | No | No | No |

Mi cuenta, cambio de contraseña y cierre de sesión siguen disponibles para cada persona.
Un analista con lista vacía de PDV tiene alcance general; el Reponedor requiere al menos
un PDV y una cuenta sin asignaciones no recibe datos. Las asignaciones admiten varios códigos.

## Compatibilidad y datos

- Las cuentas existentes conservan sus valores almacenados: `supervisor` se interpreta
  como Analista y `tienda` como Reponedor. `/api/auth/me` conserva `role` para el piloto
  y añade `profile`, `permissions` y `store_ids`. Next normaliza los nombres.
- No se editaron las páginas del piloto en `app/frontend` ni su código de captura.
  Los permisos del servidor sí cambian; la validación del piloto completo queda para
  el entorno dev antes de promover la rama.
- SQLite y PostgreSQL reciben columnas aditivas `users.store_ids_json` y
  `readings.captured_by`. No se borran cuentas, contraseñas ni lecturas.
- El worker conserva al autor de las capturas nuevas. Para lecturas antiguas solo se
  recupera la autoría que ya figure en `api_jobs.payload_json.user`; una lectura sin
  autor comprobable no se atribuye a un Reponedor.
- Las fotografías originales y los recortes comprueban permisos por sesión, PDV y
  autor. El consumidor externo que recupera una foto original debe autenticar también
  esa solicitud con su API key; las claves existentes no se modifican.
- Los maestros de PDV, Infraestructura y Productos, los estados de aprobación/rechazo
  y los formatos de exportación completos corresponden a los siguientes bloques.

## Validación

Pruebas de perfiles del navegador:

```powershell
node --test web/lib/profiles.test.mjs
```

Pruebas HTTP con rutas/autenticación/base SQLite reales y servicios externos aislados:

```powershell
python -m unittest discover -s app/backend/tests -v
```

Dependencias de QA: FastAPI, httpx, python-multipart, python-dotenv, Pillow y uvicorn.
La suite no conecta con AWS, con la API dev ni con el motor. La migración PostgreSQL
está preparada en el esquema, pero no fue ejecutada contra una instancia PostgreSQL.

Verificado: build de exportación Next con Node 20; recorridos reales de navegador de
Administrador, Analista, Reponedor y Superusuario contra la API temporal. Se comprobaron
menús, acciones, navegación directa, cuatro opciones del selector de perfiles y ancho móvil.
`scripts/profile-browser-qa.cjs` exige el marcador del QA local antes de enviar logins;
usa un navegador de pruebas con DevTools en `127.0.0.1:9225`.

Vista local opcional de los perfiles, con base temporal y motor deshabilitado:

```powershell
python scripts/serve_profile_qa.py
# En otra terminal, dentro de web/:
$env:SALCOBRAND_BACKEND_URL='http://127.0.0.1:8011'
$env:NV_NEXT_DIST_DIR='.next-local-management'
node node_modules/next/dist/bin/next dev -p 3001
```

Usuarios exclusivamente ficticios: `local-admin`, `local-analyst`,
`local-replenisher` y `local-viewer`. Contraseña del QA temporal:
`Isolated-local-password-2026!`. La base se elimina al cerrar el proceso de QA.

## Segundo bloque: PDV e Infraestructura

Trabajo local sobre `migration/four-client-profiles`; sin push ni despliegue.
Los módulos aparecen por separado en Administración, solamente para Administrador.
Los otros perfiles conservan lectura/captura según las reglas del primer bloque.

- PDV: código inmutable, nombre, tipo, región/comuna dependientes, dirección,
  Encargado de Local, estado y descripción; búsqueda/filtros, edición, eliminación
  lógica, restauración como Inactivo e historial con usuario y fecha.
- Infraestructura: catálogo de tipos con ancho, niveles, profundidad por nivel,
  miniatura opcional y estado; cantidades por PDV, estructuras con etiqueta/nota
  y enlace al historial de lecturas.
- Los códigos de local ya usados se registran sin inventar ubicaciones ni medidas.
  Aparecen como «Completar datos». Los puntos sin tipo se vinculan explícitamente:
  vincular suma una unidad activa y conserva identificador, planograma y lecturas.
- Aumentar cantidades reutiliza las estructuras inactivas antes de crear otras.
  Disminuir desactiva las últimas activas; no borra puntos ni mediciones.
- PDV/tipo/estructura inactivos bloquean nuevas capturas en servidor y en interfaz.
  El historial permanece visible. Cada nuevo job incluye una copia de las medidas
  que se guarda con la lectura; posteriores ediciones no cambian esa copia.
- Las escrituras usan versiones y transacciones: una edición desactualizada devuelve
  409, conserva el formulario y pide actualizar. No se permite borrar un punto con
  lecturas o vinculado a infraestructura.

### API propia del backend

Estas rutas son FastAPI y no dependen de React ni de las rutas hash del portal.
La autenticación es la misma sesión del backend; las rutas `/api/admin/*` requieren
Administrador. `GET /api/stores` devuelve solamente datos básicos, limitados a los
PDV asignados cuando el perfil tiene alcance restringido.

| Método y ruta | Función |
| --- | --- |
| GET `/api/admin/location-catalog` | Regiones, comunas y tipos de PDV |
| GET/POST `/api/admin/stores` | Listar / crear PDV |
| PATCH `/api/admin/stores/{code}` | Editar con `version` |
| DELETE `/api/admin/stores/{code}?version=N` | Eliminación lógica |
| POST `/api/admin/stores/{code}/restore` | Restaurar con `version` |
| GET `/api/admin/stores/{code}/history` | Auditoría del local |
| GET/POST `/api/admin/shelf-types` | Listar / crear tipos |
| PATCH `/api/admin/shelf-types/{id}` | Editar dimensiones, foto y estado |
| GET `/api/admin/infrastructure?store_code=CODIGO` | Asignaciones, estructuras y puntos sin tipo |
| PUT `/api/admin/stores/{code}/shelf-assignments/{id}` | Cantidad activa y versión de asignación |
| POST `/api/admin/shelf-instances/link-existing` | Vincular un punto existente |
| PATCH `/api/admin/shelf-instances/{id}` | Etiqueta y nota con versión |

Esquema aditivo compartido SQLite/PostgreSQL en `management_schema.py`; las tablas
originales conservan sus identificadores. Se añade `readings.capture_context_json`.
El catálogo chileno se reutilizó de la migración original (`chile-data.mjs`).
No se copiaron bases ni datos productivos. Importación Excel de PDV/Infraestructura
y un piloto contra PostgreSQL quedan fuera de este bloque.

Validación: 20 pruebas HTTP/SQLite, 3 de permisos JavaScript, exportación estática
Next con Node 20 y recorridos de navegador de los cuatro perfiles. El recorrido de
Administrador crea PDV, tipo, cantidades y etiqueta, comprueba persistencia tras
recargar, ancho móvil y alineación de botones. Motor y servicios externos aislados.
La integración con API v1 conserva la autorización por cliente, añade el control
de estructura inactiva y transporta las medidas en el job; requiere validación con
el servicio real antes de publicar. No se ejecutó el motor ni PostgreSQL.

Para compilar en Windows/OneDrive sin que la limpieza de Next quede bloqueada:

```powershell
$env:NEXT_OUTPUT='export'
$env:NV_NEXT_DIST_DIR='.next-local-export-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$env:NV_KEEP_BUILD_CACHE='1'
node node_modules/next/dist/bin/next build
```

En exportación estática Next usa `.next` para compilar y `NV_NEXT_DIST_DIR` como
destino de exportación. Por eso la caché del servidor local debe estar fuera de
`.next` (`.next-local-management`), para que un build no la elimine.
`NV_KEEP_BUILD_CACHE` es opcional y solo se usó en QA local; producción mantiene la
limpieza predeterminada. Cada validación usa un destino nuevo de exportación para
evitar los bloqueos de OneDrive al sobrescribir carpetas generadas.
El directorio de exportación no se publicó. El QA local incluye `L128` como
«PDV de demostración», con ubicación/encargado ficticios y `point-a` vinculado a
un tipo de ejemplo; sus dos lecturas originales de prueba permanecen disponibles.

## Productos y Planogramas

Productos dispone de alta y edición con SKU, código de barras, submarca, categoría,
subcategoría, tipo, formato, cantidad, dimensiones, volumen calculado, precio,
precio por kg/litro y fotografía. La clasificación admite ingreso manual y ofrece
sugerencias alfabéticas basadas en los productos locales. La configuración central
de clasificación del portal Django requiere su propia integración en Salcobrand.
Los filtros de submarca y categoría y la selección de productos del planograma se
ordenan alfabéticamente. Seleccionar todo actúa sobre los resultados filtrados.

La eliminación individual se encuentra en el modal del producto. La selección
múltiple muestra «Eliminar producto(s)», con confirmación y versiones. Una
referencia en un planograma bloquea toda la eliminación, incluidos los productos
seleccionados que estaban libres. Los identificadores anteriores de un producto
editado también se consideran al comprobar referencias de planogramas importados.

El Excel mantiene la hoja y las columnas de la plantilla anterior y añade código
de barras opcional. Plantilla, exportación, vista previa y confirmación se ejecutan
en el backend. La importación es atómica, valida nuevamente el archivo y rechaza
una vista previa cuyo catálogo cambió. Conserva fotografías existentes. SKU y
código de barras se leen como texto para mantener ceros iniciales. Se validan los
límites de tamaño, filas y fórmulas y se exportan los textos como texto de Excel.

Planogramas incluye filtros de región, comuna dependiente, PDV, estado y búsqueda.
El modal permite imagen o PDF de hasta 5 MB, navegación por páginas, descarga del
original y selección de la página inicial. PDF.js y sus recursos locales se
reutilizan desde el portal anterior, con su licencia, sin solicitudes a un CDN.
Las posiciones contienen nivel, producto, posición inicial, SKU, código de barras
y caras. Se validan identidad, superposiciones y máximo de 5.000 caras. No se
incluyen carga masiva ni plantilla Excel de posiciones en el modal de planogramas.
Se conserva la importación PDF con texto/JSON del repositorio Salcobrand.

Los planogramas importados conservan sus códigos y productos todavía no registrados
en el maestro. Las asignaciones compartidas que ya existían en otros PDV se
conservan al incorporar la edición de catálogo. Las asignaciones nuevas requieren
un planograma activo del mismo PDV. Cambiar de PDV un planograma propio asignado
requiere desasignarlo primero. Un planograma inactivo bloquea nuevas capturas,
manteniendo la consulta de lecturas anteriores.

La edición/eliminación conserva una copia de la referencia de cada lectura.
Los jobs nuevos transportan su referencia y los jobs anteriores en cola reciben
la referencia previa antes de un cambio. Un job anterior ya iniciado impide editar
su referencia hasta terminar. La revisión y el reanálisis consultan esa copia.
El reemplazo de un JSON/PDF anterior es transaccional y conserva las asignaciones.

### Rutas del catálogo

Todas requieren la sesión de Administrador y están implementadas en FastAPI.
`GET /api/admin/catalog` devuelve listas sin imágenes ni PDF. El editor obtiene
los adjuntos al solicitar el detalle de un registro.

| Método y ruta | Función |
| --- | --- |
| GET `/api/admin/catalog` | Listas y versión del catálogo |
| GET `/api/admin/catalog/products/{id}` | Producto completo con fotografía |
| POST `/api/admin/catalog/products` | Crear producto |
| PATCH `/api/admin/catalog/products/{id}` | Editar con versión |
| POST `/api/admin/catalog/products/delete` | Eliminar selección con versiones |
| GET `/api/admin/catalog/products.xlsx?template=true` | Plantilla Excel |
| GET `/api/admin/catalog/products.xlsx` | Exportar productos |
| POST `/api/admin/catalog/products/import` | Vista previa o confirmación multipart |
| GET `/api/admin/catalog/planograms/{id}` | Detalle y referencia del planograma |
| POST `/api/admin/catalog/planograms` | Crear planograma |
| PATCH `/api/admin/catalog/planograms/{id}` | Editar con versión |
| DELETE `/api/admin/catalog/planograms/{id}?version=N` | Eliminar conservando historial |
| POST `/api/admin/catalog/reference` | Validar PDF y contar páginas |

Se añaden tablas de productos, metadatos/versiones de planogramas y versión global
del catálogo. `readings.plan_snapshot_json` conserva la referencia histórica.
Las tablas originales de planogramas siguen siendo la entrada del motor.

Validación local de este bloque incluye 31 pruebas HTTP/SQLite, 3 pruebas de
perfiles JavaScript, exportación estática con Node 20 y recorridos de los cuatro
perfiles en navegador. Se comprueban fotos, páginas de PDF renderizadas, Excel
descargado/importado, caras, superposiciones, referencias bloqueadas, filtros,
alineación y ancho móvil. PostgreSQL y el motor real siguen pendientes de piloto.

Dependencias adicionales de QA y backend son `openpyxl` y `pypdf`, incluidas en
`app/requirements.txt`. Para el navegador aislado con DevTools en el puerto 9225
puede indicarse el Python del entorno de QA para generar archivos ficticios.

```powershell
$env:CATALOG_QA_PYTHON='ruta-al-entorno-de-QA\Scripts\python.exe'
node scripts/profile-browser-qa.cjs
```

El QA local incorpora dos productos y un planograma de demostración en L128.
Sus datos son temporales y desaparecen al cerrar el servidor de QA.

## Captura con la API real de desarrollo

El módulo Escanear utiliza solicitudes asíncronas autenticadas en FastAPI.
Acepta hasta seis fotografías JPG, PNG, WebP o HEIC, con 25 MB por archivo
y 100 MB por solicitud. Conserva el orden, normaliza la orientación y permite
recuperar el resultado al recargar la página. Las credenciales del proveedor
permanecen en el backend.

| Método y ruta | Función |
| --- | --- |
| GET `/api/capture/status` | Disponibilidad del motor configurado |
| POST `/api/points/{id}/analysis-jobs` | Cargar fotos multipart y encolar con `Idempotency-Key` |
| GET `/api/analysis-jobs` | Solicitudes activas del usuario |
| GET `/api/analysis-jobs/{id}` | Estado y medición final autorizada |
| GET `/api/analysis-requests/{id}` | Recuperar la solicitud si se perdió la confirmación de carga |
| POST `/api/analysis-jobs/{id}/resume` | Recuperar un resultado remoto ambiguo |

La tabla aditiva `management_capture_requests` relaciona usuario, identificador
de solicitud, huella de las fotos y job. Los reintentos conservan el mismo job.
Una captura remota pendiente o ambigua bloquea otra nueva en la misma góndola
para mantener la asociación entre fotografía y resultado. La recuperación
consulta el resultado previamente enviado. Las fotografías se conservan cuando
la respuesta remota se interrumpe.

El modo `NEURAVISION_ANALYSIS_BACKEND=remote` utiliza
`NEURAVISION_REMOTE_URL`, `NEURAVISION_REMOTE_USERNAME` y
`NEURAVISION_REMOTE_PASSWORD`. `NEURAVISION_REMOTE_POINT_PREFIX` o
`NEURAVISION_REMOTE_POINT_MAP` definen las góndolas de destino. El tiempo de
recuperación se configura mediante `NEURAVISION_REMOTE_TIMEOUT_S`, con 900
segundos por defecto. El arranque habitual conserva el motor integrado.

El adaptador inicia sesión en `/api/auth/login`, consulta `/v1/health`, crea
una góndola de desarrollo mediante `/api/points` y envía las fotos a
`/api/points/{id}/analyze`. Consulta `/api/points/{id}` para recuperar resultados.
Cuando hay una referencia de planograma, crea una versión inmutable mediante
`/api/admin/planograms` y la asigna mediante `/api/points/{id}/planogram`.
La revisión manual se guarda localmente. El modo remoto conserva esa revisión
sin entrenar la memoria visual del proveedor.

### Ejecutar en localhost

El servidor real de desarrollo mantiene SQLite, imágenes y sesión en
`.local/capture-dev`, excluido de Git. Utiliza un prefijo remoto independiente
por instalación. El documento de acceso puede proporcionar las credenciales
de aplicación directamente al proceso.

```powershell
python scripts/serve_capture_dev.py --access-document 'ruta\Acceso-AWS-Salcobrand-dev-Cris.pdf'
```

En otra terminal, desde `web`, con Node 20 disponible en PATH.

```powershell
$env:SALCOBRAND_BACKEND_URL='http://127.0.0.1:8012'
$env:NV_NEXT_DIST_DIR='.next-local-capture-dev'
npm run dev -- --port 3001
```

Los usuarios locales son `local-admin`, `local-analyst`, `local-replenisher`
y `local-viewer`, con contraseña inicial `Isolated-local-password-2026!`.
Analista y Reponedor pueden cargar fotografías desde Escanear en `pdv-001`.

### Resultado de validación real

Se procesó la foto proporcionada por el usuario con Salcobrand dev y el PDV
`PDV-001`, en una góndola remota con prefijo `MIGLOCAL`. La lectura local 1
corresponde a la remota 83. La lectura local 2, enviada desde el navegador como
Reponedor, corresponde a la remota 84. Ambas registraron 85 caras visibles y
84 elementos pendientes de revisión. La calidad de identificación requiere
validación manual.

El navegador comprobó carga de archivo, consulta asíncrona, recarga durante
el procesamiento, recuperación tras una interrupción HTTP 503, imagen original,
recortes, superposición de detecciones, autor y restricciones por perfil.
Se comprobó el ancho móvil de 390 píxeles. La evidencia local y los IDs de
solicitud están en `.local/capture-dev/proof.json` y sus capturas de pantalla.
`scripts/capture-browser-qa.cjs` repite la comprobación sobre esa evidencia.

El planograma versionado tiene una prueba de contrato con transporte simulado.
La validación automatizada terminó con 40 pruebas de backend y 3 de perfiles
JavaScript aprobadas. La compilación y exportación estática de Next con Node 20
terminaron correctamente.
Las dos pruebas reales utilizaron una góndola sin planograma asignado. Quedan
pendientes el piloto con planograma real, PostgreSQL y la validación del entorno
de despliegue antes de publicar.

## Reportes, exportaciones y desempeño

Reportes ofrece filtros por PDV, fechas y estado, una vista previa de hasta 100
mediciones y descarga completa en Excel o CSV. Ambos formatos comparten el orden
de columnas del portal anterior.

`ID`, `PDV`, `Nombre PDV`, `Región`, `Comuna`, `Fecha`, `Hora`, `Puntaje`,
`Estado`, `Observación`, `Considerar en desempeño`, `Medición hecha por`,
`Encargado de Local`.

El Excel utiliza celdas de fecha y hora independientes y ordenables. La hora se
muestra como `15:35 hrs.`, con zona `America/Santiago` y sus cambios estacionales.
Los filtros de fechas incluyen el día completo en esa zona. El CSV usa UTF-8 con
BOM y punto y coma. El Excel conserva los textos como texto y el CSV neutraliza
los prefijos de fórmula. El módulo reutiliza `openpyxl`, ya utilizado por el
catálogo, y añade `tzdata` para resolver el horario chileno también en Windows.

El estado global de cada medición se guarda en la tabla aditiva
`management_reading_reviews`, con observación, autor, fecha y versión. El Analista
puede modificarlo desde el detalle de una lectura. El rechazo requiere un motivo.
Las modificaciones concurrentes producen un conflicto 409. Corregir productos o
reanálizar devuelve la medición a En revisión e invalida su aprobación anterior.
Las mediciones antiguas sin aprobación registrada se consideran En revisión.

El promedio del reporte utiliza únicamente mediciones aprobadas que coincidan
con los filtros. Sin aprobaciones, muestra ausencia de datos. Los registros
rechazados y pendientes siguen disponibles en el historial y sus descargas,
marcados con `Considerar en desempeño = No`.

Inicio y el listado de góndolas calculan cumplimiento, quiebres e impacto usando
la última medición aprobada por góndola dentro del período seleccionado. La
actividad reciente conserva la última captura de cualquier estado. El conteo de
capturas registradas conserva todos los estados y el conteo de aprobadas queda
identificado por separado. Las tendencias, métricas diarias y recurrencia de
quiebres utilizan exclusivamente aprobaciones, antes de aplicar sus límites.
El detalle de una lectura conserva los resultados individuales de su análisis.

| Método y ruta | Función |
| --- | --- |
| GET `/api/reports/measurements` | Vista previa, filtros disponibles y totales |
| GET `/api/reports/measurements.xlsx` | Excel completo de mediciones filtradas |
| GET `/api/reports/measurements.csv` | CSV con las mismas columnas y filtros |
| PATCH `/api/readings/{id}/review` | Estado, observación y versión de revisión |

Los reportes admiten `store`, `point`, `from`, `to` y `status`. Las tres rutas
requieren permisos de reportes y aplican el ámbito de PDV en el backend. El
Reponedor carece de exportaciones. Administrador y Superusuario consultan los
estados y descargan reportes. Solo el Analista guarda revisiones autorizadas.
La descarga CSV desde una góndola utiliza este mismo contrato. Las rutas CSV
anteriores del backend siguen disponibles para sus consumidores existentes.

La validación terminó con 47 pruebas de backend y 3 de perfiles JavaScript
aprobadas. Incluye columnas exactas, fecha/hora nativas, límites del día chileno,
horario de invierno y verano, permisos, aislamiento, estados mezclados, conjunto
vacío, promedio aprobado, cumplimiento y conflictos de revisión. El navegador
comprobó aprobación/rechazo desde el formulario, filtros, descargas reales,
restricciones por perfil, alineación y ancho móvil. La evidencia temporal está
en `.local/reports-qa`. El recorrido se repite mediante
`scripts/reports-browser-qa.cjs`, con QA en 8011, Next en 3002 y DevTools en 9225.

## Piloto real con referencia de planograma

El inventario de equivalencia con el portal anterior está en
`MIGRATION-PARITY.md`. Registra las funciones implementadas y las diferencias
todavía abiertas, incluyendo Dashboards, fichas completas de
Personas, Uso de análisis, Excel de PDV y consola de clientes. El cierre de este
piloto acredita su recorrido específico.

Se importaron los 82 productos de `Plantilla_Productos_Completada.xlsx` mediante
vista previa y confirmación de la API. Las dimensiones de ese archivo están
declaradas como simuladas. Se copió la ficha de `PDV-001` desde la base local
anterior, con su nombre, tipo, ubicación, dirección, encargado y estado.

La referencia real de Salcobrand dev es
`desodorantes-masculinos-gb1-brick-nunoa-vina`. Se conserva su PDF de seis páginas,
sus 82 posiciones y 90 caras esperadas. `position_mode=products` conserva la
numeración ordinal del documento para posiciones con varias caras. Los
planogramas de catálogo anteriores conservan su numeración por caras. La
importación JSON conserva también los precios y su procedencia, incluido cero.

Se realizó una sola carga nueva desde Escanear como Reponedor con la foto del
usuario. Job `j_602498e8cc8d852d`, lectura local 4, lectura remota 86. La carga
conservó la referencia y se recuperó al recargar. El resultado inicial fue 85
caras detectadas, 8,9 % de cumplimiento y 89 elementos por revisar.

El recorte 0/37 se inspeccionó visualmente y confirmó como
`REXONA DEO AER ANTI TRANSPIRANTE 2X`, con una cara. La corrección se guardó
localmente y quedaron 88 elementos por revisar. Se probaron aprobación,
rechazo y la inclusión/exclusión en las métricas. El estado final quedó En
revisión, con una observación técnica y pendiente de validación del Analista.
El resultado requiere revisión humana antes de considerarse una evaluación
comercial validada.

El Excel real del piloto se descargó y comprobó con sus 13 columnas, fecha y
hora nativas, autor, ubicación y encargado heredados. Se comprobaron la consulta
de capturas propias y el rechazo de revisión/exportación para el Reponedor.
El navegador comprobó las seis páginas del PDF, su renderizado, numeración
original, selector alfabético y vista móvil.

Se recuperó el módulo independiente Mediciones mediante `GET /api/measurements`,
con filtros de PDV, góndola, fechas y estado, paginación de 50 filas y detalle.
Todos los perfiles autorizados consultan su historial según su ámbito. Las
cuentas Reponedor reciben únicamente sus propias capturas y las exportaciones
requieren permiso de reportes. Las fotos antiguas con `image_path` conservan su
compatibilidad.

La evidencia y la copia SQLite previa están en `.local/planogram-pilot`. El
SKU `594473` existe en el planograma real y falta en el Excel de productos. Su
posición se mantiene con la compatibilidad de referencias anteriores. La
reconciliación del maestro sigue pendiente de sus datos definitivos.

El bloque terminó con 49 pruebas de backend y 3 de perfiles JavaScript
aprobadas, compilación Next correcta y recorrido real de navegador. Las seis
páginas del PDF se renderizaron y recorrieron en ambos sentidos. Las capturas de
pantalla verificadas incluyen el resultado, el editor PDF y Mediciones a 390 px.


## Configuración del Administrador

El módulo `/#/configuracion` recupera los catálogos y parámetros del portal
anterior. Solo el Administrador puede consultar o modificar su configuración
completa: tipos de PDV; marcas/submarcas; categorías/subcategorías; categorías
exclusivas; marcas propias; semáforo de puntaje; margen de profundidad y metas
KPI de cobertura, OSA, SOS, cumplimiento, ausencias y período de vigencia.

Contratos: `GET /api/admin/settings`,
`PATCH /api/admin/settings/{catalog|pdv-types|score|product|kpi}` y
`GET /api/display-settings` para parámetros de presentación autenticados.
`management_settings` persiste JSON, versión y autor/fecha. Cada sección se
guarda independientemente, con control de concurrencia y auditoría. Los
borradores de otras secciones se conservan. Recargar valores guardados permite
recuperarse de conflictos descartando explícitamente los borradores.

Los tipos alimentan el formulario de PDV. La clasificación alimenta Productos
y valida su API y la vista previa/confirmación de Excel. Se impide quitar tipos
y clasificaciones referenciados. La exclusividad filtra opciones válidas y se
comprueba en el servidor. Los desplegables se ordenan alfabéticamente. Los
catálogos sin configuración explícita conservan compatibilidad hasta su primera
configuración.

El semáforo cambia colores, sin alterar el puntaje ni las reglas de aprobación.
Cobertura y cumplimiento aplican sus metas. La configuración OSA/SOS/OOS y las
marcas propias quedan persistidas; sus dashboards completos siguen pendientes
según `MIGRATION-PARITY.md`. La capacidad teórica usa profundidad capturada,
espesor y margen: es un máximo estimado y queda indeterminada si falta evidencia.
El emparejamiento visual conservador procede del portal anterior.

`scripts/import_legacy_settings.py` importó la copia SQLite anterior mediante
la API local. Resultado: 6 tipos de PDV, 14 marcas/submarcas y 7 categorías,
conservando los datos del piloto. Respaldo y checkpoint están excluidos de Git
en `.local/settings-migration`. El script completado no vuelve a sobrescribir
cambios posteriores.

Validación: 56 pruebas de backend, 8 de JavaScript y compilación Next con Node 20
aprobadas. `scripts/settings-browser-qa.cjs` comprueba permisos de los cuatro
perfiles, creación de clasificación/producto/tipo, referencias protegidas,
conflictos, borradores, persistencia y vista móvil de 390 px en datos desechables.
Su modo `--live-preview` inspecciona localhost:3001 sin editar la configuración.
Evidencia visual: `.local/settings-qa`. Los ensayos no publican cambios.
