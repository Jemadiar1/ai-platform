"""
Módulo del orquestador Odin.

Odin es el cerebro de AI Platform. Decide qué módulo especializado
debe actuar en cada tarea, mantiene el contexto de sesión y coordina
la ejecución entre los 7 módulos de IA.

Arquitectura:
    Request -> Odin (LLM-based routing) -> Module Handler -> Response

Componentes:
    - Odin.py: Motor de decisión principal
    - llm_client.py: Cliente OpenRouter para decisiones LLM
    - session.py: Gestión de sesión con frozen snapshots
    - memory.py: Memoria acotada con bounded memory
    - skills.py: Gestión de skills con security scanning
    - budget.py: Tracking de iteraciones y costos
    - observability.py: Logging de decisiones críticas
"""

from ai_platform.orchestrator import budget, llm_client, memory, observability, odin, session, skills

__all__ = [
    "budget",
    "llm_client",
    "memory",
    "observability",
    "odin",
    "session",
    "skills",
]
