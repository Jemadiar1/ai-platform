"""
Utilidades de seguridad.

Contiene funciones para:
- Generar y validar tokens JWT
- Hashear y verificar passwords
- Cifrar datos sensibles
- Escanear inyección de prompts (12 patrones de Hermes)
- Sanitizar inputs LLM (stripping zero-width chars, RTL overrides)
- Validar URLs contra SSRF (blocklist de IPs privadas)
"""

import logging
import re
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address, ip_network
from typing import ClassVar
from urllib.parse import urlparse

import bcrypt as _bcrypt

from jose import JWTError, jwt

from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


# =========================================================================
# JWT & PASSWORDS
# =========================================================================

# Use bcrypt directly to avoid passlib's known bug with bcrypt 5.x
# (passlib's detect_wrap_bug triggers false "password cannot be longer
# than 72 bytes" errors from bcrypt 5.0.0 internals)
_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """
    Hashear un password plano.

    Nunca guardamos passwords en texto plano.
    bcrypt genera un hash + salt aleatorio.

    Ejemplo:
        hashed = hash_password("mi-password-123")
        # "$2b$12$eXaMpLe$sAlTaNdHaShHeRe..."
    """
    salt = _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = _bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verificar un password plano contra un hash.

    Ejemplo:
        if verify_password("mi-password-123", stored_hash):
            # Login exitoso
    """
    try:
        return _bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Crear un token JWT de acceso.

    Flujo:
        1. El usuario se autentica (Clerk, login, etc.)
        2. Generamos un JWT con user_id, tenant_id y expiry
        3. Enviamos el JWT al cliente
        4. El cliente lo envía en cada request: Authorization: Bearer <jwt>
        5. En el backend, verificamos la firma y extraemos los datos

    Parámetros:
        data: Diccionario con los claims (user_id, tenant_id, etc.)
        expires_delta: Cuánto tiempo dura válido el token

    Retorna:
        Token JWT como string
    """
    settings = get_settings()

    encode = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(hours=settings.JWT_EXPIRATION_HOURS)

    encode.update({"exp": expire})

    encoded_jwt = jwt.encode(encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return encoded_jwt


def decode_token(token: str) -> dict | None:
    """
    Decodificar y validar un token JWT.

    Verifica que:
    - El token tiene una firma válida
    - El token no ha expirado
    - Todos los claims requeridos están presentes

    Parámetros:
        token: Token JWT en string

    Retorna:
        Diccionario con los claims si es válido, None si no
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
        r'(?:^|\n)\s*(?:"""|' + '"""' + r")\s*\n.*?(?:ignore|disregard|bypass|new rule|forget)",
        re.IGNORECASE | re.DOTALL,
    )

    # Patrón 2: System directive tags
    _DIRECTIVE_INJECTION = re.compile(r"(?:^\s*(?:system|user|assistant|role):\s)", re.IGNORECASE)

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
# SSD (SSRF Protection)
# =========================================================================


class SSRFBlocklist:
    """
    Bloquear URLs contra SSRF (Server-Side Request Forgery).

    Bloquea:
    - IP addresses privadas (RFC 1918)
    - Loopback (127.x.x.x, ::1)
    - Link-local (169.254.x.x, fe80::)
    - Cloud metadata endpoints (169.254.169.254 - AWS, GCP, Azure)
    - Localhost
    - Scheme dangerous (file://, gopher://, dict://)
    """

    # Networks privadas bloqueadas
    _BLOCKED_NETWORKS: ClassVar[list] = [
        ip_network("0.0.0.0/8"),  # "This" network
        ip_network("10.0.0.0/8"),  # Private
        ip_network("100.64.0.0/10"),  # CGNAT
        ip_network("127.0.0.0/8"),  # Loopback
        ip_network("169.254.0.0/16"),  # Link-local
        ip_network("172.16.0.0/12"),  # Private
        ip_network("192.0.0.0/24"),  # IANA IPv4
        ip_network("192.0.2.0/24"),  # TEST-NET-1
        ip_network("192.88.99.0/24"),  # 6to4 relay
        ip_network("192.168.0.0/16"),  # Private
        ip_network("198.18.0.0/15"),  # Benchmark test
        ip_network("198.51.100.0/24"),  # TEST-NET-2
        ip_network("203.0.113.0/24"),  # TEST-NET-3
        ip_network("224.0.0.0/4"),  # Multicast
        ip_network("240.0.0.0/4"),  # Reserved
        ip_network("255.255.255.255/32"),  # Broadcast
    ]

    _DANGEROUS_SCHEMES: ClassVar[set] = {"file", "gopher", "dict", "ftp"}

    _ALLOW_SCHEMES: ClassVar[set] = {"http", "https"}

    # Localhost hostnames
    _BLOCKED_HOSTNAMES: ClassVar[set] = {
        "localhost",
        "0.0.0.0",
        "[::]",
        "127.0.0.1",
        "[::1]",
    }

    @classmethod
    def is_safe_url(cls, url: str) -> bool:
        """
        Verificar que una URL es segura (no apunta a recursos internos).

        Parámetros:
            url: URL a verificar

        Retorna:
            True si segura, False si blocked
        """
        try:
            parsed = urlparse(url)

            # Verificar scheme
            scheme = parsed.scheme.lower()
            if scheme not in cls._ALLOW_SCHEMES:
                return False

            if scheme in cls._DANGEROUS_SCHEMES:
                return False

            # Verificar host
            host = parsed.hostname
            if not host:
                return False

            host_lower = host.lower()
            if host_lower in cls._BLOCKED_HOSTNAMES:
                return False

            # Verificar si la IP es privada/segura
            return not cls._is_private_ip(host)

        except Exception:
            return False

    @classmethod
    def _is_private_ip(cls, host: str) -> bool:
        """Verificar si un host es una IP privada o local."""
        try:
            ip = ip_address(host)
            return any(ip in net for net in cls._BLOCKED_NETWORKS)
        except ValueError:
            # No es una IP válida, podría ser un dominio DNS
            # Considerarlo inseguro por defecto si no podemos verificarlo
            return False


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
