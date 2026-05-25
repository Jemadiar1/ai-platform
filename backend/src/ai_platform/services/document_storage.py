"""
Servicio de almacenamiento de archivos para document ingestion.

Gestiona el guardado, lectura y eliminación de archivos de documentos
en el sistema de archivos local (con ruta configurable).

Multi-tenant: archivos se almacenan en /data/documents/{tenant_id}/{uuid}.{ext}

Usar:
    from ai_platform.services.document_storage import save_uploaded_file, get_file_path, delete_file
"""

import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Root directory for document storage
DOCUMENT_STORAGE_ROOT = Path(settings.DOCUMENT_STORAGE_ROOT)


def save_uploaded_file(file_bytes: bytes, original_filename: str, tenant_id: str) -> str:
    """
    Guardar archivo subido en el sistema de archivos local.

    Crea el directorio del tenant si no existe, genera un nombre seguro
    con UUID, y calcula SHA-256 checksum para deduplicación.

    Parámetros:
        file_bytes: Contenido binario del archivo
        original_filename: Nombre original del archivo
        tenant_id: ID del tenant propietario

    Retorna:
        file_path: Ruta relativa almacenada en la BD (ej: "abc123def456.pdf")
    """
    # Calcular checksum para deduplicación
    checksum = hashlib.sha256(file_bytes).hexdigest()

    # Crear directorio del tenant
    tenant_dir = DOCUMENT_STORAGE_ROOT / str(tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)

    # Generar nombre seguro
    ext = Path(original_filename).suffix or ".bin"
    filename = f"{uuid4().hex}{ext}"
    file_path = tenant_dir / filename

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    logger.info(
        "file_saved",
        tenant_id=tenant_id,
        filename=filename,
        size=len(file_bytes),
        checksum=checksum[:16],
    )

    return filename


def get_file_path(file_name: str, tenant_id: str) -> Path:
    """
    Resolver nombre de archivo a ruta absoluta.

    Parámetros:
        file_name: Nombre de archivo (como se almacena en la BD)
        tenant_id: ID del tenant

    Retorna:
        Path absoluto al archivo
    """
    return DOCUMENT_STORAGE_ROOT / str(tenant_id) / file_name


def delete_file(file_name: str, tenant_id: str) -> bool:
    """
    Eliminar archivo del sistema de archivos.

    Parámetros:
        file_name: Nombre de archivo
        tenant_id: ID del tenant

    Retorna:
        True si se eliminó, False si el archivo no existía
    """
    path = DOCUMENT_STORAGE_ROOT / str(tenant_id) / file_name
    if path.exists():
        path.unlink()
        logger.info("file_deleted", tenant_id=tenant_id, filename=file_name)
        return True
    logger.warning("file_not_found_for_deletion", tenant_id=tenant_id, filename=file_name)
    return False


def get_file_size(file_name: str, tenant_id: str) -> int:
    """
    Obtener tamaño de archivo en bytes.

    Retorna:
        Tamaño en bytes, o -1 si el archivo no existe
    """
    path = DOCUMENT_STORAGE_ROOT / str(tenant_id) / file_name
    if path.exists():
        return path.stat().st_size
    return -1
