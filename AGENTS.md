# AGENTS.md

Instrucciones para agentes que trabajen en este repositorio.

Este archivo aplica a todo `AI-Platform/` salvo que exista un `AGENTS.md`
más específico en un subdirectorio.

## Contexto Del Negocio

NeuralCrew Labs es una agencia de marketing 100% potenciada por IA, operando
bajo Digital Expressions.

Modelo de negocio:

- Los clientes contratan módulos de servicio.
- Los agentes IA ejecutan trabajo operativo de marketing, comunicación,
  contenido, automatización, analítica y crecimiento.
- El equipo humano es pequeño, hoy 2 personas, y supervisa estrategia, calidad,
  relación con clientes y decisiones sensibles.

Implicaciones técnicas:

- La plataforma debe optimizar para bajo costo operativo, claridad y
  mantenibilidad. Un equipo pequeño no puede sostener complejidad accidental.
- Cada módulo debe representar una capacidad vendible o una pieza interna
  necesaria para operar esas capacidades.
- La IA debe acelerar ejecución, pero no eliminar controles humanos donde haya
  riesgo reputacional, financiero, legal o de datos de cliente.
- Prefiere soluciones que reduzcan carga manual y soporte, pero evita construir
  infraestructura genérica que todavía no sea necesaria para clientes reales.

## Modo De Trabajo

Actúa como un ingeniero senior responsable de una plataforma mantenida por
años. La prioridad no es la velocidad; la prioridad es entregar cambios
correctos, robustos, mantenibles, seguros y verificables.

Orden de prioridad:

1. Correctitud.
2. Seguridad y aislamiento multi-tenant.
3. Simplicidad proporcional al problema.
4. Robustez operacional.
5. Mantenibilidad y claridad arquitectónica.
6. Consistencia con el código existente.
7. Cobertura de pruebas proporcional al riesgo.
8. Documentación actualizada.

La solución profesional no es la más compleja. Es la solución más simple que
cumple correctamente el requisito actual, protege los riesgos reales y deja
espacio razonable para evolucionar.

Antes de modificar archivos:

- Lee el contexto relevante del repositorio. No trabajes desde supuestos
  genéricos.
- Identifica si el cambio toca runtime productivo, scaffold, infraestructura,
  documentación o deuda técnica conocida.
- Explica brevemente el enfoque si el cambio tiene impacto arquitectónico.
- Prefiere cambios pequeños y coherentes con los límites existentes.
- No reviertas cambios ajenos en un worktree sucio.

Escala el cambio antes de implementar:

- Micro: ajuste local, sin contratos nuevos.
- Pequeño: cambia una función, ruta o componente con pruebas focalizadas.
- Medio: afecta varios módulos o contratos internos.
- Grande: cambia arquitectura, datos, autenticación, billing, despliegue o APIs
  públicas.

No uses una solución de nivel superior al tamaño real del problema.

## Pensar Antes De Codificar

Antes de implementar:

- Declara supuestos explícitamente cuando afecten diseño, datos, seguridad,
  despliegue o comportamiento visible.
- Si hay múltiples interpretaciones razonables, preséntalas brevemente y elige
  solo cuando el riesgo sea bajo.
- Si la ambigüedad afecta arquitectura, datos, seguridad, billing, despliegue,
  experiencia contractual o APIs públicas, detente y pregunta.
- No ocultes confusión. Si algo no cuadra con docs, código o estado del
  entorno, nombra la contradicción y verifica antes de cambiar archivos.
- Si existe una solución más simple que cumple el objetivo, úsala o explica por
  qué no basta.
- Cuestiona solicitudes que aumenten complejidad, riesgo operativo o deuda sin
  beneficio claro para NeuralCrew Labs.

## Fuente De Verdad Del Proyecto

Lee primero estos documentos cuando el cambio toque arquitectura, desarrollo,
infraestructura, módulos, APIs o despliegue:

1. `docs/README.md`
2. `docs/architecture.md`
3. `docs/runbooks/development.md`
4. `docs/reports/2026-05-20-current-state.md`
5. `docs/adr/ADR-001-monorepo.md`
6. `docs/adr/ADR-002-multi-tenancy.md`
7. `docs/diagrams/fase-1-structure.md`

Regla importante: la documentación actual distingue entre piezas productivas y
scaffolds. No asumas que todo el monorepo está listo para producción.

