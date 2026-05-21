"""
Base de conocimiento vectorizada para Odin.

Implementa búsqueda semántica simple usando TF-IDF (sin dependencias externas
como FAISS o Chroma) para mantener el proyecto ligero.

Inspirado en Hermes Agent's knowledge base:
- Almacena documentos con metadata por tenant
- Busca documentos relevantes por similitud de palabras clave
- Integra resultados en el contexto de las sesiones
- Permite actualizar/eliminar documentos

Ventajas del enfoque TF-IDF puro:
- Cero dependencias externas (solo stdlib de Python)
- Funciona en cualquier entorno sin compilación
- Transparente y debuggable (los pesos son números reales)
- Escala linealmente con el número de documentos del tenant
"""

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Stop words en español (comunes a cualquier documento)
# Incluidas para filtrar términos sin valor semántico en la búsqueda
STOP_WORDS = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "al",
    "en",
    "con",
    "por",
    "para",
    "sin",
    "sobre",
    "entre",
    "hacia",
    "hasta",
    "desde",
    "durante",
    "ante",
    "como",
    "mas",
    "que",
    "lo",
    "se",
    "me",
    "mi",
    "tu",
    "su",
    "no",
    "si",
    "y",
    "o",
    "u",
    "ni",
    "pero",
    "menos",
    "más",
    "qué",
    "cuál",
    "quien",
    "cual",
    "este",
    "esta",
    "estos",
    "estas",
    "ese",
    "esa",
    "esos",
    "esas",
    "aquel",
    "aquella",
    "todo",
    "todos",
    "toda",
    "todas",
    "mismo",
    "misma",
    "mismos",
    "tambien",
    "también",
    "cada",
    "sus",
    "nuestro",
    "nuestra",
    "eso",
    "fue",
    "son",
    "era",
    "eran",
    "ser",
    "estar",
    "haber",
    "hacer",
    "poder",
    "decir",
    "tener",
    "ver",
    "dar",
    "llegar",
    "pasar",
    "ir",
}


@dataclass
class Document:
    """Documento indexado en la base de conocimiento."""

    doc_id: str
    tenant_id: str
    content: str
    title: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    embedding: list[float] | None = None  # Placeholder para embeddings futuros


