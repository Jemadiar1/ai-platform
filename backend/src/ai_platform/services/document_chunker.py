"""
Servicio de segmentación de documentos en chunks.

Provee múltiples estrategias de chunking:
- hybrid: semantic first, fixed-size overflow (default)
- semantic: split at section boundaries
- fixed: split by character count with overlap
- page: split by page

Usar:
    from ai_platform.services.document_chunker import DocumentChunker
    chunker = DocumentChunker()
    chunks = chunker.chunk_hybrid(text, metadata)
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Un chunk de texto extraído de un documento."""

    content: str
    chunk_index: int
    level: int = 1
    chunk_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentChunker:
    """
    Segmentador de documentos en chunks.

    Estrategias:
    - hybrid: detecta secciones (headings, blank lines, markdown #),
      luego aplica fixed-size para secciones > max_section_size
    - semantic: split al nivel de sección
    - fixed: split por tamaño fijo con overlap
    - page: split por página

    Configurable:
    - max_chunk_size: chars por chunk (default 1000)
    - max_section_size: tokens por sección antes de split (default 2000)
    - overlap: chars de overlap entre chunks (default 200)
    - min_chunk_size: descartar chunks menores (default 200)
    """

    def __init__(
        self,
        max_chunk_size: int = 1000,
        max_section_size: int = 2000,
        overlap: int = 200,
        min_chunk_size: int = 200,
    ) -> None:
        self.max_chunk_size = max_chunk_size
        self.max_section_size = max_section_size
        self.overlap = overlap
        self.min_chunk_size = min_chunk_size

    def chunk_hybrid(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """
        Chunking híbrido: semantic first, fixed-size overflow.

        1. Detecta límites de sección (headings, blank lines, markdown #)
        2. Para cada sección:
           - Si <= max_section_size: un chunk
           - Si > max_section_size: split en fixed-size con overlap
        """
        sections = self._split_into_sections(text)
        chunks: list[Chunk] = []
        idx = 0

        for section in sections:
            section_text = section["content"]
            section_meta = {**section.get("metadata", {}), **(metadata or {})}

            if len(section_text) <= self.max_section_size:
                chunks.append(
                    Chunk(
                        content=section_text.strip(),
                        chunk_index=idx,
                        level=1,
                        chunk_type="text",
                        metadata=section_meta,
                    )
                )
                idx += 1
            else:
                sub_chunks = self._chunk_fixed(section_text, start_idx=idx, metadata=section_meta)
                chunks.extend(sub_chunks)
                idx = chunks[-1].chunk_index + 1 if chunks else idx + 1

        return chunks

    def chunk_semantic(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunking semántico: split al nivel de sección."""
        sections = self._split_into_sections(text)
        chunks: list[Chunk] = []

        for i, section in enumerate(sections):
            section_text = section["content"].strip()
            if len(section_text) < self.min_chunk_size:
                continue
            chunks.append(
                Chunk(
                    content=section_text,
                    chunk_index=i,
                    level=1,
                    chunk_type="text",
                    metadata={**section.get("metadata", {}), **(metadata or {})},
                )
            )

        return chunks

    def chunk_fixed(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunking por tamaño fijo con overlap."""
        return self._chunk_fixed(text, start_idx=0, metadata=metadata)

    def chunk_page(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Chunking por página (split por \\f o \\n\\n---\\n\\n)."""
        pages = re.split(r"\f|\\n---\\n", text)
        chunks: list[Chunk] = []

        for i, page in enumerate(pages):
            page_text = page.strip()
            if len(page_text) < self.min_chunk_size:
                continue
            chunks.append(
                Chunk(
                    content=page_text,
                    chunk_index=i,
                    level=1,
                    chunk_type="text",
                    metadata={**{"page": i}, **(metadata or {})},
                )
            )

        return chunks

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _split_into_sections(self, text: str) -> list[dict[str, str]]:
        """
        Dividir texto en secciones usando heurísticas:
        1. Markdown headings (## Title)
        2. ALL CAPS headings on their own line
        3. Numbered headings (1., 1.1, 2.3)
        4. Fallback: single section
        """
        lines = text.split("\n")
        sections: list[dict[str, str]] = []
        current_section_lines: list[str] = []
        current_title: str | None = None

        # Regex patterns for section headings
        heading_patterns = [
            r"^#{1,6}\s+(.+)$",  # Markdown: # Title
            r"^([0-9]+\.?[0-9]?\s[.\s]+.+)$",  # Numbered: 1. Title, 1.1 Subtitle
            r"^([A-Z][A-Z\s&\-]+)$",  # ALL CAPS
        ]

        for line in lines:
            matched_heading = False
            for pattern in heading_patterns:
                match = re.match(pattern, line.strip())
                if match:
                    # Save previous section
                    if current_section_lines:
                        sections.append(
                            {
                                "content": "\n".join(current_section_lines),
                                "metadata": {"section_title": current_title or "Untitled"},
                            }
                        )
                    current_section_lines = []
                    current_title = match.group(1).strip()
                    matched_heading = True
                    break

            if not matched_heading:
                current_section_lines.append(line)

        # Save last section
        if current_section_lines:
            sections.append(
                {
                    "content": "\n".join(current_section_lines),
                    "metadata": {"section_title": current_title or "Untitled"},
                }
            )

        # If no sections found, return as single section
        if not sections:
            sections.append({"content": text, "metadata": {"section_title": "Full Document"}})

        return sections

    def _chunk_fixed(self, text: str, start_idx: int = 0, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        """Split text into fixed-size chunks with overlap."""
        if len(text) <= self.max_chunk_size:
            return [
                Chunk(
                    content=text.strip(),
                    chunk_index=start_idx,
                    level=1,
                    chunk_type="text",
                    metadata=metadata or {},
                )
            ]

        chunks: list[Chunk] = []
        idx = start_idx
        start = 0

        while start < len(text):
            end = start + self.max_chunk_size
            chunk_text = text[start:end].strip()

            # Try to break at word boundary
            if end < len(text):
                space_pos = chunk_text.rfind(" ", 0, self.max_chunk_size // 2)
                if space_pos > self.min_chunk_size:
                    chunk_text = chunk_text[:space_pos].strip()
                    end = start + space_pos

            if len(chunk_text) >= self.min_chunk_size:
                chunks.append(
                    Chunk(
                        content=chunk_text,
                        chunk_index=idx,
                        level=1,
                        chunk_type="text",
                        metadata={**{"overlap": start > 0}, **(metadata or {})},
                    )
                )
                idx += 1

            # Move forward: overlap means we go back
            start = end - self.overlap if end < len(text) else end

        return chunks
