"""
Catálogo de modelos LLM disponibles.

Inspirado en Hermes Agent's model_metadata.py y build_model_catalog.py.
Proporciona metadata completa de modelos: precios, velocidad, calidad.

Patrones de Hermes aplicados:
- Catálogo centralizado de modelos con metadata
- Clasificación por calidad (fast, balanced, high, reasoning)
- Integración con prompts de routing para que el LLM elija el mejor modelo
- Soporte para múltiples providers (OpenAI, Anthropic, Google, Meta)
"""

from dataclasses import dataclass
from enum import StrEnum


class Provider(StrEnum):
    """Proveedores de modelos LLM."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    META = "meta"
    OPENROUTER = "openrouter"


class Quality(StrEnum):
    """Categorías de calidad."""

    FAST = "fast"
    BALANCED = "balanced"
    HIGH = "high"
    REASONING = "reasoning"


@dataclass
class ModelInfo:
    """Información de un modelo LLM."""

    name: str
    provider: Provider
    quality: Quality
    input_price_per_million: float
    output_price_per_million: float
    max_tokens: int
    speed: str  # "fast", "medium", "slow"
    vision: bool = False
    reasoning: bool = False
    context_window: int = 128000

    @property
    def cost_efficient(self) -> bool:
        """Es económico (<$0.50 input, <$1 output)."""
        return self.input_price_per_million < 0.5 and self.output_price_per_million < 1.0


class ModelCatalog:
    """
    Catálogo completo de modelos disponibles.

    Inyecta metadata de modelos en los prompts de Ragnar para
    que el LLM pueda elegir el mejor modelo para cada tarea.
    """

    def __init__(self):
        self._models: dict[str, ModelInfo] = {}
        self._register_builtin_models()

    def _register_builtin_models(self):
        """Registrar modelos base inspirados en Hermes."""
        # Anthropic Claude
        self.add(
            ModelInfo(
                name="anthropic/claude-3.5-sonnet",
                provider=Provider.ANTHROPIC,
                quality=Quality.HIGH,
                input_price_per_million=3.0,
                output_price_per_million=15.0,
                max_tokens=8192,
                speed="medium",
                reasoning=True,
            )
        )
        self.add(
            ModelInfo(
                name="anthropic/claude-3-haiku",
                provider=Provider.ANTHROPIC,
                quality=Quality.FAST,
                input_price_per_million=0.25,
                output_price_per_million=1.25,
                max_tokens=8192,
                speed="fast",
            )
        )
        # OpenAI
        self.add(
            ModelInfo(
                name="openai/gpt-4o-mini",
                provider=Provider.OPENAI,
                quality=Quality.FAST,
                input_price_per_million=0.15,
                output_price_per_million=0.6,
                max_tokens=128000,
                speed="fast",
            )
        )
        self.add(
            ModelInfo(
                name="openai/gpt-4o",
                provider=Provider.OPENAI,
                quality=Quality.BALANCED,
                input_price_per_million=2.5,
                output_price_per_million=10.0,
                max_tokens=128000,
                speed="medium",
                vision=True,
            )
        )
        # Google
        self.add(
            ModelInfo(
                name="google/gemini-2.0-flash-exp:free",
                provider=Provider.GOOGLE,
                quality=Quality.FAST,
                input_price_per_million=0.0,
                output_price_per_million=0.0,
                max_tokens=128000,
                speed="fast",
            )
        )
        # Meta
        self.add(
            ModelInfo(
                name="meta-llama/llama-3.1-405b",
                provider=Provider.META,
                quality=Quality.REASONING,
                input_price_per_million=2.0,
                output_price_per_million=4.0,
                max_tokens=131072,
                speed="slow",
                reasoning=True,
            )
        )

    def add(self, model: ModelInfo):
        """Agregar modelo al catálogo."""
        self._models[model.name] = model

    def get_model(self, name: str) -> ModelInfo | None:
        """
        Obtener info de un modelo.

        Parámetros:
            name: Nombre del modelo

        Retorna:
            ModelInfo o None si no existe
        """
        return self._models.get(name)

    def get_models_by_quality(self, quality: Quality) -> list[ModelInfo]:
        """
        Listar modelos por calidad.

        Parámetros:
            quality: Categoría de calidad

        Retorna:
            Lista de ModelInfo con la calidad especificada
        """
        return [m for m in self._models.values() if m.quality == quality]

    def get_cost_efficient_models(self) -> list[ModelInfo]:
        """Listar modelos económicos."""
        return [m for m in self._models.values() if m.cost_efficient]

    def build_system_prompt_for_routing(self) -> str:
        """
        Construir prompt que incluya metadata de modelos disponibles.

        Este prompt se inyecta en el system prompt del LLM de routing
        para que pueda elegir el mejor modelo para cada tarea.

        Retorna:
            String con el prompt del sistema
        """
        fast_models = self.get_models_by_quality(Quality.FAST)
        high_models = self.get_models_by_quality(Quality.HIGH)

        fast_names = ", ".join(m.name for m in fast_models)
        high_names = ", ".join(m.name for m in high_models)

        return (
            "Módulos disponibles:\n"
            "- ai-connect: Mensajería\n"
            "- ai-content: Contenido\n"
            "- ai-social: Redes sociales\n"
            "- ai-leads: Leads\n"
            "- ai-ads: Publicidad\n"
            "- ai-analytics: Analytics\n"
            "- ai-web: Páginas web\n\n"
            f"Modelos rápidos: {fast_names}\n"
            f"Modelos alta calidad: {high_names}\n"
        )


# Instancia global
_model_catalog: ModelCatalog | None = None


def get_model_catalog() -> ModelCatalog:
    """
    Obtener catálogo de modelos (singleton).

    Retorna:
        Instancia de ModelCatalog
    """
    global _model_catalog
    if _model_catalog is None:
        _model_catalog = ModelCatalog()
    return _model_catalog
