"""Application configuration."""
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App settings from env."""

    app_name: str = "P&ID Backend"
    debug: bool = False

    # Storage (set via env in Docker, e.g. /data/uploads)
    upload_dir: Path = Path("data/uploads")
    pid_upload_dir: Path = Path("data/uploads/pid")
    sop_upload_dir: Path = Path("data/uploads/sop")
    chroma_persist_dir: Path = Path("data/chroma")

    # Database
    database_url: str = "postgresql+asyncpg://piduser:pidpass@localhost:5432/pid_db"
    database_url_sync: str = "postgresql://piduser:pidpass@localhost:5432/pid_db"

    # Pipeline lives in backend/pid_graph; override only if running from another layout
    pid_graph_root: Optional[Path] = None  # default: backend root (parent of app/)
    yolo_weights_path: Optional[Path] = None  # optional override for weights/best.pt

    # Gemini / LangChain
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3.1-flash-lite-preview"

    class Config:
        # Load .env from backend root so it works when run from project root or backend/
        env_file = str(Path(__file__).resolve().parent.parent.parent / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
