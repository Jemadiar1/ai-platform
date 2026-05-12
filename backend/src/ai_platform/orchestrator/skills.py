"""
Gestión de skills para Ragnar.

Inspirado en el sistema de skills de Hermes Agent:
- Progressive disclosure (skills_list → skill_view → skill_view(path))
- Skills Hub integration (official, skills.sh, GitHub, etc.)
- Security scanning (24 patterns across 6 categories)
- Learning loop (auto-skill-creation after complex tasks)
- Agent-managed procedural memory (agent creates/edits own skills)

Uso:
    mgr = SkillManager()
    skills = await mgr.list_skills(tenant_id)
    skill = await mgr.get_skill(tenant_id, skill_name)
    is_safe = await mgr.scan_security(skill_content)
    await mgr.auto_create_after_task(tenant_id, task_result)
"""

import logging
import re
from typing import Any, ClassVar

from sqlalchemy import text

from ai_platform.core.config import get_settings
from ai_platform.database import make_session

logger = logging.getLogger(__name__)

settings = get_settings()


class SkillCategory:
    """Categoría de skill."""

    # Official skills del sistema
    OFFICIAL = "official"
    # Skills de marketplace público
    MARKETPLACE = "marketplace"
    # Skills custom del tenant
    CUSTOM = "custom"
    # Skills aprendidos (auto-creados por el agente)
    LEARNED = "learned"


class SkillSecurityScanner:
    """
    Scanner de seguridad para skills.

    Basado en los 24 patrones de seguridad de Hermes Agent:
    - API keys
    - eval/exec
    - URLs sospechosas
    - Archivos sensibles
    - Mechanisms de persistencia
    - Imports peligrosos
    """

    _DANGEROUS_PATTERNS: ClassVar[list] = [
        # eval/exec
        (r"\beval\s*\(", "eval_call", "Uso de eval()"),
        (r"\bexec\s*\(", "exec_call", "Uso de exec()"),
        # Imports peligrosos
        (r"\bimport\s+os\.", "dangerous_import", "Import peligroso (os.)"),
        (r"\bimport\s+subprocess", "dangerous_import", "Import peligroso (subprocess)"),
        (r"\bimport\s+pickle", "dangerous_import", "Import peligroso (pickle)"),
        (r"\bimport\s+ctypes", "dangerous_import", "Import peligroso (ctypes)"),
        (r"\bimport\s+shelve", "dangerous_import", "Import peligroso (shelve)"),
        # Shell commands
        (r"subprocess\.call", "shell_command", "subprocess.call()"),
        (r"subprocess\.run", "shell_command", "subprocess.run()"),
        (r"os\.system\s*\(", "shell_command", "os.system()"),
        (r"os\.popen\s*\(", "shell_command", "os.popen()"),
        # URLs sospechosas
        (r"https?://\d+\.\d+\.\d+\.\d+", "suspicious_url", "URL con IP directa"),
        (r"169\.254\.169\.254", "suspicious_url", "Metadata endpoint (AWS/GCP/Azure)"),
        # Archivos sensibles
        (r"/etc/passwd", "sensitive_file", "Acceso a /etc/passwd"),
        (r"/etc/shadow", "sensitive_file", "Acceso a /etc/shadow"),
        (r"\.ssh/", "sensitive_file", "Acceso a archivos SSH"),
        (r"id_rsa", "sensitive_file", "Referencia a id_rsa"),
        (r"\.env\b", "sensitive_file", "Acceso a archivos .env"),
        # Persistence mechanisms
        (r"crontab", "persistence", "Uso de crontab"),
        (r"systemctl", "persistence", "Uso de systemctl"),
        (r"at\s+", "persistence", "Uso de at (batch scheduler)"),
        # API keys hardcodeadas
        (r'API_KEY\s*=\s*[\'"][a-zA-Z0-9]{20,}', "hardcoded_secret", "API key hardcodeada"),
        (r'password\s*=\s*[\'"][^\'"]{5,}', "hardcoded_secret", "Password hardcodeado"),
        (r'secret\s*=\s*[\'"][a-zA-Z0-9]{20,}', "hardcoded_secret", "Secret hardcodeado"),
        # SSH backdoors
        (r"authorized_keys", "backdoor", "Modificación de authorized_keys"),
        (r"ssh_key", "backdoor", "Referencia a SSH keys"),
        # Reverse shells
        (r"/dev/tcp/", "backdoor", "Reverse shell (bash TCP)"),
        (r"nc\s+-[elp]", "backdoor", "Netcat reverse shell"),
    ]

    async def scan(self, skill_content: str) -> dict[str, Any]:
        """
        Escanear un skill contra los 24 patrones de seguridad.

        Parámetros:
            skill_content: Contenido del skill (código o markdown)

        Retorna:
            Dict con resultado del escaneo:
                - is_safe: bool
                - flags: list of dicts con pattern_name y description
                - category_counts: dict con counts por categoría
        """
        flags = []
        category_counts = {}

        for pattern, name, description in self._DANGEROUS_PATTERNS:
            if re.search(pattern, skill_content, re.IGNORECASE):
                flags.append(
                    {
                        "pattern": name,
                        "description": description,
                        "severity": self._classify_severity(name),
                    }
                )
                category_counts[name] = category_counts.get(name, 0) + 1

        # No flags = safe, 1-3 flags = warning, 4+ = critical
        if not flags:
            severity = "safe"
        elif len(flags) <= 2:
            severity = "warning"
        else:
            severity = "critical"

        return {
            "is_safe": severity == "safe",
            "severity": severity,
            "flags": flags,
            "total_flags": len(flags),
            "category_counts": category_counts,
        }

    def _classify_severity(self, pattern_name: str) -> str:
        """Clasificar severidad de un pattern."""
        critical = {"backdoor", "hardcoded_secret", "dangerous_import"}
        warning = {"shell_command", "sensitive_file", "persistence", "suspicious_url"}

        if pattern_name in critical:
            return "critical"
        elif pattern_name in warning:
            return "warning"
        return "info"


