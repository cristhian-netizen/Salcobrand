# Equivalencia funcional con el portal anterior

La referencia funcional es el portal autenticado de Django y sus módulos
operativos en `portal/dist`, además de la configuración guardada en la base
local anterior. Los componentes de demostración se identifican por separado de
las funciones que persistían mediante API. Esta revisión corresponde a la rama
local `migration/four-client-profiles`.

## Funciones que se deben conservar

| Área anterior | Estado en esta rama | Verificación o trabajo pendiente |
| --- | --- | --- |
| Login, sesión, cambio de contraseña y cierre de sesión | Implementado | Pruebas de sesión y permisos de los cuatro perfiles |
| Administrador, Analista, Reponedor y Superusuario | Implementado | Autorización en backend y compatibilidad con cuentas supervisor/tienda |
| Ámbito de PDV y capturas propias del Reponedor | Implementado | Rutas de lecturas, imágenes, recortes, jobs y Mediciones |
| Inicio por perfil | Implementado localmente | Estructuras finales de `profile-management.js`: seis accesos de Administrador, contadores propios y revisión del Analista, capturas/rechazos propios del Reponedor y cinco PDV con menor puntaje aprobado más rechazos del Superusuario. Detalle desde las tablas y refresco al cerrar. Acceso a Dashboards habilitado para Superusuario |
| Escanear con fotos, ubicación y planograma | Implementado para el piloto | Captura real, orden de fotos, referencia congelada, reintentos y recuperación |
| Historial global de Mediciones con filtros | Implementado | Módulo separado, PDV, góndola, fechas, estado, paginación y detalle |
| Detalle de medición, fotos, recortes y posiciones | Implementado para el piloto | Evidencia autenticada y comparación con la referencia de origen |
| Confirmación de productos y caras | Implementado localmente | Correcciones persistidas. El adaptador remoto conserva la revisión local sin entrenar la memoria visual remota |
| Aprobar/rechazar, observación y exclusión de métricas | Implementado | Solo Analista, motivo de rechazo, conflictos de versión y desaprobación al cambiar evidencia |
| Detalle manual por SKU y confirmaciones OSA/SOS/CP | Implementado localmente | Producto, posición, propiedad, esperado/presente, caras, planograma, precio y confianza; góndola física y tres confirmaciones. Reglas de `retail.js` validadas en backend, OSA por producto, SOS por caras, CP por posición, parámetros configurados y aprobación obligatoria. Versiones, auditoría y nueva revisión tras cambios. Agregación integrada en Dashboards |
| Alertas, prioridad, responsable, resolver y reabrir | Implementado localmente | Hallazgos observados, prioridad y responsable originales; rechazos propios y de otros usuarios según perfil; filtros de PDV/góndola/fechas/estado; detalle; resolución/reapertura solo Analista, persistencia, versiones y auditoría. Faltantes aprobados y resolución de quiebres de proveedor conservados |
| Dashboards como módulo independiente | Implementado localmente | Filtros de región/comuna/tipo/PDV/fechas, tendencias mensuales, rankings, rechazos, cobertura/frecuencia, OSA/SOS/CP/OOS confirmados, participación por marca, calendario, selección de PDV, preferencias y cuatro exportaciones CSV. El proveedor cartográfico sigue pendiente como en el portal anterior |
| Reportes de mediciones | Implementado | Excel/CSV con las 13 columnas acordadas, fecha/hora chilenas separadas y desempeño aprobado. PDV autorizados sin góndolas incluidos en filtros. Superusuario recupera Excel de Productos y PDV |
| PDV como módulo independiente | Implementado localmente | CRUD, estado, región/comuna y encargado; plantilla e importación Excel con vista previa, exportación PDV/Gondolas, CSV filtrado y protección de versiones. Inventario anterior comparado y preparado por separado, conforme a la decisión del usuario |
| Infraestructura independiente | Implementado localmente | Catálogo con creación, edición, eliminación, búsqueda, Estante/Vin/Vitrina, proveedor, ancho/alto, niveles, profundidades, foto, miniatura y zoom. Cantidades por tipo dentro de Crear/Editar PDV. Estructuras, etiquetas y vínculo histórico dentro de PDV. Inventario PF identificado para revisión |
| Productos independientes | Implementado | Fotografías, clasificación, medidas, precios, Excel con vista previa y eliminación individual/selección masiva con protección de referencias |
| Planogramas independientes | Implementado para el piloto | PDF/imagen, páginas, descarga, nivel/posición/caras, SKU, código de barras, orden alfabético y versiones. Se conserva también la numeración por producto del documento importado |
| Personas, fichas y accesos | Implementado localmente | Fichas con nombres/apellidos/email/cargo/fechas/estado, acceso opcional, cuatro roles, PDV con filtros geográficos y selección múltiple, suspensión en modo consulta, baja, eliminación, cambio de contraseña y Excel con vista previa. Cuentas previas visibles con ficha por completar |
| Parámetros y clasificación | Implementado localmente | Configuración del Administrador: tipos de PDV, marcas/submarcas, categorías/subcategorías, exclusividad, marcas propias, semáforo, margen de profundidad y metas KPI. Conectado a PDV, Productos y Excel. Cobertura/CP y colores aplican parámetros. Indicadores OSA/SOS/OOS integrados en Dashboards |
| Uso de análisis del Superusuario | Implementado localmente; costos reales pendientes del proveedor | Acceso exclusivo, período mensual de hasta 120 meses, costos de vision_gondola, importes USD con cuatro decimales, meses sin información y CSV del resultado consultado. El proveedor de desarrollo responde 404 en /api/usage/summary |
| Identidad del cliente y consola interna de clientes | Implementado localmente | Acceso interno independiente, clientes registrados, identidad/logo/colores/fuentes/módulos, vista previa, borradores locales, JSON, referencias de modelo, versiones y auditoría. Portal vinculado al cliente del despliegue; la consola de identidades no cambia su base operativa |
| Ayuda por perfil | Implementado localmente | Ayuda y soporte para Administrador, Analista y Superusuario; Reponedor excluido como en el portal anterior. Recorridos, módulos, permisos, fotos, preguntas frecuentes, límites y preparación de consultas de soporte |

