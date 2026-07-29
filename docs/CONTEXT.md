# AI Platform — NeuralCrew Labs

## Propósito del Proyecto

AI Platform es el motor de agentes IA de NeuralCrew Labs, una agencia de marketing 100% potenciada por IA. La plataforma permite a los clientes contratar agentes especializados (módulos) según su plan, cada uno con habilidades instalables (skills) para ejecutar tareas de marketing de forma autónoma y profesional.

## Visión del Producto

Cada cliente recibe un agente personal que puede:

1. **Investigar** — navegar la web, scrapear fuentes, analizar documentos, hacer OCR de imágenes
2. **Generar contenido** — crear posts, blogs, copy publicitario, landing pages
3. **Gestionar redes sociales** — publicar en Instagram, Facebook, LinkedIn, TikTok
4. **Generar leads** — encontrar y calificar prospectos
5. **Crear campañas** — diseñar campañas publicitarias en Meta Ads, Google Ads
6. **Responder conversaciones** — WhatsApp, Telegram, Discord
7. **Generar reportes** — PDF, DOCX, XLSX, CSV con gráficos profesionales

El agente no es un chatbot genérico. Es un **ejecutor de trabajo operativo** que:
- Genera **productos reales** (reportes PDF, posts, landing pages, campañas)
- Trabaja con el **contexto propio del cliente** (documentos, datos, historial)
- Combina **múltiples habilidades** (skills) en secuencia para tareas complejas
- Opera de forma **autónoma** — decide qué herramientas usar y en qué orden

## Arquitectura: Monolito Modular Orquestado

backend/src/ai_platform/
  agents/                    # cada agente es un DIR independiente
    ai_connect/              # mensajería (WhatsApp, Telegram, Discord)
    ai_analytics/            # investigación web, reportes, OCR
    ai_content/              # generación de contenido
    ai_social/               # gestión de redes sociales
    ai_leads/                # generación de leads
    ai_ads/                  # campañas publicitarias
    ai_web/                  # generación de landing pages
  shared_skills/             # habilidades compartidas por todos los agentes
    llm_client.py            # conexión NAN (todos lo usan)
    web_browser.py           # Playwright (analytics + content)
    vision_ocr.py            # OCR + chart detection
    report_generator.py      # PDF/DOCX/XLSX
    file_reader.py           # leer PDF, DOCX, XLSX, TXT, CSV
  core/                      # compartidos por TODOS los agentes
    config.py                # configuración con Pydantic
    security.py              # sanitización, anti-injection
    licensing.py             # verificación de acceso a agentes
  orchestrator/
    odin.py                  # router/orquestador (el cerebro)
    modules.py               # catálogo de agentes con acciones
  services/                  # servicios productivos existentes
    web_research_service.py  # fetch, scrape, Playwright
    report_renderer.py       # PDF, DOCX, XLSX, CSV, HTML
    vision_ocr.py            # Tesseract OCR + OpenCV
    document_chunker.py      # chunking de documentos
    document_storage.py      # almacenamiento de archivos
    embedding_service.py     # embeddings NAN
  middleware/
    tenant.py                # resolución de tenant
    json_logging.py          # logging estructurado
  models/
    db.py                    # 16 tablas SQLAlchemy (multi-tenant)
  api/v1/                    # REST API versionada
  channels/                  # adaptadores de canales
    telegram.py              # Telegram Bot API
    whatsapp_channel.py      # Meta Graph API v18
    discord.py               # Discord Bot API v10

## Flujo de Mensaje

Usuario (Telegram/WhatsApp/Discord)
  ↓
Odín.decide() → [sanitización] [contexto] [memoria] [KB] [plugins]
  ↓
LLM routing → {"module": "ai-analytics", "action": "web_research", ...}
  ↓
Verificar licencia del tenant
  ↓
Ejecutar módulo (agent handler)
  ↓
Handler llama a shared_skills en secuencia
  ↓
