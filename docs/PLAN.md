# Plan de Trabajo: Implementar Agentes/Modules

## Estado 2026-07-23

### COMPLETADO

**Fase 1: ai-connect (messaging)**
- ✅ Telegram webhook funcional (VPS 147.93.3.250)
- ✅ Discord webhook endpoint (`api/v1/webhooks/discord`) — Type 1 challenge funciona, verificación Ed25519 implementada
- ✅ WhatsApp webhook — parcial (GET challenge pendiente)
- ✅ `TelegramChannel`, `DiscordChannel`, `WhatsAppChannel` — adaptadores de canales listos

**Fases 2 & 3: Handlers productivos**
- ✅ `ai_content` — `generate_content` → LLM (PASS)
- ✅ `ai_social` — `create_post` → LLM (PASS)
- ✅ `ai_leads` — `generate_leads` → LLM (PASS)
- ✅ `ai_ads` — `create_campaign` → LLM (PASS)
- ✅ `ai_web` — `generate_page` → LLM (PASS)
- ✅ 5 handlers deployados en VPS

**Fase 4: Licensing**
- ✅ Migración 012 — `tenant_agents` table
- ✅ Middleware de verificación de licencia
- ✅ `POST /admin/tenants/{tenant_id}/set-plan`
- ✅ Odin integrado con licensing

**Infraestructura**
- ✅ `pynacl` instalado para Discord Ed25519
- ✅ LLMClient: `max_tokens` aumentado 1024 → 4096
- ✅ `config.py`: `PRIMARY_MODEL`, `FAST_MODEL`, `FALLBACK_MODEL`
- ✅ Docker deploy pipeline funcional (paramiko SFTP → docker cp → py_compile → restart)
- ✅ Nginx: NGINX_SERVER_NAME en `docker-compose.prod.yml` ✓

### PENDIENTE

**Discord (bloqueo)**
- ❌ `interactions_endpoint_url: No se ha podido verificar la URL` persiste en Discord Developer Portal
- ✅ Token configurado (`DISCORD_BOT_TOKEN`)
- ✅ Public Key configurada (`DISCORD_PUBLIC_KEY`)
- ✅ Challenge type 1 respuesta correcta (`{"type":1,"data":{"value":"..."}}`)
- ❌ Verificación Ed25519 bloquea el challenge (firma no validada en server)
- 🔧 Acciones: Reintentar URL Interactions en Developer Portal tras verificar DNS/SSL en VPS

**Fase 1 (restantes)**
- ⏳ ai-analytics handler (stub → services productivos)
- ⏳ EMBEDDING_API_URL en config
- ⏳ Tests unitarios handlers

## FASE 2: Licenciamiento por agente (COMPLETADO)

### Tarea 2.1: Tabla tenant_agents ✅

**Commit:** `feat(licensing): agregar tabla tenant_agents`
- `models/db.py` — `TenantAgent` modelo
- `backend/alembic/versions/012_add_tenant_agents.py` — migración

### Tarea 2.2: Middleware de verificación de licencia ✅

**Commit:** `feat(licensing): middleware de verificación`
- `backend/src/ai_platform/middleware/licensing.py`
- `check_agent_access(tenant_id, agent_name)`

### Tarea 2.3: Endpoint de admin para gestionar planes ✅

**Commit:** `feat(licensing): admin endpoint`
- `POST /admin/tenants/{tenant_id}/set-plan`
- Actualiza `Tenant.plan` + `TenantAgent`

### Tarea 2.4: Integrar verificación en Odín ✅

**Commit:** `feat(licensing): integrar verificación`
- En `odin.py` antes de `_invoke_module()`, verifica licencia

## FASE 3: Handlers Productivos (COMPLETADO — 5/6)

### Tarea 3.1: ai_content ✅
- `generate_content` → LLM chat (637 chars)
- Deploy en VPS: `docker cp` → `py_compile` → `restart`

### Tarea 3.2: ai_social ✅
- `create_post` → LLM (1421 chars)
- Deploy en VPS

### Tarea 3.3: ai_leads ✅
- `generate_leads` → LLM (471 chars)
- Deploy en VPS

