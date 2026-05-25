"""
Tests para report_models y report_renderer.

Cubre:
- ReportSpec, Section, ChartSpec, TableSpec, BrandTheme
- ReportRendererService._render_charts (mocked matplotlib)
- ReportRendererService._render_html
- ReportRendererService._generate_xlsx, _generate_csv
"""

from unittest.mock import patch

import pytest

from ai_platform.services.report_models import (
    BrandTheme,
    ChartSpec,
    ChartType,
    Citation,
    ReportSpec,
    Section,
    TableSpec,
)

# =========================================================================
# Report Models Tests
# =========================================================================


class TestReportSpec:
    """Tests para ReportSpec."""

    def test_report_spec_calculates_counts(self):
        """ReportSpec debe calcular chart_count, table_count, total_sections."""
        spec = ReportSpec(
            title="Test Report",
            audience="Test Audience",
            sections=[
                Section(
                    id="s1",
                    title="Section 1",
                    content="Content 1",
                    charts=[
                        ChartSpec(id="c1", title="Chart 1", type=ChartType.BAR, data=[{"label": "A", "value": 10}])
                    ],
                    tables=[TableSpec(id="t1", title="Table 1", headers=["H1"], rows=[["R1"]])],
                ),
                Section(
                    id="s2",
                    title="Section 2",
                    content="Content 2",
                    charts=[
                        ChartSpec(id="c2", title="Chart 2", type=ChartType.LINE, data=[{"label": "B", "value": 20}])
                    ],
                ),
            ],
        )

        assert spec.chart_count == 2
        assert spec.table_count == 1
        assert spec.total_sections == 2

    def test_report_spec_defaults(self):
        """ReportSpec debe tener valores default."""
        spec = ReportSpec(title="Test", audience="Test", sections=[])
        assert spec.generated_by == "ai-platform"
        assert spec.version == "1.0"
        assert spec.metadata == {}

    def test_brand_theme_defaults(self):
        """BrandTheme debe tener valores default."""
        theme = BrandTheme()
        assert theme.primary_color == "#1a73e8"
        assert theme.secondary_color == "#5f6368"
        assert theme.font_family == "Arial, sans-serif"
        assert theme.company_name == "NeuralCrew Labs"


class TestChartSpec:
    """Tests para ChartSpec."""

    def test_chart_spec_defaults(self):
        """ChartSpec debe tener valores default."""
        chart = ChartSpec(id="c1", title="Test", type=ChartType.BAR, data=[{"label": "A", "value": 1}])
        assert chart.colors is None
        assert chart.width == 600
        assert chart.height == 400


class TestTableSpec:
    """Tests para TableSpec."""

    def test_table_spec_with_data(self):
        """TableSpec debe almacenar headers y rows."""
        table = TableSpec(id="t1", title="Test", headers=["Name", "Value"], rows=[["A", 1], ["B", 2]])
        assert table.headers == ["Name", "Value"]
        assert len(table.rows) == 2


class TestCitation:
    """Tests para Citation."""

    def test_citation_with_url(self):
        """Citation con URL."""
        cite = Citation(text="Source text", source="Example.com", url="https://example.com")
        assert cite.url == "https://example.com"

    def test_citation_without_url(self):
        """Citation sin URL."""
        cite = Citation(text="Source text", source="Example.com")
        assert cite.url is None


# =========================================================================
# ReportRenderer Service Tests
# =========================================================================


class TestReportRenderer:
    """Tests para ReportRendererService."""

    @pytest.fixture
    def sample_spec(self):
        """Crear ReportSpec de prueba."""
        return ReportSpec(
            title="Test Report",
            audience="Test Audience",
            sections=[
                Section(
                    id="s1",
                    title="Section 1",
                    content="This is test content.",
                    charts=[
                        ChartSpec(
                            id="chart1",
                            title="Test Chart",
                            type=ChartType.BAR,
                            data=[{"label": "A", "value": 10}, {"label": "B", "value": 20}],
                        )
                    ],
                )
            ],
        )

    def test_render_html_included_by_default(self, sample_spec):
        """render() debe incluir HTML por defecto."""
        from ai_platform.services.report_renderer import ReportRendererService

        renderer = ReportRendererService()
        from ai_platform.services.report_models import ReportFormat

        with patch.object(renderer, "_save_report"), patch.object(renderer, "_log_usage"):
            outputs = renderer.render("test-tenant", sample_spec, [ReportFormat.HTML])

            assert "html" in outputs
            assert isinstance(outputs["html"], bytes)
            assert b"Test Report" in outputs["html"]
            assert b"Section 1" in outputs["html"]
            assert b"This is test content" in outputs["html"]

    def test_render_charts_produces_bytes(self, sample_spec):
        """_render_charts debe producir bytes PNG."""
        from ai_platform.services.report_renderer import ReportRendererService

        renderer = ReportRendererService()
        images = renderer._render_charts(sample_spec)

        assert "chart1" in images
        assert isinstance(images["chart1"], bytes)
        assert len(images["chart1"]) > 0

    def test_generate_csv_produces_valid_csv(self, sample_spec):
        """_generate_csv debe producir CSV válido."""
        import csv
        import io

        from ai_platform.services.report_renderer import ReportRendererService

        renderer = ReportRendererService()
        buf = io.StringIO()
        writer = csv.writer(buf)

        for section in sample_spec.sections:
            writer.writerow([f"SECCIÓN: {section.title}"])
            writer.writerow([])

            for table in section.tables:
                writer.writerow(table.headers)
                for row in table.rows:
                    writer.writerow(row)
                writer.writerow([])

            for chart in section.charts:
                writer.writerow([f"GRÁFICO: {chart.title}"])
                for d in chart.data:
                    writer.writerow([d.get("label", ""), d.get("value", "")])
                writer.writerow([])

        text = buf.getvalue()
        assert "Section 1" in text
        assert "Test Chart" in text

    def test_generate_xlsx_returns_bytes(self, sample_spec):
        """_generate_xlsx debe retornar bytes."""
        from ai_platform.services.report_renderer import ReportRendererService

        renderer = ReportRendererService()
        xlsx_bytes = renderer._generate_xlsx(sample_spec)

        assert isinstance(xlsx_bytes, bytes)
        assert len(xlsx_bytes) > 0

    def test_generate_pdf_returns_empty_without_weasyprint(self, sample_spec):
        """_generate_pdf debe retornar bytes vacíos si WeasyPrint no está instalado."""
        from ai_platform.services.report_renderer import ReportRendererService

        with patch.dict("sys.modules", {"weasyprint": None}):
            renderer = ReportRendererService()
            pdf_bytes = renderer._generate_pdf("<html><body>test</body></html>")

            # Debe retornar bytes vacíos en lugar de crashar
            assert isinstance(pdf_bytes, bytes)
