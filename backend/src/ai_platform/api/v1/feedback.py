"""Feedback endpoints for user ratings on Odin's decisions."""

import logging
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from ai_platform.database import make_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/decisions", tags=["feedback"])


class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=3, description="1=down, 2=neutral, 3=up")
    comment: str | None = None


@router.post("/{decision_id}/feedback")
async def submit_feedback(
    decision_id: str,
    request: FeedbackRequest,
    tenant_id: str = Query(..., description="ID del tenant"),
    user_id: str = Query(..., description="ID del usuario que envía el feedback"),
):
    """Enviar feedback sobre una decisión de Odin."""
    with make_session() as db:
        db.execute(
            text("""
                INSERT INTO decision_feedback (id, decision_id, tenant_id, user_id, rating, comment, created_at)
                VALUES (:id, :decision_id, :tenant_id, :user_id, :rating, :comment, NOW())
            """),
            {
                "id": str(uuid4()),
                "decision_id": decision_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "rating": request.rating,
                "comment": request.comment,
            },
        )
        db.commit()

    return {"status": "recorded", "rating": request.rating}
