"""
Utilidades de seguridad.

Contiene funciones para:
- Decodificar tokens JWT (solo lectura, Clerk gestiona auth)
- Escanear inyección de prompts (12 patrones de Hermes)
- Sanitizar inputs LLM (stripping zero-width chars, RTL overrides)
"""

import logging
import re
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from urllib.parse import urlparse

import bcrypt as _bcrypt
from jose import JWTError, jwt

from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


# =========================================================================
# JWT TOKEN DECODING (read-only, Clerk handles auth)
# =========================================================================

# Use bcrypt directly to avoid passlib's known bug with bcrypt 5.x
_BCRYPT_ROUNDS = 12


def decode_token(token: str) -> dict | None:
    """
    Decodificar y validar un token JWT.

    Solo se usa para lectura de claims. Clerk gestiona la autenticación.
    """
    settings = get_settings()

    try:
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return decoded
    except JWTError:
        return None


# =========================================================================
# INJECTION SCANNER (12 patrones inspirados en Hermes)
# =========================================================================


class InjectionScanner:
    """
    Escáner de seguridad contra inyección de prompts.

    Basado en los patrones de seguridad de Hermes Agent.
    Escanea texto antes de ser inyectado en un LLM.

    Los 12 patrones detectan:
    1. Prompt injection markers (ignorar instrucciones previas)
    2. System directive injection (system:, user:, assistant:)
    3. JSON injection ({"type":"system"})
    4. HTML/JS injection
    5. XML injection
    6. Backtick code blocks
    7. Markdown header injection
    8. Shell command injection
    9. Credential exfiltration patterns
    10. Invisible Unicode (U+200B, etc.)
    11. Bidirectional override (U+202A-U+202E)
    12. Null bytes y control chars

    Uso:
        scanner = InjectionScanner()
        result = scanner.scan("Tu texto aquí")
        if result.is_safe:
            # texto seguro
        else:
            # bloquear o sanitize
    """

    # Patrón 1: Prompt injection markers
    _SYSTEM_INJECTION = re.compile(
        r"ignore\s+previous\s+instructions|disregard\s+all|bypass\s+all|forget\s+previous|new\s+rule",
        re.IGNORECASE,
    )

    # Patrón 2: System directive tags
    _DIRECTIVE_INJECTION = re.compile(r"(?:^\s*(?:system|user|assistant|role):\s)", re.IGNORECASE | re.MULTILINE)

    # Patrón 3: JSON injection en texto plano
    _JSON_INJECTION = re.compile(r'\{(?:\s*"(?:system|role|instruction|command)"\s*:)', re.IGNORECASE)

    # Patrón 4: HTML/JS injection
    _HTML_INJECTION = re.compile(r"<script|onerror\s*=|onload\s*=|javascript\s*:", re.IGNORECASE)

    # Patrón 5: XML injection
    _XML_INJECTION = re.compile(r"<\?xml|<!DOCTYPE|<\!ENTITY|<\!ENTITY", re.IGNORECASE)

    # Patrón 6: Código de bloquete
    _CODE_INJECTION = re.compile(r"`{3,}.*?\n.*?system:|`{3,}.*?\n.*?ignore\s+previous", re.IGNORECASE | re.DOTALL)

    # Patrón 7: Headers markdown como injection
    _MD_INJECTION = re.compile(r"^#{1,2}\s+(?:SYSTEM|INSTRUCTION|COMMAND|ROLE)\s*$", re.IGNORECASE)

    # Patrón 8: Shell command injection
    _SHELL_INJECTION = re.compile(r"(?:`[^`]+`|\$\([^)]+\))\s*(?:;|&&|\|\||\|)")

    # Patrón 9: Credential exfiltration
    _CREDENTIAL_EXFIL = re.compile(r"(?:token|api[_-]?key|secret|password|private[_-]?key)\s*[:=]\s*\S+", re.IGNORECASE)

    # Patrón 10: Invisible Unicode chars (zero-width)
    _INVISIBLE_UNICODE = re.compile(r"[\u200B-\u200F\u2028-\u202E\u2060-\u2069\uFEFF\uFFF0-\uFFF9]")

    # Patrón 11: Bidirectional override
    _BIDI_OVERRIDE = re.compile(r"[\u202A-\u202E]")

    # Patrón 12: Control chars y null bytes
    _CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

    def __init__(self, max_content_length: int = 65536):
        """
        Inicializar el escáner.

        Parámetros:
            max_content_length: Longitud máxima permitida para contenido
        """
        self.max_content_length = max_content_length

    def scan(self, text: str) -> dict:
        """
        Escanear texto contra los 12 patrones de inyección.

        Parámetros:
            text: Texto a escanear

        Retorna:
            dict con:
                - is_safe: bool
                - flagged_patterns: list[str] de patrones detectados
                - sanitized: str con control chars y invisible strips
                - is_truncated: bool si excedió el límite
        """
        flagged_patterns = []
        sanitized = text

        # Verificar longitud máxima
        if len(text) > self.max_content_length:
            return {
                "is_safe": False,
                "flagged_patterns": ["content_too_long"],
                "is_truncated": True,
                "sanitized": text[: self.max_content_length],
            }

        # Patrón 1: Prompt injection
        if self._SYSTEM_INJECTION.search(text):
            flagged_patterns.append("system_injection")

        # Patrón 2: System directive
        if self._DIRECTIVE_INJECTION.search(text):
            flagged_patterns.append("directive_injection")

        # Patrón 3: JSON injection
        if self._JSON_INJECTION.search(text):
            flagged_patterns.append("json_injection")

        # Patrón 4: HTML/JS injection
        if self._HTML_INJECTION.search(text):
            flagged_patterns.append("html_injection")

        # Patrón 5: XML injection
        if self._XML_INJECTION.search(text):
            flagged_patterns.append("xml_injection")

        # Patrón 6: Code block injection
        if self._CODE_INJECTION.search(text):
            flagged_patterns.append("code_injection")

        # Patrón 7: Markdown header injection
        if self._MD_INJECTION.search(text):
            flagged_patterns.append("md_injection")

        # Patrón 8: Shell injection
        if self._SHELL_INJECTION.search(text):
            flagged_patterns.append("shell_injection")

        # Patrón 9: Credential exfiltration
        if self._CREDENTIAL_EXFIL.search(text):
            flagged_patterns.append("credential_exfil")

        # Patrón 10: Invisible unicode
        if self._INVISIBLE_UNICODE.search(text):
            flagged_patterns.append("invisible_unicode")
            sanitized = self._INVISIBLE_UNICODE.sub("", sanitized)

        # Patrón 11: Bidirectional override
        if self._BIDI_OVERRIDE.search(text):
            flagged_patterns.append("bidi_override")
            sanitized = self._BIDI_OVERRIDE.sub("", sanitized)

        # Patrón 12: Control chars
        if self._CONTROL_CHARS.search(text):
            flagged_patterns.append("control_chars")
            sanitized = self._CONTROL_CHARS.sub("", sanitized)

        return {
            "is_safe": len(flagged_patterns) == 0,
            "flagged_patterns": flagged_patterns,
            "is_truncated": False,
            "sanitized": sanitized,
        }

    def sanitize(self, text: str) -> str:
        """
        Sanitizar texto removiendo caracteres peligrosos.

        Útil cuando quieres preservar el contenido pero limpiar
        caracteres que podrían ser usados en ataques.

        Parámetros:
            text: Texto a sanitizar

        Retorna:
            Texto sanitizado
        """
        result = self.scan(text)
        return result["sanitized"]


