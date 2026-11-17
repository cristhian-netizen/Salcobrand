import {profileOf} from '../../lib/profiles.mjs';

const STEP = {
  settings: {title: 'Define los parámetros', text: 'En Configuración crea tipos de PDV, marcas/submarcas, categorías y subcategorías. Revisa las marcas propias y los criterios de análisis.', view: 'configuracion'},
  infrastructure: {title: 'Crea el catálogo de góndolas', text: 'En Infraestructura crea, modifica o elimina tipos de góndola y registra sus medidas, niveles y foto de referencia. La foto se puede ver en miniatura y ampliar al hacer clic.', view: 'infraestructura'},
  stores: {title: 'Registra los PDV y sus estructuras', text: 'En Puntos de venta completa código, nombre, tipo, región, comuna y encargado. Asigna aquí los tipos y cantidades de góndola y revisa las estructuras físicas. Las asignaciones se hacen en PDV, no en Infraestructura.', view: 'pdv'},
  products: {title: 'Completa los productos', text: 'Registra nombre, SKU, clasificación, formato, dimensiones, precio y foto. Puedes importar Excel con vista previa, exportar y eliminar productos individualmente o mediante selección múltiple.', view: 'productos'},
  plans: {title: 'Prepara los planogramas', text: 'Selecciona el PDV y la categoría, marca una o varias subcategorías, carga una imagen o PDF y añade los productos por nivel, posición y caras. Los productos deben existir previamente en el catálogo. Revisa la referencia asignada antes de capturar.', view: 'planogramas', module: 'planograms'},
  people: {title: 'Habilita al equipo', text: 'En Personas y roles crea las fichas, habilita las cuentas que necesiten acceso y asigna su perfil y PDV. Una ficha sin acceso habilitado no permite iniciar sesión.', view: 'usuarios'},
  capture: {title: 'Captura la góndola', text: 'En Escanear góndola filtra tus PDV por región y comuna, selecciona la categoría, una o varias subcategorías y el tipo de góndola. Consulta su foto ampliable, medidas, niveles y profundidades. El botón Ingresar medidas manualmente permite indicar otras medidas para esa captura. Si hay un planograma clasificado, la captura utiliza todas sus subcategorías. Si el PDV no tiene góndolas asignadas, se habilitan automáticamente las medidas manuales. El ancho en metros es opcional; completa los niveles y sus profundidades en centímetros. Adjunta de 1 a 6 fotos JPG, PNG, WebP o HEIC/HEIF, de hasta 25 MB cada una. Revisa su orden de izquierda a derecha antes de enviar. La API del modelo debe estar disponible.', view: 'escanear'},
  history: {title: 'Consulta la medición y su evidencia', text: 'En Mediciones filtra por PDV, góndola, fechas y estado. Abre el detalle para consultar fotos, productos identificados y la referencia utilizada en esa captura, y descargar el Excel individual. El Reponedor recibe en Inicio las notificaciones de aprobación y rechazo de sus mediciones.', view: 'mediciones'},
  review: {title: 'Revisa y confirma el resultado', text: 'Confirma los productos y caras dudosos desde Revisión. En el detalle registra las observaciones manuales y confirmaciones OSA/SOS/CP cuando corresponda. Aprobar o rechazar requiere el perfil Analista; el rechazo lleva una observación.', view: 'revision'},
  alerts: {title: 'Da seguimiento a los hallazgos', text: 'En Alertas consulta ubicación, prioridad, responsable y estado. El Analista puede resolver o reabrir hallazgos. Las correcciones de evidencia pueden exigir una nueva aprobación.', view: 'alertas'},
  dashboard: {title: 'Evalúa el desempeño', text: 'En Dashboards filtra región, comuna, tipo de PDV, local, categoría/subcategoría y fechas. El Analista consulta sus PDV asignados y el Superusuario puede consultar todos. Consulta tendencias, cobertura y frecuencia. Los indicadores de desempeño usan mediciones aprobadas y las confirmaciones requeridas; no se inventan datos faltantes.', view: 'dashboards'},
  reports: {title: 'Descarga los resultados', text: 'En Reportes y exportaciones selecciona PDV, fechas y estado y descarga Excel o CSV. Fecha y hora están separadas; la hora usa formato de 24 horas y zona America/Santiago. La autoría aparece como «Medición hecha por».', view: 'reportes'},
  usage: {title: 'Consulta el uso de análisis', text: 'Selecciona meses Desde/Hasta en Uso de análisis. Los costos estimados USD provienen del resumen del proveedor para toda la organización. Un resumen no disponible se informa como error, no como costo cero. El CSV exporta la consulta mostrada.', view: 'uso-analisis'},
};

const ROLES = {
  admin: {
    title: 'Prepara la operación de tu organización',
    overview: 'Como Administrador configuras locales, infraestructura, catálogos, personas y parámetros, y consultas los resultados.',
    limits: 'Tu perfil no permite escanear fotos, confirmar resultados ni aprobar, rechazar o resolver mediciones. La consola interna de clientes requiere una autorización independiente del equipo Neuramorphic.',
    steps: ['settings', 'infrastructure', 'stores', 'products', 'plans', 'people'],
    modules: ['inicio', 'configuracion', 'pdv', 'infraestructura', 'productos', 'planogramas', 'usuarios', 'mediciones', 'gondolas', 'alertas', 'dashboards', 'reportes', 'enlaces', 'cuenta'],
  },
  analyst: {
    title: 'De la captura a la revisión aprobada',
    overview: 'Como Analista capturas, revisas y das seguimiento a las mediciones de los PDV a los que tienes acceso.',
    limits: 'Tu perfil no permite administrar PDV, infraestructura, productos, planogramas, parámetros ni cuentas. El ámbito de PDV lo configura el Administrador.',
    steps: ['capture', 'history', 'review', 'alerts', 'dashboard', 'reports'],
    modules: ['inicio', 'escanear', 'mediciones', 'gondolas', 'revision', 'alertas', 'dashboards', 'reportes', 'cuenta'],
  },
  viewer: {
    title: 'Consulta resultados para tomar decisiones',
    overview: 'Como Superusuario consultas las mediciones, alertas, indicadores, reportes y el uso estimado de análisis de la organización.',
    limits: 'Tu perfil es de consulta: no permite escanear, confirmar productos, aprobar o rechazar mediciones, resolver hallazgos ni modificar los datos de administración.',
    steps: ['history', 'alerts', 'dashboard', 'reports', 'usage'],
    modules: ['inicio', 'mediciones', 'gondolas', 'alertas', 'dashboards', 'reportes', 'uso-analisis', 'cuenta'],
  },
};

export const MODULE_HELP = {
  inicio: 'Resumen y accesos según tu perfil. El Analista ve su actividad y las revisiones pendientes; el Superusuario ve prioridades del negocio.',
  configuracion: 'Tipos de PDV, marcas/submarcas, categorías/subcategorías y criterios de análisis de la organización.',
  pdv: 'Locales, ubicación, estado, encargado y asignación de tipos/cantidades de góndola. Excel con vista previa, exportación y vínculos con las estructuras existentes.',
  infraestructura: 'Catálogo de tipos de góndola: crear, modificar, eliminar y cargar una foto con miniatura y zoom. Las asignaciones a locales se realizan desde PDV.',
  productos: 'Maestro de productos con SKU, clasificación, medidas, precio, foto, Excel y eliminación individual o múltiple. Las listas de clasificación se ordenan alfabéticamente.',
  planogramas: 'Referencias visuales por PDV, imagen o PDF, productos por nivel/posición y caras esperadas. La selección de productos está ordenada alfabéticamente.',
  usuarios: 'Fichas y cuentas de acceso, perfil, PDV, fechas, vigencia y restablecimiento de contraseñas. La importación Excel crea fichas y no concede cuentas automáticamente.',
  escanear: 'Envía fotos al modelo desde una góndola autorizada. Puedes ordenar o quitar fotos antes del envío y recuperar una solicitud existente si el resultado se interrumpe.',
  mediciones: 'Historial filtrable, estados, evidencia y detalle de las capturas. Las observaciones manuales se identifican separadamente del resultado del modelo.',
  gondolas: 'Lecturas por góndola, evidencia y reposición sugerida. Las solicitudes y quiebres no equivalen a inventario confirmado ni a un despacho automático.',
  revision: 'Productos dudosos por confirmar. La aprobación o rechazo de la medición y los detalles manuales se revisan en su detalle.',
  alertas: 'Hallazgos y rechazos con filtros por ubicación, fechas y estado. Solo el Analista puede resolver o reabrir hallazgos.',
  dashboards: 'Desempeño aprobado, tendencias, rankings, cobertura, frecuencia, calendario y exportaciones. Las preferencias de indicadores se guardan en este navegador.',
  reportes: 'Historial filtrado en Excel/CSV con código y nombre del PDV, fecha y hora separadas, estado y «Medición hecha por». Rechazados y En revisión quedan fuera del desempeño. El Superusuario dispone además de Excel de Productos y Puntos de venta.',
  'uso-analisis': 'Resumen mensual de costos estimados USD entregados por el proveedor y CSV del resultado consultado. Exclusivo para Superusuario.',
  enlaces: 'Enlaces para que el personal de un local cargue fotos desde su teléfono. Las fotos se guardan; el enlace no ejecuta por sí mismo el análisis del modelo.',
  cuenta: 'Consulta tu usuario y cambia tu contraseña con la actual y la confirmación de la nueva. El cambio cierra las otras sesiones de tu cuenta.',
};

