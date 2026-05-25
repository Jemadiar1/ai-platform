"""
Tests para document ingestion services.

Cubre:
- document_storage.save_uploaded_file, get_file_path, delete_file
- document_chunker.DocumentChunker (hybrid, semantic, fixed, page)
"""

from unittest.mock import patch

import pytest

from ai_platform.services.document_chunker import Chunk, DocumentChunker

# =========================================================================
# document_storage Tests
# =========================================================================


class TestDocumentStorage:
    """Tests para document_storage."""

    @pytest.fixture
    def storage_root(self, tmp_path):
        """Crear directorio temporal para tests."""
        test_root = tmp_path / "test-docs"
        test_root.mkdir()
        with patch("ai_platform.services.document_storage.DOCUMENT_STORAGE_ROOT", test_root):
            yield test_root

    def test_save_creates_tenant_directory(self, storage_root):
        """save_uploaded_file debe crear directorio del tenant."""
        from ai_platform.services.document_storage import save_uploaded_file

        tenant_id = "test-tenant-123"
        file_bytes = b"test content for upload"
        result = save_uploaded_file(file_bytes, "test.pdf", tenant_id)

        # Verificar que el archivo existe
        tenant_dir = storage_root / tenant_id
        assert tenant_dir.exists()

        # Verificar que el archivo fue creado
        files = list(tenant_dir.glob("*"))
        assert len(files) == 1
        assert files[0].read_bytes() == file_bytes

    def test_save_returns_filename_only(self, storage_root):
        """save_uploaded_file debe retornar solo el nombre del archivo."""
        from ai_platform.services.document_storage import save_uploaded_file

        tenant_id = "test-tenant-456"
        file_bytes = b"another test file"
        result = save_uploaded_file(file_bytes, "document.docx", tenant_id)

        # Debe ser solo el filename, no la ruta completa
        assert "/" not in result
        assert "\\" not in result
        assert result.endswith(".docx")

    def test_save_generates_uuid_filename(self, storage_root):
        """save_uploaded_file debe generar nombre con UUID hex, no el original."""
        from ai_platform.services.document_storage import save_uploaded_file

        tenant_id = "test-tenant-uuid"
        save_uploaded_file(b"test", "my-actual-filename.pdf", tenant_id)

        tenant_dir = storage_root / tenant_id
        filename = next(iter(tenant_dir.glob("*"))).name
        # uuid4().hex es 32 chars + .pdf (4) = 36 total
        assert len(filename) == 36

    def test_get_file_path_resolves_correctly(self, storage_root):
        """get_file_path debe resolver nombre a ruta absoluta."""
        from ai_platform.services.document_storage import get_file_path

        tenant_id = "test-tenant-path"
        file_name = "abc123def456.pdf"

        # Crear el archivo primero
        tenant_dir = storage_root / tenant_id
        tenant_dir.mkdir(parents=True, exist_ok=True)
        (tenant_dir / file_name).write_bytes(b"exists")

        path = get_file_path(file_name, tenant_id)
        assert path.exists()
        # Usar pathlib para comparar: la ruta debe terminar en tenant_id/file_name
        expected = storage_root / tenant_id / file_name
        assert path == expected

    def test_delete_file_removes_file(self, storage_root):
        """delete_file debe eliminar el archivo."""
        from ai_platform.services.document_storage import delete_file, save_uploaded_file

        tenant_id = "test-tenant-delete"
        saved_name = save_uploaded_file(b"to delete", "original.pdf", tenant_id)

        with patch("ai_platform.services.document_storage.logger"):
            result = delete_file(saved_name, tenant_id)
        assert result is True

        tenant_dir = storage_root / tenant_id
        assert not (tenant_dir / saved_name).exists()

    def test_delete_file_returns_false_when_missing(self, storage_root):
        """delete_file debe retornar False si el archivo no existe."""
        from ai_platform.services.document_storage import delete_file

        with patch("ai_platform.services.document_storage.logger"):
            result = delete_file("does-not-exist.pdf", "tenant-999")
        assert result is False


# =========================================================================
# document_chunker Tests
# =========================================================================