El criterio de cierre exige marcar cada fila como verificada con sus entradas
normales de interfaz, autorización, persistencia y datos de origen. Este piloto
valida el recorrido de planograma a reporte. La equivalencia completa de la
plataforma requiere cerrar también las filas parciales y pendientes.

## Fuentes revisadas

- `GUIA-CLIENTE.md` del repositorio anterior define módulos, perfiles y límites.
- `portal/dist/retail.js`, `operations.js`, `administration.js`,
  `decision-metrics.js`, `settings-ui.js` y `analysis-usage.js` implementan el
  comportamiento anterior.
- `backend/api/portal_views.py`, `person_views.py`, `usage_views.py` y
  `backend/config/urls.py` definen persistencia, permisos y contratos anteriores.
- La copia local anterior contiene 53 PDV, 2 tipos de góndola, 9 instancias,
  50 productos, 3 fichas de personas y 1 planograma. Esos conteos describen la
  copia local inspeccionada, cuya configuración todavía debe reconciliarse con
  el conjunto definitivo a trasladar.
- `frontend-next/PARITY-AUDIT.md` identifica diferencias de una etapa previa.
  Sus marcas de avance deben volver a comprobarse en esta rama Salcobrand.

## Referencia del piloto

Se utiliza `PDV-001`, su ficha existente en la base local anterior y una copia
del planograma de Salcobrand dev
`desodorantes-masculinos-gb1-brick-nunoa-vina`. La referencia tiene 6 niveles,
82 posiciones y 90 caras esperadas. El PDF original tiene 6 páginas. El Excel
`Plantilla_Productos_Completada.xlsx` aporta 82 productos y declara dimensiones
simuladas. El SKU `594473` aparece en el planograma y falta en ese Excel. La
referencia original se conserva para esa posición mediante la compatibilidad de
productos anteriores.

Las posiciones originales enumeran productos, aunque alguno tenga varias caras.
La propiedad `position_mode=products` mantiene esa numeración. Los planogramas
creados con posiciones por cara conservan `position_mode=faces` y su validación
de superposición. SKU, códigos de barras, niveles, posiciones y caras del piloto
se comparan contra la copia original antes de asignarla.

La preparación y evidencia quedan en `.local/planogram-pilot`, excluido de Git.
Se conserva una copia SQLite previa al piloto. Los scripts
`prepare_planogram_pilot.py` y `planogram-pilot-browser.cjs` usan las entradas
normales de la API y de Escanear. La evidencia guarda el job para recuperar la
misma solicitud en ejecuciones posteriores.


## Validación del detalle manual

Se trasladaron los campos y confirmaciones de `retail.js` a las rutas
`GET/PATCH /api/readings/{id}/product-details` y
`GET /api/readings/{id}/product-detail-options`. Las opciones de edición
requieren Analista y pertenecen al PDV de la lectura. El servidor conserva
identidad, origen manual, referencia del planograma, versión y auditoría.
Los cambios requieren una nueva aprobación y las correcciones de evidencia
invalidan las confirmaciones previas.

