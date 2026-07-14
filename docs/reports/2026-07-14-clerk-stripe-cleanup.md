# Reporte De Limpieza De Integraciones Clerk Y Stripe

Fecha: 2026-07-14
Autor: Sesión de limpieza de deuda técnica

## Contexto

El sistema contenía integración completa de Clerk (Auth) y Stripe (Billing), pero ninguna de estas estaba configurada en producción: no había variables de entorno válidas, no había usuarios creados en la BD, y los webhooks no recibían tráfico real. Todo el código existía pero no funcionaba — era deuda técnica activa que enmascaraba el flujo real del sistema.

## Decisión

Eliminar completamente Clerk y Stripe de toda la base de código. El flujo actual de producción depende exclusivamente de:
- Telegram
- WhatsApp
- Discord
- LLM via NaN (no OpenRouter)

## Cambios Implementados

### Backend Python

| Archivo | Acción | Líneas eliminadas |
|---------|--------|-------------------|
| `webhooks.py` | Eliminar endpoints `/webhooks/clerk` y `/webhooks/stripe`, funciones de firma y handlers | ~370 |
| `middleware/auth.py` | **Archivo eliminado** — solo contenía `verify_clerk_token()` | 87 |
| `services/auth_service.py` | **Archivo eliminado** — AuthService solo referenciaba Clerk | 194 |
| `services/billing_service.py` | **Archivo eliminado** — BillingService solo referenciaba Stripe | 314 |
| `core/config.py` | Eliminar `CLERK_SECRET_KEY`, `CLERK_API_URL`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `OPENROUTER_API_KEY`, `OPENROUTER_API_URL`, `VAPI_API_KEY`. Cambiar `LLM_PROVIDER` default de `"openrouter"` a `"nan"` | 25 vars de config |

### Configuración

| Archivo | Acción |
|---------|--------|
| `backend/.env.example` | Sección Clerk, Stripe, OpenRouter, Vapi eliminadas |
| `infra/docker/.env.example` | Sección Clerk, Stripe, OpenRouter, Vapi eliminadas |
| `infra/docker/docker-compose.prod.yml` | Vars Clerk, Stripe, OpenRouter, Vapi eliminadas |
| `backend/tests/conftest.py` | Quitar `mock_settings.CLERK_SECRET_KEY` |

### Debug Cleanup

| Archivo | Acción |
|---------|--------|
| `webhooks.py` | Eliminar 5 prints de debug con `[DEBUG]` que exponían PII en logs |

### Documentación

| Archivo | Acción |
|---------|--------|
| `architecture.md` | Diagrama Mermaid: `OpenRouter / NaN` → `NaN` |

### Código Preservado (no tocar)

Las siguientes integraciones se **preservan porque están activas en producción**:
- Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET`)
- WhatsApp (`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`)
- Discord (`DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`)
- LLM NaN (`NAN_API_KEY`, `NAN_API_URL`)

## Impacto

| Área | Antes | Después |
|------|-------|---------|
| Archivos eliminados | — | 3 (`auth.py`, `auth_service.py`, `billing_service.py`) |
| Código eliminado | ~1200 líneas (incluyendo docstrings) | ~440 líneas de código funcional + 1200 de documentación/marco |
| Variables de config | 14 vars de Clerk/Stripe/OpenRouter/Vapi vacías | 0 |
| Endpoints muertos | `/webhooks/clerk`, `/webhooks/stripe` | Eliminados |
| Riesgo de confusión | Alto (el código sugería funcionalidades que no existían) | Bajo |

## Brechas Resueltas

- `CLERK_SECRET_KEY` ya no aparece listado como "falta en `.env.example`"
- `STRIPE_SECRET_KEY` ya no aparece listado como placeholder
- `WHATSAPP_APP_SECRET` ya no es inconsistente entre Settings y `.env.example`
- `LLM_PROVIDER` ahora es `"nan"` por defecto (no `"openrouter"`)

## Notas

- `UsageEvent` en `models/db.py` se preserva porque otros servicios lo usan (`task_runner.py`, `web_research_service.py`, `vision_ocr.py`, `report_renderer.py`). Solo se removió su uso en el handler de pago de Stripe.
- `embedding_service.py` se preserva porque se usa activamente en `knowledge_base.py` y `memory.py`.
- `credential_pool.py` y `rate_limiter.py` conservan entradas para vapi/strip como código muerto heredado de Hermes — no se tocaron porque no afectan el runtime.