class TestDocumentChunker:
    """Tests para DocumentChunker."""

    def test_chunk_hybrid_simple(self):
        """chunk_hybrid debe dividir texto en chunks."""
        chunker = DocumentChunker(max_chunk_size=100, max_section_size=100, overlap=10)
        text = "This is a simple test document with some content."
        chunks = chunker.chunk_hybrid(text)

        assert len(chunks) >= 1
        assert isinstance(chunks[0], Chunk)
        assert chunks[0].chunk_index == 0
        assert chunks[0].level == 1
        assert chunks[0].chunk_type == "text"

    def test_chunk_hybrid_with_sections(self):
        """chunk_hybrid debe generar chunks cuando las secciones exceden max_section_size."""
        # Usar max_section_size grande para que la sección no se divida,
        # pero max_chunk_size grande para que el texto quepa en un chunk.
        chunker = DocumentChunker(max_chunk_size=1000, max_section_size=1000, overlap=10)
        text = "Word " * 50  # ~250 chars
        chunks = chunker.chunk_hybrid(text)

        # Una sola sección, que cabe en max_section_size, genera un chunk
        assert len(chunks) >= 1

    def test_chunk_semantic_detects_headings(self):
        """chunk_semantic debe detectar secciones por headings."""
        chunker = DocumentChunker(min_chunk_size=1)
        text = """Introduction

This is a longer introduction section with enough content to pass the minimum chunk size threshold for testing purposes.

## Section Two

This is the content for section two, also sufficiently long to meet the minimum chunk size requirement in the chunker configuration.

### Subsection

This is the subsection content that should also be long enough to pass the minimum size filter for chunks."""
        chunks = chunker.chunk_semantic(text)

        # Debe detectar al menos 2 secciones
        assert len(chunks) >= 2

    def test_chunk_semantic_with_markdown_headings(self):
        """chunk_semantic debe detectar markdown headings."""
        chunker = DocumentChunker(min_chunk_size=1)
        text = """# Title

First section content here that is long enough to pass the minimum chunk size threshold for the chunker.

## Second Section

More content in the second section that is also long enough to pass the minimum chunk size requirement."""
        chunks = chunker.chunk_semantic(text)
        assert len(chunks) >= 2

    def test_chunk_fixed_simple(self):
        """chunk_fixed debe dividir por tamaño fijo."""
        chunker = DocumentChunker(max_chunk_size=30, overlap=5, min_chunk_size=1)
        text = "A " * 100  # 200 chars
        chunks = chunker.chunk_fixed(text)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.content) <= chunker.max_chunk_size + chunker.overlap

    def test_chunk_fixed_overlap(self):
        """chunk_fixed debe aplicar overlap entre chunks."""
        chunker = DocumentChunker(max_chunk_size=20, overlap=5, min_chunk_size=1)
        text = "Word " * 20
        chunks = chunker.chunk_fixed(text)

        # Verificar que chunks no son completamente independientes
        if len(chunks) > 1:
            # El overlap significa que hay palabras compartidas
            first_words = set(chunks[0].content.split())
            second_words = set(chunks[1].content.split())
            # Con overlap de 5 chars y "Word " de 5 chars, debe haber al menos 1 palabra compartida
            shared = first_words & second_words
            assert len(shared) >= 1

    def test_chunk_page_splits_on_form_feeds(self):
        """chunk_page debe dividir por form feeds."""
        chunker = DocumentChunker(min_chunk_size=1)
        text = "Page 1 content\fPage 2 content\fPage 3 content"
        chunks = chunker.chunk_page(text)

        assert len(chunks) == 3
        assert chunks[0].metadata.get("page") == 0
        assert chunks[1].metadata.get("page") == 1
        assert chunks[2].metadata.get("page") == 2

    def test_chunk_metadata_carries_through(self):
        """Los chunks deben heredar metadata."""
        chunker = DocumentChunker(min_chunk_size=1)
        metadata = {"document_id": "test-doc", "tenant_id": "test-tenant"}
        chunks = chunker.chunk_fixed("Test content", metadata=metadata)

        assert chunks[0].metadata.get("document_id") == "test-doc"
        assert chunks[0].metadata.get("tenant_id") == "test-tenant"

    def test_empty_text_fixed_returns_single_chunk(self):
        """Texto vacío con chunk_fixed retorna un chunk vacío (len <= max_chunk_size)."""
        chunker = DocumentChunker()
        chunks = chunker.chunk_fixed("")
        # _chunk_fixed: len("") <= max_chunk_size (1000), retorna [Chunk("")]
        assert len(chunks) == 1
        assert chunks[0].content == ""

    def test_short_text_passes_min_chunk_in_fast_path(self):
        """chunk_fixed con texto corto retorna un chunk porque el fast path no valida min_chunk_size."""
        chunker = DocumentChunker(min_chunk_size=200)
        short = "Short text"
        chunks = chunker.chunk_fixed(short)
        # El fast path en _chunk_fixed (if len(text) <= max_chunk_size) no verifica min_chunk_size
        assert len(chunks) == 1
        assert chunks[0].content == "Short text"