Pasaron 66 pruebas de backend y la compilación Next con Node 20. El navegador
verificó OSA 100 %, SOS 75 % y CP 50 %, valores cero, persistencia, validación,
conflictos, consulta de otros perfiles y vista móvil. Evidencia en
`.local/details-qa`, excluida de Git. En localhost:3001 se comprobó la consulta
con los cuatro perfiles y la apertura/cancelación del formulario. PDV-001 tiene
82 productos y referencia de planograma, pero todavía necesita vincular una
góndola física desde Puntos de venta para guardar el detalle. La agregación
de estos indicadores está integrada en el módulo Dashboards.


## Validación de Dashboards

`GET /api/dashboard` aplica el ámbito del usuario en el backend. Solo
Administrador, Analista y Superusuario acceden al módulo y a las exportaciones
`/api/dashboard/export/{operation|locations|rejections|measurements}.csv`.
Los filtros comparten catálogo geográfico y tipos de PDV con la administración.
Las descargas incluyen el filtro completo y neutralizan fórmulas de CSV.

Se conservaron los meses sin actividad con conteo cero y puntaje/tasa sin datos,
el calendario de fechas válidas, los PDV activos sin lecturas y la última lectura
aprobada al corte. Los indicadores usan denominadores ponderados y umbrales sin
redondear. Ausencias recientes usa la última lectura aprobada por góndola física
y la vigencia configurada. La clasificación de marca capturada se conserva cuando
existe y las observaciones restantes usan la configuración de marcas propias.

Las pruebas cubrieron permisos, ámbito, geografía, cortes, ponderación, umbrales,
calendario bisiesto, meses vacíos, marcas y exportaciones. Compilación Next/Node 20
aprobada. El navegador verificó filtros, gráficos, cuatro descargas, preferencias
persistentes, modal de detalle y vista móvil. Evidencia en `.local/dashboard-qa`.
En localhost:3001 se comprobaron los cuatro perfiles. El piloto actual tiene
cuatro mediciones en revisión y ninguna aprobada, por lo que el desempeño y los
KPI confirmados permanecen sin datos. El panel de red conserva la selección por
PDV y el estado pendiente de proveedor cartográfico de la versión anterior.


## Validación de Alertas

`GET /api/alerts` recupera los hallazgos de `restored-portal.js` y el seguimiento
de rechazos de `decision-dashboard.js`. Incluye avisos de planograma registrados,
espacio vacío observado, posiciones sin precio explícitamente visible y productos
reportados ausentes. El hallazgo de precio requiere precio nulo o una señal explícita de etiqueta no visible.
La prioridad conserva Alta para el primer hallazgo y Media para los siguientes.
El responsable figura como Sin asignar, tal como en el portal anterior.

`PATCH /api/alerts/readings/{id}/{kind}` permite resolver y reabrir únicamente al
Analista dentro de su ámbito. `management_reading_alerts` conserva versión, autor,
fecha y huella de evidencia. Una corrección que cambia el hallazgo vuelve a
mostrarlo pendiente. Su estado permanece asociado a su tipo y evidencia aunque
cambie el orden de otros hallazgos. Las ediciones simultáneas devuelven conflicto
y la resolución del hallazgo conserva el estado de revisión de la medición.

Las tablas de rechazo incluyen autor, motivo, revisor y acceso al detalle.
Administrador/Superusuario consultan los rechazos accesibles, Analista distingue
propios y otros en sus PDV, y Reponedor consulta sus propias capturas. Los filtros
por PDV, góndola y fecha usan el día de Chile. El filtro de estado corresponde al
ciclo Pendiente/Resuelta de los hallazgos. Se conservan los faltantes de la última
lectura aprobada del período de 30 días y los quiebres de proveedor abiertos con
su acción de resolver.

Pasaron 80 pruebas de backend y la compilación Next con Node 20. El navegador
comprobó resolución/reapertura, persistencia tras recarga, recuperación de
conflictos, filtros, resolución de proveedor, modal, permisos y alineación móvil.
Evidencia y respaldo previo local están en `.local/alerts-qa`, excluidos de Git.
La revisión en localhost:3001 abrió y consultó Alertas con los cuatro perfiles.

## Validación de Excel e inventario de PDV

La carga masiva conserva las nueve columnas de la hoja `PDV` del portal anterior.
La plantilla contiene esa hoja y la exportación completa añade `Gondolas` con
código de PDV, nombre de tipo y cantidad. La importación crea o actualiza por
código y procesa la hoja `PDV`. Las relaciones se administran en Puntos de venta.
Los códigos de texto conservan ceros iniciales y los encabezados anteriores
`Responsable` y `Responsable de local` siguen siendo compatibles. Los nombres
regionales con los prefijos Región, Región de y Región del se validan contra
el catálogo y se guardan con su denominación canónica.

