"""P&ID processing: run pipeline and store graph."""
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.core.config import get_settings
from app.services.graph_convert import graph_to_api_format

logger = logging.getLogger(__name__)

# Backend root = parent of app/ (so pid_graph and yolov5 live next to app/)
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _ensure_pid_graph_on_path() -> None:
    """Ensure backend root is on sys.path so pid_graph (backend/pid_graph) is importable."""
    root = get_settings().pid_graph_root
    if root:
        root = Path(root).resolve()
        if not root.exists():
            raise FileNotFoundError(f"PID_GRAPH_ROOT not found: {root}")
    else:
        root = _BACKEND_ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _text_metadata_from_result(result: Any) -> str:
    """Extract all OCR text from pipeline result for metadata/retrieval."""
    text_regions = getattr(result, "text_regions", None) or []
    parts: List[str] = []
    for tr in text_regions:
        text = getattr(tr, "text", None) or str(tr) if tr else ""
        if text and text.strip():
            parts.append(text.strip())
    # Also include labels from detections (node-associated text)
    for det in getattr(result, "detections", []) or []:
        label = getattr(det, "label", None) or getattr(det, "isa_tag", None)
        if label and label not in parts:
            parts.append(label)
    return " ".join(parts) if parts else ""


def run_pipeline(
    image_or_pdf_path: str | Path,
    page_index: int | None = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Run the pid_graph pipeline on a file (image or PDF page).
    Returns (API-format graph dict, text_metadata string for retrieval).
    For PDFs, pass page_index (0-based) to process a specific page.
    """
    _ensure_pid_graph_on_path()

    from pid_graph.pipeline import Pipeline
    from pid_graph.config import PipelineConfig

    path = Path(image_or_pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    settings = get_settings()
    cfg = PipelineConfig()
    cfg.report.output_dir = path.parent / "outputs"
    cfg.report.save_annotated_image = False
    cfg.report.save_graph_image = False
    cfg.report.save_json = False
    cfg.report.save_html = False
    if settings.yolo_weights_path and Path(settings.yolo_weights_path).exists():
        cfg.yolo.weights = Path(settings.yolo_weights_path)
    result = Pipeline(cfg).run(path, sop_path=None, page_index=page_index)

    graph = graph_to_api_format(result.graph)
    text_metadata = _text_metadata_from_result(result)
    return graph, text_metadata


def get_pdf_page_count(path: str | Path) -> int:
    """Return number of pages in a PDF. Returns 1 for non-PDF files."""
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return 1
    _ensure_pid_graph_on_path()
    from pid_graph.ingestion import load_pdf_pages
    return len(list(load_pdf_pages(path)))
