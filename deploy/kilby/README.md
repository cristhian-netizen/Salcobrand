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
