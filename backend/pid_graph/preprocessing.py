"""
preprocessing.py — Image preprocessing for P&ID analysis.

Steps
-----
1. Greyscale conversion
2. Fast non-local means denoising
3. Adaptive threshold binarisation (Otsu fallback)
4. Morphological closing (bridge small gaps in lines)
5. Deskewing via Hough line angle histogram

All functions are pure (input → output) with no side-effects.
"""

from __future__ import annotations

import logging
import math
from typing import Tuple

import cv2
import numpy as np

from pid_graph.config import PreprocessConfig

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess(
    image: np.ndarray,
    cfg: PreprocessConfig | None = None,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Full preprocessing pipeline.

    Parameters
    ----------
    image : BGR numpy array (H, W, 3)
    cfg   : PreprocessConfig

    Returns
    -------
    gray      : greyscale image (H, W)
    binary    : binarised image, white lines on black background (H, W)
    skew_deg  : detected skew angle in degrees (positive = clockwise)
    """
    cfg = cfg or PreprocessConfig()

    # 1. Greyscale
    gray = to_gray(image)

    # 2. Denoise
    gray = denoise(gray, cfg)

    # 3. Deskew (updates gray in-place semantics)
    skew_deg = 0.0
    if cfg.deskew:
        gray, skew_deg = deskew(gray, cfg)

    # 4. Binarise
    binary = binarise(gray, cfg)

    # 5. Morph close (bridge small line breaks)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (cfg.morph_close_ksize, cfg.morph_close_ksize),
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    log.info(
        "Preprocessing done — size %s, skew %.2f°", gray.shape[::-1], skew_deg
    )
    return gray, binary, skew_deg


def to_gray(image: np.ndarray) -> np.ndarray:
    """Convert BGR or BGRA to greyscale."""
    if len(image.shape) == 2:
        return image
    if image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def denoise(gray: np.ndarray, cfg: PreprocessConfig) -> np.ndarray:
    """Apply fast non-local means denoising."""
    h = cfg.denoise_h
    if h <= 0:
        return gray
    return cv2.fastNlMeansDenoising(gray, h=h, templateWindowSize=7, searchWindowSize=21)


def binarise(gray: np.ndarray, cfg: PreprocessConfig) -> np.ndarray:
    """
    Adaptive threshold binarisation.

    Returns a binary image where lines/symbols are WHITE (255) and
    background is BLACK (0) — consistent with skeletonisation expectations.
    """
    # Adaptive threshold: pixels darker than local mean → foreground
    bsize = cfg.adaptive_block_size
    if bsize % 2 == 0:
        bsize += 1

    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,     # invert: dark strokes → white
        bsize,
        cfg.adaptive_C,
    )

    # Fallback: if adaptive result is mostly white (bad scan), use Otsu
    white_fraction = np.sum(binary > 0) / binary.size
    if white_fraction > 0.6:
        log.warning(
            "Adaptive threshold gave %.0f%% white — falling back to Otsu",
            white_fraction * 100,
        )
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )

    return binary


def deskew(
    gray: np.ndarray,
    cfg: PreprocessConfig,
) -> Tuple[np.ndarray, float]:
    """
    Detect and correct document skew using Hough line angle histogram.

    Returns corrected greyscale image and the angle applied (degrees).
    """
    angle_range = cfg.deskew_angle_range

    # Edge detect for Hough
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)
    if lines is None or len(lines) < 5:
        log.debug("Deskew: not enough Hough lines — skipping")
        return gray, 0.0

    # Collect angles of near-horizontal lines
    angles = []
    for line in lines[:200]:
        rho, theta = line[0]
        # theta is angle of the normal; convert to line angle
        angle_deg = math.degrees(theta) - 90  # shift to [-90, 90)
        if abs(angle_deg) <= angle_range:
            angles.append(angle_deg)

    if not angles:
        return gray, 0.0

    # Weighted median
    skew = float(np.median(angles))
    if abs(skew) < 0.2:
        return gray, 0.0

    log.info("Deskewing by %.2f°", -skew)
    h, w = gray.shape
    center = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(center, skew, 1.0)
    rotated = cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated, skew


def remove_text_regions(
    binary: np.ndarray,
    text_bboxes: list,
    padding: int = 4,
) -> np.ndarray:
    """
    Zero-out (blank) text regions in the binary image so OCR regions
    don't interfere with line tracing.

    text_bboxes : list of BoundingBox objects
    """
    result = binary.copy()
    h, w = result.shape[:2]
    for bb in text_bboxes:
        x1 = max(0, bb.x1 - padding)
        y1 = max(0, bb.y1 - padding)
        x2 = min(w, bb.x2 + padding)
        y2 = min(h, bb.y2 + padding)
        result[y1:y2, x1:x2] = 0
    return result


def mask_symbol_regions(
    binary: np.ndarray,
    detections: list,
    padding: int = 8,
) -> np.ndarray:
    """
    Zero-out bounding boxes of detected symbols from the binary image.
    This leaves only pipes/lines for the line tracer.

    detections : list of Detection objects
    """
    result = binary.copy()
    h, w = result.shape[:2]
    for det in detections:
        bb = det.bbox
        x1 = max(0, bb.x1 - padding)
        y1 = max(0, bb.y1 - padding)
        x2 = min(w, bb.x2 + padding)
        y2 = min(h, bb.y2 + padding)
        result[y1:y2, x1:x2] = 0
    return result


def enhance_for_ocr(gray: np.ndarray) -> np.ndarray:
    """
    Additional sharpening step to improve OCR on small / blurry labels.
    """
    # Unsharp mask
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    sharp = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
    # CLAHE for contrast
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(sharp)
