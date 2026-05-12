# Reporte de Cambios Arquitectonicos

Fecha: 2026-04-16

## Resumen ejecutivo

Se reestructuro el repositorio `AI-Platform` desde un esquema inicial orientado a multiples servicios por modulo hacia una arquitectura de fase 1 basada en `modular monolith + orchestrator + workers`.

El objetivo del cambio fue reducir complejidad operativa temprana, mantener aislamiento de dominios en codigo y dejar preparada la base para una extraccion progresiva a microservicios cuando exista evidencia tecnica o de negocio para hacerlo.

## Motivo del cambio

La estructura anterior era valida como arquitectura objetivo de largo plazo, pero demasiado costosa para una etapa temprana del proyecto por estas razones:

- Multiplicaba el numero de procesos desplegables sin necesidad inmediata.
- Introducia overhead operacional en Docker, CI/CD, observabilidad y manejo de secretos.
- Hacia mas costoso el debugging al distribuir responsabilidades demasiado pronto.
- Forzaba contratos de red y aislamiento fisico antes de validar suficiente carga, equipo o necesidad de despliegue independiente.

La nueva estructura conserva separacion por dominios, pero evita pagar desde hoy el costo total de una arquitectura de microservicios puros.

## Cambios realizados

### 1. Cambio de `agents/` a `modules/`

Se elimino el directorio `agents/` y se reemplazo por `modules/`.

Antes:

- `agents/ai-connect`
- `agents/ai-web`
- `agents/ai-content`
- `agents/ai-social`
- `agents/ai-leads`
- `agents/ai-ads`
- `agents/ai-analytics`

Ahora:

- `modules/ai-connect`
- `modules/ai-web`
- `modules/ai-content`
- `modules/ai-social`
- `modules/ai-leads`
- `modules/ai-ads`
- `modules/ai-analytics`

Motivo:

- En fase 1 esos dominios no necesitan operar como microservicios independientes.
- El termino `module` representa mejor una unidad de negocio aislada en codigo, pero no necesariamente aislada en despliegue.

### 2. Reorganizacion interna de cada dominio

Cada modulo `ai-*` fue reorganizado con la misma forma:

- `application/`
- `domain/`
- `infrastructure/`
- `contracts/`
- `prompts/`
- `tools/`
- `tests/`

Motivo:

- Separar casos de uso, reglas de negocio, integraciones y contratos.
- Facilitar mantenibilidad y pruebas.
- Preparar una futura extraccion a microservicio con minima friccion.

### 3. Eliminacion de artefactos de despliegue prematuros por modulo

Se removieron de los modulos:

- `Dockerfile`
- `config.yaml`
- `memory/`
- `src/agent.py`

Motivo:

- Esos artefactos modelaban a cada dominio como servicio independiente desde el inicio.
- Para fase 1 la prioridad es estabilizar los limites del dominio, no multiplicar contenedores.

### 4. Simplificacion de servicios separados

Se mantuvieron como procesos separados solo:

- `services/api-gateway`
- `services/orchestrator`
- `workers/task-runner`
- `workers/scheduler`

Y se removieron placeholders de:

- `services/auth-service`
- `services/billing-service`
- `services/notification-svc`

Motivo:

- `auth` y `billing` deben integrarse con terceros y no justifican un servicio propio temprano.
- `notification` puede vivir inicialmente como adaptador o capacidad interna del orchestrator o workers.
- Se redujo el numero de componentes operativos sin perder claridad de responsabilidades.

### 5. Ajuste de documentacion

Se actualizaron:

- `README.md`
- `docs/architecture.md`
- `docs/adr/ADR-001-monorepo.md`
- `docs/adr/ADR-002-multi-tenancy.md`
- `services/orchestrator/config/SOUL.md`
- `infra/docker/README.md`

Motivo:

- Alinear el discurso tecnico con la estructura real del repositorio.
- Evitar que el repo documente una arquitectura distinta a la implementada.

### 6. Estandarizacion minima de los modulos

Cada modulo recibio:

- `README.md`
- un `application/handler.py` minimo
- `tests/test_module.py`
- placeholders de `domain`, `infrastructure`, `contracts`, `tools` y `prompts`

Motivo:

- Dejar una base consistente para crecimiento posterior.
- Evitar carpetas vacias ambiguas.
- Establecer una convencion uniforme desde el inicio.

## Beneficios esperados

- Menor complejidad operativa en fase temprana.
- Mejor velocidad de iteracion para un equipo pequeno.
- Limites de dominio claros sin sobrecargar despliegue.
- Menor costo de debugging.
- Preparacion realista para evolucionar a microservicios cuando haga falta.

## Tradeoffs aceptados

- Menor aislamiento fisico entre dominios en la etapa actual.
- Algunos modulos compartiran runtime o proceso hasta que la carga justifique separacion.
- Parte de la robustez operativa de microservicios puros se posterga a una fase posterior.

## Criterio de extraccion futura a microservicios

Un modulo `ai-*` deberia extraerse a servicio independiente cuando cumpla una o mas de estas condiciones:

- necesita escalado independiente
- tiene un perfil de fallos que debe aislarse
- despliega con una frecuencia distinta al resto
- requiere stack o dependencias diferentes
- concentra integraciones externas complejas
- genera suficiente carga o latencia para justificar separacion

## Conclusión

La estructura actual no abandona la idea de microservicios; la pospone de manera disciplinada.

Se diseno una base modular fuerte, con `api-gateway`, `orchestrator` y `workers` separados, y con dominios `ai-*` listos para evolucionar a servicios independientes cuando el proyecto lo necesite.

