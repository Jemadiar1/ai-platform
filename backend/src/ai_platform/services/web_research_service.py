"""
Servicio de investigación web para la plataforma.

Provee dos niveles:
- fetch_url/search: HTTP GET seguro, extracción de contenido, cache, rate limiting.
- browser_session: Playwright headless para JS, screenshots, interacción.

Es un servicio interno: no es un módulo vendible. Lo usan otros módulos
para investigar fuentes externas de forma segura y trazable.

Multi-tenant: todos los resultados se asocian a tenant_id.
"""

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from sqlalchemy import select

from ai_platform.core.config import get_settings
from ai_platform.database import make_session
from ai_platform.models.db import Tenant, UsageEvent, WebResearchResult

logger = logging.getLogger(__name__)


# =========================================================================
# Enumeraciones y Data Classes
# =========================================================================


class ResearchLevel(str, Enum):
    """Nivel de investigación web."""

    FETCH = "fetch"
    BROWSER = "browser"


@dataclass
class FetchResult:
    """Resultado de fetch_url o fetch_search."""

    url: str
    content: str
    title: str
    source: str
    fetch_date: datetime
    content_hash: str
    status_code: int
    cached: bool
    content_type: str
    size_bytes: int
    tenant_id: str
    source_by: str
    task_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "content": self.content,
            "title": self.title,
            "source": self.source,
            "fetch_date": self.fetch_date.isoformat(),
            "content_hash": self.content_hash,
            "status_code": self.status_code,
            "cached": self.cached,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "tenant_id": str(self.tenant_id),
            "source_by": self.source_by,
        }


@dataclass
class BrowserResult:
    """Resultado de una sesión de browser (Playwright)."""

    url: str
    screenshot_base64: str | None
    page_title: str
    final_url: str
    content: str | None
    fetch_date: datetime
    tenant_id: str
    source_by: str
    task_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "screenshot_base64": self.screenshot_base64,
            "page_title": self.page_title,
            "final_url": self.final_url,
            "fetch_date": self.fetch_date.isoformat(),
            "tenant_id": str(self.tenant_id),
            "source_by": self.source_by,
            "error": self.error,
        }


# =========================================================================
# SSRF Protection
# =========================================================================


class SSRFBlocklist:
    """
    Protección contra SSRF (Server-Side Request Forgery).

    Bloquea:
    - Esquemas peligrosos: file://, gopher://, dict://, ssh://, etc.
    - Direcciones IP privadas: 10.x, 172.16-31.x, 192.168.x, 127.x
    - Metadata endpoints de cloud: 169.254.169.254
    - Direcciones link-local y de loopback
    - Dominios .internal, .local, .localhost
    - IPv6 equivalentes (::1, ::ffff:127.0.0.1, etc.)
    """

    _PRIVATE_NETWORKS = [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "0.0.0.0/8",
        "100.64.0.0/10",
        "::1/128",
        "::ffff:127.0.0.0/104",
        "fc00::/7",
        "fe80::/10",
    ]

    _BLOCKED_SCHEMES = {"file", "gopher", "dict", "ssh", "ftp", "telnet", "ldap", "mailto"}
    _BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata.aws.internal"}

    @classmethod
    def is_safe_url(cls, url: str) -> tuple[bool, str]:
        """
        Verificar si una URL es segura para fetch.

        Retorna:
            (is_safe, reason) - reason vacío si es segura
        """
        if not url or not isinstance(url, str):
            return False, "empty_url"

        url = url.strip()

        try:
            parsed = urlparse(url)
        except Exception:
            return False, "invalid_url"

        # 1. Bloquear esquemas peligrosos
        if parsed.scheme.lower() in cls._BLOCKED_SCHEMES:
            return False, f"blocked_scheme:{parsed.scheme}"

        # 2. Solo permitir http/https
        if parsed.scheme not in ("http", "https"):
            return False, f"disallowed_scheme:{parsed.scheme}"

        # 3. Bloquear hosts sin dominio
        host = parsed.hostname or ""
        if not host:
            return False, "no_hostname"

        # 4. Bloquear hosts por nombre
        host_lower = host.lower()
        for blocked in cls._BLOCKED_HOSTS:
            if host_lower == blocked or host_lower.endswith("." + blocked):
                return False, f"blocked_host:{host}"

        # 5. Bloquear dominios internos
        for suffix in (".internal", ".local", ".localhost", ".corp", ".home"):
            if host_lower.endswith(suffix):
                return False, f"internal_domain:{host}"

        # 6. Bloquear IPs privadas
        import ipaddress

        try:
            ip = ipaddress.ip_address(host)
            for network in cls._PRIVATE_NETWORKS:
                if ip in ipaddress.ip_network(network, strict=False):
                    return False, f"private_ip:{host}"
        except ValueError:
            pass

        return True, ""


