"""Database session and lifecycle."""
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

from app.core.config import get_settings
from app.db.models import Base

_settings = get_settings()
_async_engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
)
_async_session_factory = async_sessionmaker(
    _async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Sync engine for pipeline (runs in thread pool or sync code)
_sync_url = _settings.database_url_sync
if _sync_url.startswith("postgresql+asyncpg"):
    _sync_url = _sync_url.replace("postgresql+asyncpg", "postgresql", 1)
_sync_engine = create_engine(
    _sync_url,
    echo=_settings.debug,
    pool_pre_ping=True,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_session() -> Session:
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=_sync_engine, autocommit=False, autoflush=False)
    return SessionLocal()


async def init_db() -> None:
    async with _async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Add new columns to existing pid_documents table (idempotent)
    await _migrate_pid_documents_columns()
    await _migrate_sop_documents_pid_nullable()
    await _migrate_validation_runs_sop_id()


async def _migrate_pid_documents_columns() -> None:
    """Add page_num, text_metadata, upload_batch_id if they don't exist."""
    from sqlalchemy import text
    try:
        async with _async_engine.connect() as conn:
            async with conn.begin():
                for col, sql_type in [
                    ("page_num", "INTEGER"),
                    ("text_metadata", "TEXT"),
                    ("upload_batch_id", "VARCHAR(36)"),
                ]:
                    await conn.execute(text(
                        f"ALTER TABLE pid_documents ADD COLUMN IF NOT EXISTS {col} {sql_type}"
                    ))
    except Exception as e:
        if "does not exist" not in str(e).lower():
            raise


async def _migrate_sop_documents_pid_nullable() -> None:
    """Make sop_documents.pid_id nullable (SOP can be standalone)."""
    from sqlalchemy import text
    try:
        async with _async_engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text(
                    "ALTER TABLE sop_documents ALTER COLUMN pid_id DROP NOT NULL"
                ))
    except Exception as e:
        if "does not exist" not in str(e).lower() and "already" not in str(e).lower():
            raise


async def _migrate_validation_runs_sop_id() -> None:
    """Add sop_id to validation_runs (SOP can link to multiple P&IDs)."""
    from sqlalchemy import text
    try:
        async with _async_engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text(
                    "ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS sop_id VARCHAR(36) REFERENCES sop_documents(id) ON DELETE SET NULL"
                ))
    except Exception as e:
        if "does not exist" not in str(e).lower() and "already" not in str(e).lower():
            raise
