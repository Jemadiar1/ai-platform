"""
Registro centralizado de módulos de negocio.

Fuente única de verdad para:
- Qué módulos existen
- Qué handler importa cada módulo
- Qué acciones expone cada módulo
- Descripción y categoría de cada módulo

Los módulos son la unidad visible de producto, venta, routing,
permisos, billing y ejecución.

Skills y MCP tools quedan como infraestructura interna subordinada
al módulo, no como capas paralelas.

Uso:
    from ai_platform.orchestrator.modules import (
        MODULE_REGISTRY,
        get_module_info,
        get_all_modules,
        get_handler,
    )

    module = get_module_info("ai-connect")
    for name, info in get_all_modules():
        print(f"{name}: {info.description}")
    handler = get_handler("ai-connect")
    result = handler.execute(payload)
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModuleAction:
    """Acción que un módulo puede ejecutar."""

    name: str
    description: str


@dataclass(frozen=True)
class ModuleInfo:
    """Información de un módulo de negocio."""

    name: str
    description: str
    handler_path: str
    category: str
    actions: tuple[ModuleAction, ...] = field(default_factory=tuple)

    @property
    def action_names(self) -> tuple[str, ...]:
        """Nombres de las acciones de este módulo."""
        return tuple(a.name for a in self.actions)

    @property
    def action_descriptions(self) -> dict[str, str]:
        """Mapeo de nombre -> descripción de acciones."""
        return {a.name: a.description for a in self.actions}


# =========================================================================
# Definición de módulos
# =========================================================================

_MODULES: list[ModuleInfo] = [
    ModuleInfo(
        name="ai-connect",
        description="Mensajería (WhatsApp, Telegram, Slack, Messenger)",
        handler_path="ai_platform.modules.ai_connect.handler",
        category="messaging",
        actions=(
            ModuleAction("send_message", "Enviar respuesta IA a canal de mensajería"),
            ModuleAction("send_whatsapp_message", "Enviar mensaje por WhatsApp Business API"),
            ModuleAction("make_voice_call", "Realizar llamada de voz con IA"),
            ModuleAction("handle_chat_message", "Procesar mensaje entrante de chat en vivo"),
            ModuleAction("schedule_appointment", "Agendar cita en calendario"),
            ModuleAction("update_contact", "Actualizar contacto en CRM"),
            ModuleAction("get_contacts", "Listar contactos del CRM"),
        ),
    ),
    ModuleInfo(
        name="ai-content",
        description="Generación de contenido (textos, posts, blogs)",
        handler_path="ai_platform.modules.ai_content.handler",
        category="content",
        actions=(
            ModuleAction("generate_content", "Generar contenido de marketing con IA"),
            ModuleAction("default", "Acción genérica de contenido"),
        ),
    ),
    ModuleInfo(
        name="ai-social",
        description="Gestión de redes sociales (Instagram, Facebook, LinkedIn, TikTok)",
        handler_path="ai_platform.modules.ai_social.handler",
        category="social",
        actions=(
            ModuleAction("create_post", "Crear post para redes sociales"),
            ModuleAction("analyze_engagement", "Analizar métricas de engagement"),
            ModuleAction("default", "Acción genérica de redes sociales"),
        ),
    ),
    ModuleInfo(
        name="ai-leads",
        description="Generación y gestión de leads",
        handler_path="ai_platform.modules.ai_leads.handler",
        category="leads",
        actions=(
            ModuleAction("generate_leads", "Generar leads calificados con IA"),
            ModuleAction("default", "Acción genérica de leads"),
        ),
    ),
    ModuleInfo(
        name="ai-ads",
        description="Campañas publicitarias (Meta Ads, Google Ads)",
        handler_path="ai_platform.modules.ai_ads.handler",
        category="ads",
        actions=(
            ModuleAction("create_campaign", "Crear campaña publicitaria"),
            ModuleAction("default", "Acción genérica de campañas"),
        ),
    ),
    ModuleInfo(
        name="ai-analytics",
        description="Análisis de datos, métricas, reportes e investigación web",
        handler_path="ai_platform.modules.ai_analytics.handler",
        category="analytics",
        actions=(
            ModuleAction("generate_report", "Generar reporte analítico con datos de múltiples fuentes"),
            ModuleAction("web_research", "Investigar fuentes web y extraer información relevante"),
            ModuleAction("web_fetch", "Fetch y parsear contenido de una URL específica"),
            ModuleAction("web_browser", "Fetch con navegador headless para contenido dinámico"),
            ModuleAction("document_ingest", "Subir y procesar documentos (PDF, DOCX, imágenes)"),
            ModuleAction("document_chunk", "Dividir documentos en chunks con estrategias de chunking"),
            ModuleAction("document_fts_search", "Buscar texto completo en documentos indexados"),
            ModuleAction("ocr_extract", "Extracción de texto OCR de imágenes y documentos escaneados"),
            ModuleAction("chart_detect", "Detección y análisis de gráficos/charts en imágenes"),
            ModuleAction("render_report", "Renderizar reportes en múltiples formatos (PDF, DOCX, XLSX, CSV)"),
            ModuleAction("default", "Acción genérica de analítica"),
        ),
    ),
    ModuleInfo(
        name="ai-web",
        description="Generación de páginas web y landing pages",
        handler_path="ai_platform.modules.ai_web.handler",
        category="web",
        actions=(
            ModuleAction("generate_page", "Generar página web o landing page"),
            ModuleAction("default", "Acción genérica de web"),
        ),
    ),
]

# Build lookup dict
MODULE_REGISTRY: dict[str, ModuleInfo] = {m.name: m for m in _MODULES}


# =========================================================================
# API pública
# =========================================================================


def get_module_info(name: str) -> ModuleInfo | None:
    """Obtener información de un módulo por nombre."""
    return MODULE_REGISTRY.get(name)


def get_all_modules() -> list[ModuleInfo]:
    """Listar todos los módulos registrados."""
    return list(MODULE_REGISTRY.values())


def get_module_names() -> list[str]:
    """Listar nombres de todos los módulos."""
    return list(MODULE_REGISTRY.keys())


def get_handler(name: str) -> Any | None:
    """
    Importar dinámicamente la clase Handler de un módulo.

    Parámetros:
        name: Nombre del módulo (ej: "ai-connect")

    Retorna:
        Clase Handler o None si el módulo no existe
    """
    module = MODULE_REGISTRY.get(name)
    if not module:
        return None

    import importlib

    handler_module = importlib.import_module(module.handler_path)
    HandlerClass = getattr(handler_module, "Handler", None)
    if HandlerClass is None:
        raise AttributeError(f"No se encontró Handler en {module.handler_path}")
    return HandlerClass


def get_route_modules_description() -> str:
    """
    Generar descripción de módulos para inyectar en el routing prompt del LLM.

    Retorna una string formateada que el LLM usa para decidir
    qué módulo ejecutar.
    """
    lines = ["Módulos disponibles:\n"]
    for module in _MODULES:
        lines.append(f"- {module.name}: {module.description}\n")
    lines.append("\nMódulos válidos para 'module': ")
    lines.append(" | ".join(f'"{m.name}"' for m in _MODULES))
    return "".join(lines)