Resultado → _extract_response_text()
  ↓
Enviar respuesta al canal

## Agentes y Planes

| Plan | Agentes incluidos |
|------|-------------------|
| **Free** | ai-connect |
| **Starter** | ai-connect, ai-analytics |
| **Pro** | ai-connect, ai-analytics, ai-content, ai-social |
| **Enterprise** | todos los agentes |

## Skills (Habilidades)

Las skills son módulos de código que los agentes pueden usar. Se dividen en:
- **Oficiales** — incluidas con la plataforma (web_research, report_generator, OCR)
- **Custom** — creadas por el tenant (almacenadas en BD)
- **Aprendidas** — auto-creadas por el agente tras tareas complejas

Cada skill tiene:
- Entrada/salida definida (schema)
- Escaneo de seguridad (24 patrones)
- Logging de usage (para billing)
- Categorización (category, version)

## Técnico

- **Backend:** Python 3.11, FastAPI, SQLAlchemy, Alembic, Poetry
- **Frontend:** TypeScript, Next.js, pnpm, Turborepo (prototipos)
- **Infra:** Docker, Nginx, PostgreSQL 16, Redis 7
- **LLM:** NaN Builders (NAN_API_KEY) con fallback rule-based
- **CI:** GitHub Actions (Ruff, pytest, Docker build/push GHCR)

## Estado Actual (2026-07-23)

- **Backend productivo** — 70%+ código funcional en Python
- **ai-connect funciona** — Telegram funcionando en VPS (147.93.3.250), webhook validado
- **Discord integrado** — webhook endpoint en `.../api/v1/webhooks/discord`, challenge type 1 respuesta correcta, verificación Ed25519 implementada pero con firma no validada (Discord no verifica URL aún)
- **Discord pendiente** — error `interactions_endpoint_url` persiste en Discord Developer Portal. Token configurado (`DISCORD_BOT_TOKEN`), Public Key configurada (`DISCORD_PUBLIC_KEY`). Se requiere reintentar URL después de resolver problema de firma DNS/SSL en VPS.
- **Licensing implementado** — Tabla `tenant_agents` (migración 012), middleware de verificación, admin endpoints, Odin integrado
- **5 handlers productivos** — `ai_content`, `ai_social`, `ai_leads`, `ai_ads`, `ai_web` (deploy en VPS)
- **LLMClient fix** — `max_tokens` aumentado 1024→4096, detección `finish_reason="length"`
- **Config actualizado** — campos `PRIMARY_MODEL`, `FAST_MODEL`, `FALLBACK_MODEL` agregados
- **Scaffolds TS** — `apps/dashboard` (prototipo), `apps/admin/website` (placeholders), `services/api-gateway` (Fastify mínimo), `services/orchestrator` (sin runtime)
- **Sin Celery** — `POST /api/v1/tasks` no conectado a Celery
- **Sin `GET /api/v1/usage`** — dashboard rota
- **1 tenant** en producción, plan starter

## Reglas de Desarrollo

- No hardcodear secretos
- Multi-tenancy en todas las entidades
- Handlers síncronos llamando servicios asíncronos vía asyncio.run()
- Cada acción del handler retorna dict con response, status, note
- _extract_response_text() filtra metadata y status strings
- Commits convencionales, push a GitHub, deploy al VPS

## Próximos Pasos

1. **Discord** — Reintentar URL Interactions en Discord Developer Portal después de verificar DNS/SSL en VPS. Token y clave pública configurados ya.
2. **Celery** — Conectar `POST /api/v1/tasks` con worker Celery en Redis
3. **Usage endpoint** — Implementar `GET /api/v1/usage` para dashboard
4. **Odín** — Conectar `_invoke_module()` con handlers productivos reales
5. **Admin UI** — Frontend para gestionar planes/licencias
6. **WhatsApp** — Completar webhook Meta (GET challenge pendiente)
7. **Scaffolds TS** — Decidir si mantener roadmap TS o reducirlo