# Salcobrand · app (entorno de desarrollo)

- `web/`: frontend principal (Next.js, diseño de Cris). Se publica en la raíz del dominio y habla
  directo con la API de Salcobrand (`/api/*`, mismo origen, cookie de sesión). Local:
  `cd web && npm ci && npm run dev` (por defecto usa el backend de salcobrand-dev).
- `app/frontend`: páginas del piloto que siguen en sus rutas (tienda, captura, cámara en vivo, panel, revisión).
- `app/backend`: la API.

## Ramas

| Rama | Uso |
|---|---|
| `develop` | Trabajo diario. **Cada push despliega automáticamente** en https://salcobrand-dev.neuramorphic.ai |
| `main` | Refleja producción. Solo lectura para desarrollo: los cambios llegan por pull request desde `develop`. |

## Flujo

1. `git clone https://git-codecommit.us-east-1.amazonaws.com/v1/repos/salcobrand && cd salcobrand && git checkout develop`
2. Cambia `web/` (y si hace falta `app/backend`), commit y `git push origin develop`.
3. Queda publicado solo: `web/` en 1 a 3 minutos (CodeBuild `salcobrand-dev-web`), `app/` en 3 a 5 minutos
   (CodeBuild `salcobrand-dev`, reinicia la API dev). `app/frontend` son las páginas del piloto que usan las
   farmacias: no cambiarlas sin coordinar.
4. Logs: CloudWatch → `/ecs/salcobrand-dev` (API), `/ecs/salcobrand-dev-worker` (motor) y
   `/aws/codebuild/salcobrand-dev-web` (build del frontend).

El entorno dev usa datos copiados de producción (3 farmacias) en su propia base, bucket y cola: nada de lo
que se haga aquí afecta a producción. El motor de análisis se enciende solo al subir una foto
(hasta unos 6 minutos la primera vez; luego unos 15 segundos) y se apaga tras 15 minutos sin trabajo.

## Credenciales git

Consola de AWS → tu usuario (arriba a la derecha) → Credenciales de seguridad →
"Credenciales HTTPS de Git para AWS CodeCommit" → Generar. Usa ese usuario y contraseña al hacer clone/push.
