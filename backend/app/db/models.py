"""SQLAlchemy models."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Text, JSON, String, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class PidDocument(Base):
    __tablename__ = "pid_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending"
    )  # pending | processing | completed | failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    graph_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    page_num: Mapped[Optional[int]] = mapped_column(nullable=True)  # 1-based; null for single images
    text_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # all OCR text for retrieval
    upload_batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # groups pages from same PDF
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sops: Mapped[List["SopDocument"]] = relationship(
        "SopDocument", back_populates="pid", cascade="all, delete-orphan"
    )
    validations: Mapped[List["ValidationRun"]] = relationship(
        "ValidationRun", back_populates="pid", cascade="all, delete-orphan"
    )


class SopDocument(Base):
    __tablename__ = "sop_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    pid_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("pid_documents.id", ondelete="SET NULL"), nullable=True
    )  # optional; SOP is standalone; matching P&IDs found via vector search
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pid: Mapped[Optional["PidDocument"]] = relationship("PidDocument", back_populates="sops")


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    pid_id: Mapped[str] = mapped_column(String(36), ForeignKey("pid_documents.id", ondelete="CASCADE"), nullable=False)
    sop_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("sop_documents.id", ondelete="SET NULL"), nullable=True
    )  # SOP can link to multiple P&IDs; each run = one P&ID validated against one SOP
    status: Mapped[str] = mapped_column(
        String(32), default="pending"
    )  # pending | completed | failed
    issues: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pid: Mapped["PidDocument"] = relationship("PidDocument", back_populates="validations")
