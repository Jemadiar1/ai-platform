"""
Tests para web_research_service.py

Cubre:
- SSRFBlocklist.is_safe_url()
- TenantRateLimiter.is_allowed() y record()
- WebResearchService (mocked HTTP calls)
"""

import datetime
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_platform.services.web_research_service import (
    SSRFBlocklist,
    BrowserResult,
    FetchResult,
    ResearchLevel,
    TenantRateLimiter,
    WebResearchService,
)


# =========================================================================
# SSRFBlocklist Tests
# =========================================================================


class TestSSRFBlocklist:
    """Tests para la protección SSRF."""

    def test_allow_http(self):
        """URLs HTTP/HTTPS seguras deben pasar."""
        safe, reason = SSRFBlocklist.is_safe_url("http://example.com")
        assert safe is True
        assert reason == ""

        safe, reason = SSRFBlocklist.is_safe_url("https://example.com/path?q=test")
        assert safe is True
        assert reason == ""

    def test_block_file_scheme(self):
        """Esquema file:// debe bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("file:///etc/passwd")
        assert safe is False
        assert "blocked_scheme" in reason

    def test_block_gopher_scheme(self):
        """Esquema gopher:// debe bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("gopher://evil.com")
        assert safe is False
        assert "blocked_scheme" in reason

    def test_block_localhost(self):
        """localhost debe bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("http://localhost")
        assert safe is False
        assert "blocked_host" in reason

        safe, reason = SSRFBlocklist.is_safe_url("http://localhost:8080")
        assert safe is False
        assert "blocked_host" in reason

    def test_block_private_ip_192(self):
        """IPs 192.168.x.x deben bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("http://192.168.1.1")
        assert safe is False
        assert "private_ip" in reason

    def test_block_private_ip_10(self):
        """IPs 10.x.x.x deben bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("http://10.0.0.1")
        assert safe is False
        assert "private_ip" in reason

    def test_block_private_ip_172(self):
        """IPs 172.16-31.x.x deben bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("http://172.16.0.1")
        assert safe is False
        assert "private_ip" in reason

        safe, reason = SSRFBlocklist.is_safe_url("http://172.31.255.255")
        assert safe is False
        assert "private_ip" in reason

    def test_block_cloud_metadata(self):
        """Cloud metadata endpoints deben bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("http://169.254.169.254/latest/meta-data/")
        assert safe is False
        assert "private_ip" in reason

        safe, reason = SSRFBlocklist.is_safe_url("http://metadata.google.internal")
        assert safe is False
        assert "blocked_host" in reason

    def test_block_internal_domains(self):
        """Dominios internos deben bloquearse."""
        # .localhost matches _BLOCKED_HOSTS first, so it gets "blocked_host"
        for domain, expected_reason in (
            (".internal", "internal_domain"),
            (".local", "internal_domain"),
            (".localhost", "blocked_host"),
            (".corp", "internal_domain"),
            (".home", "internal_domain"),
        ):
            safe, reason = SSRFBlocklist.is_safe_url(f"http://server{domain}")
            assert safe is False, f"Should block {domain}"
            assert expected_reason in reason

    def test_block_empty_url(self):
        """URL vacía debe bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("")
        assert safe is False
        assert reason == "empty_url"

        safe, reason = SSRFBlocklist.is_safe_url(None)
        assert safe is False

    def test_block_ipv6_loopback(self):
        """IPv6 loopback debe bloquearse."""
        safe, reason = SSRFBlocklist.is_safe_url("http://[::1]")
        assert safe is False
        assert "private_ip" in reason

    def test_allow_public_ip(self):
        """IPs públicas deben permitirse."""
        safe, reason = SSRFBlocklist.is_safe_url("http://8.8.8.8")
        assert safe is True
        assert reason == ""

        safe, reason = SSRFBlocklist.is_safe_url("https://142.250.80.46")
        assert safe is True
        assert reason == ""


# =========================================================================
# TenantRateLimiter Tests
# =========================================================================