# =========================================================================
# Rate Limiter por Tenant
# =========================================================================


class TenantRateLimiter:
    """
    Rate limiter por tenant usando ventana deslizante en memoria.

    Cada tenant tiene un límite de requests por minuto.
    Los límites se escalan por plan:

    | Plan       | Fetch/min | Browser/min |
    |------------|-----------|-------------|
    | free       | 10        | 0           |
    | starter    | 30        | 2           |
    | pro        | 100       | 10          |
    | enterprise | 500       | 50          |
    """

    LIMITS: dict[str, dict[str, int]] = {
        "free": {"fetch": 10, "browser": 0},
        "starter": {"fetch": 30, "browser": 2},
        "pro": {"fetch": 100, "browser": 10},
        "enterprise": {"fetch": 500, "browser": 50},
    }

    def __init__(self) -> None:
        self._timestamps: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, tenant_id: str, level: ResearchLevel, plan: str = "free") -> tuple[bool, int]:
        """
        Verificar si un tenant puede hacer una request.

        Retorna:
            (allowed, remaining_requests)
        """
        limits = self.LIMITS.get(plan, self.LIMITS["free"])
        max_requests = limits.get(level.value, 0)

        if max_requests == 0:
            return False, 0

        with self._lock:
            now = time.time()
            window = 60.0

            if tenant_id not in self._timestamps:
                self._timestamps[tenant_id] = []

            self._timestamps[tenant_id] = [ts for ts in self._timestamps[tenant_id] if ts > now - window]

            current_count = len(self._timestamps[tenant_id])
            remaining = max(0, max_requests - current_count)

            if remaining <= 0:
                return False, 0

            return True, remaining

    def record(self, tenant_id: str, level: ResearchLevel) -> None:
        """Registrar una request consumida."""
        with self._lock:
            if tenant_id not in self._timestamps:
                self._timestamps[tenant_id] = []
            self._timestamps[tenant_id].append(time.time())


# =========================================================================
# Service Principal
# =========================================================================


