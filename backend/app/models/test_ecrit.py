"""
Modèle test écrit (table Supabase tests_ecrits).
"""
import uuid

from sqlalchemy import Boolean, Column, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class TestEcrit(Base):
    __tablename__ = "tests_ecrits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_candidature = Column(
        UUID(as_uuid=True),
        ForeignKey("candidatures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score_ecrit = Column(Float, nullable=False)
    status_reussite = Column(Boolean, nullable=False, default=False)
