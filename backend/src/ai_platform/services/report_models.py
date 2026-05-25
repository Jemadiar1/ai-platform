"""
Modelos para especificación de reportes profesionales.

Usados por report_renderer para generar reportes en múltiples formatos.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReportFormat(str, Enum):
    """Formatos de salida soportados."""

    HTML = "html"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"


class ChartType(str, Enum):
    """Tipos de gráficos soportados."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    TABLE = "table"


@dataclass
class ChartSpec:
    """Especificación de un gráfico dentro de un reporte."""

    id: str
    title: str
    type: ChartType
    data: list[dict]  # [{"label": "Enero", "value": 1500}, ...]
    colors: list[str] | None = None
    width: int = 600
    height: int = 400


@dataclass
class TableSpec:
    """Especificación de una tabla dentro de un reporte."""

    id: str
    title: str
    headers: list[str]
    rows: list[list[Any]]


@dataclass
class Citation:
    """Cita/fuente dentro de un reporte."""

    text: str
    source: str
    url: str | None = None


@dataclass
class Section:
    """Sección de un reporte."""

    id: str
    title: str
    content: str  # Markdown o HTML
    charts: list[ChartSpec] = field(default_factory=list)
    tables: list[TableSpec] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)


@dataclass
class BrandTheme:
    """Tema de marca para personalización visual."""

    primary_color: str = "#1a73e8"
    secondary_color: str = "#5f6368"
    font_family: str = "Arial, sans-serif"
    logo_url: str | None = None
    company_name: str = "NeuralCrew Labs"
    page_numbering: bool = True


@dataclass
class ReportSpec:
    """
    Especificación completa de un reporte profesional.

    Ejemplo de uso:
        spec = ReportSpec(
            title="Reporte Mensual de Marketing",
            audience="Director de Marketing",
            sections=[
                Section(id="exec_summary", title="Resumen Ejecutivo", content="..."),
            ],
            theme=BrandTheme(company_name="MiEmpresa"),
        )
    """

    title: str
    audience: str
    sections: list[Section]
    theme: BrandTheme = field(default_factory=BrandTheme)
    generated_by: str = "ai-platform"
    version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    # Campos calculados
    chart_count: int = field(init=False)
    table_count: int = field(init=False)
    total_sections: int = field(init=False)

    def __post_init__(self) -> None:
        self.chart_count = sum(len(s.charts) for s in self.sections)
        self.table_count = sum(len(s.tables) for s in self.sections)
        self.total_sections = len(self.sections)