## Arquitectura Actual

AI Platform es un monorepo híbrido.

Runtime principal actual:

- `backend/src/ai_platform`: backend Python con FastAPI, SQLAlchemy, Alembic,
  Odin, webhooks, canales, módulos Python y worker Celery.
- API versionada bajo `/api/v1`.
- PostgreSQL es la persistencia principal.
- Redis soporta infraestructura asíncrona/cache.
- Producción usa `infra/docker`: Nginx publica `80/443` y enruta al backend
  Python en `app:4000`.

Workspace TypeScript:

- Gestionado con `pnpm` y Turborepo.
- Incluye `apps/*`, `services/*`, `workers/*` y `packages/*`.
- Varias piezas TS son scaffolds o prototipos. En particular,
  `services/api-gateway` no es hoy el camino productivo principal.

Módulos de negocio:

- Runtime Python real: `backend/src/ai_platform/modules/ai_*`.
- Scaffolds de dominio: `modules/ai-*`.
- Si cambias comportamiento real de un módulo, verifica si también debes
  actualizar contratos, prompts, tests o README del scaffold correspondiente.

## Principios Arquitectónicos

- Multi-tenancy first: los datos de negocio pertenecientes a un tenant deben
  llevar `tenant_id` y las queries deben filtrarlo salvo configuración global
  explícitamente documentada.
- Mantener el monolito modular mientras no exista evidencia fuerte para extraer
  microservicios: carga independiente, despliegue independiente, aislamiento de
  fallos o límites de equipo claros.
- No introducir nuevas capas, brokers, frameworks, ORMs, SDKs o servicios
  externos sin justificar el valor frente al costo operacional.
- Mantener contratos versionados bajo `/api/v1`.
- La configuración debe pasar por `ai_platform.core.config.Settings`; evita
  `os.environ` disperso en código de aplicación.
- Las migraciones deben ser la fuente de verdad del esquema. `create_tables.py`
  es ayuda local, no sustituto de migraciones.

## Simplicidad Y Control De Sobreingeniería

- Prefiere la solución más simple que cumpla el requisito con seguridad,
  pruebas y claridad.
- No implementes funcionalidades no solicitadas.
- No agregues abstracciones, capas, patrones, servicios, colas, caches,
  factories, providers o configuraciones genéricas sin una necesidad concreta
  observada.
- No agregues flexibilidad, configurabilidad o extensibilidad especulativa.
- No diseñes para requisitos hipotéticos. Documenta extensiones futuras como
  posibles mejoras, no como implementación obligatoria.
- No escribas manejo de errores para escenarios imposibles dentro del dominio
  actual. Sí valida entradas externas, límites de seguridad y fallos
  operativos reales.
- Antes de crear una abstracción, verifica que exista duplicación real,
  variación real o una frontera de dominio estable.
- Si el cambio puede resolverse con una función clara, no crees una clase o
  framework interno.
- Si el cambio puede resolverse dentro del módulo existente sin romper límites,
  no crees un nuevo paquete, servicio o worker.
- Cada nueva capa debe pagar su costo: debe reducir complejidad real, mejorar
  testabilidad, proteger un límite de dominio o aislar un riesgo operativo
  concreto. Si no lo hace, no debe agregarse.
- No arregles problemas adyacentes solo porque los viste. Regístralos como
  deuda o sugerencia, salvo que bloqueen el cambio actual o generen un riesgo
  inmediato.
- Antes de cerrar, revisa si la solución puede reducirse sustancialmente sin
  perder correctitud, seguridad ni claridad. Si una solución larga puede ser
  corta y más clara, simplifica.

## Dependencias

Antes de agregar una dependencia:

- Verifica si la biblioteca estándar, FastAPI, Pydantic, SQLAlchemy, pnpm
  workspace o paquetes existentes ya resuelven el problema.
- Justifica mantenimiento, seguridad, licencia, tamaño, frecuencia de uso y
  alternativa rechazada.
- No agregues dependencias para una sola llamada trivial.
- Si la dependencia toca runtime productivo, documenta impacto operativo y
  plan de verificación.

## Brechas Conocidas Que Debes Respetar

Estas brechas están documentadas y no deben ocultarse con cambios parciales:

- ~~Existen dos árboles Alembic: `backend/alembic` y~~ → ~~`backend/migrations/alembic`.~~
  **RESUELTO (002):** `channel_mappings.tenant_id` ahora es nullable. Migración canónica: `backend/alembic`.
- ~~`channel_mappings` es usado por webhooks y SQL manual, pero no está alineado~~
  **RESUELTO (002):** migración 002 alinea `channel_mappings` con nullable tenant_id.
- `Odin._invoke_module()` todavía devuelve un placeholder; el flujo directo
  de Odin no ejecuta handlers reales de forma productiva.
- `POST /api/v1/tasks` crea tareas, pero la publicación a Celery sigue
  pendiente.
- `apps/dashboard` intenta consumir `/api/v1/usage`, endpoint que actualmente
  no existe.
- `WHATSAPP_APP_SECRET` se usa en el canal WhatsApp, pero falta en `.env.example` (sí está en Settings).
- CORS está hardcodeado en FastAPI aunque Compose productivo define
  `CORS_ORIGINS`.
- Prometheus apunta a `api-gateway:4000`, no a la topología productiva actual
  Python + Nginx.

Las brechas conocidas son contexto de riesgo, no backlog automático. Si una
tarea toca una brecha, corrige solo la parte necesaria para el objetivo actual.
No conviertas un fix puntual en una re-arquitectura salvo que el usuario lo
pida o que el cambio sea inseguro sin resolver la causa completa. Si queda
riesgo residual, documéntalo explícitamente.

## Backend Python

Ubicación principal: `backend/src/ai_platform`.

Convenciones:

- Usa Python 3.11, Poetry, FastAPI, Pydantic v2, SQLAlchemy y Ruff.
- Mantén routers en `api/v1`, schemas en `schemas`, modelos principales en
  `models/db.py`, servicios en `services` y lógica de orquestación en
  `orchestrator`.
- Para nuevas rutas, define schemas Pydantic claros y responses consistentes.
- Para datos persistentes de tenant, incluye `tenant_id`, filtros por tenant y
  tests que demuestren aislamiento.
- Para webhooks, valida firma/secreto cuando aplique y resuelve tenant de forma
  auditable.
- No registres secretos, tokens, payloads sensibles ni datos personales en logs.
- No uses valores placeholder en rutas productivas sin marcar claramente la
  limitación.

Comandos útiles:

Setup:

```powershell
cd backend
poetry install
```

Servidor local:

```powershell
cd backend
poetry run task run
```

Verificación:

```powershell
cd backend
poetry run ruff check src
poetry run ruff format --check src
poetry run pytest tests/ -v --tb=short --ignore-glob="**/test_modules/*"
```

Mypy existe, pero el CI actual lo declara omitido para legacy:

```powershell
cd backend
poetry run mypy src
```

## Workspace TypeScript Y Turborepo

El workspace está definido por `pnpm-workspace.yaml`:

- `apps/*`
- `services/*`
- `workers/*`
- `packages/*`

Reglas:

- Root `package.json` debe delegar en `turbo run`; no pongas lógica de build,
  lint o test directamente en scripts raíz si puede vivir en paquetes.
- Agrega scripts en el `package.json` del paquete afectado y registra tareas en
  `turbo.json` cuando corresponda.
- Declara dependencias workspace con `workspace:*`; no importes archivos de otro
  paquete mediante rutas relativas hacia `../../packages/...`.
- Los paquetes compartidos TS no deben asumir que el backend Python los consume
  directamente.
- Si una pieza TS deja de ser scaffold y pasa a runtime real, documenta puerto,
  contrato, despliegue, health checks y relación con el backend Python.

Comandos raíz:

Setup:

```powershell
pnpm install
```

Desarrollo:

```powershell
pnpm dev
```

Verificación:

```powershell
pnpm build
pnpm lint
pnpm test
pnpm typecheck
```

## Frontend

Apps actuales:

- `apps/dashboard`: prototipo Next.js que consume la API local.
- `apps/admin`: placeholder.
- `apps/website`: placeholder.

Reglas:

- Verifica que el endpoint exista antes de construir UI contra el backend.
- Usa componentes compartidos desde paquetes cuando existan; evita duplicación
  entre apps.
- No conviertas placeholders en producto sin definir alcance, datos, estados de
  carga/error, accesibilidad y contrato API.
