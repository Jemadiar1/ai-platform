"""
Soporte para Model Context Protocol (MCP) de Hermes Agent.

MCP permite que los modelos LLM accedan a herramientas externas
de forma estandarizada. Implementamos un subset para Ragnar.

Inspirado en:
- Model Context Protocol (Anthropic)
- Hermes Agent MCP tools integration
"""

import json
import logging
import httpx
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """
    Representa una herramienta MCP disponible.

    Cada herramienta tiene un nombre único, descripción,
    esquema de parámetros y puede estar habilitada/deshabilitada.

    Atributos:
        name: Identificador único de la herramienta
        description: Descripción legible para el LLM
        parameters: Esquema JSON de parámetros esperados
        enabled: Si la herramienta está activa
        metadata: Datos extra (endpoint, headers, auth, etc.)
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """
    Cliente MCP para conectar con herramientas externas.

    Permite a los módulos de Ragnar acceder a:
    - Herramientas web (navegación, búsqueda)
    - Herramientas de código
    - Herramientas de datos

    Uso:
        client = MCPClient()
        client.register_tool(MCPTool(
            name="web_search",
            description="Buscar en la web",
            parameters={"query": {"type": "string"}},
        ))
        result = await client.call_tool("web_search", {"query": "noticias"})
    """

    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """
        Registrar herramientas MCP integradas por defecto.

        Estas herramientas están siempre disponibles y no requieren
        configuración externa.
        """
        self.register_tool(MCPTool(
            name="time",
            description=(
                "Obtener la fecha y hora actual. Útil para tareas que "
                "necesitan contexto temporal como 'programar para mañana' "
                "o 'cuánto tiempo ha pasado desde...'."
            ),
            parameters={},
            metadata={"type": "builtin"},
        ))

        self.register_tool(MCPTool(
            name="calculate",
            description=(
                "Evaluar expresiones matemáticas. Soporta operaciones "
                "aritméticas básicas (+, -, *, /), funciones trigonométricas, "
                "logaritmos y constantes matemáticas."
            ),
            parameters={
                "expression": {
                    "type": "string",
                    "description": "Expresión matemática a evaluar",
                }
            },
            metadata={"type": "builtin"},
        ))

        self.register_tool(MCPTool(
            name="json_formatter",
            description=(
                "Formatear y validar datos JSON. Útil para estructurar "
                "respuestas, validar esquemas o beautify JSON."
            ),
            parameters={
                "json_string": {
                    "type": "string",
                    "description": "Cadena JSON a formatear",
                }
            },
            metadata={"type": "builtin"},
        ))

        logger.info(f"MCPClient initialized with {len(self._tools)} built-in tools")

    def register_tool(self, tool: MCPTool) -> None:
        """
        Registrar una herramienta MCP.

        Si ya existe una herramienta con el mismo nombre, se reemplaza.

        Parámetros:
            tool: Herramienta MCP a registrar

        Raises:
            ValueError: Si name o parameters están vacíos
        """
        if not tool.name:
            raise ValueError("Tool name cannot be empty")
        if not tool.parameters:
            raise ValueError("Tool parameters schema cannot be empty")

        self._tools[tool.name] = tool
        logger.info(f"MCP tool registered: {tool.name}")

    def unregister_tool(self, tool_name: str) -> bool:
        """
        Desregistrar una herramienta MCP.

        Parámetros:
            tool_name: Nombre de la herramienta a desregistrar

        Retorna:
            True si se desregistró, False si no existía
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.info(f"MCP tool unregistered: {tool_name}")
            return True
        logger.warning(f"Attempted to unregister non-existent tool: {tool_name}")
        return False

    def enable_tool(self, tool_name: str) -> bool:
        """
        Habilitar una herramienta MCP.

        Parámetros:
            tool_name: Nombre de la herramienta

        Retorna:
            True si se habilitó, False si no existía
        """
        tool = self._tools.get(tool_name)
        if tool:
            tool.enabled = True
            logger.info(f"MCP tool enabled: {tool_name}")
            return True
        return False

    def disable_tool(self, tool_name: str) -> bool:
        """
        Deshabilitar una herramienta MCP.

        Parámetros:
            tool_name: Nombre de la herramienta

        Retorna:
            True si se deshabilitó, False si no existía
        """
        tool = self._tools.get(tool_name)
        if tool:
            tool.enabled = False
            logger.info(f"MCP tool disabled: {tool_name}")
            return True
        return False

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict:
        """
        Ejecutar una herramienta MCP.

        Maneja tanto herramientas builtin como HTTP-based:
        - Builtin: Se ejecuta directamente en Python
        - HTTP-based: Se llama a un endpoint externo vía MCP

        Parámetros:
            tool_name: Nombre de la herramienta
            params: Parámetros para la herramienta

        Retorna:
            Dict con resultado o error
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {
                "error": f"Tool not found: {tool_name}",
                "available_tools": list(self._tools.keys()),
            }

        if not tool.enabled:
            return {
                "error": f"Tool disabled: {tool_name}",
                "message": "Contact your administrator to enable this tool.",
            }

        # Ejecutar herramientas builtin
        if tool.metadata.get("type") == "builtin":
            return await self._execute_builtin(tool_name, params)

        # Ejecutar herramientas HTTP-based (MCP server)
        return await self._execute_http_tool(tool, params)

    async def _execute_builtin(
        self, tool_name: str, params: Dict[str, Any]
    ) -> Dict:
        """
        Ejecutar una herramienta builtin integrada.

        Parámetros:
            tool_name: Nombre de la herramienta
            params: Parámetros

        Retorna:
            Dict con resultado
        """
        try:
            if tool_name == "time":
                now = datetime.now(timezone.utc)
                return {
                    "timezone": "UTC",
                    "datetime": now.isoformat(),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                }

            elif tool_name == "calculate":
                expression = params.get("expression", "")
                if not expression:
                    return {"error": "No expression provided"}

                # Evaluación segura con funciones limitadas
                allowed_names = {
                    "abs": abs,
                    "round": round,
                    "min": min,
                    "max": max,
                    "sum": sum,
                    "pow": pow,
                    "sqrt": __import__("math").sqrt,
                    "log": __import__("math").log,
                    "log10": __import__("math").log10,
                    "sin": __import__("math").sin,
                    "cos": __import__("math").cos,
                    "tan": __import__("math").tan,
                    "pi": __import__("math").pi,
                    "e": __import__("math").e,
                }

                try:
                    result = eval(expression, {"__builtins__": {}}, allowed_names)
                    return {"expression": expression, "result": result}
                except Exception as e:
                    return {"error": f"Calculation failed: {str(e)}"}

            elif tool_name == "json_formatter":
                json_string = params.get("json_string", "")
                if not json_string:
                    return {"error": "No JSON string provided"}

                try:
                    parsed = json.loads(json_string)
                    formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                    return {"formatted": formatted, "valid": True}
                except json.JSONDecodeError as e:
                    return {"error": f"Invalid JSON: {str(e)}", "valid": False}

            else:
                return {"error": f"Unknown builtin tool: {tool_name}"}

        except Exception as e:
            logger.error(f"Builtin tool '{tool_name}' execution failed: {e}")
            return {"error": str(e)}

    async def _execute_http_tool(
        self, tool: MCPTool, params: Dict[str, Any]
    ) -> Dict:
        """
        Ejecutar una herramienta HTTP-based via MCP server.

        Parámetros:
            tool: Definición de la herramienta
            params: Parámetros combinados con los del esquema

        Retorna:
            Dict con resultado del endpoint o error
        """
        endpoint = tool.metadata.get("endpoint", "")
        if not endpoint:
            return {"error": "No endpoint configured for tool: " + tool.name}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    endpoint,
                    json={**tool.parameters, **params},
                    headers=tool.metadata.get("headers", {}),
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            logger.error(f"MCP tool timeout: {tool.name} -> {endpoint}")
            return {"error": f"Timeout calling MCP tool: {tool.name}"}
        except httpx.HTTPStatusError as e:
            logger.error(f"MCP tool HTTP error: {tool.name} -> {e.response.status_code}")
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return {"error": str(e)}

    async def list_tools(self, tenant_id: str) -> List[Dict]:
        """
        Listar herramientas MCP disponibles para un tenant.

        Parámetros:
            tenant_id: ID del tenant (para contexto de autorización)

        Retorna:
            Lista de dicts con nombre, descripción y parámetros
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "enabled": t.enabled,
                "metadata_type": t.metadata.get("type", "http"),
            }
            for t in self._tools.values()
            if t.enabled
        ]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Obtener esquemas de herramientas para inyectar en prompts del LLM.

        Retorna:
            Lista de dicts con formato para system prompt del LLM
        """
        schemas = []
        for tool in self._tools.values():
            if not tool.enabled:
                continue

            param_descriptions = []
            for param_name, param_schema in tool.parameters.items():
                if isinstance(param_schema, dict):
                    desc = param_schema.get("description", "")
                    param_descriptions.append(f"    - {param_name}: {desc}")
                else:
                    param_descriptions.append(f"    - {param_name}")

            param_str = "\n".join(param_descriptions) if param_descriptions else "    (ninguno)"

            schemas.append(
                f"- {tool.name}: {tool.description}\n  Parámetros:\n{param_str}"
            )

        return schemas

    async def close(self) -> None:
        """Cerrar recursos del cliente MCP."""
        self._tools.clear()
        logger.info("MCPClient closed")


# Instancia global
_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    """
    Obtener la instancia de MCPClient (singleton).

    Retorna:
        Instancia de MCPClient
    """
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
