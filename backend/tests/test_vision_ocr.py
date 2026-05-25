"""
Tests para vision_ocr.py

Cubre:
- VisionOCRService._validate_image
- VisionOCRService._preprocess_pipeline
- VisionOCRService._run_tesseract (mocked)
- VisionOCRService._detect_charts
- VisionOCRService._generate_warnings
"""

from unittest.mock import MagicMock, patch

import pytest

from ai_platform.services.vision_ocr import VisionOCRService, OCRAnalysisResult


# =========================================================================
# Test fixtures
# =========================================================================


def _make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Crear imagen PNG de prueba."""
    from PIL import Image
    import io

    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def _make_jpg_bytes(width: int = 100, height: int = 100) -> bytes:
    """Crear imagen JPG de prueba."""
    from PIL import Image
    import io

    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
def service():
    """Crear instancia del servicio."""
    return VisionOCRService()


# =========================================================================
# Validate image Tests
# =========================================================================


class TestValidateImage:
    """Tests para validación de imágenes."""

    def test_accept_png(self, service):
        """PNG debe ser aceptado."""
        result = service._validate_image(_make_png_bytes())
        assert result["format"] == "PNG"

    def test_accept_jpg(self, service):
        """JPG debe ser aceptado."""
        result = service._validate_image(_make_jpg_bytes())
        assert result["format"] == "JPEG"

    def test_reject_gif(self, service):
        """GIF debe ser rechazado."""
        from PIL import Image
        import io

        img = Image.new("RGB", (100, 100))
        buf = io.BytesIO()
        img.save(buf, format="GIF")
        buf.seek(0)

        with pytest.raises(ValueError, match="no soportado"):
            service._validate_image(buf.getvalue())

    def test_reject_empty_bytes(self, service):
        """Bytes vacíos deben ser rechazados."""
        with pytest.raises(ValueError):
            service._validate_image(b"")

    def test_returns_dimensions(self, service):
        """Debe retornar dimensiones de la imagen."""
        result = service._validate_image(_make_png_bytes(200, 150))
        assert result["width"] == 200
        assert result["height"] == 150


# =========================================================================
# Preprocess pipeline Tests
# =========================================================================


class TestPreprocessPipeline:
    """Tests para el pipeline de preprocesamiento."""

    def test_preprocess_returns_bytes(self, service):
        """Debe retornar bytes procesados."""
        result = service._preprocess_pipeline(_make_png_bytes(), "PNG")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_preprocess_handles_jpeg(self, service):
        """Debe procesar imágenes JPEG."""
        result = service._preprocess_pipeline(_make_jpg_bytes(), "JPEG")
        assert isinstance(result, bytes)


# =========================================================================
# Run Tesseract Tests (mocked)
# =========================================================================


class TestRunTesseract:
    """Tests para ejecución de Tesseract (mocked)."""

    def test_tesseract_returns_text_and_confidence(self, service):
        """Debe retornar texto y confianza."""
        mock_data = {
            "text": ["Hello", "world"],
            "conf": [95, 90],
        }

        with patch("pytesseract.image_to_data", return_value=mock_data):
            text, confidence = service._run_tesseract(_make_png_bytes())

            assert text == "Hello world"
            assert confidence == 0.925  # (95 + 90) / 2 / 100

    def test_tesseract_handles_empty(self, service):
        """Debe manejar texto vacío."""
        mock_data = {"text": [""], "conf": [0]}

        with patch("pytesseract.image_to_data", return_value=mock_data):
            text, confidence = service._run_tesseract(_make_png_bytes())
            assert text == ""
            assert confidence == 0.0

    def test_tesseract_returns_zero_on_error(self, service):
        """Debe retornar (0, 0) si Tesseract falla."""
        with patch("pytesseract.image_to_data", side_effect=Exception("Tesseract not found")):
            text, confidence = service._run_tesseract(_make_png_bytes())
            assert text == ""
            assert confidence == 0.0


# =========================================================================
# Chart Detection Tests
# =========================================================================


class TestChartDetection:
    """Tests para detección de gráficos."""

    def test_chart_detection_returns_list(self, service):
        """Debe retornar lista (puede estar vacía)."""
        result = service._detect_charts(_make_png_bytes())
        assert isinstance(result, list)

    def test_chart_detection_no_crash_on_missing_cv2(self, service):
        """No debe crashar si opencv no está disponible."""
        with patch.dict("sys.modules", {"cv2": None, "numpy": None}):
            result = service._detect_charts(_make_png_bytes())
            assert isinstance(result, list)


# =========================================================================
# Warnings Tests
# =========================================================================


class TestWarnings:
    """Tests para generación de advertencias."""

    def test_low_confidence_warning(self, service):
        """Confianza < 0.3 debe generar advertencia."""
        warnings = service._generate_warnings(0.2, [], "PNG")
        assert len(warnings) >= 1
        assert any("baja confianza" in w.lower() for w in warnings)

    def test_medium_confidence_warning(self, service):
        """Confianza 0.3-0.6 debe generar advertencia moderada."""
        warnings = service._generate_warnings(0.5, [], "PNG")
        assert len(warnings) >= 1
        assert any("moderada" in w.lower() for w in warnings)

    def test_high_confidence_no_warning(self, service):
        """Confianza > 0.6 no debe generar advertencia de confianza."""
        warnings = service._generate_warnings(0.9, [], "PNG")
        confidence_warnings = [w for w in warnings if "confianza" in w.lower() or "confidence" in w.lower()]
        assert len(confidence_warnings) == 0

    def test_jpeg_compression_warning(self, service):
        """Fuente JPEG debe generar advertencia de compresión."""
        warnings = service._generate_warnings(0.9, [], "JPEG")
        assert any("jpeg" in w.lower() or "compresión" in w.lower() or "compression" in w.lower() for w in warnings)

    def test_chart_low_confidence_warning(self, service):
        """Gráfico con baja confianza debe generar advertencia."""
        charts = [{"type": "bar", "confidence": 0.3}]
        warnings = service._generate_warnings(0.9, charts, "PNG")
        assert any("gráfico" in w.lower() or "chart" in w.lower() for w in warnings)


# =========================================================================
# OCRAnalysisResult Tests
# =========================================================================


class TestOCRAnalysisResult:
    """Tests para el dataclass de resultado."""

    def test_to_dict_includes_all_fields(self):
        """to_dict() debe incluir todos los campos."""
        result = OCRAnalysisResult(
            text="Hello world",
            confidence=0.85,
            engine="tesseract",
            charts=[{"type": "bar"}],
            warnings=["test warning"],
            storage_id="test-uuid",
        )
        d = result.to_dict()
        assert d["text"] == "Hello world"
        assert d["confidence"] == 0.85
        assert d["engine"] == "tesseract"
        assert d["charts"] == [{"type": "bar"}]
        assert d["warnings"] == ["test warning"]
        assert d["storage_id"] == "test-uuid"

    def test_to_dict_with_defaults(self):
        """to_dict() debe incluir campos default vacíos."""
        result = OCRAnalysisResult(text="test", confidence=0.5, engine="tesseract")
        d = result.to_dict()
        assert d["charts"] == []
        assert d["warnings"] == []
        assert d["storage_id"] is None
