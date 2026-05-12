"""
Módulo del orquestador Ragnar.

Ragnar es el cerebro de AI Platform. Decide qué módulo especializado
debe actuar en cada tarea, mantiene el contexto de sesión y coordina
la ejecución entre los 7 módulos de IA.

Arquitectura:
    Request -> Ragnar (LLM-based routing) -> Module Handler -> Response
    
Componentes:
    - ragnar.py: Motor de decisión principal
    - llm_client.py: Cliente OpenRouter para decisiones LLM
    - session.py: Gestión de sesión con frozen snapshots
    - memory.py: Memoria acotada con bounded memory
    - skills.py: Gestión de skills con security scanning
    - budget.py: Tracking de iteraciones y costos
    - observability.py: Logging de decisiones críticas
"""

from ai_platform.orchestrator import ragnar
from ai_platform.orchestrator import llm_client
from ai_platform.orchestrator import session
from ai_platform.orchestrator import memory
from ai_platform.orchestrator import skills
from ai_platform.orchestrator import budget
from ai_platform.orchestrator import observability

__all__ = [
    "ragnar",
    "llm_client",
    "session",
    "memory",
    "skills",
    "budget",
    "observability",
]
