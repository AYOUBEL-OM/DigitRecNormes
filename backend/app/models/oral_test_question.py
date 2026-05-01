"""
Modèle SQLAlchemy — table PostgreSQL `oral_test_questions` (schéma réel).
"""
import uuid

from sqlalchemy import Column, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class OralTestQuestion(Base):
    __tablename__ = "oral_test_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_oral_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tests_oraux.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_order = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    audio_url = Column(Text, nullable=True)
    transcript_text = Column(Text, nullable=True)
    answer_duration_seconds = Column(Integer, nullable=True)
    hesitation_score = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=True)
