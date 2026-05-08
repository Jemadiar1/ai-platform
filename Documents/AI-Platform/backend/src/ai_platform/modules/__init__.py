"""
Registro centralizado de módulos de negocio.

Fuente única de verdad para todos los mappings de módulo.
Este registro define qué nombre de módulo se corresponde con
el path del handler que debe invocarse dinámicamente.

Principio aplicado:
- Single Source of Truth (SSOT): todos los módulos del sistema
  leen de este archivo, nunca duplican definiciones.
- Si se agrega un nuevo módulo, se agrega AQUÍ Y SOLAMENTE AQUÍ.

Uso:
    from ai_platform.modules import MODULE_HANDLERS, VALID_MODULES
"""

MODULE_HANDLERS: dict[str, str] = {
    "ai-connect": "ai_platform.modules.ai_connect.handler",
    "ai-content": "ai_platform.modules.ai_content.handler",
    "ai-social": "ai_platform.modules.ai_social.handler",
    "ai-leads": "ai_platform.modules.ai_leads.handler",
    "ai-ads": "ai_platform.modules.ai_ads.handler",
    "ai-analytics": "ai_platform.modules.ai_analytics.handler",
    "ai-web": "ai_platform.modules.ai_web.handler",
}

VALID_MODULES: list[str] = list(MODULE_HANDLERS.keys())