Los endpoints `/api/admin/store-transfer/workbook.xlsx`,
`/api/admin/store-transfer/filtered.csv` y `/api/admin/store-transfer/import`
requieren Administrador. La vista previa valida ubicación, tipo configurado,
estado, duplicados, fórmulas y límites de archivo. La confirmación es atómica
y verifica que el archivo, las fichas y los tipos coincidan con lo revisado.
Preserva puntos, asignaciones, instancias, usuarios y mediciones. El CSV aplica
búsqueda, región, comuna, estado y la selección de incluir eliminados.

La copia anterior corresponde a Productos PF y contiene 53 PDV. Localhost tiene
tres PDV. Comparten `PDV-001`, cuya ficha coincide al normalizar la región. Se compararon
los 52 códigos exclusivos del origen y los dos exclusivos de localhost. Por
decisión expresa del usuario, los 52 adicionales quedan en
`.local/pdv-reconciliation/Productos_PF_PDV_pendientes.xlsx` para revisión.
`Comparacion_PDV.csv` conserva las diferencias y referencias del origen, y
`summary.json` registra los conteos. La validación de los 52 adicionales pasa
tras admitir los nombres regionales del portal anterior. La vista previa en
localhost se canceló y los tres PDV actuales conservaron sus datos y versiones.

Las pruebas de regresión verifican permisos, hojas, columnas, códigos de texto,
compatibilidad de encabezados, creación/actualización, atomicidad, conflictos,
CSV filtrado y conservación de relaciones e historial. El navegador comprobó
vista previa, confirmación en datos ficticios, errores, recuperación de conflicto,
plantilla, Excel, CSV y alineación de escritorio/móvil. La evidencia y el respaldo
local están en `.local/pdv-qa`, excluidos de Git.

Pasaron 86 pruebas de backend y la compilación Next con Node 20.

## Validación de Infraestructura y asignaciones desde PDV

La comparación con `management.js` y `operations.js` recuperó el catálogo
compartido y la asignación de cantidades dentro de Crear/Editar PDV.
Infraestructura presenta crear, editar y eliminar góndolas, búsqueda y fotos.
La tabla de PDV muestra tipos y cantidades, y su acceso Góndolas conserva las
estructuras, etiquetas, lecturas y vínculo de puntos anteriores.

El formulario de Infraestructura incluye nombre/código, proveedor/fabricante,
Estante/Vin/Vitrina, ancho, alto cuando corresponde, profundidades y hasta
100 niveles para Estante. La numeración parte desde abajo, como en el original.
Las fotos JPG/PNG/WebP de hasta 5 MB se reducen a 640 px. La miniatura se amplía
al hacer clic tanto en el catálogo como en la ficha del PDV. Escape cierra
la foto y mantiene abierto el formulario.

Crear/Editar PDV envía cantidades y versiones en `assignments` a las rutas
existentes `/api/admin/stores`. La ficha y todas sus asignaciones se guardan en
una transacción. Los conflictos revierten la operación completa. Los clientes
anteriores que omiten asignaciones conservan el comportamiento previo.
Las cantidades admiten 0 a 10000, como el formulario original, y la reactivación
reutiliza las estructuras existentes.

`DELETE /api/admin/shelf-types/{id}?version=...` requiere Administrador y versión
vigente. La eliminación retira el tipo del catálogo, pone sus cantidades en cero,
desactiva estructuras y registra auditoría en el tipo y los PDV. Las mediciones,
fotos históricas, puntos y referencias conservan sus identificadores. Un nuevo
tipo puede reutilizar el nombre del eliminado con identidad independiente.

La ampliación de esquema es aditiva para SQLite/PostgreSQL. Las pruebas locales
ejercitaron SQLite, incluida una base con el esquema anterior y dos arranques
consecutivos. Los registros previos conservan dimensiones, fotos y versiones.
Los campos que antes faltaban, como el alto de G1, figuran por completar.
La verificación de esta etapa corresponde a localhost y SQLite.

Pasaron 90 pruebas de backend y la compilación Next con Node 20. El navegador
verificó los tres tipos, creación/edición/eliminación, persistencia de foto, zoom,
Escape, asignación desde PDV, cantidades cero/reactivación, etiquetas, historial
y vista móvil. La consulta de localhost:3001 abrió y canceló formularios.
Evidencia, respaldo e inventario anterior en `.local/infrastructure-qa`.
La copia Productos PF contiene dos tipos, cuatro asignaciones y nueve estructuras.
Su inventario queda identificado para revisión junto a los PDV preparados.

## Validación de Personas y roles

