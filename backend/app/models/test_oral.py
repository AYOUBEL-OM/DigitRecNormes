"""
Modèle SQLAlchemy — table PostgreSQL `tests_oraux` (schéma réel).
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import expression, func

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

    score_oral_global = Column(Float, nullable=True)
    cheating_flags = Column(JSONB, nullable=True)
    date_passage = Column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )
    language_level_global = Column(Text, nullable=True)
    soft_skills_summary = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    stress_score = Column(Float, nullable=True)
    eye_contact_score_global = Column(Float, nullable=True)
    suspicious_movements_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    tab_switch_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    fullscreen_exit_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    presence_anomaly_detected = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=expression.false(),
    )
    phone_detected = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=expression.false(),
    )
    other_person_detected = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=expression.false(),
    )
    status = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    candidate_access_token = Column(Text, nullable=True)
    candidate_photo_url = Column(Text, nullable=True)