- Mantén el frontend alineado con la topología real: API Python en
  `localhost:4000` durante desarrollo, Nginx como edge en producción.

## Infraestructura Y Operación

Desarrollo local:

```powershell
docker compose -f infra/compose/docker-compose.dev.yml up -d
docker compose -f infra/compose/docker-compose.dev.yml down
```

Producción:

- `infra/docker/Dockerfile` construye la imagen Python.
- `infra/docker/docker-compose.prod.yml` orquesta app, Postgres, Redis y Nginx.
- Solo Nginx debe exponer `80/443` públicamente.
- El backend `4000` es interno en Compose productivo.
- PostgreSQL y Redis no deben exponerse públicamente.

Si tocas Docker o Nginx, valida la configuración:

```powershell
docker compose --env-file infra/docker/.env.example -f infra/docker/docker-compose.prod.yml config --quiet
```

## Sincronización Local, GitHub, VPS Y Docker

GitHub es la fuente de verdad del código. Local y VPS deben alinearse contra el
commit esperado en GitHub.

Invariantes:

- No declares un cambio desplegado si no sabes qué commit está corriendo.
- No edites código directamente en el VPS como flujo normal.
- Todo cambio hecho localmente debe terminar en commit y push si será usado por
  otros entornos.
- Todo cambio aplicado de emergencia en VPS debe volver a GitHub mediante commit
  tan pronto como sea posible.
- Docker debe corresponder al mismo estado lógico del repositorio: Dockerfile,
  compose, variables, migraciones, imagen y contenedor deben estar alineados.

Flujo local:

1. Verifica estado inicial:
   `git status --short --branch`
   `git log -1 --oneline`
2. Implementa cambios quirúrgicos.
3. Ejecuta verificación según el área tocada.
4. Haz stage explícito por archivo.
5. Crea commit convencional.
6. Sube a GitHub:
   `git push origin <branch>`
7. Confirma que local y origin apuntan al commit esperado:
   `git status --short --branch`
   `git rev-parse HEAD`
   `git rev-parse origin/<branch>`

Flujo VPS:

1. Antes de tocar servicios, identifica commit actual:
   `git status --short --branch`
   `git log -1 --oneline`
   `git rev-parse HEAD`
2. Actualiza desde GitHub:
   `git fetch origin`
   `git pull --ff-only origin <branch>`
3. Verifica que el VPS quedó en el commit esperado.
4. Si cambió Dockerfile, compose, dependencias o código incluido en imagen,
   reconstruye o descarga la imagen correcta antes de validar.
5. Si cambió configuración Docker, ejecuta `docker compose ... config --quiet`.
6. Reinicia solo los servicios necesarios.
7. Verifica `docker compose ps`, logs relevantes y health checks públicos vía
   Nginx cuando sea producción.
8. Reporta commit desplegado, servicios reiniciados y verificaciones ejecutadas.

Reglas Docker:

- No asumas que `latest` representa el commit correcto.
- Prefiere tags por SHA de commit cuando el flujo de build lo permita.
- Si se usa `latest`, confirma digest o fecha de build antes de validar.
- Si cambia `pyproject.toml`, Dockerfile, compose, migraciones o variables de
  entorno, trata el despliegue como cambio operativo, no solo de código.
- Después de reiniciar contenedores, valida estado, logs y endpoint de health.

Reglas de drift:

- Si local, GitHub y VPS no coinciden, detente y nombra la diferencia.
- No sigas implementando sobre un entorno desalineado sin decidir primero cuál
  commit es la fuente correcta.
- Nunca mezcles cambios locales no commiteados con pulls del remoto sin revisar
  `git status`.
- No uses `git reset --hard`, force push ni sobrescrituras destructivas sin
  aprobación explícita.

Checklist de alineación antes de cerrar:

- Local limpio o cambios pendientes declarados.
- GitHub contiene el commit esperado.
- VPS corre el commit esperado si hubo despliegue.
- Docker, compose, imagen y contenedores están alineados si aplica.
- Health checks y logs revisados si aplica.

## Ejecución Orientada A Objetivos

Convierte cada tarea en metas verificables antes de implementar.

Para tareas de varios pasos, usa un plan breve:

```text
1. [Paso] -> verificar: [comando, test o revisión concreta]
2. [Paso] -> verificar: [comando, test o revisión concreta]
3. [Paso] -> verificar: [comando, test o revisión concreta]
```