### Tarea 3.4: ai_ads ✅
- `create_campaign` → LLM (6246 chars)
- Deploy en VPS

### Tarea 3.5: ai_web ✅
- `generate_page` → LLM (12569 chars)
- Deploy en VPS

### ⏳ ai-analytics ⏳ (próximo)
- web_research → web_research_service.fetch_search()
- web_fetch → web_research_service.fetch_url()
- web_browser → web_research_service.browser_session()
- generate_report → report_renderer.render()
- default → fallback conversacional

## FASE 4: Discord (Bloqueado en URL verification)

### ✅ Implementado
- `discord.py` — `DiscordChannel` class
- Ed25519 signature verification (`pynacl` dependencia)
- Webhook endpoint: `POST /api/v1/webhooks/discord`
- Type 1 challenge response: `{"type": 1, "data": {"value": "..."}}`
- Type 5 interaction reply con embed
- Chunking de mensajes (>2000 chars)

### ❌ Bloqueado
- `interactions_endpoint_url` no verificable en Discord Developer Portal
- Causa probable: la verificación Ed25519 no pasa (firma no validada en servidor)

### 🔧 Acciones
1. Verificar DNS: `nslookup vmi3151337.contaboserver.net` → apunta a 147.93.3.250 ✓
2. Verificar SSL: `openssl s_client` → cert válido, expira 2026-08-19 ✓
3. Reintentar URL en Developer Portal después de confirmar que el endpoint responde en 3s ✓
4. Si persiste: usar `ngrok` temporalmente para descartar firewall

## FASE 5: Próximos Pasos (No. Discord)

### 5.1: Celery worker
- Conectar `POST /api/v1/tasks` con Celery
- Worker en Redis: `celery -A workers.task_runner worker --loglevel=info`

### 5.2: `GET /api/v1/usage`
- Implementar endpoint para dashboard
- Consultar tabla `UsageEvent`

### 5.3: Odín → Handlers reales
- Conectar `Odin._invoke_module()` con handlers productivos
- Eliminar placeholder

### 5.4: WhatsApp completo
- Completar GET challenge en webhook
- Handler de mensajes entrantes

### 5.5: Admin UI (opcional)
- Frontend para gestionar planes/licencias
- `apps/admin` → reemplazar placeholder

### 5.6: AI Analytics (próximo handler)
- Conectar `ai_analytics/handler.py` con servicios productivos
- web_research, web_fetch, web_browser, generate_report

## Resumen de Commits Realizados

| # | Commit | Archivos |
|---|--------|----------|
| 1 | feat(licenses): añadir tabla tenant_agents | models/db.py + migration 012 |
| 2 | feat(licensing): middleware de verificación | middleware/licensing.py |
| 3 | feat(licensing): endpoint admin set-plan | api/v1/routes/admin.py |
| 4 | feat(licensing): integrar verificación en Odin | orchestrator/odin.py |
| 5 | feat(handlers): ai_content, ai_social, ai_leads, ai_ads, ai_web | handlers productivos |
| 6 | feat(llm): aumentar max_tokens 1024→4096, detección finish_reason | llm_client.py |
| 7 | feat(config): PRIMARY_MODEL, FAST_MODEL, FALLBACK_MODEL | core/config.py |
| 8 | feat(discord): integración completa con Ed25519 | channels/discord.py, docker-compose.prod.yml |
| 9 | fix(deploy): corregir Dockerfile NGINX_SERVER_NAME | Dockerfile |
| 10 | docs: actualizar AGENTS.md con patrones VPS | AGENTS.md |
| 11 | Add `pynacl` dependency | pyproject.toml |
| 12 | Add `webhooks.py` with type 1 challenge fix | api/v1/webhooks.py |

## Notas para Continuidad de Sesión

Si la sesión se interrumpe:
- Verificar git log --oneline -3 para ver último commit
- Verificar git status --short para archivos sin commitear
- El VPS está en 147.93.3.250 con deploy reciente via paramiko SFTP
- El canal Telegram está funcionando y respondiendo
- Discord: token configurado, Interactions URL bloqueada en verificar
- Nginx: NGINX_SERVER_NAME corregido en compose, build y restart pendiente