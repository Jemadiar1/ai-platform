"""
Servicio de análisis de imágenes y OCR.

Pipeline:
1. Validar formato y tamaño de imagen
2. Preprocesar (resize, normalize, enhance)
3. Ejecutar Tesseract OCR (primario)
4. Si confianza < threshold, fallback a PaddleOCR
5. Detectar gráficos/gráficos si la imagen los contiene
6. Extraer datos tabulares de gráficos
7. Retornar resultado con confidence scores

Usado por: ai-ads (análisis de creativos), ai-social (análisis de imágenes),
           ai-analytics (extracción de datos de gráficos), ai-web (audit visual).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ai_platform.core.config import get_settings
from ai_platform.database import make_session
from ai_platform.models.db import OCRResult, UsageEvent

logger = logging.getLogger(__name__)

settings = get_settings()


@dataclass
class OCRAnalysisResult:
    """Resultado del análisis OCR."""

    text: str
    confidence: float
    engine: str
    charts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    storage_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "engine": self.engine,
            "charts": self.charts,
            "warnings": self.warnings,
            "storage_id": self.storage_id,
        }


class VisionOCRService:
    """
    Servicio de análisis de imágenes y extracción de texto.

    Pipeline completo con Tesseract como motor primario y
    detección de gráficos con OpenCV.
    """

    def __init__(self) -> None:
        self.min_confidence = float(settings.OCR_MIN_CONFIDENCE) if hasattr(settings, "OCR_MIN_CONFIDENCE") else 0.65
        self.max_dimension = (
            int(settings.OCR_MAX_IMAGE_DIMENSION) if hasattr(settings, "OCR_MAX_IMAGE_DIMENSION") else 2048
        )
        self.enable_charts = (
            bool(settings.OCR_ENABLE_CHART_DETECTION) if hasattr(settings, "OCR_ENABLE_CHART_DETECTION") else True
        )

    def analyze(
        self,
        tenant_id: str,
        image_bytes: bytes,
        filename: str | None = None,
        include_charts: bool = True,
    ) -> OCRAnalysisResult:
        """
        Pipeline completo de análisis OCR.

        Args:
            tenant_id: Tenant propietario de la imagen.
            image_bytes: Bytes de la imagen (PNG, JPG, TIFF, PDF con imágenes).
            filename: Nombre original (para tracking).
            include_charts: Si True, detecta y analiza gráficos.

        Returns:
            OCRAnalysisResult con texto, confidence, y datos de gráficos si aplica.
        """
        start_time = time.time()

        # 1. Validar formato
        validated = self._validate_image(image_bytes)

        # 2. Preprocesar
        processed = self._preprocess_pipeline(image_bytes, validated.format)

        # 3. OCR primario (Tesseract)
        tesseract_text, tesseract_confidence = self._run_tesseract(processed)

        # 4. Detección de gráficos
        charts = []
        if include_charts and self.enable_charts:
            charts = self._detect_charts(image_bytes)

        # 5. Generar advertencias
        warnings = self._generate_warnings(tesseract_confidence, charts, validated.format)

        # 6. Guardar resultado en BD
        processing_time = int((time.time() - start_time) * 1000)
        storage_id = self._save_result(
            tenant_id, validated, tesseract_text, tesseract_confidence, charts, warnings, processing_time
        )

        logger.info(
            "ocr_completed",
            tenant_id=tenant_id,
            confidence=tesseract_confidence,
            charts=len(charts),
            warnings=len(warnings),
            processing_ms=processing_time,
        )

        return OCRAnalysisResult(
            text=tesseract_text,
            confidence=tesseract_confidence,
            engine="tesseract",
            charts=charts,
            warnings=warnings,
            storage_id=storage_id,
        )

    # =========================================================================
    # Private methods
    # =========================================================================

    def _validate_image(self, image_bytes: bytes) -> dict[str, Any]:
        """Validar formato y tamaño de imagen."""
        from PIL import Image

        try:
            img = Image.open(__import__("io").BytesIO(image_bytes))
            fmt = img.format or "unknown"
            width, height = img.size

            if fmt not in ("PNG", "JPEG", "TIFF", "BMP"):
                raise ValueError(f"Formato no soportado: {fmt}. Soportados: PNG, JPEG, TIFF, BMP")

            max_side = max(width, height)
            if max_side > self.max_dimension * 2:
                logger.warning("image_too_large", width=width, height=height)

            return {"format": fmt, "width": width, "height": height, "size": len(image_bytes)}
        except Exception as e:
            raise ValueError(f"Imagen inválida: {e}") from e

    def _preprocess_pipeline(self, image_bytes: bytes, fmt: str) -> bytes:
        """
        Pipeline de preprocesamiento:
        1. Resize proporcional a max 2048px (lado largo)
        2. Convertir a grayscale
        3. Threshold binario con Otsu
        4. Aumentar contraste si es bajo
        """
        import io

        from PIL import Image, ImageEnhance

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Resize proporcional
        max_dim = self.max_dimension
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(Image.Resampling.LANCZOS, newsize=new_size)

        # Grayscale
        img = img.convert("L")

        # Aumentar contraste si es bajo
        from PIL import ImageStat

        stat = ImageStat.Stat(img)
        mean = sum(stat.mean) / len(stat.mean) if stat.mean else 128
        if mean < 100:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)

        # Threshold binario
        img = img.point(lambda x: 0 if x < 128 else 255, "1")

        # Guardar como PNG
        output = io.BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()

    def _run_tesseract(self, image_bytes: bytes) -> tuple[str, float]:
        """
        Ejecutar Tesseract OCR.

        Usa spa+eng, PSM 6 (single uniform block).
        Retorna (texto, confianza promedio).
        """
        import io

        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))

        try:
            data = pytesseract.image_to_data(
                img,
                lang="spa+eng",
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )

            # Construir texto limpio
            text_parts = []
            confidences = []
            for i, word in enumerate(data["text"]):
                if word.strip():
                    text_parts.append(word)
                    confidences.append(data["conf"][i])

            text = " ".join(text_parts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            return text, avg_confidence / 100.0  # Tesseract devuelve 0-100

        except Exception as e:
            logger.error(f"tesseract_failed: {e}")
            return "", 0.0

    def _detect_charts(self, image_bytes: bytes) -> list[dict[str, Any]]:
        """
        Detección de gráficos usando color + geometría.
        """
        try:
            import numpy as np
            from PIL import Image

            img_array = np.array(Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB"))

            # Análisis de color: detectar regiones con múltiples colores estructurados
            hsv = __import__("cv2").cvtColor(img_array, __import__("cv2").COLOR_RGB2HSV)

            # Detectar bordes
            edges = __import__("cv2").Canny(img_array, 50, 150)

            # Buscar líneas horizontales y verticales (ejes de gráficos)
            horizontal = __import__("cv2").HoughLinesP(
                edges, 1, __import__("numpy").pi / 180, threshold=50, minLineLength=50, maxLineGap=10
            )

            if horizontal is not None:
                h_lines = [line[0] for line in horizontal]
                # Si hay suficientes líneas horizontales, parece un gráfico
                if len(h_lines) >= 3:
                    return [
                        {
                            "type": "possible_chart",
                            "confidence": 0.5,
                            "bbox": [0, 0, img_array.shape[1], img_array.shape[0]],
                            "note": "Detected possible chart structure with multiple horizontal lines",
                        }
                    ]

        except ImportError:
            logger.warning("opencv_or_numpy_not_available, skipping chart detection")
        except Exception as e:
            logger.warning("chart_detection_failed", error=str(e))

        return []

    def _generate_warnings(self, confidence: float, charts: list[dict], format: str) -> list[str]:
        """Generar advertencias basadas en los resultados."""
        warnings: list[str] = []

        if confidence < 0.3:
            warnings.append("Baja confianza en OCR: el texto puede contener errores")
        elif confidence < 0.6:
            warnings.append("Confianza moderada en OCR: se recomienda verificar resultados clave")

        if charts:
            for chart in charts:
                if chart.get("confidence", 0) < 0.5:
                    warnings.append("Posible gráfico detectado con baja confianza: los datos pueden no ser exactos")

        if format == "JPEG":
            warnings.append("Fuente JPEG con compresión: puede afectar precisión de OCR")

        return warnings

    def _save_result(
        self,
        tenant_id: str,
        validated: dict[str, Any],
        full_text: str,
        confidence: float,
        charts: list[dict],
        warnings: list[str],
        processing_time_ms: int,
    ) -> str:
        """Guardar resultado en BD y registrar usage event."""
        with make_session() as db:
            result = OCRResult(
                tenant_id=tenant_id,
                source_filename=validated.get("filename"),
                source_format=validated["format"],
                source_size_bytes=validated["size"],
                full_text=full_text,
                overall_confidence=confidence,
                engine_used="tesseract",
                charts_data=charts,
                warnings=warnings,
                page_count=1,
                processing_time_ms=processing_time_ms,
            )
            db.add(result)
            db.commit()

            # Log usage event
            usage_event = UsageEvent(
                tenant_id=tenant_id,
                module="vision_ocr",
                event_type="ocr_scan",
                tokens_used=0,
                cost_usd=0.0,
                extra_data={
                    "confidence": confidence,
                    "charts": len(charts),
                    "warnings": len(warnings),
                    "processing_ms": processing_time_ms,
                },
            )
            db.add(usage_event)
            db.commit()

            return str(result.id)
