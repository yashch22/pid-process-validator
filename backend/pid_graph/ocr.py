"""
ocr.py — Text / label extraction for P&ID images.

Backends (auto-selected by OcrConfig.engine):
  "tesseract"  — pytesseract wrapper  (recommended fallback, always works)
  "paddleocr"  — PaddleOCR v3 PP-OCRv5  (best accuracy, needs paddle)
  "easyocr"    — EasyOCR  (good multilingual, simpler API)

All backends return the same List[TextRegion] contract.

ISA S5.1 Tag Parsing
---------------------
After OCR, instrument tags are normalised and parsed:
  "FCV-101"  → type_prefix="FCV", loop_number="101", isa_tag="FCV-101"
  "TE_3B"    → type_prefix="TE",  loop_number="3B",  isa_tag="TE-3B"

Label Association
-----------------
Each TextRegion is spatially associated with the nearest Detection whose
centre is within label_search_radius pixels.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from pid_graph.config import OcrConfig
from pid_graph.models import BoundingBox, Detection, TextRegion

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ISA tag utilities
# ---------------------------------------------------------------------------

_TAG_PATTERN = re.compile(
    r"\b([A-Z]{1,4})[_\-\s]?(\d{1,5}[A-Z]?)\b"
)

# Common OCR confusions in alphanumeric tags
_OCR_FIXES: Dict[str, str] = {
    "0": "O",  # zero ↔ O — context-dependent; prefer digits in number part
    "1": "I",
    "l": "1",
    "I": "1",
}

# ISA first-letter codes → instrument category
ISA_FIRST_LETTER: Dict[str, str] = {
    "F": "flow",
    "P": "pressure",
    "T": "temperature",
    "L": "level",
    "A": "analyzer",
    "S": "speed_vibration",
    "W": "weight",
    "H": "hand",
    "E": "electrical",
    "X": "unclassified",
    "Y": "event_state",
    "Z": "position",
}

ISA_SECOND_LETTER: Dict[str, str] = {
    "C": "controller",
    "I": "indicator",
    "T": "transmitter",
    "V": "control_valve",
    "E": "primary_element",
    "S": "switch",
    "R": "recorder",
    "A": "alarm",
    "G": "glass_gauge",
    "H": "high",
    "L": "low",
}


def parse_isa_tag(text: str) -> Optional[Tuple[str, str, str]]:
    """
    Parse ISA S5.1 instrument tag from raw OCR text.

    Returns
    -------
    (type_prefix, loop_number, normalised_tag) or None if no match.

    Examples
    --------
    >>> parse_isa_tag("FCV-101A")
    ("FCV", "101A", "FCV-101A")
    >>> parse_isa_tag("P-101")
    ("P", "101", "P-101")
    """
    text = text.upper().strip()
    m = _TAG_PATTERN.search(text)
    if not m:
        return None
    prefix = m.group(1)
    number = m.group(2)
    normalised = f"{prefix}-{number}"
    return prefix, number, normalised


def tag_to_component_hint(tag: str) -> str:
    """
    Map an ISA tag prefix to the most likely P&ID symbol class.

    e.g. "FCV" → "control_valve"  |  "PT" → "pressure_transmitter"
    """
    tag = tag.upper()
    if len(tag) >= 2:
        first = tag[0]
        second = tag[1]
        cat = ISA_FIRST_LETTER.get(first, "")
        func = ISA_SECOND_LETTER.get(second, "")
        if cat and func:
            return f"{cat}_{func}"
    if tag[0] in ISA_FIRST_LETTER:
        return ISA_FIRST_LETTER[tag[0]]
    return "unknown"


def normalise_ocr_text(text: str) -> str:
    """Light cleanup of OCR output for tag parsing."""
    # Remove garbage characters
    text = re.sub(r"[^A-Za-z0-9\-_ ]", "", text)
    text = text.strip().upper()
    return text


# ---------------------------------------------------------------------------
# Tesseract backend
# ---------------------------------------------------------------------------

class TesseractOCR:
    def __init__(self, cfg: OcrConfig):
        self.cfg = cfg
        self._available = False
        try:
            import pytesseract  # noqa: F401
            self._available = True
            log.info("Tesseract OCR available")
        except ImportError:
            log.warning("pytesseract not installed")

    @property
    def available(self) -> bool:
        return self._available

    def extract(self, image: np.ndarray) -> List[TextRegion]:
        if not self._available:
            return []
        import pytesseract

        gray = _to_gray(image)
        enhanced = _enhance_for_ocr(gray)

        # Use Tesseract OSD bounding-box output
        custom_cfg = (
            f"--oem 3 --psm {self.cfg.tesseract_psm} "
            f"-l {self.cfg.tesseract_lang}"
        )
        data = pytesseract.image_to_data(
            enhanced,
            output_type=pytesseract.Output.DICT,
            config=custom_cfg,
        )

        regions: List[TextRegion] = []
        n = len(data["text"])
        for i in range(n):
            text = str(data["text"][i]).strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = 0.0
            if conf < self.cfg.min_text_confidence * 100:
                continue

            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            if w < 3 or h < 3:
                continue

            regions.append(
                TextRegion(
                    text=normalise_ocr_text(text),
                    confidence=conf / 100.0,
                    bbox=BoundingBox(x, y, x + w, y + h),
                )
            )

        log.info("Tesseract: %d text regions", len(regions))
        return regions


# ---------------------------------------------------------------------------
# PaddleOCR backend
# ---------------------------------------------------------------------------

class PaddleOCRBackend:
    def __init__(self, cfg: OcrConfig):
        self.cfg = cfg
        self._ocr = None
        self._available = False
        try:
            from paddleocr import PaddleOCR  # type: ignore

            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                show_log=False,
            )
            self._available = True
            log.info("PaddleOCR backend loaded")
        except ImportError:
            log.info("PaddleOCR not installed")

    @property
    def available(self) -> bool:
        return self._available

    def extract(self, image: np.ndarray) -> List[TextRegion]:
        if not self._available or self._ocr is None:
            return []

        results = self._ocr.ocr(image, cls=True)
        regions: List[TextRegion] = []

        for line_group in (results or []):
            if line_group is None:
                continue
            for item in line_group:
                if not item:
                    continue
                poly, (text, conf) = item
                pts = np.array(poly, dtype=np.int32)
                x1, y1 = pts.min(axis=0)
                x2, y2 = pts.max(axis=0)

                if conf < self.cfg.min_text_confidence:
                    continue
                clean = normalise_ocr_text(str(text))
                if not clean:
                    continue

                regions.append(
                    TextRegion(
                        text=clean,
                        confidence=float(conf),
                        bbox=BoundingBox(int(x1), int(y1), int(x2), int(y2)),
                    )
                )

        log.info("PaddleOCR: %d text regions", len(regions))
        return regions


# ---------------------------------------------------------------------------
# EasyOCR backend
# ---------------------------------------------------------------------------

class EasyOCRBackend:
    def __init__(self, cfg: OcrConfig):
        self.cfg = cfg
        self._reader = None
        self._available = False
        try:
            import easyocr  # type: ignore

            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            self._available = True
            log.info("EasyOCR backend loaded")
        except ImportError:
            log.info("EasyOCR not installed")

    @property
    def available(self) -> bool:
        return self._available

    def extract(self, image: np.ndarray) -> List[TextRegion]:
        if not self._available or self._reader is None:
            return []

        results = self._reader.readtext(image, detail=1, paragraph=False)
        regions: List[TextRegion] = []
        for bbox_pts, text, conf in results:
            if conf < self.cfg.min_text_confidence:
                continue
            pts = np.array(bbox_pts, dtype=np.int32)
            x1, y1 = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            clean = normalise_ocr_text(str(text))
            if clean:
                regions.append(
                    TextRegion(
                        text=clean,
                        confidence=float(conf),
                        bbox=BoundingBox(int(x1), int(y1), int(x2), int(y2)),
                    )
                )

        log.info("EasyOCR: %d text regions", len(regions))
        return regions


# ---------------------------------------------------------------------------
# Fallback / heuristic-only extractor (pure OpenCV, no external OCR)
# ---------------------------------------------------------------------------

class HeuristicOCR:
    """
    When no OCR engine is installed, extract potential labels from
    the image using morphological analysis.

    Identifies text blobs by aspect ratio + connected component statistics
    and returns their bounding boxes with empty text (to be filled by manual
    review or a VLM call).
    """

    def __init__(self, cfg: OcrConfig):
        self.cfg = cfg
        log.warning(
            "No OCR engine available — using heuristic text-region detector. "
            "Install pytesseract, paddleocr, or easyocr for actual text extraction."
        )

    @property
    def available(self) -> bool:
        return True

    def extract(self, image: np.ndarray) -> List[TextRegion]:
        gray = _to_gray(image)
        # Adaptive threshold
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 25, 8,
        )

        # MSER for text blob candidates
        mser = cv2.MSER_create(
            _delta=5, _min_area=30, _max_area=3000,
            _max_variation=0.25,
        )
        regions, _ = mser.detectRegions(gray)

        text_regions: List[TextRegion] = []
        seen: set = set()
        for region in regions:
            x, y, w, h = cv2.boundingRect(region.reshape(-1, 1, 2))
            key = (x // 4, y // 4)  # cluster nearby detections
            if key in seen:
                continue
            seen.add(key)
            # Text-like aspect: wide and short
            ar = w / max(h, 1)
            if 0.15 < ar < 12 and 6 < h < 80:
                text_regions.append(
                    TextRegion(
                        text="",  # unknown without OCR
                        confidence=0.3,
                        bbox=BoundingBox(x, y, x + w, y + h),
                    )
                )

        log.info("Heuristic text detector: %d candidate regions", len(text_regions))
        return text_regions


# ---------------------------------------------------------------------------
# OCR orchestrator
# ---------------------------------------------------------------------------

class OCREngine:
    """
    Auto-selects the best available OCR backend and handles label ↔ symbol
    spatial association.
    """

    def __init__(self, cfg: OcrConfig | None = None):
        self.cfg = cfg or OcrConfig()
        self._backend = self._pick_backend()

    def _pick_backend(self):
        engine = self.cfg.engine.lower()
        if engine == "paddleocr":
            b = PaddleOCRBackend(self.cfg)
            if b.available:
                return b
        if engine == "easyocr":
            b = EasyOCRBackend(self.cfg)
            if b.available:
                return b
        if engine == "tesseract":
            b = TesseractOCR(self.cfg)
            if b.available:
                return b
        # Auto-fallback chain
        for cls in [PaddleOCRBackend, TesseractOCR, EasyOCRBackend]:
            b = cls(self.cfg)
            if b.available:
                return b
        return HeuristicOCR(self.cfg)

    def extract_text(self, image: np.ndarray) -> List[TextRegion]:
        """Run OCR on the full image, return all detected text regions."""
        return self._backend.extract(image)

    def associate_labels(
        self,
        text_regions: List[TextRegion],
        detections: List[Detection],
    ) -> List[Detection]:
        """
        Assign the nearest text label to each Detection.

        For each detection, find all TextRegions within label_search_radius
        of the detection centre, pick the highest-confidence one that parses
        as an ISA tag (or the highest-confidence one overall as fallback).
        """
        radius = self.cfg.label_search_radius

        for det in detections:
            cx, cy = det.bbox.center
            candidates: List[Tuple[float, TextRegion]] = []

            for tr in text_regions:
                tx, ty = tr.bbox.center
                dist = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                if dist <= radius:
                    candidates.append((dist, tr))

            if not candidates:
                continue

            # Prefer ISA-tag matching candidates
            isa_candidates = []
            for dist, tr in candidates:
                parsed = parse_isa_tag(tr.text)
                if parsed:
                    isa_candidates.append((dist, tr, parsed))

            if isa_candidates:
                # Closest ISA tag wins
                isa_candidates.sort(key=lambda x: x[0])
                _, best_tr, (prefix, number, norm_tag) = isa_candidates[0]
                det.label = best_tr.text
                det.isa_tag = norm_tag
                # Refine class based on ISA prefix if current class is generic
                if det.symbol_class in ("unknown", "junction"):
                    hint = tag_to_component_hint(prefix)
                    if hint != "unknown":
                        det.symbol_class = hint
                        det.attributes["class_source"] = "isa_tag_hint"
            else:
                # Use closest text as generic label
                candidates.sort(key=lambda x: x[0])
                det.label = candidates[0][1].text

        labelled = sum(1 for d in detections if d.label)
        log.info("Label association: %d/%d detections labelled", labelled, len(detections))
        return detections


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_gray(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 2:
        return image
    if image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _enhance_for_ocr(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    sharp = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(sharp)


def build_ocr_engine(cfg: OcrConfig | None = None) -> OCREngine:
    return OCREngine(cfg)