La referencia incluye `person-access.js`, `operations.js`, `administration.js`
y `backend/api/person_views.py`. Personas y roles muestra fichas y cuentas
existentes en una sola tabla, búsqueda por persona/usuario/email/cargo/rol,
fechas de alta/baja, estado, acceso y ámbito de PDV. El formulario recupera
nombres, apellidos paterno y materno, email, nombre de usuario, cargo y rol.
La selección de PDV incluye región, comuna, selección individual y selección
de todos los locales visibles. El Analista conserva también el ámbito completo
de las cuentas anteriores.

`/api/admin/people` permite consultar, crear y editar fichas con versión.
El inicio de sesión es opcional para una ficha nueva. Habilitarlo requiere
contraseña inicial y los permisos se guardan junto con la ficha en una sola
transacción. Las cuentas existentes conservan su nombre de usuario. Cambiar
contraseña usa un formulario independiente con confirmación y cierra las
sesiones de la cuenta. El Administrador conserva la protección contra cambiar
su propio rol, suspenderse, darse de baja o eliminarse.

Vigente permite operar según el perfil. Suspendido permite iniciar sesión y
consultar, y el backend rechaza todas las solicitudes de modificación. De baja
bloquea el acceso y exige fecha de baja. Las fechas registradas conservan el
carácter informativo del formulario anterior, y el estado controla el acceso.
Suspender o dar de baja conserva los PDV asignados cuando el rol se mantiene.
Eliminar retira la ficha y el acceso conservando mediciones y autoría histórica.

`management_people` conserva los datos personales y versiones. Los usuarios
previos aparecen sin inventar nombres, correo, cargo o fechas, con la indicación
Completar ficha. Sus credenciales, roles y PDV se mantienen. `users.auth_version`
es aditivo y permite invalidar sesiones al cambiar rol, ámbito, estado o
contraseña. Las sesiones anteriores siguen válidas hasta que se modifica
el acceso. El cambio de contraseña desde Mi cuenta renueva la sesión actual
y revoca las demás. El restablecimiento administrativo revoca todas.
Los endpoints anteriores `/api/admin/users` siguen disponibles y sincronizan
las versiones de fichas y la revocación de sesiones.

La carga masiva conserva la hoja Personas y sus once columnas originales.
La plantilla está en `/api/admin/people/template.xlsx` y la vista previa y
confirmación en `/api/admin/people/import`. Acepta fechas ISO, fechas Excel y
fechas numéricas de Excel. Se validan duplicados, fechas, email, rol, estado,
PDV, fórmulas, tamaño y cantidad de filas. La confirmación es atómica y rechaza
una vista previa desactualizada. El Excel crea fichas sin conceder nuevas
cuentas. Los cambios de permisos de cuentas vinculadas se realizan desde
Editar usuario, según la protección del portal anterior.

La regresión general pasó 98 pruebas de backend y las nueve pruebas específicas
finales de Personas también pasaron, incluido el cambio de contraseña propio.
La compilación Next con Node 20 pasó. El navegador comprobó creación, selección
de PDV, confirmación de contraseña, suspensión/consulta, reactivación, baja,
restablecimiento, eliminación, Excel, errores, persistencia y vista móvil.
El esquema y el comportamiento local se verificaron con SQLite.
La evidencia y respaldo están en `.local/people-qa`. Las tres fichas de la copia
Productos PF quedan identificadas para revisión en `legacy-people.json`.

## Validación de Uso de análisis

La referencia es `analysis-usage.js`, `usage_views.py` y sus pruebas del portal
anterior. El módulo Uso de análisis aparece en Análisis exclusivamente para
Superusuario. `GET /api/reports/analysis-usage` aplica el mismo permiso en el
backend. Administrador, Analista y Reponedor reciben 403 y el usuario sin sesión
recibe 401. La consulta del Superusuario suspendido conserva el modo lectura.

Desde/Hasta seleccionan meses, con seis meses iniciales según America/Santiago.
El backend admite fechas ISO válidas, normaliza al mes y valida de 1 a 120 meses
inclusivos. Recupera cada mes completo del resumen del proveedor y contempla
años bisiestos. El ámbito es la organización completa, independiente de PDV,
geografía y estado de revisión de las mediciones.

El adaptador reutiliza la URL y el acceso de servidor de `remote_model`.
Autentica una vez por consulta y solicita `/api/usage/summary` para cada mes.
Las credenciales y cookies del proveedor permanecen en el backend.
Los importes proceden exclusivamente de las filas `vision_gondola` de
`by_endpoint`. La suma usa Decimal y descarta costos negativos, no finitos,
ausentes o inválidos como información desconocida. Una lista de endpoints
vacía produce cero, siguiendo el contrato original.