# Instancia global del scanner
scanner = InjectionScanner()

# =========================================================================
# PROMPT SANITIZER (inspirado en Hermes sanitize_title)
# =========================================================================


class PromptSanitizer:
    """
    Sanitizar prompts para inyección de prompts.

    Basado en sanitize_title() de Hermes Agent (hermes_state.py:628-670).

    Aplica:
    1. Stripping de control characters (ASCII 0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F, 0x7F)
    2. Stripping de Unicode manipulation sequences (U+200B-0x200F, U+2028-0x202E, etc.)
    3. Collapsing de whitespace
    4. Enforcing de MAX_LENGTH
    """

    MAX_TITLE_LENGTH = 500
    MAX_CONTENT_LENGTH = 65536

    # Control chars a remover
    _CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

    # Unicode manipulation (zero-width, bidi, etc.)
    _UNICODE_PATTERN = re.compile(r"[\u200B-\u200F\u2028-\u202E\u2060-\u2069\uFEFF\uFFF0-\uFFF9]")

    def sanitize(self, text: str, max_length: int = MAX_CONTENT_LENGTH) -> str:
        """
        Sanitizar el texto aplicando todas las reglas.

        Parámetros:
            text: Texto a sanitizar
            max_length: Longitud máxima después de sanitizar

        Retorna:
            Texto sanitizado, truncado si excede max_length
        """
        if not isinstance(text, str):
            return text

        # Remover control chars
        text = self._CONTROL_PATTERN.sub("", text)

        # Remover unicode manipulation
        text = self._UNICODE_PATTERN.sub(" ", text)

        # Collapsing de whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Truncar
        return text[:max_length]


prompt_sanitizer = PromptSanitizer()


# =========================================================================
# BOUNDED LRU CACHE
# =========================================================================


class LRUCache:
    """
    LRU (Least Recently Used) Cache con tamaño acotado.

    Inspirado en el bounded LRU pattern de Python functools.lru_cache.

    Útil para:
    - Cached de tokens Clerk (evita llamadas repetidas a la API)
    - Cached de resultados de LLM
    - Cached de resultados de HTTP

    Uso:
        cache = LRUCache(maxsize=1000, ttl=300)
        cache.set("token123", data)
        value = cache.get("token123")
        cache.delete("token123")
        cache.clear()
    """

    def __init__(self, maxsize: int = 1000, ttl: int = 3600):
        """
        Inicializar un LRUCache.

        Parámetros:
            maxsize: Capacidad máxima del cache
            ttl: Time-to-live en segundos (0 = infinito)
        """
        self._cache = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl

    def get(self, key: str, default=None):
        """
        Obtener un valor del cache.

        Devuelve None si:
        - No existe la clave
        - La entrada ha expirado

        Parámetros:
            key: Clave de la entrada
            default: Valor por defecto si no existe

        Retorna:
            El valor cached o default
        """
        if key not in self._cache:
            return default

        value, timestamp = self._cache[key]

        # Verificar expiración
        if self._ttl > 0 and time.time() - timestamp > self._ttl:
            self._cache.pop(key, None)
            return default

        # Mover al final (más reciente)
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value) -> None:
        """
        Guardar un valor en el cache.

        Si el cache está lleno, elimina el más antiguo (LRU).

        Parámetros:
            key: Clave de la entrada
            value: Valor a almacenar
        """
        if key in self._cache:
            # Actualizar valor existente
            self._cache.move_to_end(key)

        # Si está lleno, eliminar el más antiguo
        if len(self._cache) >= self._maxsize:
            self._cache.popitem(last=False)

        self._cache[key] = (value, time.time())

    def delete(self, key: str) -> bool:
        """
        Eliminar una entrada del cache.

        Parámetros:
            key: Clave a eliminar

        Retorna:
            True si se eliminó, False si no existía
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Limpiar todo el cache."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        return key in self._cache