const COMMON_FAQ = [
  {title: '¿Por qué no veo los mismos módulos que otra persona?', text: 'El menú depende de tu perfil, del ámbito de PDV y de los módulos habilitados para el cliente. El Administrador gestiona las cuentas y asignaciones. Cada persona debe usar su propia cuenta.'},
  {title: '¿Qué significa que una cuenta esté suspendida o de baja?', text: 'Suspendido permite iniciar sesión y consultar, pero bloquea las modificaciones. De baja bloquea el acceso. El Administrador revisa la vigencia en Personas y roles.'},
  {title: '¿Por qué faltan lecturas, productos o locales?', text: 'Comprueba los filtros y los PDV asignados. Localhost y producción pueden usar bases distintas: la información de producción no aparece automáticamente en desarrollo. Si faltan datos, consulta al Administrador antes de volver a cargarlos.'},
  {title: '¿Qué mediciones cuentan para el desempeño?', text: 'Solo las aprobadas. Las rechazadas y las que están En revisión no forman parte de esas métricas, aunque puedes consultarlas y exportarlas según los filtros. Los indicadores manuales requieren sus detalles y confirmaciones.'},
  {title: '¿La plataforma conoce las ventas o las unidades ocultas?', text: 'Las fotos y los detalles confirmados aportan evidencia visible. La capacidad teórica por dimensiones no confirma unidades ocultas. Ventas, inventario ERP y despachos requieren una fuente verificada e integración adicional; no se generan automáticamente.'},
];
const CAPTURE_FAQ = [
  {title: '¿Confirmar un producto entrena automáticamente el modelo?', text: 'Las correcciones se guardan como revisión local y pueden requerir una nueva aprobación. En esta integración no entrenan automáticamente la memoria visual del proveedor.'},
  {title: '¿Qué hago si el análisis tarda o se interrumpe?', text: 'El primer análisis puede tardar varios minutos. Consulta la solicitud en curso y el historial antes de volver a enviar fotos. La solicitud se conserva al recargar; usa su recuperación cuando esté disponible para evitar duplicar el envío.'},
  {title: '¿Por qué no puedo seleccionar una góndola?', text: 'Verifica tus PDV autorizados y que el local, el tipo de góndola y su estructura estén activos. El Administrador revisa esas asignaciones desde Puntos de venta. La captura también requiere conexión con el modelo.'},
];

export function helpFor(user) {
  const role = profileOf(user), content = ROLES[role];
  if (!content || user?.portal_access === false) return null;
  const enabled = key => user?.tenant?.modules?.[key] !== false;
  return {...content, role, steps: content.steps.map(key => STEP[key]).filter(step => !step.module || enabled(step.module)),
    modules: content.modules.filter(view => view !== 'planogramas' || enabled('planograms')),
    faqs: [...(role === 'analyst' ? CAPTURE_FAQ : []), ...COMMON_FAQ], photos: role === 'analyst'};
}