La tabla conserva Mes, Período y Costo estimado (USD), con cuatro decimales en
pantalla y alineación numérica. El conteo original de costos conocidos se
rotula Meses con información, porque incluye meses con costo cero. Los importes
desconocidos se muestran con un guion y el total indica cuántos meses lo
componen. El CSV conserva las tres columnas, el importe decimal del proveedor
y celdas vacías para costos desconocidos. Exporta la consulta mostrada, sin
volver a consultar al proveedor. Cambiar filtros exige Consultar antes de
exportar y los errores de conexión impiden mostrar o descargar un resultado
anterior como si correspondiera al nuevo período.

Pasaron 105 pruebas de backend y la compilación Next con Node 20. El navegador
aislado comprobó roles, filtros, límites, decimales, ceros, valores desconocidos,
CSV, recuperación de errores, vista móvil y la descarga de plantilla PDV que
comparte la utilidad de archivos. Evidencia y respaldo en `.local/usage-qa`.

La prueba real confirmó autenticación HTTP 200 y HTTP 404 en
`https://salcobrand-dev.neuramorphic.ai/api/usage/summary`. Localhost muestra
la indisponibilidad del resumen y mantiene la sesión del Superusuario.
La integración de importes reales depende de que el proveedor habilite ese
endpoint con el contrato anterior o comunique su reemplazo y esquema. La
validación numérica de la interfaz se hizo con respuestas sintéticas aisladas.


## Validación de identidad y consola interna de clientes

La referencia es `console/dist/console.js`, `config-schema.js`, `console-gate.js`,
`backend/api/console_views.py` y `portal_gateway.py` del portal anterior.
La consola se abre en `/#/consola` y requiere autorización interna independiente
del rol Administrador. Las cuentas previas conservan sus credenciales, permisos
y acceso al cliente. `users.is_internal` y `users.portal_access` son columnas
aditivas; las cuentas internas quedan protegidas de los listados, edición,
eliminación y restablecimiento desde Personas y roles y los endpoints anteriores.

Los runners locales crean explícitamente `local-internal`, con acceso exclusivo
a la consola y la contraseña de desarrollo documentada para los perfiles locales.
La aplicación desplegable no crea este operador al arrancar. No se conceden
permisos internos automáticamente a administradores de clientes.

La consola lista clientes registrados y permite consultar y modificar nombre,
logo, colores principal/lateral, fuentes y colores de barra/contenido, tamaño
lateral de 10 a 24 px, indicadores de ejecución y participación y Planogramas.
Ventas e inventario conserva la indicación de integración pendiente. El logo
PNG/JPG/WebP de hasta 5 MB se optimiza a 500 px y se valida también en backend.
La vista previa permanece separada de la identidad fija de la consola.
La identidad se aplica al portal autenticado al volver a iniciar sesión.
El login mantiene su paleta Neuramorphic. Se conservan colores semánticos de
estados y permisos; desactivar indicadores no quita permisos para capturar.
Desactivar Planogramas retira sus accesos y congela nuevas capturas sin esa
referencia, conservando las asignaciones y lecturas históricas existentes.

Los borradores se guardan en `nv-console-drafts`, son compatibles con el formato
plano anterior y siempre se abren sin cliente seleccionado. Para aplicar uno,
se abre el cliente registrado y se carga explícitamente un borrador del mismo
cliente y versión. Los borradores de otro cliente o versión se rechazan. Cambios
sin guardar requieren confirmación al cambiar de cliente. Un fallo de carga
retira el formulario y la vinculación anterior. Seleccionar un borrador sin
abrirlo no cambia cuál se está editando. Exportar JSON conserva el formato plano
anterior y excluye catálogos, identificadores internos y claves reales.
Nuevo borrador local no registra organizaciones ni provisiona usuarios, como en
la consola anterior; ese alta continúa siendo un proceso separado.

Las rutas son `GET /api/internal/clients`, `GET /api/internal/clients/{id}` y
`PATCH /api/internal/clients/{id}`. El guardado comprueba versión e identificador
inmutable y registra auditoría. Preserva clasificaciones guardadas en la identidad
y no escribe PDV, productos, infraestructura, personas, mediciones ni parámetros
operativos. `/api/auth/me` expone únicamente la identidad pública del cliente
vinculado al entorno, sin la configuración interna del modelo.

`management_clients` es un directorio de identidades. La base operativa del
piloto continúa vinculada a un solo cliente por despliegue, identificado mediante
`NEURAVISION_TENANT_ID` (Salcobrand por defecto). Editar la identidad de otro
cliente no permite navegar sus datos ni cambia la vinculación del portal.
No se importaron clientes ni datos operativos de Productos PF.

