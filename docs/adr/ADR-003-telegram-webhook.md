# ADR-003: Telegram Webhook via Nginx (No Tunnels)

## Estado

Aceptado. Creado el 2026-05-21.

## Contexto

Se intentó conectar Telegram con ngrok y Cloudflare Tunnel para exponer el
endpoint webhook de Telegram desde desarrollo local y el VPS. Ambos enfoques
fallaron por:

- ngrok: IPs efímeras, rotación de dominios, no apto para producción.
- Cloudflare Tunnel: complejidad innecesaria, dependencias externas, dificultad
  de debugging.

La arquitectura de Hermes Agent (referencia: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)
demuestra que el patrón correcto es webhook directo al VPS con URL pública
estable, publicado por Nginx.

## Decisión

Telegram se conecta mediante **webhook directo al VPS**, sin tunnels ni
exposición de puertos locales:

1. **RUTA PÚBLICA:** `https://<dominio>/api/v1/webhooks/telegram`
   - Publicada por Nginx en puerto 443 (HTTPS).
   - Nginx enruta a `app:4000` dentro de la red Docker.

2. **VALIDACIÓN:** `X-Telegram-Bot-Api-Secret-Token` header verificado contra
   `TELEGRAM_WEBHOOK_SECRET` (no contra el bot token).

3. **CONFIGURACIÓN:**
   - `TELEGRAM_BOT_TOKEN`: token del bot desde @BotFather (para enviar mensajes).
   - `TELEGRAM_WEBHOOK_URL`: URL pública del endpoint (para registrar en BotFather).
   - `TELEGRAM_WEBHOOK_SECRET`: secret token opcional (para validar webhooks).

4. **BOTFATHER SETUP:**
   - `@BotFather` → `/mybots` → seleccionar bot → `Set Webhook` → URL pública.
   - Opcional: `Set Webhook` → `Set Secret Token`.

## Consecuencias

### Positivas

- Sin dependencias externas (ngrok, cloudflared).
- URL pública estable y predecible.
- HTTPS nativo vía Nginx + Let's Encrypt.
- Mismo flujo para desarrollo local (con URL pública) y producción.
- Compatible con rate limiting y headers de seguridad de Nginx.
- Patrón consistente con Hermes Agent.

### Negativas

- Requiere dominio y SSL configurado en el VPS.
- El webhook es asíncrono: Telegram no espera respuesta, se pierde un update
  si el servidor cae durante la entrega (Telegram retry 1 vez en 1 minuto).
- No funciona sin conexión a internet desde el VPS.

## Archivos Modificados

- `backend/src/ai_platform/core/config.py`: agregado `TELEGRAM_WEBHOOK_URL`,
  `TELEGRAM_WEBHOOK_SECRET`.
- `backend/src/ai_platform/channels/telegram.py`: `TelegramChannel` ahora
  separa `token` de `webhook_secret`. Validación usa `webhook_secret`.
- `backend/alembic/versions/002_make_channel_mappings_tenant_nullable.py`:
  migración que hace `channel_mappings.tenant_id` nullable.
- `infra/docker/.env.example`: agregadas vars de webhook Telegram.
- `infra/docker/docker-compose.prod.yml`: agregadas vars de webhook Telegram.
- `docs/reports/2026-05-20-current-state.md`: actualizado estado de Telegram.
- `docs/runbooks/development.md`: agregada sección Telegram Webhook.
- `AGENTS.md`: actualizadas brechas conocidas.

## Alternativas Consideradas

1. **Polling (getUpdates):**
   - Pros: no requiere URL pública, funciona desde cualquier IP.
   - Contras: más latencia, más carga en API de Telegram, no escala bien con
     múltiples bots.
   - Rechazado: webhook es más eficiente y profesional para VPS con IP pública.

2. **ngrok / Cloudflare Tunnel:**
   - Pros: funciona sin dominio propio.
   - Contras: IPs efímeras, rotación de dominios, complejidad operativa.
   - Rechazado: no apto para producción estable.

3. **Hermes Agent como dependencia:**
   - Pros: implementación probada, multiprotocolo, features avanzadas.
   - Contras: acopla AI Platform a un producto externo, dificultad de
     personalización, licencia MIT (aceptable pero añade dependencia).
   - Rechazado: AI Platform necesita su propia implementación de canales
     como parte del modelo de negocio vendible.
