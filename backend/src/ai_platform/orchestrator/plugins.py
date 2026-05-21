"""
Sistema de plugins para extender funcionalidad de Odin.

Inspirado en el sistema de plugins de Hermes Agent. Permite agregar
nuevos comportamientos sin modificar el código principal del orquestador.

Patrones implementados:
- Hook-based architecture: plugins se conectan mediante puntos de gancho
- Ordered loading: plugins se cargan en orden especificado
- Graceful degradation: fallos en un plugin no afectan a otros
- Lifecycle management: on_start, on_stop, on_decide, on_execute, on_message

Uso:
    manager = PluginManager()
    manager.register(PluginSpec(
        name="logging",
        version="1.0",
        description="Log every decision",
        on_decide=lambda **kw: logger.info(kw),
    ))
    await manager.execute_hook("on_decide", decision=routing)
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PluginSpec:
    """
    Especificación de un plugin de Odin.

    Define el ciclo de vida y los puntos de gancho (hooks) de un plugin.
    Cada hook se ejecuta en un momento específico del flujo de Odin.

    Atributos:
        name: Identificador único del plugin
        version: Versão semántica (x.y.z)
        description: Descripción legible del plugin
        enabled: Si el plugin está activo
        load_order: Orden de carga (menor = primero)
        on_start: Hook ejecutado al iniciar Odin
        on_stop: Hook ejecutado al detener Odin
        on_decide: Hook ejecutado antes/después de decide()
        on_execute: Hook ejecutado antes/después de execute()
        on_message: Hook ejecutado antes de enviar respuesta al cliente
    """

    name: str
    version: str
    description: str
    enabled: bool = True
    load_order: int = 0

    # Hook points del ciclo de vida
    on_start: Callable | None = None
    on_stop: Callable | None = None
    on_decide: Callable | None = None
    on_execute: Callable | None = None
    on_message: Callable | None = None


class PluginManager:
    """
    Gestiona el ciclo de vida de plugins de Odin.

    Los plugins permiten extender la funcionalidad de Odin sin
    modificar su código central. Cada plugin puede conectar hooks
    en puntos específicos del flujo de ejecución.

    Patrones de Hermes aplicados:
    - Plugin discovery: carga automática de plugins registrados
    - Hook execution: ejecución ordenada de hooks por tipo
    - Error isolation: fallos en un plugin no afectan a otros
    - Lifecycle management: inicio y parada ordenados

    Uso:
        manager = PluginManager()
        manager.register(PluginSpec(
            name="audit",
            version="1.0",
            description="Audit every decision",
            on_decide=lambda **kw: audit_log(kw),
        ))
    """

    def __init__(self):
        self._plugins: dict[str, PluginSpec] = {}
        self._hooks: dict[str, list[Callable]] = {
            "on_start": [],
            "on_stop": [],
            "on_decide": [],
            "on_execute": [],
            "on_message": [],
        }
        self._started = False
        self._stopped = False

    def register(self, spec: PluginSpec) -> None:
        """
        Registrar un plugin y sus hooks.

        El plugin se registra inmediatamente pero sus hooks
        solo se ejecutan después de llamar a start().

        Parámetros:
            spec: Especificación del plugin a registrar

        Raises:
            ValueError: Si name o version están vacíos
        """
        if not spec.name:
            raise ValueError("Plugin name cannot be empty")
        if not spec.version:
            raise ValueError("Plugin version cannot be empty")

        if spec.name in self._plugins:
            logger.warning(f"Plugin '{spec.name}' already registered, replacing")

        self._plugins[spec.name] = spec
        self._register_hooks(spec)
        logger.info(f"Plugin registered: {spec.name} v{spec.version} ({spec.description})")

    def unregister(self, plugin_name: str) -> bool:
        """
        Desregistrar un plugin y sus hooks.

        Parámetros:
            plugin_name: Nombre del plugin a desregistrar

        Retorna:
            True si se desregistró, False si no existía
        """
        if plugin_name not in self._plugins:
            return False

        spec = self._plugins.pop(plugin_name)
        self._unregister_hooks(spec)
        logger.info(f"Plugin unregistered: {plugin_name}")
        return True

    def _register_hooks(self, spec: PluginSpec) -> None:
        """
        Registrar todos los hooks de un plugin.

        Solo se registran hooks no-nulos y del plugin habilitado.

        Parámetros:
            spec: Especificación del plugin
        """
        if not spec.enabled:
            logger.debug(f"Skipping disabled plugin: {spec.name}")
            return

        for hook_name, hook_func in [
            ("on_start", spec.on_start),
            ("on_stop", spec.on_stop),
            ("on_decide", spec.on_decide),
            ("on_execute", spec.on_execute),
            ("on_message", spec.on_message),
        ]:
            if hook_func:
                self._hooks[hook_name].append(hook_func)
                logger.debug(f"Hook registered: {spec.name}.{hook_name} -> {hook_func.__name__}")

    def _unregister_hooks(self, spec: PluginSpec) -> None:
        """
        Remover todos los hooks de un plugin al desregistrarlo.

        Parámetros:
            spec: Especificación del plugin a remover
        """
        for hook_name in self._hooks:
            self._hooks[hook_name] = [h for h in self._hooks[hook_name] if h.__name__ != spec.name]

    async def start(self) -> None:
        """
        Iniciar todos los plugins habilitados.

        Ejecuta el hook on_start de cada plugin en orden de carga.
        Los plugins se ordenan por load_order (menor primero).

        Raises:
            RuntimeError: Si ya se inició
        """
        if self._started:
            logger.warning("PluginManager already started")
            return

        self._started = True
        sorted_plugins = sorted(
            self._plugins.values(),
            key=lambda p: p.load_order,
        )

        for plugin in sorted_plugins:
            if not plugin.enabled:
                continue
            await self.execute_hook("on_start", plugin_name=plugin.name)

        logger.info(f"PluginManager started with {len(self._plugins)} plugins")

    async def stop(self) -> None:
        """
        Detener todos los plugins habilitados.

        Ejecuta el hook on_stop de cada plugin en orden inverso
        (mayor load_order primero = LIFO).
        """
        if self._stopped:
            logger.warning("PluginManager already stopped")
            return

        self._stopped = True
        sorted_plugins = sorted(
            self._plugins.values(),
            key=lambda p: p.load_order,
            reverse=True,
        )

        for plugin in sorted_plugins:
            if not plugin.enabled:
                continue
            await self.execute_hook("on_stop", plugin_name=plugin.name)

        logger.info("PluginManager stopped")

    async def execute_hook(
        self,
        hook_name: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Ejecutar todos los hooks de un tipo específico.

        Los hooks se ejecutan en orden de carga. Los fallos en
        un hook no afectan la ejecución de otros hooks del mismo tipo.

        Parámetros:
            hook_name: Nombre del hook a ejecutar
            **kwargs: Argumentos pasados a cada hook

        Retorna:
            Dict con resultados de cada hook ejecutado
        """
        if hook_name not in self._hooks:
            logger.warning(f"Unknown hook type: {hook_name}")
            return {}

        results: dict[str, Any] = {}
        hooks = self._hooks[hook_name]

        for hook_func in hooks:
            try:
                hook_result = await self._invoke_hook(hook_func, **kwargs)
                results[hook_func.__name__] = hook_result
            except Exception as e:
                logger.error(f"Plugin hook '{hook_func.__name__}' ({hook_name}) failed: {e}")
                results[hook_func.__name__] = {"error": str(e)}

        return results

    async def _invoke_hook(
        self,
        func: Callable,
        **kwargs: Any,
    ) -> Any:
        """
        Invocar un hook individual, manejando sync/async.

        Parámetros:
            func: Función del hook
            **kwargs: Argumentos para la función

        Retorna:
            Resultado de la función
        """
        if asyncio.iscoroutinefunction(func):
            return await func(**kwargs)
        else:
            return func(**kwargs)

    def list_plugins(self) -> list[dict[str, Any]]:
        """
        Listar todos los plugins registrados.

        Retorna:
            Lista de dicts con nombre, versión, descripción y estado
        """
        return [
            {
                "name": spec.name,
                "version": spec.version,
                "description": spec.description,
                "enabled": spec.enabled,
                "load_order": spec.load_order,
            }
            for spec in self._plugins.values()
        ]

    def get_plugin(self, plugin_name: str) -> PluginSpec | None:
        """
        Obtener un plugin por nombre.

        Parámetros:
            plugin_name: Nombre del plugin

        Retorna:
            PluginSpec o None si no existe
        """
        return self._plugins.get(plugin_name)

    @property
    def plugin_count(self) -> int:
        """Número total de plugins registrados."""
        return len(self._plugins)

    @property
    def enabled_count(self) -> int:
        """Número de plugins habilitados."""
        return sum(1 for p in self._plugins.values() if p.enabled)


# Instancia global
_plugin_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    """
    Obtener la instancia de PluginManager (singleton).

    Retorna:
        Instancia de PluginManager
    """
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