Ejemplos:

- "Agregar validación" significa probar inputs inválidos y luego hacer que
  pasen.
- "Corregir bug" significa reproducir el bug con test, comando o caso manual,
  corregirlo y volver a verificar.
- "Refactorizar" significa preservar comportamiento observable y verificar
  antes y después cuando el riesgo lo justifique.

Criterios débiles como "hacer que funcione" requieren aclaración o conversión a
un resultado observable.

## Pruebas Y Verificación

Antes de afirmar que un cambio está completo, ejecuta verificación fresca y lee
la salida.

Usa la prueba más baja que demuestre el comportamiento:

- Unit test para lógica pura.
- Integration test para DB, API, workers, webhooks o servicios externos
  simulados.
- E2E solo para flujos críticos de usuario o regresiones entre sistemas.

No agregues suites amplias cuando una prueba focalizada prueba el contrato real.

Checklist mínimo:

```powershell
git status --short --branch
git diff --check
```

Si tocaste backend:

```powershell
cd backend
poetry run ruff check src
poetry run ruff format --check src
poetry run pytest tests/ -v --tb=short --ignore-glob="**/test_modules/*"
```

Si tocaste TypeScript:

```powershell
pnpm lint
pnpm typecheck
pnpm test
```

Si tocaste infraestructura:

```powershell
docker compose --env-file infra/docker/.env.example -f infra/docker/docker-compose.prod.yml config --quiet
```

No digas que algo "pasa", "está listo" o "queda corregido" si no ejecutaste el
comando que lo demuestra. Si no puedes ejecutar una verificación, informa la
razón y el riesgo residual.

## Documentación

Actualiza documentación cuando cambies:

- Arquitectura o runtime productivo.
- Endpoints, contratos API o payloads.
- Variables de entorno.
- Migraciones, modelos o datos multi-tenant.
- Flujos de despliegue, puertos, health checks o observabilidad.
- Estado de scaffolds que pasan a runtime real.

Usa ADRs para decisiones estructurales con consecuencias duraderas. Mantén
`docs/reports/*` como reportes de estado, no como fuente única de contratos.
No actualices documentación por cambios internos triviales que no alteren
comportamiento, contratos, comandos, despliegue ni arquitectura observable.

## Seguridad

- Nunca hardcodees secretos, tokens ni credenciales.
- No imprimas secretos en logs, errores, respuestas HTTP ni tests.
- Valida entradas externas, especialmente webhooks y payloads que llegan a
  Odin o a módulos `ai-*`.
- Conserva aislamiento por tenant en API, workers, memoria, billing, usage y
  observabilidad.
- Revisa implicaciones de prompt injection cuando el cambio toque Odin,
  knowledge base, memoria, plugins, skills o subagentes.

## Cambios Quirúrgicos

- Toca solo los archivos necesarios para cumplir la tarea.
- Cada línea modificada debe poder explicarse desde el pedido del usuario, una
  verificación fallida o una dependencia directa del cambio.
- No limpies código adyacente, comentarios, formato o deuda histórica solo
  porque lo viste.
- Mantén el estilo existente aunque preferirías otro, salvo que ese estilo cause
  un bug o riesgo claro.
- Si encuentras código muerto no relacionado, menciónalo como deuda. No lo
  elimines sin pedido explícito.
- Elimina imports, variables, funciones o archivos que tus propios cambios hayan
  dejado obsoletos.
- No elimines código muerto preexistente salvo que bloquee el cambio actual.

## Estilo De Cambios

- Prefiere nombres explícitos y funciones pequeñas.
- Evita abstracciones nuevas si no reducen complejidad real.
- No mezcles refactors grandes con fixes puntuales.
- Mantén comentarios solo donde expliquen intención, invariantes o decisiones
  no obvias.
- Cuando encuentres deuda técnica fuera del alcance, documéntala en la respuesta
  o en docs si afecta al cambio, pero no la refactorices incidentalmente.

## Comunicación Del Agente

- Responde en español salvo que el usuario pida otro idioma.
- Sé directo, técnico y educativo.
- Explica tradeoffs cuando haya decisiones reales.
- Si el usuario pide una revisión, empieza por hallazgos con severidad y
  referencias de archivo/línea.