class TFIDFVectorizer:
    """
    Vectorizador TF-IDF simple en Python puro.

    Calcula TF-IDF para documentos y queries.
    TF = frecuencia del término en el documento / términos totales en documento
    IDF = log(total de documentos / frecuencia del término en TODOS los documentos)

    Diseño:
    - fit(): se llama con un corpus para calcular los pesos IDF
    - transform(): convierte un texto individual en un vector TF-IDF disperso
    - cosine_similarity(): compara dos vectores dispersos por producto escalar

    Limitaciones conscientes:
    - No soporta stemming ni lematización
    - No maneja n-gramas
    - IDF usa smoothing (laplace) para términos nuevos
    """

    def __init__(self):
        self._idf: dict[str, float] = {}
        self._docs_count = 0

    def fit(self, documents: list[str]) -> None:
        """
        Calcular IDF desde un corpus de documentos.

        Este método reconstruye los pesos IDF desde cero.
        Se llama cada vez que se agrega, elimina o actualiza un documento
        para mantener los pesos actualizados.

        Parámetros:
            documents: Lista de strings (contenidos de documentos)
        """
        n_docs = len(documents)
        self._docs_count = n_docs

        # Calcular DF (document frequency): cuántos documentos contienen cada término
        df = defaultdict(int)
        for doc in documents:
            tokens = self._tokenize(doc)
            # Usar set para contar documentos únicos (no repites el mismo token)
            for token in set(tokens):
                df[token] += 1

        # Calcular IDF con smoothing de Laplace para robustez
        for term, freq in df.items():
            # log((N + 1) / (df + 1)) + 1: smoothing para evitar ceros
            self._idf[term] = math.log((n_docs + 1) / (freq + 1)) + 1

    def _tokenize(self, text: str) -> list[str]:
        """
        Tokenizar texto en palabras limpias.

        Filtra stop words, caracteres especiales y tokens muy cortos
        que no aportan valor semántico.

        Parámetros:
            text: Texto crudo a tokenizar

        Retorna:
            Lista de tokens limpios en minúscula
        """
        tokens = text.lower().split()
        return [
            t.strip(".,;:!?()[]{}\"'-").lower()
            for t in tokens
            if t.strip(".,;:!?()[]{}\"'-").lower() not in STOP_WORDS and len(t.strip(".,;:!?()[]{}\"'-")) > 2
        ]

    def transform(self, text: str) -> dict[str, float]:
        """
        Convertir texto a vector TF-IDF disperso.

        Retorna un dict {término: peso} en vez de un array denso,
        lo que ahorra memoria y permite comparaciones rápidas
        usando solo términos comunes entre dos vectores.

        Parámetros:
            text: Texto a vectorizar

        Retorna:
            Dict disperso {término: valor TF-IDF}
        """
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        # TF: frecuencia normalizada del término en el documento
        tf = defaultdict(int)
        for token in tokens:
            tf[token] += 1

        # Normalizar TF dividiendo por total de tokens
        total = len(tokens) or 1
        tf = {k: v / total for k, v in tf.items()}

        # Calcular TF * IDF para cada término
        tfidf = {}
        for token, freq in tf.items():
            idf = self._idf.get(token, 1.0)  # Default 1.0 para términos nuevos
            tfidf[token] = freq * idf

        return tfidf

    def cosine_similarity(self, vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        """
        Calcular similitud de coseno entre dos vectores TF-IDF dispersos.

        Solo considera términos comunes entre ambos vectores,
        lo que hace la comparación O(n) en vez de O(n*m).

        Parámetros:
            vec_a: Primer vector disperso {término: peso}
            vec_b: Segundo vector disperso {término: peso}

        Retorna:
            Similitud en rango [0.0, 1.0], donde 1.0 es idéntico
        """
        # Términos comunes entre ambos vectores
        common_terms = set(vec_a.keys()) & set(vec_b.keys())
        if not common_terms:
            return 0.0

        # Producto escalar sobre términos comunes
        dot_product = sum(vec_a[t] * vec_b[t] for t in common_terms)

        # Magnitudes de cada vector
        mag_a = math.sqrt(sum(v**2 for v in vec_a.values()))
        mag_b = math.sqrt(sum(v**2 for v in vec_b.values()))

        if mag_a * mag_b == 0:
            return 0.0

        return dot_product / (mag_a * mag_b)


class KnowledgeBase:
    """
    Base de conocimiento con búsqueda TF-IDF.

    Almacena y busca documentos por similitud de contenido usando
    un vectorizador TF-IDF puro en Python. Inspirado en el sistema
    de knowledge base de Hermes Agent.

    Características:
    - Aislamiento por tenant: cada tenant solo ve sus propios documentos
    - Límite de capacidad: máximo 1000 documentos por tenant
    - Categorización opcional: organiza documentos por categoría
    - Actualización incremental: re-calcula IDF al modificar documentos
    - Búsqueda por similitud de coseno: ranking por relevancia

    Uso:
        kb = get_knowledge_base()
        doc_id = await kb.add_document("tenant_1", "Contenido del documento")
        results = await kb.search("consulta relevante", "tenant_1", limit=5)
    """

    def __init__(self):
        self._documents: dict[str, Document] = {}
        self._vectorizer = TFIDFVectorizer()
        self._max_documents_per_tenant = 1000

    async def add_document(
        self,
        tenant_id: str,
        content: str,
        title: str | None = None,
        category: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Agregar un documento a la base de conocimiento.

        Valida que no se exceda el límite de documentos del tenant,
        genera un ID único, almacena el documento y recalcula
        los pesos TF-IDF para el corpus del tenant.

        Parámetros:
            tenant_id: ID del tenant propietario
            content: Contenido textual del documento
            title: Título opcional para el documento
            category: Categoría opcional para agrupación
            metadata: Metadata adicional (dict arbitrario)

        Retorna:
            doc_id del documento agregado

        Levanta:
            ValueError: Si se excede el límite de documentos del tenant
        """
        # Validar límite de capacidad por tenant
        tenant_doc_count = sum(1 for d in self._documents.values() if d.tenant_id == tenant_id)
        if tenant_doc_count >= self._max_documents_per_tenant:
            raise ValueError(
                f"Capacidad máxima alcanzada para tenant {tenant_id}: {self._max_documents_per_tenant} documentos"
            )

        doc_id = f"doc_{datetime.now(UTC).timestamp().hex[:12]}_{len(self._documents)}"

        doc = Document(
            doc_id=doc_id,
            tenant_id=tenant_id,
            content=content,
            title=title,
            category=category,
            metadata=metadata or {},
        )
        self._documents[doc_id] = doc

        # Re-calcular vectorizador con todos los docs del tenant
        tenant_docs = [d.content for d in self._documents.values() if d.tenant_id == tenant_id]
        try:
            self._vectorizer.fit(tenant_docs)
        except Exception as e:
            logger.warning(f"Error al actualizar vectorizador: {e}")

        logger.info(f"Documento agregado a KB: {doc_id} (tenant: {tenant_id})")
        return doc_id

    async def remove_document(self, doc_id: str) -> bool:
        """
        Eliminar un documento de la base.

        Parámetros:
            doc_id: ID del documento a eliminar

        Retorna:
            True si se eliminó, False si no existía
        """
        if doc_id in self._documents:
            del self._documents[doc_id]
            logger.info(f"Documento eliminado de KB: {doc_id}")
            return True
        return False

    async def search(
        self,
        query: str,
        tenant_id: str,
        limit: int = 5,
        threshold: float = 0.05,
    ) -> list[dict[str, Any]]:
        """
        Buscar documentos relevantes por similitud TF-IDF.

        Vectoriza la consulta y compara con cada documento del tenant
        usando similitud de coseno. Solo retorna documentos con
        similitud >= threshold.

        Parámetros:
            query: Texto de búsqueda
            tenant_id: Filtrar documentos por tenant
            limit: Máximo de resultados (default: 5)
            threshold: Similitud mínima [0.0, 1.0] (default: 0.05)

        Retorna:
            Lista de dicts ordenados por similitud descendente:
                - doc_id, title, category, similarity, content (truncado), metadata
        """
        query_vec = self._vectorizer.transform(query)
        if not query_vec:
            return []

        results = []
        for doc_id, doc in self._documents.items():
            if doc.tenant_id != tenant_id:
                continue

            doc_vec = self._vectorizer.transform(doc.content)
            if not doc_vec:
                continue

            similarity = self._vectorizer.cosine_similarity(query_vec, doc_vec)

            if similarity >= threshold:
                results.append(
                    {
                        "doc_id": doc_id,
                        "title": doc.title or "(sin título)",
                        "category": doc.category or "general",
                        "similarity": round(similarity, 4),
                        "content": doc.content[:500],  # Truncar para no saturar contexto
                        "metadata": doc.metadata,
                    }
                )

        # Ordenar por similitud descendente
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    async def update_document(
        self,
        doc_id: str,
        content: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Actualizar un documento existente.

        Recalcula los pesos TF-IDF después de modificar contenido
        para mantener la precisión de las búsquedas.

        Parámetros:
            doc_id: ID del documento a actualizar
            content: Nuevo contenido (opcional)
            title: Nuevo título (opcional)
            metadata: Metadata para fusionar con la existente (opcional)

        Retorna:
            True si se actualizó, False si no existía
        """
        doc = self._documents.get(doc_id)
        if not doc:
            return False

        if content:
            doc.content = content
        if title:
            doc.title = title
        if metadata:
            doc.metadata.update(metadata)
        doc.updated_at = datetime.now(UTC)

        # Re-calcular vectorizador para mantener precisión de búsqueda
        tenant_docs = [d.content for d in self._documents.values() if d.tenant_id == doc.tenant_id]
        try:
            self._vectorizer.fit(tenant_docs)
        except Exception as e:
            logger.warning(f"Error al actualizar vectorizador tras edición: {e}")

        return True

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """
        Obtener un documento por ID con todos sus campos.

        Parámetros:
            doc_id: ID del documento

        Retorna:
            Dict con campos del documento, o None si no existe
        """
        doc = self._documents.get(doc_id)
        if doc:
            return {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "category": doc.category,
                "content": doc.content,
                "metadata": doc.metadata,
                "created_at": doc.created_at.isoformat(),
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            }
        return None

    async def get_stats(self, tenant_id: str) -> dict[str, Any]:
        """
        Obtener estadísticas de la base de conocimiento para un tenant.

        Parámetros:
            tenant_id: ID del tenant

        Retorna:
            Dict con estadísticas:
                - total_documents: número de documentos
                - max_documents: límite máximo
                - capacity_percent: porcentaje de uso
                - by_category: conteo por categoría
        """
        tenant_docs = [d for d in self._documents.values() if d.tenant_id == tenant_id]
        categories = defaultdict(int)
        for doc in tenant_docs:
            categories[doc.category or "unclassified"] += 1

        return {
            "total_documents": len(tenant_docs),
            "max_documents": self._max_documents_per_tenant,
            "capacity_percent": round((len(tenant_docs) / self._max_documents_per_tenant) * 100, 1),
            "by_category": dict(categories),
        }

    async def list_documents(
        self,
        tenant_id: str,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Listar documentos de un tenant con filtro opcional por categoría.

        Parámetros:
            tenant_id: ID del tenant
            category: Filtrar por categoría (opcional)
            limit: Máximo de resultados

        Retorna:
            Lista de dicts con info resumida de documentos
        """
        results = []
        for doc in self._documents.values():
            if doc.tenant_id != tenant_id:
                continue
            if category and doc.category != category:
                continue
            results.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title or "(sin título)",
                    "category": doc.category or "general",
                    "created_at": doc.created_at.isoformat(),
                    "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                }
            )

        results.sort(
            key=lambda x: x["created_at"],
            reverse=True,
        )
        return results[:limit]


# Instancia global singleton
_knowledge_base: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    """
    Obtener la base de conocimiento (singleton).

    Retorna:
        Instancia de KnowledgeBase
    """
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = KnowledgeBase()
    return _knowledge_base
