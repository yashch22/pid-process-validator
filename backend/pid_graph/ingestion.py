"""
ingestion.py — Load a P&ID from PDF or image file and produce tiles.

Supports:
  - PDF via PyMuPDF (fitz) when available, otherwise pdf2image / Pillow
  - PNG / JPEG / TIFF images directly
  - Tiling with configurable overlap for large sheets
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator, List, Tuple

import cv2
import numpy as np

from pid_graph.config import IngestionConfig

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_image(path: str | Path, cfg: IngestionConfig | None = None, page_index: int | None = None) -> np.ndarray:
    """
    Load a P&ID file (PDF or image) and return a single high-resolution
    numpy array (H, W, 3) in BGR colour space.

    For multi-page PDFs: pass page_index (0-based) to load that page.
    If page_index is None, the first page is used.
    For images, page_index is ignored.
    """
    cfg = cfg or IngestionConfig()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = list(load_pdf_pages(path, cfg))
        if not pages:
            raise ValueError(f"PDF has no renderable pages: {path}")
        idx = page_index if page_index is not None else 0
        if idx < 0 or idx >= len(pages):
            raise ValueError(f"PDF page_index {idx} out of range (0..{len(pages)-1})")
        return pages[idx]
    else:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"OpenCV could not read image: {path}")
        log.info("Loaded image %s → %s", path.name, img.shape[:2])
        return img


def load_pdf_pages(
    path: str | Path,
    cfg: IngestionConfig | None = None,
) -> Iterator[np.ndarray]:
    """Yield one BGR numpy array per PDF page at the configured DPI."""
    cfg = cfg or IngestionConfig()
    path = Path(path)
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        zoom = cfg.dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, 3
            )
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            log.info("PDF page %d rendered: %s", page_num + 1, bgr.shape[:2])
            yield bgr
        doc.close()
    except ImportError:
        log.warning("PyMuPDF not installed — falling back to pdf2image")
        yield from _load_pdf_pdf2image(path, cfg)


def tile_image(
    image: np.ndarray,
    cfg: IngestionConfig | None = None,
) -> List[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
    """
    Split *image* into overlapping tiles.

    Returns
    -------
    list of (tile_array, (x1, y1, x2, y2)) where coordinates are in the
    *full* image space — use them to map detections back to global coords.
    """
    cfg = cfg or IngestionConfig()
    h, w = image.shape[:2]
    tile_size = cfg.tile_size
    overlap = cfg.tile_overlap

    if tile_size == 0 or (h <= tile_size and w <= tile_size):
        return [(image, (0, 0, w, h))]

    step = int(tile_size * (1 - overlap))
    tiles = []

    y = 0
    while y < h:
        x = 0
        while x < w:
            x2 = min(x + tile_size, w)
            y2 = min(y + tile_size, h)
            tile = image[y:y2, x:x2]
            tiles.append((tile, (x, y, x2, y2)))
            if x2 == w:
                break
            x += step
        if y2 == h:
            break
        y += step

    log.info("Tiled %dx%d image into %d tiles of ~%dpx", w, h, len(tiles), tile_size)
    return tiles


def merge_tile_detections(
    tile_detections: List[Tuple[List, Tuple[int, int, int, int]]],
) -> List:
    """
    Shift detection bounding boxes from tile-local to full-image coordinates.

    *tile_detections* is a list of (detections, (tx1, ty1, tx2, ty2)) tuples
    where detections is a list of Detection objects.
    """
    from pid_graph.models import Detection, BoundingBox

    merged: List[Detection] = []
    for dets, (tx1, ty1, _, _) in tile_detections:
        for d in dets:
            bb = d.bbox
            d.bbox = BoundingBox(
                bb.x1 + tx1, bb.y1 + ty1,
                bb.x2 + tx1, bb.y2 + ty1,
            )
            merged.append(d)
    return merged


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_pdf_pdf2image(
    path: Path,
    cfg: IngestionConfig,
) -> Iterator[np.ndarray]:
    """Fallback: use pdf2image (requires poppler)."""
    try:
        from pdf2image import convert_from_path  # type: ignore

        pages = convert_from_path(str(path), dpi=cfg.dpi)
        for i, pil_img in enumerate(pages):
            arr = np.array(pil_img.convert("RGB"))
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            log.info("pdf2image page %d: %s", i + 1, bgr.shape[:2])
            yield bgr
    except ImportError:
        raise ImportError(
            "Neither PyMuPDF nor pdf2image is installed.  "
            "Install one of: pip install pymupdf  |  pip install pdf2image"
        )