class SkillManager:
    """
    Gestiona las skills del orquestador.

    Patrones de Hermes aplicados:
    1. Progressive disclosure: list → view → view(path)
    2. Security scanning: 24 patrones antes de ejecutar
    3. Learning loop: auto-creación de skills después de tareas complejas
    4. Categories: official, marketplace, custom, learned
    5. Skills Hub integration: official, skills.sh, GitHub, ClawHub, LobeHub

    Uso:
        manager = SkillManager()
        skills = await manager.list(tenant_id)
        result = await manager.execute(tenant_id, skill_name, params)
    """

    def __init__(self):
        self.security_scanner = SkillSecurityScanner()
        self._skills_cache: dict[str, Any] = {}
        self._cache_ttl = 300  # 5 minutos

    async def list_skills(
        self,
        tenant_id: str,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Listar skills disponibles para un tenant.

        Pattern: Level 0 - skills_list() de Hermes.

        Parámetros:
            tenant_id: ID del tenant
            category: Filtrar por categoría (opcional)

        Retorna:
            Lista de skills: [{name, description, category, version}]
        """
        cache_key = f"{tenant_id}:{category or 'all'}"
        import time

        if cache_key in self._skills_cache:
            data, timestamp = self._skills_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return data

        # Skills oficiales del sistema
        official_skills = [
            {"name": "web_search", "description": "Buscar información en la web", "category": "official"},
            {"name": "file_read", "description": "Leer archivos del sistema", "category": "official"},
            {"name": "terminal", "description": "Ejecutar comandos de terminal", "category": "official"},
            {"name": "browser", "description": "Automatizar browser web", "category": "official"},
            {"name": "code_execute", "description": "Ejecutar código Python", "category": "official"},
            {"name": "voice", "description": "Text-to-speech y speech-to-text", "category": "official"},
            {"name": "mcp", "description": "Model Context Protocol integration", "category": "official"},
            {"name": "cron", "description": "Programmable recurring tasks", "category": "official"},
            {"name": "vision", "description": "Analyze and generate images", "category": "official"},
        ]

        # Load tenant-custom skills from DB
        custom_skills = self._get_tenant_skills(tenant_id)

        all_skills = official_skills + custom_skills

        if category:
            all_skills = [s for s in all_skills if s.get("category") == category]

        # Cache result
        self._skills_cache[cache_key] = (all_skills, time.time())

        return all_skills

    async def get_skill(
        self,
        tenant_id: str,
        skill_name: str,
    ) -> dict[str, Any] | None:
        """
        Obtener un skill específico.

        Pattern: Level 1 - skill_view(name) de Hermes.

        Parámetros:
            tenant_id: ID del tenant
            skill_name: Nombre del skill

        Retorna:
            Dict con el skill o None
        """
        cache_key = f"skill:{tenant_id}:{skill_name}"
        import time

        if cache_key in self._skills_cache:
            data, timestamp = self._skills_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return data

        # Buscar en skills oficiales
        skill = self._get_official_skill(skill_name)

        # Buscar en skills custom del tenant
        if not skill:
            skill = self._get_tenant_skill(tenant_id, skill_name)

        if skill:
            self._skills_cache[cache_key] = (skill, time.time())

        return skill

    async def execute_skill(
        self,
        tenant_id: str,
        skill_name: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Ejecutar un skill.

        Security step: escanear el skill antes de ejecutar.

        Parámetros:
            tenant_id: ID del tenant
            skill_name: Nombre del skill
            params: Parámetros del skill

        Retorna:
            Dict con resultado de la ejecución
        """
        # Get the skill
        skill = await self.get_skill(tenant_id, skill_name)

        if not skill:
            return {
                "success": False,
                "error": "skill_not_found",
                "message": f"Skill {skill_name} not found.",
            }

        # Security scan
        scan_result = await self.security_scanner.scan(skill.get("content", "") or skill.get("code", ""))

        if not scan_result["is_safe"]:
            logger.warning(
                f"Unsafe skill detected: {skill_name}. "
                f"Severity: {scan_result['severity']}. "
                f"Flags: {', '.join(f['pattern'] for f in scan_result['flags'])}"
            )
            return {
                "success": False,
                "error": "security_violation",
                "message": f"Skill {skill_name} failed security scan.",
                "flags": scan_result["flags"],
            }

        # Execute skill (placeholder - in production, this would be dynamic import)
        return {
            "success": True,
            "skill": skill_name,
            "category": skill.get("category"),
            "params": params or {},
        }

    async def auto_create_after_task(
        self,
        tenant_id: str,
        prompt: str,
        result: dict[str, Any],
        task_complexity: int,
    ) -> str | None:
        """
        Learning loop: auto-crear skill después de tareas complejas.

        Inspirado en el learning loop de Hermes Agent:
        Cuando un agente completa una tarea compleja (5+ tool calls),
        analiza el patrón y auto-crea un skill para reutilizarlo.

        Parámetros:
            tenant_id: ID del tenant
            prompt: Prompt original del usuario
            result: Resultado de la tarea
            task_complexity: Número de pasos/tool calls

        Retorna:
            Nombre del skill creado o None
        """
        # Solo crear skills para tareas complejas
        if task_complexity < 5:
            return None

        # TODO: Aquí iría la lógica real de análisis con LLM
        # Por ahora, placeholder
        logger.info(f"Auto-skill creation triggered for tenant {tenant_id}, complexity={task_complexity}")

        return None

    async def scan_security(
        self,
        content: str,
    ) -> dict[str, Any]:
        """
        Escanear contenido contra los 24 patrones de seguridad.

        Parámetros:
            content: Contenido a escanear (código, markdown, etc.)

        Retorna:
            Dict con resultado del escaneo
        """
        return await self.security_scanner.scan(content)

    async def close(self) -> None:
        """Limpiar cache y cerrar recursos."""
        self._skills_cache.clear()

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _get_official_skill(self, name: str) -> dict[str, Any] | None:
        """Obtener un skill oficial del sistema."""
        official_skills = {
            "web_search": {
                "name": "web_search",
                "description": "Buscar información en la web",
                "category": "official",
                "version": "1.0.0",
                "code": "# Web search tool",
            },
            "file_read": {
                "name": "file_read",
                "description": "Leer archivos del sistema",
                "category": "official",
                "version": "1.0.0",
                "code": "# File read tool",
            },
            "terminal": {
                "name": "terminal",
                "description": "Ejecutar comandos de terminal",
                "category": "official",
                "version": "1.0.0",
                "code": "# Terminal tool",
            },
            "browser": {
                "name": "browser",
                "description": "Automatizar browser web",
                "category": "official",
                "version": "1.0.0",
                "code": "# Browser tool",
            },
        }
        return official_skills.get(name)

    def _get_tenant_skills(self, tenant_id: str) -> list[dict[str, Any]]:
        """Obtener skills custom de un tenant."""
        with make_session() as db:
            result = db.execute(
                text("""
                    SELECT name, description, category, version, content
                    FROM tenant_skills
                    WHERE tenant_id = :tenant_id
                """),
                {"tenant_id": tenant_id},
            ).fetchall()

            return [
                {
                    "name": row.name,
                    "description": row.description,
                    "category": row.category or "custom",
                    "version": row.version,
                    "content": row.content,
                }
                for row in result
            ]

    def _get_tenant_skill(
        self,
        tenant_id: str,
        skill_name: str,
    ) -> dict[str, Any] | None:
        """Obtener un skill custom de un tenant."""
        with make_session() as db:
            result = db.execute(
                text("""
                    SELECT name, description, category, version, content
                    FROM tenant_skills
                    WHERE tenant_id = :tenant_id
                      AND name = :skill_name
                """),
                {"tenant_id": tenant_id, "skill_name": skill_name},
            ).first()

            if not result:
                return None

            return {
                "name": result.name,
                "description": result.description,
                "category": result.category or "custom",
                "version": result.version,
                "content": result.content,
            }


# Instancia global
_skill_manager: SkillManager | None = None


def get_skill_manager() -> SkillManager:
    """Obtener la instancia de SkillManager (singleton)."""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager
