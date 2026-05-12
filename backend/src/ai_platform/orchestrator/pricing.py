"""
Precios reales por token de OpenRouter.

Fuente: https://openrouter.ai/models (actualizado periódicamente)
Los precios son por millón de tokens.

Inspirado en el pricing tracking de Hermes Agent.

Patrones implementados:
- Precios reales por modelo (input vs output diferenciados)
- Cálculo de costo basado en tokens usados
- Categorización por tipo de modelo (free, economy, standard, premium)
- Fallback genérico cuando el modelo no está en la lista
"""

# Diccionario con precios reales por modelo
# Los precios están en USD por cada millón de tokens
MODEL_PRICING = {
    # ------------------------------------------------------------------
    # Anthropic Claude
    # ------------------------------------------------------------------
    "anthropic/claude-3.5-sonnet": {
        "input_price_per_1m": 3.0,       # $3 por cada 1M tokens de entrada
        "output_price_per_1m": 15.0,     # $15 por cada 1M tokens de salida
        "category": "premium",
    },
    "anthropic/claude-3.5-sonnet:beta": {
        "input_price_per_1m": 3.0,
        "output_price_per_1m": 15.0,
        "category": "premium",
    },
    "anthropic/claude-3.5-sonnet:latest": {
        "input_price_per_1m": 3.0,
        "output_price_per_1m": 15.0,
        "category": "premium",
    },
    "anthropic/claude-3-opus": {
        "input_price_per_1m": 15.0,      # $15 entrada, $75 salida - el más caro
        "output_price_per_1m": 75.0,
        "category": "premium",
    },
    "anthropic/claude-3-opus:beta": {
        "input_price_per_1m": 15.0,
        "output_price_per_1m": 75.0,
        "category": "premium",
    },
    "anthropic/claude-3.5-sonnet": {
        "input_price_per_1m": 3.0,
        "output_price_per_1m": 15.0,
        "category": "premium",
    },
    "anthropic/claude-3.5-sonnet-v2": {
        "input_price_per_1m": 3.0,
        "output_price_per_1m": 15.0,
        "category": "premium",
    },
    "anthropic/claude-3-haiku": {
        "input_price_per_1m": 0.25,      # $0.25 entrada, $1.25 salida
        "output_price_per_1m": 1.25,
        "category": "economy",
    },
    "anthropic/claude-instant-1.2": {
        "input_price_per_1m": 0.80,
        "output_price_per_1m": 2.40,
        "category": "economy",
    },
    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    "openai/gpt-4o": {
        "input_price_per_1m": 2.50,      # $2.50 entrada, $10 salida
        "output_price_per_1m": 10.0,
        "category": "premium",
    },
    "openai/gpt-4o-mini": {
        "input_price_per_1m": 0.15,      # $0.15 entrada, $0.60 salida
        "output_price_per_1m": 0.60,
        "category": "economy",
    },
    "openai/gpt-4o-mini-2024-07-18": {
        "input_price_per_1m": 0.15,
        "output_price_per_1m": 0.60,
        "category": "economy",
    },
    "openai/gpt-4-turbo": {
        "input_price_per_1m": 10.0,
        "output_price_per_1m": 30.0,
        "category": "premium",
    },
    "openai/gpt-4": {
        "input_price_per_1m": 10.0,
        "output_price_per_1m": 30.0,
        "category": "premium",
    },
    "openai/o1": {
        "input_price_per_1m": 15.0,
        "output_price_per_1m": 60.0,
        "category": "premium",
    },
    "openai/o1-mini": {
        "input_price_per_1m": 3.0,
        "output_price_per_1m": 12.0,
        "category": "standard",
    },
    "openai/o3-mini": {
        "input_price_per_1m": 1.10,
        "output_price_per_1m": 4.40,
        "category": "economy",
    },
    "openai/text-embedding-3-small": {
        "input_price_per_1m": 0.02,
        "output_price_per_1m": 0.0,
        "category": "economy",
    },
    "openai/text-embedding-3-large": {
        "input_price_per_1m": 0.13,
        "output_price_per_1m": 0.0,
        "category": "economy",
    },
    "openai/embedding": {
        "input_price_per_1m": 0.02,
        "output_price_per_1m": 0.0,
        "category": "economy",
    },
    # ------------------------------------------------------------------
    # Google / Gemini
    # ------------------------------------------------------------------
    "google/gemini-2.0-flash-exp:free": {
        "input_price_per_1m": 0.0,        # Gratis
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    "google/gemini-2.0-flash-lite-preview-02-05:free": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    "google/gemini-2.0-pro-exp-02-05:free": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    "google/gemini-2.5-pro-exp-05-06:free": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    "google/gemini-2.5-pro-exp-06-05:free": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    "google/gemini-2.5-flash-preview-05-20": {
        "input_price_per_1m": 0.15,
        "output_price_per_1m": 1.50,
        "category": "economy",
    },
    "google/gemini-2.5-flash": {
        "input_price_per_1m": 0.15,
        "output_price_per_1m": 1.50,
        "category": "economy",
    },
    "google/gemini-2.0-flash": {
        "input_price_per_1m": 0.10,
        "output_price_per_1m": 0.40,
        "category": "economy",
    },
    "google/gemini-2.0-flash-lite": {
        "input_price_per_1m": 0.075,
        "output_price_per_1m": 0.30,
        "category": "free",
    },
    "google/gemini-2.5-pro": {
        "input_price_per_1m": 1.25,
        "output_price_per_1m": 12.50,
        "category": "premium",
    },
    "google/gemini-exp-1206": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    "google/gemini-exp-1206:free": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    "google/gemini-exp-1114": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "free",
    },
    # ------------------------------------------------------------------
    # Meta / Llama
    # ------------------------------------------------------------------
    "meta-llama/llama-3.3-70b-instruct": {
        "input_price_per_1m": 0.20,
        "output_price_per_1m": 0.40,
        "category": "economy",
    },
    "meta-llama/llama-3.1-405b-instruct": {
        "input_price_per_1m": 2.00,
        "output_price_per_1m": 4.00,
        "category": "standard",
    },
    "meta-llama/llama-3.1-8b-instruct": {
        "input_price_per_1m": 0.05,
        "output_price_per_1m": 0.10,
        "category": "free",
    },
    "meta-llama/llama-3.2-90b-vision-instruct": {
        "input_price_per_1m": 0.50,
        "output_price_per_1m": 0.90,
        "category": "economy",
    },
    "meta-llama/llama-3.2-11b-vision-instruct": {
        "input_price_per_1m": 0.05,
        "output_price_per_1m": 0.10,
        "category": "free",
    },
    # ------------------------------------------------------------------
    # Microsoft / Phi
    # ------------------------------------------------------------------
    "microsoft/phi-3.5-mini": {
        "input_price_per_1m": 0.10,
        "output_price_per_1m": 0.30,
        "category": "economy",
    },
    # ------------------------------------------------------------------
    # Mistral
    # ------------------------------------------------------------------
    "mistralai/mistral-7b-instruct": {
        "input_price_per_1m": 0.05,
        "output_price_per_1m": 0.10,
        "category": "free",
    },
    "mistralai/mistral-small-24b-instruct": {
        "input_price_per_1m": 0.10,
        "output_price_per_1m": 0.30,
        "category": "economy",
    },
    "mistralai/mistral-large": {
        "input_price_per_1m": 2.00,
        "output_price_per_1m": 6.00,
        "category": "standard",
    },
    "mistralai/mistral-nemo": {
        "input_price_per_1m": 0.05,
        "output_price_per_1m": 0.10,
        "category": "free",
    },
    # ------------------------------------------------------------------
    # Cohere
    # ------------------------------------------------------------------
    "cohere/command-r": {
        "input_price_per_1m": 0.50,
        "output_price_per_1m": 1.50,
        "category": "economy",
    },
    "cohere/command-r-plus": {
        "input_price_per_1m": 3.00,
        "output_price_per_1m": 15.00,
        "category": "premium",
    },
    # ------------------------------------------------------------------
    # Perplexity
    # ------------------------------------------------------------------
    "perplexity/llama-3.1-sonar-small-128k-chat": {
        "input_price_per_1m": 0.20,
        "output_price_per_1m": 2.00,
        "category": "economy",
    },
    "perplexity/llama-3.1-sonar-large-128k-chat": {
        "input_price_per_1m": 1.00,
        "output_price_per_1m": 10.00,
        "category": "standard",
    },
    # ------------------------------------------------------------------
    # DeepSeek
    # ------------------------------------------------------------------
    "deepseek/deepseek-r1": {
        "input_price_per_1m": 0.55,
        "output_price_per_1m": 2.19,
        "category": "economy",
    },
    "deepseek/deepseek-chat": {
        "input_price_per_1m": 0.27,
        "output_price_per_1m": 1.10,
        "category": "economy",
    },
    # ------------------------------------------------------------------
    # Fireworks
    # ------------------------------------------------------------------
    "fireworks/llama-v3p1-405b-instruct": {
        "input_price_per_1m": 3.00,
        "output_price_per_1m": 3.00,
        "category": "premium",
    },
    # ------------------------------------------------------------------
    # Groq
    # ------------------------------------------------------------------
    "groq/llama-3.1-70b-versatile": {
        "input_price_per_1m": 0.59,
        "output_price_per_1m": 0.79,
        "category": "economy",
    },
    # ------------------------------------------------------------------
    # OpenRouter Auto
    # ------------------------------------------------------------------
    "openrouter/auto": {
        "input_price_per_1m": 0.5,        # Aproximado (varía según el modelo que elija)
        "output_price_per_1m": 2.0,
        "category": "standard",
    },
    # ------------------------------------------------------------------
    # Qwen (Alibaba)
    # ------------------------------------------------------------------
    "qwen/qwen-2.5-vl-72b-instruct": {
        "input_price_per_1m": 0.35,
        "output_price_per_1m": 0.55,
        "category": "economy",
    },
    "qwen/qwen3.6-plus": {
        "input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "category": "premium",
    },
    "qwen/qwen-2.5-72b-instruct": {
        "input_price_per_1m": 0.35,
        "output_price_per_1m": 0.55,
        "category": "economy",
    },
    # ------------------------------------------------------------------
    # AI21
    # ------------------------------------------------------------------
    "ai21/jamba-1-5-large": {
        "input_price_per_1m": 2.00,
        "output_price_per_1m": 8.00,
        "category": "premium",
    },
    "ai21/jamba-1-5-mini": {
        "input_price_per_1m": 0.20,
        "output_price_per_1m": 0.40,
        "category": "economy",
    },
}


