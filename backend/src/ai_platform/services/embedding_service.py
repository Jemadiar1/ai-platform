"""Service para generar embeddings usando NAN qwen3-embedding."""

import logging

import httpx

from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Genera embeddings usando el modelo qwen3-embedding de NAN."""

    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.settings.EMBEDDING_API_URL,
                headers={"Authorization": f"Bearer {self.settings.NAN_API_KEY}"},
                timeout=30.0,
            )
        return self._client

    def generate_embedding(self, text: str) -> list[float] | None:
        """Generar un embedding para un texto dado."""
        if not self.settings.NAN_API_KEY:
            logger.debug("NAN_API_KEY no configurado, skipping embedding generation")
            return None

        if not text:
            return None

        try:
            client = self._get_client()
            response = client.post(
                "/embeddings",
                json={
                    "model": self.settings.EMBEDDING_MODEL,
                    "input": [text],
                    "encoding_format": "float",
                },
            )
            response.raise_for_status()
            data = response.json()

            if data.get("data") and len(data["data"]) > 0:
                return data["data"][0]["embedding"]
            return None
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

    def generate_batch_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generar embeddings para un batch de textos."""
        if not texts:
            return []

        filtered = [t for t in texts if t]
        if not filtered:
            return []

        if not self.settings.NAN_API_KEY:
            return []

        try:
            client = self._get_client()
            batch = filtered[:32]  # Max batch size
            response = client.post(
                "/embeddings",
                json={
                    "model": self.settings.EMBEDDING_MODEL,
                    "input": batch,
                    "encoding_format": "float",
                },
            )
            response.raise_for_status()
            data = response.json()

            return [item["embedding"] for item in data.get("data", [])]
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            return []

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calcular similitud cosina entre dos vectores."""
        if not a or not b:
            return 0.0
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def close(self):
        if self._client:
            self._client.close()
            self._client = None


# Singleton instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