La conexión permite conservar el acceso de servidor actual o guardar referencias
`remoteOrgId` y `credentialEnv`. Esta última solo admite nombres `INTEGRATION_`:
la clave real permanece en variables de entorno del servidor. El adaptador con
clave verifica `/api/auth/me` y el `org_id` antes de acceder a datos del proveedor.
Cambiar la vinculación del cliente activo se bloquea si hay capturas en cola,
en proceso o con resultado ambiguo por recuperar. La validación de clave y
organización se probó con transporte simulado; no se configuró una clave real
ni se cambió la conexión de desarrollo existente.

Pasaron 112 pruebas de backend con SQLite, la compilación Next con Node 20 y
pruebas de navegador en escritorio y móvil. Se verificaron los cuatro perfiles,
logo, fuentes, módulos, permisos, JSON, borradores anteriores, selección explícita,
aislamiento de dos identidades sintéticas, versiones y recuperación de errores.
En localhost:3001 se revisó la consola y los cuatro perfiles sin aplicar cambios
de identidad. La API de captura siguió disponible. Se comparó el respaldo contra
la base local y se confirmaron intactos los datos operativos y cuentas anteriores.
Evidencia, scripts de navegador y respaldo en `.local/identity-qa`, excluido de Git.
La validación de PostgreSQL y del despliegue definitivo permanece para la etapa
correspondiente. El punto siguiente es trasladar Ayuda por perfil.


## Validación de Ayuda y soporte por perfil

Se compararon `portal/dist/restored-portal.js`, `app.js` y `GUIA-CLIENTE.md`
del portal anterior con las funciones ya implementadas en esta rama. Se conserva
el nombre Ayuda y soporte y su visibilidad para Administrador, Analista y
Superusuario. El Reponedor no recibe ese acceso; una URL directa vuelve a Inicio.
La cuenta interna continúa en su consola independiente.

El contenido está separado en `web/modules/help`: recorrido, módulos, preguntas
frecuentes, preparación de consultas de soporte y presentación. Administrador
recibe el orden de configuración, catálogo de góndolas, asignaciones en PDV,
productos, planogramas y personas. Analista recibe captura, revisión, evidencia,
confirmaciones, aprobación/rechazo y seguimiento. Superusuario recibe consultas,
reportes e información de uso de análisis. Cada guía explica sus permisos y
límites y ofrece accesos a sus módulos permitidos. Planogramas desaparece también
de la guía cuando el cliente lo tiene deshabilitado. La cuenta suspendida muestra
una aclaración de consulta sin modificaciones.

Se actualizó la guía genérica para describir el flujo actual: de una a seis fotos,
formatos admitidos y límite por archivo, orden y recuperación de solicitudes,
fotos de infraestructura con miniatura y zoom, asignaciones dentro de PDV,
fichas separadas del acceso, Excel con vista previa, fecha/hora de reportes y
métricas de desempeño aprobadas. Se distinguen los detalles manuales de los
resultados del modelo y se explica que las correcciones locales no entrenan
por sí mismas la memoria visual remota. Los enlaces de captura guardan fotos
sin ejecutar análisis. Ventas/inventario requieren fuentes verificadas y los
costos dependen del resumen del proveedor. Soporte muestra los datos necesarios
para comunicar un caso, sin inventar direcciones, tickets ni invitaciones por
correo. El nombre del cliente procede de la identidad autenticada.

La compilación Next con Node 20 pasó. La prueba de navegador en localhost:3001
comprobó los tres perfiles con ayuda, todos sus enlaces de módulos, los límites
de visibilidad, preguntas frecuentes con teclado, escritorio y móvil. Se
verificaron además el Reponedor y la cuenta interna. Las comprobaciones de
contenido cubrieron módulos deshabilitados, perfil anterior supervisor y uso de
análisis exclusivo para Superusuario. No se enviaron solicitudes de modificación
de datos; solo se iniciaron las sesiones de prueba. Evidencia y script en
`.local/help-qa`, excluido de Git. Esta etapa modifica el frontend; la validación
anterior de las 112 pruebas del backend sigue registrada en el punto 9.

Los puntos 9 y 10 quedan cerrados en localhost. Las comprobaciones de integración
con el entorno definitivo, PostgreSQL, el endpoint pendiente de costos del
proveedor y la preparación/publicación de producción siguen siendo actividades
de validación y despliegue posteriores.


## Prueba integral de aceptación en localhost