class WebResearchService:
    """
    Servicio de investigación web.

    NIVEL 1 - fetch_url / fetch_search:
        HTTP GET seguro con protección SSRF, extracción HTML->Markdown,
        cache por tenant+URL, rate limiting, y registro persistente.

    NIVEL 2 - browser_session:
        Playwright headless para páginas con JS, screenshots,
        interacción con formularios. Cada sesión está aislada.

    Uso desde módulos:
        from ai_platform.services.web_research_service import web_research_service
        result = web_research_service.fetch_url(
            url="https://example.com",
            tenant_id=tenant_id,
            source_by="ai-content"
        )
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.rate_limiter = TenantRateLimiter()

        self.max_content_size = 500_000
        self.max_download_size = 5_000_000
        self.request_timeout = 15.0
        self.browser_timeout = 30_000

        # Cache en memoria (LRU)
        self._cache: dict[str, tuple[FetchResult, float]] = {}
        self._cache_maxsize = 1000
        self._cache_ttl = 3600
        self._cache_lock = threading.Lock()

    async def fetch_url(
        self,
        url: str,
        tenant_id: str,
        source_by: str,
        task_id: str | None = None,
        force_refresh: bool = False,
    ) -> FetchResult:
        """
        Nivel 1: Fetch seguro de una URL.

        Flujo:
        1. Validar URL (SSRF protection)
        2. Verificar rate limit por tenant
        3. Verificar cache (tenant_id + url)
        4. HTTP GET con timeout y size limit
        5. Extraer contenido (HTML -> Markdown)
        6. Guardar en cache y BD
        7. Registrar usage event
        """
        # 1. Validar URL (SSRF)
        is_safe, reason = SSRFBlocklist.is_safe_url(url)
        if not is_safe:
            logger.warning(f"SSRF blocked: url={url} reason={reason} tenant_id={tenant_id}")
            raise ValueError(f"URL bloqueada por seguridad: {reason}")

        # 2. Rate limiting
        plan = await self._get_tenant_plan(tenant_id)
        allowed, _ = self.rate_limiter.is_allowed(tenant_id, ResearchLevel.FETCH, plan)
        if not allowed:
            raise ValueError(f"Límite de fetch excedido para tenant. Plan: {plan}")
        self.rate_limiter.record(tenant_id, ResearchLevel.FETCH)

        # 3. Cache check
        cache_key = self._make_cache_key(tenant_id, url)
        if not force_refresh:
            cached = self._get_cached(cache_key)
            if cached:
                logger.info(f"Cache hit: url={url} tenant_id={tenant_id}")
                cached.cached = True
                return cached

        # 4. HTTP GET
        result = await self._safe_http_get(url)

        # 5. Extraer contenido
        title, markdown_content = self._extract_markdown(result.content, result.content_type)

        # 5b. Enforce max_content_size on processed content
        if len(markdown_content) > self.max_content_size:
            raise ValueError(
                f"Contenido demasiado grande después de procesar: {len(markdown_content)} bytes (máx: {self.max_content_size})"
            )

        # 6. Construir resultado
        content_hash = hashlib.sha256(markdown_content.encode()).hexdigest()
        fetch_result = FetchResult(
            url=url,
            content=markdown_content,
            title=title,
            source=url,
            fetch_date=datetime.now(UTC),
            content_hash=content_hash,
            status_code=result.status_code,
            cached=False,
            content_type=result.content_type,
            size_bytes=result.size_bytes,
            tenant_id=tenant_id,
            source_by=source_by,
            task_id=task_id,
        )

        # 7. Guardar en cache y BD
        self._set_cached(cache_key, fetch_result)
        self._save_to_db(fetch_result)
        self._log_usage_event(fetch_result, task_id)

        logger.info(f"fetch_completed: url={url} tenant_id={tenant_id} size={len(markdown_content)} cached=False")
        return fetch_result

    async def fetch_search(
        self,
        query: str,
        tenant_id: str,
        source_by: str,
        task_id: str | None = None,
        max_results: int = 5,
    ) -> list[FetchResult]:
        """
        Nivel 1: Búsqueda web simulada.

        Hace fetch de resultados de búsqueda pública y extrae los primeros
        resultados como Markdown.
        """
        search_url = f"https://html.duckduckgo.com/html/?q={query}"
        results = []

        resp = await self._safe_http_get(search_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        result_urls = []
        for row in soup.select("result"):
            link_el = row.select_one("a.result-a")
            if link_el and link_el.get("href"):
                link = link_el["href"]
                result_urls.append(link)
            if len(result_urls) >= max_results:
                break

        for url in result_urls[:max_results]:
            try:
                result = await self.fetch_url(
                    url=url,
                    tenant_id=tenant_id,
                    source_by=source_by,
                    task_id=task_id,
                    force_refresh=True,
                )
                results.append(result)
            except Exception as e:
                logger.warning(f"Search result fetch failed: url={url} error={e!s}")

        return results

    async def browser_session(
        self,
        url: str,
        tenant_id: str,
        source_by: str,
        task_id: str | None = None,
        take_screenshot: bool = False,
        extract_content: bool = True,
        wait_for_selector: str | None = None,
        timeout_ms: int | None = None,
    ) -> BrowserResult:
        """
        Nivel 2: Sesión de browser headless con Playwright.

        Uso:
            result = await web_research_service.browser_session(
                url="https://example.com/js-page",
                tenant_id=tenant_id,
                source_by="ai-content",
                take_screenshot=True,
            )
        """
        # Validar URL
        is_safe, reason = SSRFBlocklist.is_safe_url(url)
        if not is_safe:
            raise ValueError(f"URL bloqueada por seguridad: {reason}")

        # Rate limit
        plan = await self._get_tenant_plan(tenant_id)
        allowed, _ = self.rate_limiter.is_allowed(tenant_id, ResearchLevel.BROWSER, plan)
        if not allowed:
            raise ValueError(f"Límite de browser excedido para tenant. Plan: {plan}")
        self.rate_limiter.record(tenant_id, ResearchLevel.BROWSER)

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 720},
                        user_agent=("Mozilla/5.0 (compatible; NeuralCrewBot/1.0; +https://neurialcrew.com/bot)"),
                        ignore_https_errors=False,
                    )

                    page = context.new_page()
                    page.set_default_timeout(timeout_ms or self.browser_timeout)

                    response = await page.goto(url, wait_until="domcontentloaded")

                    if wait_for_selector:
                        try:
                            await page.wait_for_selector(wait_for_selector, timeout=10_000)
                        except Exception:
                            logger.warning(f"Selector timeout: selector={wait_for_selector} url={url}")

                    screenshot_b64 = None
                    if take_screenshot:
                        screenshot_b64 = await page.screenshot(type="jpeg", quality=60)

                    page_content = None
                    if extract_content:
                        html = await page.content()
                        _, page_content = self._extract_markdown(html, "text/html")

                    return BrowserResult(
                        url=url,
                        screenshot_base64=screenshot_b64,
                        page_title=page.title(),
                        final_url=page.url,
                        content=page_content,
                        fetch_date=datetime.now(UTC),
                        tenant_id=tenant_id,
                        source_by=source_by,
                        task_id=task_id,
                    )
                except Exception as e:
                    logger.error(f"Browser session failed: url={url} error={e}")
                    return BrowserResult(
                        url=url,
                        screenshot_base64=None,
                        page_title="",
                        final_url=url,
                        content=None,
                        fetch_date=datetime.now(UTC),
                        tenant_id=tenant_id,
                        source_by=source_by,
                        task_id=task_id,
                        error=str(e),
                    )
                finally:
                    await browser.close()

        except ImportError:
            logger.error(f"Playwright not installed: url={url}")
            return BrowserResult(
                url=url,
                screenshot_base64=None,
                page_title="",
                final_url=url,
                content=None,
                fetch_date=datetime.now(UTC),
                tenant_id=tenant_id,
                source_by=source_by,
                task_id=task_id,
                error="Playwright no está instalado",
            )

    # =========================================================================
    # Internals
    # =========================================================================

    async def _safe_http_get(self, url: str) -> "_HTTPResponse":
        """HTTP GET seguro con todas las protecciones."""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.request_timeout),
            follow_redirects=True,
            max_redirects=3,
            headers={
                "User-Agent": "NeuralCrewBot/1.0 (+https://neurialcrew.com/bot)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            },
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            body = response.content
            if len(body) > self.max_download_size:
                raise ValueError(f"Contenido demasiado grande: {len(body)} bytes (máx: {self.max_download_size})")

            return _HTTPResponse(
                status_code=response.status_code,
                content=body,
                content_type=response.headers.get("content-type", ""),
                size_bytes=len(body),
            )

    @staticmethod
    def _extract_markdown(html: str, content_type: str) -> tuple[str, str]:
        """Extraer título y contenido Markdown de HTML."""
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        markdown_content = md(
            str(soup),
            heading_style="ATX",
            strip=["img"],
        )

        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content).strip()

        return title, markdown_content

    # =========================================================================
    # Cache
    # =========================================================================

    @staticmethod
    def _make_cache_key(tenant_id: str, url: str) -> str:
        """Crear clave de cache: SHA-256(tenant_id + url)."""
        raw = f"{tenant_id}:{url}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> FetchResult | None:
        """Obtener resultado cached si existe y no expiró."""
        with self._cache_lock:
            if cache_key not in self._cache:
                return None

            result, timestamp = self._cache[cache_key]
            if time.time() - timestamp > self._cache_ttl:
                del self._cache[cache_key]
                return None

            return result

    def _set_cached(self, cache_key: str, result: FetchResult) -> None:
        """Guardar en cache LRU."""
        with self._cache_lock:
            if len(self._cache) >= self._cache_maxsize:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

            self._cache[cache_key] = (result, time.time())

    # =========================================================================
    # DB & Usage
    # =========================================================================

    def _save_to_db(self, result: FetchResult) -> None:
        """Guardar resultado en PostgreSQL."""
        with make_session() as db:
            record = WebResearchResult(
                tenant_id=result.tenant_id,
                url=result.url,
                title=result.title,
                content=result.content,
                content_hash=result.content_hash,
                status_code=result.status_code,
                content_type=result.content_type,
                size_bytes=result.size_bytes,
                fetch_date=result.fetch_date,
                source_by=result.source_by,
                task_id=result.task_id,
            )
            db.add(record)
            db.commit()

    def _log_usage_event(self, result: FetchResult, task_id: str | None) -> None:
        """Registrar usage event para billing/observabilidad."""
        with make_session() as db:
            event = UsageEvent(
                tenant_id=result.tenant_id,
                task_id=task_id,
                module="web_research",
                event_type="url_fetch" if not task_id else "module_web_research",
                tokens_used=0,
                cost_usd=0.0,
                extra_data={
                    "url": result.url,
                    "content_size": result.size_bytes,
                    "cached": result.cached,
                    "status_code": result.status_code,
                },
            )
            db.add(event)
            db.commit()

    async def _get_tenant_plan(self, tenant_id: str) -> str:
        """Obtener plan del tenant desde BD."""
        with make_session() as db:
            stmt = select(Tenant).where(Tenant.id == tenant_id)
            tenant = db.execute(stmt).scalar_one_or_none()
            return tenant.plan if tenant else "free"


# Response helper internal
@dataclass
class _HTTPResponse:
    status_code: int
    content: bytes
    content_type: str
    size_bytes: int


# Instancia global singleton
web_research_service = WebResearchService()
