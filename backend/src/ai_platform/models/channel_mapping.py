from typing import Any, Optional
"""
Mapeo entre canales externos (Telegram, Discord, WhatsApp) y usuarios de la plataforma.

Este módulo permite vincular un usuario de un canal externo con un usuario
de la plataforma AI Platform, permitiendo que los mensajes de canales externos
se asocien correctamente al tenant y usuario correcto.

"""

import logging
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class MappingRowProxy:
    """
    Proxy para convertir una fila de SQLAlchemy en un objeto con atributos.

    Similar a MappingRow en _row_to_mapping, pero para uso independiente.
    """

    def __init__(self, row):
        self.id = row.id
        self.tenant_id = row.tenant_id
        self.user_id = row.user_id
        self.channel = row.channel
        self.channel_user_id = row.channel_user_id
        self.channel_username = row.channel_username
        self.channel_chat_id = row.channel_chat_id
        self.created_at = row.created_at


def get_channel_user_info(
    channel: str,
    channel_user_id: str,
) -> Optional[Any]:
    """
    Buscar un mapeo de canal externo por channel y channel_user_id.

    A diferencia de get_or_create_channel_mapping(), esta función
    no requiere tenant_id ni user_id. Busca en TODOS los tenants
    el mapeo que corresponde al channel_user_id especificado.
    Esto es necesario para los webhook handlers que no conocen
    el tenant_id antes de procesar el mensaje.

    Parámetros:
        channel: Canal ("telegram", "discord", "whatsapp")
        channel_user_id: ID del usuario en el canal externo

    Retorna:
        Objeto ChannelMapping o None si no se encuentra
    """
    from ai_platform.database import make_session

    with make_session() as db:
        try:
            result = db.execute(
                text("""
                    SELECT id, tenant_id, user_id, channel, channel_user_id,
                           channel_username, channel_chat_id, created_at
                    FROM channel_mappings
                    WHERE channel = :channel
                      AND channel_user_id = :channel_user_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {
                    "channel": channel,
                    "channel_user_id": channel_user_id,
                },
            ).first()

            if result:
                logger.info(
                    f"Mapeo de canal encontrado: channel={channel}, "
                    f"channel_user_id={channel_user_id}, "
                    f"tenant_id={result.tenant_id}, user_id={result.user_id}"
                )
                return MappingRowProxy(result)

        except Exception as e:
            logger.warning(f"Error buscando mapeo de canal por channel_user_id: {e}")

    return None


def get_or_create_channel_mapping(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    channel: str,
    channel_user_id: str,
    channel_username: Optional[str] = None,
    channel_chat_id: Optional[str] = None,
) -> Optional[Any]:
    """
    Buscar o crear un mapeo entre un usuario de canal externo y un usuario de la plataforma.

    Flujo:
    1. Buscar mapeo existente por (tenant_id, channel, channel_user_id)
    2. Si existe → retornar
    3. Si no existe → crear nuevo mapeo

    Parámetros:
        db: Sesión de SQLAlchemy
        tenant_id: ID del tenant (UUID)
        user_id: ID del usuario de plataforma (UUID)
        channel: Canal ("telegram", "discord", "whatsapp")
        channel_user_id: ID del usuario en el canal externo
        channel_username: Nombre de usuario en el canal (opcional)
        channel_chat_id: ID del chat en el canal (opcional)

    Retorna:
        Objeto ChannelMapping o None si falló la creación
    """
    try:
        result = db.execute(
            text("""
                SELECT id, tenant_id, user_id, channel, channel_user_id,
                       channel_username, channel_chat_id, created_at
                FROM channel_mappings
                WHERE tenant_id = :tenant_id
                  AND channel = :channel
                  AND channel_user_id = :channel_user_id
                LIMIT 1
            """),
            {
                "tenant_id": tenant_id,
                "channel": channel,
                "channel_user_id": channel_user_id,
            },
        ).first()

        if result:
            logger.info(
                f"Mapeo de canal existente: channel={channel}, "
                f"channel_user_id={channel_user_id}"
            )
            return _row_to_mapping(result)

    except Exception as e:
        logger.warning(f"Error buscando mapeo de canal: {e}")

    # No existe → crear nuevo
    mapping_id = uuid4()
    try:
        db.execute(
            text("""
                INSERT INTO channel_mappings (
                    id, tenant_id, user_id, channel,
                    channel_user_id, channel_username, channel_chat_id,
                    created_at
                ) VALUES (
                    :id, :tenant_id, :user_id, :channel,
                    :channel_user_id, :channel_username, :channel_chat_id,
                    NOW()
                )
            """),
            {
                "id": mapping_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "channel": channel,
                "channel_user_id": channel_user_id,
                "channel_username": channel_username,
                "channel_chat_id": channel_chat_id,
            },
        )
        db.commit()

        logger.info(
            f"Nuevo mapeo de canal creado: channel={channel}, "
            f"channel_user_id={channel_user_id}, user_id={user_id}"
        )

        return get_or_create_channel_mapping(
            db, tenant_id, user_id, channel,
            channel_user_id, channel_username, channel_chat_id,
        )

    except Exception as e:
        logger.error(f"Error creando mapeo de canal: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _row_to_mapping(row: Any) -> Any:
    """
    Convertir un row de SQLAlchemy a un objeto con atributos.

    Parámetros:
        row: Fila result de SQLAlchemy

    Retorna:
        Objeto con atributos: id, tenant_id, user_id, channel,
        channel_user_id, channel_username, channel_chat_id, created_at
    """
    class MappingRow:
        pass

    mapping = MappingRow()
    mapping.id = row.id
    mapping.tenant_id = row.tenant_id
    mapping.user_id = row.user_id
    mapping.channel = row.channel
    mapping.channel_user_id = row.channel_user_id
    mapping.channel_username = row.channel_username
    mapping.channel_chat_id = row.channel_chat_id
    mapping.created_at = row.created_at
    return mapping