class TestTenantRateLimiter:
    """Tests para el rate limiter por tenant."""

    def test_free_plan_limit(self):
        """Plan free: 10 fetch/min."""
        limiter = TenantRateLimiter()
        tenant_id = "test-tenant-free-limit"

        for i in range(10):
            allowed, remaining = limiter.is_allowed(tenant_id, ResearchLevel.FETCH, "free")
            assert allowed is True
            assert remaining == 10 - i
            # Simular el flujo real: is_allowed -> record
            limiter.record(tenant_id, ResearchLevel.FETCH)

        # El 11er request debe ser rechazado
        allowed, remaining = limiter.is_allowed(tenant_id, ResearchLevel.FETCH, "free")
        assert allowed is False
        assert remaining == 0

    def test_browser_blocked_on_free(self):
        """Plan free: browser debe estar bloqueado."""
        limiter = TenantRateLimiter()
        allowed, remaining = limiter.is_allowed("tenant", ResearchLevel.BROWSER, "free")
        assert allowed is False
        assert remaining == 0

    def test_starter_plan_limits(self):
        """Plan starter: 30 fetch/min, 2 browser/min."""
        limiter = TenantRateLimiter()
        tenant_id = "test-tenant-starter"

        allowed, _ = limiter.is_allowed(tenant_id, ResearchLevel.FETCH, "starter")
        assert allowed is True

        allowed, _ = limiter.is_allowed(tenant_id, ResearchLevel.BROWSER, "starter")
        assert allowed is True

    def test_records_consumes_quota(self):
        """record() debe consumir cuota."""
        limiter = TenantRateLimiter()
        tenant_id = "test-tenant-record"

        allowed1, rem1 = limiter.is_allowed(tenant_id, ResearchLevel.FETCH, "pro")
        assert allowed1 is True
        assert rem1 == 100

        limiter.record(tenant_id, ResearchLevel.FETCH)

        allowed2, rem2 = limiter.is_allowed(tenant_id, ResearchLevel.FETCH, "pro")
        assert allowed2 is True
        assert rem2 == 99

    def test_independent_tenants(self):
        """Tenants diferentes tienen cuotas independientes."""
        limiter = TenantRateLimiter()

        # Llenar quota de tenant A
        for _ in range(10):
            limiter.record("tenant-a", ResearchLevel.FETCH)

        # Tenant B debe tener quota intacta
        allowed, _ = limiter.is_allowed("tenant-b", ResearchLevel.FETCH, "free")
        assert allowed is True


# =========================================================================
# FetchResult / BrowserResult Tests
# =========================================================================


class TestResultDataclasses:
    """Tests para los dataclasses de resultado."""

    def test_fetch_result_to_dict(self):
        """FetchResult.to_dict() debe serializar todos los campos."""
        result = FetchResult(
            url="https://example.com",
            content="Hello",
            title="Example",
            source="https://example.com",
            fetch_date=datetime.datetime(2026, 5, 25, 10, 0, 0, tzinfo=datetime.timezone.utc),
            content_hash="abc123",
            status_code=200,
            cached=False,
            content_type="text/html",
            size_bytes=100,
            tenant_id="test-tenant",
            source_by="odin",
        )
        d = result.to_dict()
        assert d["url"] == "https://example.com"
        assert d["cached"] is False
        assert d["tenant_id"] == "test-tenant"
        assert d["status_code"] == 200

    def test_browser_result_to_dict(self):
        """BrowserResult.to_dict() debe serializar correctamente."""
        result = BrowserResult(
            url="https://example.com",
            screenshot_base64="iVBOR...",
            page_title="Example",
            final_url="https://example.com",
            content="<p>Hello</p>",
            fetch_date=datetime.datetime(2026, 5, 25, 10, 0, 0, tzinfo=datetime.timezone.utc),
            tenant_id="test-tenant",
            source_by="module",
        )
        d = result.to_dict()
        assert d["url"] == "https://example.com"
        assert d["screenshot_base64"] == "iVBOR..."
        assert d["error"] is None


# =========================================================================
# WebResearchService Tests
# =========================================================================


