"""Vector store (Chroma) for P&ID document retrieval by text metadata."""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "pid_documents"


def _get_client():
    """Lazy Chroma client."""
    try:
        import chromadb
    except ImportError:
        return None
    settings = get_settings()
    persist_dir = Path(settings.chroma_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def add_pid_to_vector_db(
    pid_id: str,
    text_metadata: str,
    file_name: Optional[str] = None,
    page_num: Optional[int] = None,
    upload_batch_id: Optional[str] = None,
) -> bool:
    """
    Add a P&ID document to the vector store for retrieval.
    Uses text_metadata (all OCR text) as the document content.
    Returns True if added, False if Chroma unavailable.
    """
    logger.info("Vector DB add: pid_id=%s, file_name=%s, page_num=%s", pid_id, file_name, page_num)
    if not text_metadata or not text_metadata.strip():
        logger.warning("Vector DB add skipped for pid_id=%s: empty text_metadata", pid_id)
        return False

    client = _get_client()
    if not client:
        logger.warning("Vector DB add skipped: Chroma not installed (pid_id=%s)", pid_id)
        return False

    try:
        coll = client.get_or_create_collection(_COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
        metadata: Dict[str, Any] = {"pid_id": pid_id}
        if file_name:
            metadata["file_name"] = file_name
        if page_num is not None:
            metadata["page_num"] = page_num
        if upload_batch_id:
            metadata["upload_batch_id"] = upload_batch_id

        coll.upsert(
            ids=[pid_id],
            documents=[text_metadata.strip()],
            metadatas=[metadata],
        )
        logger.info("Added pid_id=%s to vector DB (page=%s)", pid_id, page_num)
        return True
    except Exception as e:
        logger.exception("Vector DB add failed for pid_id=%s: %s", pid_id, e)
        return False


def search_pids(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Search for relevant P&ID documents by text query.
    Returns list of {pid_id, file_name, page_num, upload_batch_id, distance}.
    """
    logger.info("Vector DB search: query=%r, top_k=%d", query[:200] + ("..." if len(query) > 200 else ""), top_k)
    client = _get_client()
    if not client:
        logger.warning("Vector DB search skipped: Chroma not installed")
        return []

    try:
        coll = client.get_or_create_collection(_COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
        count = coll.count()
        if count == 0:
            logger.info("Vector DB search: collection empty, no matches")
            return []

        results = coll.query(
            query_texts=[query],
            n_results=min(top_k, count),
            include=["metadatas", "distances"],
        )
        out: List[Dict[str, Any]] = []
        metadatas = results.get("metadatas", [[]])
        distances = results.get("distances", [[]])
        for i, meta in enumerate(metadatas[0] if metadatas else []):
            dist = distances[0][i] if distances and distances[0] else None
            out.append({
                "pid_id": meta.get("pid_id", ""),
                "file_name": meta.get("file_name"),
                "page_num": meta.get("page_num"),
                "upload_batch_id": meta.get("upload_batch_id"),
                "distance": dist,
            })
        pid_ids = [m["pid_id"] for m in out]
        logger.info("Vector DB search: found %d matches → pid_ids=%s", len(out), pid_ids)
        return out
    except Exception as e:
        logger.exception("Vector DB search failed: %s", e)
        return []
