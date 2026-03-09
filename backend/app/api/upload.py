"""Upload endpoints: P&ID and SOP."""
import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.db.models import PidDocument, SopDocument
from app.schemas.api import UploadPidResponse
from app.services.pid_service import get_pdf_page_count, run_pipeline
from app.services.sop_service import ingest_sop_with_gemini
from app.services.vector_store import add_pid_to_vector_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["upload"])


def _process_pdf_multi_page(file_path: Path, file_name: str) -> list[tuple[dict, str, int]]:
    """Process each PDF page. Returns list of (graph, text_metadata, page_num) per page."""
    page_count = get_pdf_page_count(file_path)
    results = []
    for page_idx in range(page_count):
        graph, text_metadata = run_pipeline(file_path, page_index=page_idx)
        results.append((graph, text_metadata, page_idx + 1))  # 1-based page_num
    return results


def _process_single_image(file_path: Path) -> tuple[dict, str]:
    """Process single image or PDF first page. Returns (graph, text_metadata)."""
    graph, text_metadata = run_pipeline(file_path)
    return graph, text_metadata


@router.post("/upload/pid", response_model=UploadPidResponse)
async def upload_pid(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a P&ID PDF (or image). Processes each page; stores graph + text metadata in DB and vector DB. Returns first pid_id."""
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    if not file.filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tiff")):
        raise HTTPException(400, "Allowed: PDF, PNG, JPG, TIFF")

    settings = get_settings()
    upload_dir = Path(settings.pid_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_batch_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix or ".pdf"
    file_path = upload_dir / f"{upload_batch_id}{ext}"

    try:
        with file_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Save failed: {e}")

    is_pdf = ext.lower() == ".pdf"

    def run():
        try:
            if is_pdf:
                return _process_pdf_multi_page(file_path, file.filename or ""), None
            else:
                graph, text_metadata = _process_single_image(file_path)
                return [(graph, text_metadata, 1)], None
        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            return None, str(e)

    loop = asyncio.get_event_loop()
    page_results, err = await loop.run_in_executor(None, run)

    if err:
        rec = PidDocument(
            id=upload_batch_id,
            file_path=str(file_path),
            file_name=file.filename,
            status="failed",
            error_message=err[:2000],
        )
        db.add(rec)
        await db.commit()
        raise HTTPException(500, f"Pipeline failed: {err}")

    first_pid_id = None
    for i, (graph, text_metadata, page_num) in enumerate(page_results):
        pid_id = str(uuid.uuid4()) if len(page_results) > 1 else upload_batch_id
        if first_pid_id is None:
            first_pid_id = pid_id

        rec = PidDocument(
            id=pid_id,
            file_path=str(file_path),
            file_name=file.filename,
            status="completed",
            graph_json=graph,
            page_num=page_num if len(page_results) > 1 else None,
            text_metadata=text_metadata or None,
            upload_batch_id=upload_batch_id if len(page_results) > 1 else None,
        )
        db.add(rec)

        if text_metadata:
            logger.info("Adding pid_id=%s (page %s) to vector DB", pid_id, page_num)
            add_pid_to_vector_db(
                pid_id=pid_id,
                text_metadata=text_metadata,
                file_name=file.filename,
                page_num=page_num if len(page_results) > 1 else None,
                upload_batch_id=upload_batch_id if len(page_results) > 1 else None,
            )

    await db.commit()
    return UploadPidResponse(
        pid_id=first_pid_id or upload_batch_id,
        upload_batch_id=upload_batch_id if len(page_results) > 1 else None,
    )


@router.post("/upload/sop", response_model=dict)
async def upload_sop(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload an SOP document (.docx or .txt). Stores file, runs Gemini extraction. Returns sop_id. Matching P&IDs found via vector search when validating."""
    if not file.filename or not file.filename.lower().endswith((".docx", ".txt")):
        raise HTTPException(400, "Allowed: .docx, .txt")

    settings = get_settings()
    upload_dir = Path(settings.sop_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    sop_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix or ".docx"
    file_path = upload_dir / f"{sop_id}_{file.filename}"

    try:
        with file_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Save failed: {e}")

    extracted = ingest_sop_with_gemini(file_path, sop_id)

    sop_rec = SopDocument(
        id=sop_id,
        file_path=str(file_path),
        file_name=file.filename,
        extracted_text=extracted.get("extracted_text"),
        extracted_json=extracted,
    )
    db.add(sop_rec)
    await db.commit()
    return {"sop_id": sop_id}