def get_model_pricing(model_name: str) -> dict:
    """
    Obtener los precios de un modelo específico.

    Busca el modelo en el diccionario de precios. Si no lo encuentra,
    devuelve un fallback con precios estándar.

    Parámetros:
        model_name: Nombre del modelo (ej: "anthropic/claude-3.5-sonnet")

    Retorna:
        Dict con keys:
            - input_price_per_1m: Precio por millón de tokens de entrada
            - output_price_per_1m: Precio por millón de tokens de salida
            - category: Categoría del modelo (free, economy, standard, premium)

    Ejemplo:
        >>> pricing = get_model_pricing("anthropic/claude-3.5-sonnet")
        >>> pricing["input_price_per_1m"]
        3.0
    """
    return MODEL_PRICING.get(model_name, {
        "input_price_per_1m": 1.0,
        "output_price_per_1m": 5.0,
        "category": "standard",
    })


def calculate_cost(input_tokens: int, output_tokens: int, model_name: str) -> float:
    """
    Calcular el costo real basado en los tokens usados.

    Fórmula:
        costo = (tokens_entrada / 1M * precio_entrada) +
                (tokens_salida / 1M * precio_salida)

    Parámetros:
        input_tokens: Número de tokens de entrada
        output_tokens: Número de tokens de salida
        model_name: Nombre del modelo usado

    Retorna:
        Costo en USD (redondeado a 6 decimales)

    Ejemplo:
        >>> calculate_cost(1000, 500, "anthropic/claude-3.5-sonnet")
        0.00375
    """
    pricing = get_model_pricing(model_name)
    input_cost = (input_tokens / 1_000_000) * pricing["input_price_per_1m"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_price_per_1m"]
    return round(input_cost + output_cost, 6)


def get_model_category(model_name: str) -> str:
    """
    Obtener la categoría de un modelo.

    Parámetros:
        model_name: Nombre del modelo

    Retorna:
        Categoría: "free", "economy", "standard", o "premium"
    """
    return get_model_pricing(model_name).get("category", "standard")


def is_model_free(model_name: str) -> bool:
    """
    Verificar si un modelo es gratuito.

    Parámetros:
        model_name: Nombre del modelo

    Retorna:
        True si el modelo es gratuito
    """
    return get_model_pricing(model_name).get("category") == "free"


def list_available_models() -> list:
    """
    Listar todos los modelos disponibles con sus precios.

    Retorna:
        Lista de dicts con model, category, y precios
    """
    result = []
    for model_name, pricing in MODEL_PRICING.items():
        result.append({
            "model": model_name,
            "category": pricing["category"],
            "input_price_per_1m": pricing["input_price_per_1m"],
            "output_price_per_1m": pricing["output_price_per_1m"],
        })
    return result