class TestWebResearchService:
    """Tests para WebResearchService (mocked HTTP)."""

    @pytest.fixture
    def service(self):
        """Crear instancia del servicio con cache y DB mockeados."""
        svc = WebResearchService()
        # Limpiar cache entre tests
        svc._cache.clear()
        return svc

    @pytest.mark.asyncio
    async def test_fetch_url_raises_on_ssrf(self, service):
        """fetch_url debe levantar ValueError para URLs SSRF."""
        with pytest.raises(ValueError, match="URL bloqueada"):
            await service.fetch_url(
                url="http://192.168.1.1/admin",
                tenant_id="test-tenant",
                source_by="odin",
            )

    @pytest.mark.asyncio
    async def test_fetch_url_raises_on_rate_limit(self, service):
        """fetch_url debe levantar ValueError cuando se excede rate limit."""
        # Llenar quota del rate_limiter del service
        for _ in range(10):
            service.rate_limiter.record("rate-limited-tenant", ResearchLevel.FETCH)

        with pytest.raises(ValueError, match="Límite de fetch"):
            with patch.object(service, "_get_tenant_plan", new_callable=AsyncMock, return_value="free"):
                await service.fetch_url(
                    url="https://example.com",
                    tenant_id="rate-limited-tenant",
                    source_by="odin",
                )

    @pytest.mark.asyncio
    async def test_fetch_url_success(self, service):
        """fetch_url debe devolver FetchResult con contenido extraído."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
        mock_response.headers.get.return_value = "text/html"
        mock_response.sizeof.return_value = 80

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.object(service, "_get_tenant_plan", new_callable=AsyncMock) as mock_plan:
                mock_plan.return_value = "pro"
                with patch.object(service, "_save_to_db") as mock_save:
                    with patch.object(service, "_log_usage_event") as mock_log:
                        result = await service.fetch_url(
                            url="https://example.com",
                            tenant_id="test-tenant",
                            source_by="odin",
                        )

                        assert isinstance(result, FetchResult)
                        assert result.url == "https://example.com"
                        assert result.status_code == 200
                        assert result.cached is False
                        assert result.source_by == "odin"
                        assert "Hello world" in result.content
                        assert result.content_hash  # Non-empty SHA-256

                        mock_save.assert_called_once()
                        mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_url_cache_hit(self, service):
        """fetch_url debe servir desde cache si existe."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<html><body>cached content</body></html>"
        mock_response.headers.get.return_value = "text/html"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        # Primera llamada - cache miss
        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.object(service, "_get_tenant_plan", new_callable=AsyncMock, return_value="pro"):
                with patch.object(service, "_save_to_db"):
                    with patch.object(service, "_log_usage_event"):
                        result1 = await service.fetch_url(
                            url="https://example.com/cached",
                            tenant_id="cache-tenant",
                            source_by="odin",
                        )
                        assert result1.cached is False

        # Segunda llamada - cache hit (sin hacer HTTP)
        with patch("httpx.AsyncClient") as mock_client_class:
            with patch.object(service, "_get_tenant_plan", new_callable=AsyncMock, return_value="pro"):
                result2 = await service.fetch_url(
                    url="https://example.com/cached",
                    tenant_id="cache-tenant",
                    source_by="odin",
                )
                assert result2.cached is True
                # El HTTP client nunca fue creado
                mock_client_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_browser_session_raises_on_ssrf(self, service):
        """browser_session debe levantar ValueError para URLs SSRF."""
        with pytest.raises(ValueError, match="URL bloqueada"):
            await service.browser_session(
                url="http://metadata.google.internal",
                tenant_id="test-tenant",
                source_by="odin",
            )

    @pytest.mark.asyncio
    async def test_browser_session_returns_error_on_failure(self, service):
        """browser_session debe devolver BrowserResult con error si falla."""
        with patch.object(service, "_get_tenant_plan", new_callable=AsyncMock, return_value="pro"):
            # Simular ImportError cuando playwright no está instalado
            with patch("playwright.async_api.async_playwright") as mock_pw:
                mock_pw.side_effect = ImportError("No module named 'playwright'")
                result = await service.browser_session(
                    url="https://example.com",
                    tenant_id="test-tenant",
                    source_by="odin",
                )
                assert isinstance(result, BrowserResult)
                assert result.error is not None
                assert result.error == "Playwright no está instalado"
