"""
Modèle test oral (table tests_oraux).
"""
import uuid

from sqlalchemy import Column, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class TestOral(Base):
    __tablename__ = "tests_oraux"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_candidature = Column(
        UUID(as_uuid=True),
        ForeignKey("candidatures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score_oral = Column(Float, nullable=True)