Se ejecutó el recorrido técnico con los cuatro perfiles contra localhost:3001
y el backend local, con respaldo previo en `.local/acceptance-qa/before-data.db`.
La foto proporcionada por el usuario se envió una sola vez desde Reponedor a
`pdv-001`, dentro de PDV-001. El identificador de solicitud y el job se guardaron
para recuperar la misma operación sin duplicar el envío al proveedor dev.
La solicitud se recuperó al recargar y terminó en la lectura local #5.
La referencia conservó sus 82 posiciones y 90 caras esperadas. La API devolvió
85 caras detectadas. Un recorte Rexona 72h pack 2X se verificó visualmente y se
confirmó desde Revisión; las demás identificaciones permanecen pendientes.

Se verificaron rechazo y aprobación temporales sobre esa lectura nueva,
claramente identificada como prueba técnica. Rechazado no alteró el promedio
ni el número de aprobadas. Aprobado agregó una lectura válida y el promedio
coincidió entre Reportes y Dashboards. Los otros tres perfiles recibieron 403
al intentar cambiar el estado. Después se dejó En revisión, con una observación
explicativa; las métricas finales volvieron a excluirla. Las métricas manuales
sin cobertura confirmada permanecieron desconocidas, incluso durante la prueba
de aprobación. No se certificó la revisión visual completa de la captura.

Las descargas reales desde la interfaz pasaron la comprobación de las 13
columnas, código y nombre de PDV, autor «Medición hecha por», fecha y hora como
tipos separados en Excel, formato `hh:mm "hrs."` y CSV con separador punto y
coma. Fecha/hora correspondieron a America/Santiago. Los estados de prueba
aprobados se conservan únicamente como evidencia en `approved-download`; el
archivo `final-pending-measurements.xlsx` refleja el estado final pendiente.

El recorrido revisó filtros por PDV/estado/fechas y rechazo de rangos inválidos,
selección individual/todos de productos, eliminación disponible en su modal,
orden alfabético, foto/zoom de Infraestructura, PDF de Planogramas y ausencia
de carga masiva no solicitada, Personas y roles, Configuración, límites del
Reponedor y presentaciones de escritorio/móvil. Se corrigió la indicación del
detalle manual para vincular estructuras desde Puntos de venta (PDV). La vista
previa de Reportes conserva anchos legibles, fecha/código sin cortes y una región
con foco para desplazar horizontalmente las 13 columnas.

La comparación adicional con `portal/dist/administration.js` recuperó Reportes
de catálogos del Superusuario: Productos · Excel y Puntos de venta · Excel.
Las nuevas rutas `GET /api/reports/catalog/products.xlsx` y
`GET /api/reports/catalog/stores.xlsx` reutilizan los exportadores del backend,
requieren Superusuario, admiten consulta de cuentas suspendidas y no habilitan
las APIs de administración. Se comprobaron las descargas con 82 productos y
3 PDV, además de los rechazos de otros perfiles y usuarios sin sesión.

El filtro de Reportes/Mediciones ahora incluye los PDV registrados autorizados
que todavía no tienen góndolas, devolviendo cero filas al seleccionarlos.
Conserva los locales históricos de las lecturas y los límites de PDV del perfil;
una solicitud fuera de ese ámbito sigue recibiendo 403. Las pruebas cubren
PDV vacío, Excel vacío, exclusión de locales no asignados, exportación de
catálogos y conservación de texto literal en las celdas.

Se comparó la base contra el respaldo: maestros, cuentas y las cuatro lecturas,
jobs y revisiones anteriores se conservaron. Solo se agregó la captura de
aceptación, sus archivos y sus eventos de revisión. No quedaron jobs en proceso.
La evidencia, scripts y resultados están en `.local/acceptance-qa`, excluido de
Git. La comprobación corresponde al entorno local y a la API de análisis dev;
no se publicaron cambios en producción.

**Reserva para cerrar la aceptación operativa:** PDV-001 todavía no tiene una
estructura física vinculada. El tipo provisional G1 del catálogo tiene cinco
niveles y el planograma piloto tiene seis; las dimensiones de productos del
piloto se declararon simuladas. Se comprobó el acceso Vincular a tipo dentro
de PDV y se canceló sin asignar medidas no verificadas. La captura queda
En revisión para la revisión visual del usuario/Analista. Vincular la estructura
correcta y confirmar datos reales es necesario antes de certificar OSA/SOS/CP
de este caso; la lógica manual sí está cubierta por las pruebas aisladas.


Validación final de esta aceptación técnica: 114 pruebas de backend con SQLite,
8 pruebas JavaScript de perfiles/clasificaciones y compilación de exportación
Next con Node 20 aprobadas. Se repitieron en navegador los filtros y formatos
corregidos y las dos descargas del Superusuario con sus límites de acceso.
Las reservas sobre revisión humana y estructura física permanecen explícitas;
la prueba técnica no sustituye la confirmación de datos definitivos del cliente.
