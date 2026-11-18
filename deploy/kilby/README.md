# Salcobrand en Kilby

El frontend Next.js se compila con Node 20 como exportación estática. Nginx sirve
el portal y envía las rutas de API y las páginas del piloto al servicio privado
FastAPI. PostgreSQL 18 guarda los registros y el disco `/data` guarda las fotos.
El análisis utiliza el adaptador remoto existente.

Los servicios usan 1,5 CPU y 2,5 GB de memoria en conjunto. PostgreSQL Starter
agrega 0,5 CPU y 0,5 GB. El disco de la API y el de PostgreSQL tienen 5 GB cada uno.
Los servicios se ejecutan con una instancia y los despliegues se inician manualmente.

## Preparación

Publicar los archivos versionados del proyecto en el repositorio autorizado y
conectarlo a Kilby mediante su GitHub App. Mantener las claves y los archivos de
`.local` en el equipo del operador.

Crear una copia de los datos con contraseñas nuevas para las cuentas exportadas.
El archivo de contraseñas se entrega por un canal privado al responsable.

```powershell
python deploy/kilby/data_bundle.py export --source .local/capture-dev --output .local/kilby/salcobrand-snapshot.tar.gz --credentials-file .local/kilby/account-passwords.json
```

Configurar `KILBY_API_KEY`, `NEURAVISION_REMOTE_URL` y el acceso del servidor de
análisis en el entorno del operador. El adaptador admite el usuario y contraseña
actuales o `INTEGRATION_NEURAVISION_KEY` con la organización vinculada desde la
consola interna. La clave de Kilby autoriza administrar el alojamiento.

```powershell
python deploy/kilby/provision.py --installation 182704154 --repo cristhian-netizen/Salcobrand --branch main --snapshot .local/kilby/salcobrand-snapshot.tar.gz
```

El aprovisionamiento conserva sus identificadores y secretos en
`.local/kilby/deployment-state.json`. Se puede repetir para continuar la creación.
Las respuestas mostradas contienen identificadores y estados.

## Transferencia inicial

Cuando ambos servicios estén `live`, enviar el archivo comprimido por HTTPS a
`/api/bootstrap` del portal con `Authorization: Bearer <bootstrap_token>` del
estado privado. El receptor verifica el SHA-256 del archivo, su manifiesto y la
integridad SQLite antes de restaurarlo. Luego termina y arranca la aplicación.
El migrador copia las 26 tablas a PostgreSQL en una transacción y conserva los
identificadores de productos, PDV, estructuras, revisiones y lecturas. Al reiniciar,
el disco conserva la copia y el marcador PostgreSQL evita repetir la importación.

Comprobar inicio de sesión, las cinco cuentas y sus permisos, los 82 productos,
PDV-001 y sus estructuras, las cinco lecturas, fotos y zoom, planogramas,
configuración y descargas. Registrar el conteo de cada tabla y probar una captura
con el proveedor antes de conectar el dominio definitivo.

## Operación

Solicitar un respaldo PostgreSQL antes de un cambio de versión. Los archivos del
disco necesitan su propia copia, además del respaldo de la base. Un despliegue de
la API detiene brevemente su única instancia para volver a montar el disco.

`APIS_STORE=memory` mantiene el comportamiento del portal local para la API v1
de claves externas. Sus claves y contadores son temporales. El portal usa las
cuentas persistidas en PostgreSQL. La migración de clientes externos de la API v1
requiere configurar su almacenamiento persistente y verificar sus consumidores.


## Planogramas compartidos entre PDV

El maestro contiene el PDF/imagen, posiciones y una única subcategoría; la categoría
se obtiene del catálogo. Guardar el maestro no asigna automáticamente nuevos PDV.
«Asignar a PDV» abre la selección múltiple con región, comuna, tipo de PDV,
categoría y subcategoría. Los dos últimos filtros consultan las referencias
actuales de los locales; «Todas» incluye locales sin referencia. La selección
se conserva al cambiar filtros. La selección del país incluye los PDV activos,
sin exigir un tipo de góndola en el modal.

Primero se revisa el resumen. Si otra referencia activa ocupa el mismo PDV,
categoría, subcategoría y tipo, se requiere confirmar su reemplazo. Las
asignaciones se administran por PDV, sin selector de tipo de góndola. Las
relaciones por tipo que ya existen se conservan para los locales retenidos; los
PDV nuevos reciben una asignación general. Al desmarcar un PDV se retiran todas
sus relaciones con ese planograma. Las referencias específicas existentes
prevalecen sobre las generales. Los cambios concurrentes se rechazan por versión.

La actualización crea tablas aditivas y deriva una sola vez las asignaciones
anteriores, conservando los tipos de góndola vinculados. Desasignar no vuelve a
sembrar las relaciones antiguas. Los registros anteriores con varias
subcategorías se conservan para consulta/captura; deben clasificarse en una sola
antes de usar la nueva asignación. No se actualizan lecturas ni fotos históricas.
Cada captura nueva congela la referencia seleccionada en su solicitud.


## Cuentas: identificadores y contraseñas

El acceso admite nombre de usuario o el email registrado por el administrador,
sin distinguir mayúsculas y conservando siempre el usuario canónico en la sesión,
los permisos y la autoría. Los emails y usuarios no pueden colisionar con otra
cuenta. Las coincidencias ambiguas heredadas se rechazan, sin elegir una cuenta.
Una ficha sin acceso habilitado no permite entrar por ninguno de sus identificadores.

Solo Nombre de usuario, Email, Rol y Estado son obligatorios en la ficha. Los
antecedentes personales, fechas y PDV son opcionales. Analista/Reponedor sin PDV
mantienen un ámbito vacío. Habilitar una cuenta exige definir una contraseña de
8 a 512 caracteres, una mayúscula y un número; la misma regla se aplica al cambio
y restablecimiento. No se modifican las contraseñas ya registradas.

La carga de personas admite solo los cuatro encabezados obligatorios o la
plantilla completa. Las columnas opcionales omitidas conservan sus datos en las
fichas existentes y la importación no crea cuentas ni concede PDV automáticamente.