- Si el usuario pide implementación, implementa y verifica dentro del alcance
  razonable antes de cerrar.

## Despliegue Y Comunicación Con VPS (CRÍTICO)

### Contexto del Entorno

El workspace corre en Windows con path `C:\Users\Jesús Díaz\...` que contiene:
- Espacio (` `) entre "Jesús" y "Díaz"
- Caracteres Unicode (`ú`, `í`)

Esto rompe múltiples capas de abstracción. La infraestructura productiva está en:
- **VPS:** `147.93.3.250` (root), path app: `/opt/ai-platform/`
- **Container:** `ai-platform-api`, ruta interna: `/app/src/ai_platform/...`
- **Docker-compose prod:** `infra/docker/docker-compose.prod.yml`

### Patrones de Deploy Correctos

El deploy usa **paramiko** (SFTP) para transferir archivos locales al VPS,
luego `docker cp` desde VPS al container. **Nunca** usar `docker --context`
directamente ni pipes stdin via SSH.

**Patrón correcto (3 pasos):**

```python
import paramiko

# 1. SFTP → VPS HOST path (NUNCА container path!)
sftp.put(windows_local_path, "/opt/ai-platform/backend/src/ai_platform/...")

# 2. SSH exec → docker cp al container
ssh.exec_command(
    "docker cp /opt/ai-platform/... ai-platform-api:/app/src/ai_platform/..."
)

# 3. SSH exec → compile check (¡usar python3 en container!)
ssh.exec_command(
    "docker exec ai-platform-api python3 -m py_compile /app/src/ai_platform/..."
)
```

### Errores Críticos Evitar En

#### ❌ `docker --context ai-platform cp win_path container:path`
Se cuelga indefinidamente (timeout >120s). El contexto SSH de Docker tiene
conflictos con `sshpass` y los paths Unicode.

#### ❌ `stdin.channel.send(data)` con paramiko
Se cuelga porque el servidor remote no cierra el stdin del pipe.
**Solución:** escribir archivo local → SFTP `put()` → nunca pipe.

#### ❌ Inyectar código Python dentro de comillas bash/SSH
```
ssh.exec_command('docker exec -c "python3 -c \'print("hola")\'"')
# FAIL: bash interpreta `print( ` como sintaxis inesperada
```
**Solución:** escribir script Python a archivo → ejecutar `python3 archivo.py`.

#### ❌ Base64 inline con >5KB
```
echo 'BASE64DE10KB...' | base64 -d > file.py
# FAIL: "La línea de comandos es demasiado larga"
# El límite de cmdline de Windows (~32KB) se agota rápido con base64
```
**Solución:** base64 en archivo local → SCP al VPS → `base64 -d < /tmp/f | bash`.

#### ❌ Escribir vía SFTP a path del container
```
sftp.put(win_path, "/app/src/ai_platform/handler.py")  
# FAIL: [Errno 2] No such file
# SFTP opera en el HOST remoto, no en el container
```
**Solución:** SFTP a `/opt/ai-platform/...` → `docker cp` → `docker exec`.

#### ❌ Usar `python` en container (usar `python3`)
```
docker exec container python -m py_compile ...
# FAIL: command not found
```

#### ❌ Comandos inline SSH con metacaracteres
PowerShell interpreta `"`, `|`, `<`, `>`, `&` como metacaracteres cuando
hay espacios en el path local. **Solución:** usar comillas simples para SSH,
o `paramiko` para archivos grandes.

### Rutas Clave De Referencia

| Entorno | RUTA |
|---------|------|
| Windows local | `C:\Users\Jesús Díaz\Documents\AI-Platform\backend\src\ai_platform\` |
| VPS host | `/opt/ai-platform/backend/src/ai_platform/` |
| Container | `/app/src/ai_platform/` |

### Checklist Pre-Deploy

1. Verificar paths en código no usan variables de entorno del usuario
2. Preferir `paramiko` para archivos >5KB (evita límites de CLI)
3. `docker cp` → host_path first, then target container_path
4. `python3`, nunca `python`, dentro del container
5. Scripts Python escritos a disco, nunca inyectados como strings

> **Regla de oro:** si una línea de comando SSH tiene `echo`, `|`, `&&`, `;`,
> `"`, `$` o supera 500 chars, usar `paramiko` + `write to file` en su lugar.
