"""
straight_line_detector.py — CV algorithm for P&ID straight pipe line detection.

Recovers full continuous pipe runs interrupted by equipment symbols, text, and
dimension lines using:
  Stage 1: Otsu thresholding (binary: dark lines = 255, background = 0)
  Stage 2: Morphological stroke isolation (40px H/V kernels → keep only long strokes)
  Stage 3: ROI masking (border, title block, spec header)
  Stage 4: Probabilistic Hough (maxLineGap=600 to bridge symbol gaps)
  Stage 5: Collinear fragment merging
  Stage 6: Connect lines to equipment (T_perp snap) → graph edges

Use on the raw binary (before masking symbols) so pipes can be bridged across symbols.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from pid_graph.config import StraightLineDetectorConfig
from pid_graph.models import BoundingBox, Detection, LineSegment

log = logging.getLogger(__name__)

# Type alias: node_id -> list of connected node_ids
NodeMap = Dict[str, List[str]]

# Angle tolerance for strict H/V filtering (degrees)
ANGLE_TOLERANCE_DEG = 3.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_straight_lines(
    binary: np.ndarray,
    detections: List[Detection],
    gray: Optional[np.ndarray] = None,
    cfg: Optional[StraightLineDetectorConfig] = None,
) -> Tuple[List[LineSegment], NodeMap]:
    """
    Full straight-line detection pipeline for P&ID pipes.

    Parameters
    ----------
    binary     : Binary image (white lines = 255, black background = 0).
                 Use raw binary *before* masking symbols so Hough can bridge gaps.
    detections : YOLO (or classical) equipment bounding boxes.
    gray       : Optional grayscale; if provided, Stage 1 uses Otsu on it.
    cfg        : StraightLineDetectorConfig.

    Returns
    -------
    segments    : Detected straight line segments (after merge).
    connectivity: {node_id: [node_id, ...]} — equipment on same pipe → edges.
    """
    cfg = cfg or StraightLineDetectorConfig()

    # Stage 1: Ensure binary (Otsu if gray given and use_otsu)
    if gray is not None and cfg.use_otsu_stage:
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )

    H, W = binary.shape[:2]

    # Stage 2: Morphological stroke isolation (H and V masks, then OR)
    kernel_len = cfg.morph_kernel_length
    k_h = cv2.getStructuringElement(
        cv2.MORPH_RECT, (min(kernel_len, W), 1)
    )
    k_v = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, min(kernel_len, H))
    )
    opened_h = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_h)
    opened_v = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_v)
    mask = cv2.bitwise_or(opened_h, opened_v)

    # Stage 3: ROI masking (border, title block, spec header)
    roi_mask = _build_roi_mask(mask, cfg)
    mask = cv2.bitwise_and(mask, roi_mask)

    # Stage 4: Probabilistic Hough on combined H+V mask
    segments = _hough_straight_lines(mask, cfg)
    # Strict angle filter: keep only near-horizontal and near-vertical
    segments = _filter_angle(segments, ANGLE_TOLERANCE_DEG)

    # Stage 5: Collinear fragment merging
    segments = _merge_collinear_fragments(segments, cfg)
    # Drop very short lines (noise)
    min_len = cfg.min_line_length_final
    segments = [s for s in segments if s.length >= min_len]

    # Stage 6: Which equipment boxes does each line pass through? → connectivity
    connectivity = _lines_to_equipment_edges(segments, detections, cfg)

    log.info(
        "Straight-line detector: %d segments, %d connections",
        len(segments),
        sum(len(v) for v in connectivity.values()) // 2,
    )
    return segments, connectivity


# ---------------------------------------------------------------------------
# Stage 3: ROI mask (black out non-pipe regions)
# ---------------------------------------------------------------------------

def _build_roi_mask(binary: np.ndarray, cfg: StraightLineDetectorConfig) -> np.ndarray:
    """
    Build a mask that is 255 in the drawing area and 0 in border/title/spec.
    Returns a single-channel uint8 image (255 = keep, 0 = black out).
    """
    H, W = binary.shape[:2]
    roi = np.ones((H, W), dtype=np.uint8) * 255

    if not cfg.roi_mask_enabled:
        return roi

    fill_ratio = cfg.roi_border_fill_ratio
    border_margin = cfg.roi_border_margin
    scan_limit = min(max(H, W) // 8, 200)  # scan up to 200px or 1/8 of image from each edge

    # 1) Outer border: find first row/col with significant fill, then black out a wide band
    # Top: mask from 0 to (first filled row + margin)
    for y in range(scan_limit):
        if y >= H:
            break
        if np.sum(binary[y, :] > 0) / max(W, 1) >= fill_ratio:
            roi[0 : min(H, y + border_margin), :] = 0
            break
    # Bottom
    for y in range(H - 1, max(H - scan_limit, 0), -1):
        if np.sum(binary[y, :] > 0) / max(W, 1) >= fill_ratio:
            roi[max(0, y - border_margin) : H, :] = 0
            break
    # Left
    for x in range(scan_limit):
        if x >= W:
            break
        if np.sum(binary[:, x] > 0) / max(H, 1) >= fill_ratio:
            roi[:, 0 : min(W, x + border_margin)] = 0
            break
    # Right
    for x in range(W - 1, max(W - scan_limit, 0), -1):
        if np.sum(binary[:, x] > 0) / max(H, 1) >= fill_ratio:
            roi[:, max(0, x - border_margin) : W] = 0
            break

    # 2) Title block: black out entire bottom-right zone (don't rely on line detection)
    # This removes border lines and grid lines inside the title block.
    title_bottom_frac = cfg.roi_title_bottom_frac
    title_right_frac = cfg.roi_title_right_frac
    y_lo = int(H * (1 - title_bottom_frac))
    x_lo = int(W * (1 - title_right_frac))
    roi[y_lo:H, x_lo:W] = 0

    # 3) Spec header: top 12% × centre third
    spec_top_frac = cfg.roi_spec_top_frac
    spec_height = int(H * spec_top_frac)
    spec_left = int(W / 3)
    spec_right = int(2 * W / 3)
    roi[0:spec_height, spec_left:spec_right] = 0

    return roi


# ---------------------------------------------------------------------------
# Stage 4: HoughLinesP + angle filter
# ---------------------------------------------------------------------------

def _hough_straight_lines(
    mask: np.ndarray,
    cfg: StraightLineDetectorConfig,
) -> List[LineSegment]:
    """Run HoughLinesP with large maxLineGap to bridge symbol gaps."""
    lines = cv2.HoughLinesP(
        mask,
        rho=cfg.hough_rho,
        theta=cfg.hough_theta_rad,
        threshold=cfg.hough_threshold,
        minLineLength=cfg.hough_min_line_length,
        maxLineGap=cfg.hough_max_line_gap,
    )
    if lines is None:
        return []
    segments: List[LineSegment] = []
    for i, line in enumerate(lines):
        x1, y1, x2, y2 = line[0].tolist()
        length = math.hypot(x2 - x1, y2 - y1)
        if length < cfg.hough_min_line_length:
            continue
        segments.append(
            LineSegment(
                seg_id=f"straight_{i:04d}",
                x1=int(x1),
                y1=int(y1),
                x2=int(x2),
                y2=int(y2),
                line_type="main_process",
            )
        )
    return segments


def _angle_deg(seg: LineSegment) -> float:
    """Angle of segment in degrees, in [-90, 90] for line direction."""
    dx = seg.x2 - seg.x1
    dy = seg.y2 - seg.y1
    return math.degrees(math.atan2(dy, dx))


def _filter_angle(
    segments: List[LineSegment],
    tolerance_deg: float,
) -> List[LineSegment]:
    """Keep only segments within tolerance_deg of 0° (horizontal) or 90° (vertical)."""
    out: List[LineSegment] = []
    for s in segments:
        a = _angle_deg(s)
        # Normalize to [-90, 90]
        if a > 90:
            a -= 180
        if a < -90:
            a += 180
        # Horizontal: angle near 0
        if abs(a) <= tolerance_deg:
            out.append(s)
            continue
        # Vertical: angle near ±90
        if abs(abs(a) - 90) <= tolerance_deg:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Stage 5: Collinear fragment merging
# ---------------------------------------------------------------------------

def _merge_collinear_fragments(
    segments: List[LineSegment],
    cfg: StraightLineDetectorConfig,
) -> List[LineSegment]:
    """Collinear collapse: same axis (coord_gap ≤ N), span gap ≤ span_gap_px → one segment."""
    if not segments:
        return []
    coord_gap = cfg.merge_coord_gap_px
    span_gap = cfg.merge_span_gap_px

    def horiz(seg: LineSegment) -> Tuple[float, float, float]:
        y = (seg.y1 + seg.y2) / 2
        x_lo, x_hi = min(seg.x1, seg.x2), max(seg.x1, seg.x2)
        return (y, x_lo, x_hi)

    def vert(seg: LineSegment) -> Tuple[float, float, float]:
        x = (seg.x1 + seg.x2) / 2
        y_lo, y_hi = min(seg.y1, seg.y2), max(seg.y1, seg.y2)
        return (x, y_lo, y_hi)

    out: List[LineSegment] = []

    for is_horizontal, get_attrs in [(True, horiz), (False, vert)]:
        cands = []
        for s in segments:
            dx, dy = abs(s.x2 - s.x1), abs(s.y2 - s.y1)
            if is_horizontal and dx >= dy:
                cands.append((get_attrs(s), s))
            elif not is_horizontal and dy > dx:
                cands.append((get_attrs(s), s))
        if not cands:
            continue
        # Sort by coord then start
        cands.sort(key=lambda t: (round(t[0][0] / coord_gap) * coord_gap, t[0][1]))
        # Merge: group by coord (within coord_gap), then merge spans
        groups: List[List[Tuple[float, float, float]]] = []
        for (coord, lo, hi), _ in cands:
            merged_into = None
            for g in groups:
                if abs(g[0][0] - coord) <= coord_gap:
                    merged_into = g
                    break
            if merged_into is None:
                groups.append([(coord, lo, hi)])
            else:
                # extend merged_into with (lo, hi) if overlap or close
                _, g_lo, g_hi = merged_into[-1]
                if lo <= g_hi + span_gap:
                    merged_into.append((coord, min(g_lo, lo), max(g_hi, hi)))
                else:
                    merged_into.append((coord, lo, hi))
        # Flatten each group to one span (min of los, max of his)
        for g in groups:
            if not g:
                continue
            coords = [t[0] for t in g]
            los = [t[1] for t in g]
            his = [t[2] for t in g]
            coord = sum(coords) / len(coords)
            span_lo, span_hi = min(los), max(his)
            if span_hi - span_lo < cfg.min_line_length_final:
                continue
            if is_horizontal:
                seg = LineSegment(
                    seg_id="",
                    x1=int(span_lo),
                    y1=int(round(coord)),
                    x2=int(span_hi),
                    y2=int(round(coord)),
                    line_type="main_process",
                )
            else:
                seg = LineSegment(
                    seg_id="",
                    x1=int(round(coord)),
                    y1=int(span_lo),
                    x2=int(round(coord)),
                    y2=int(span_hi),
                    line_type="main_process",
                )
            out.append(seg)

    for idx, seg in enumerate(out):
        seg.seg_id = f"straight_merged_{idx:04d}"
    return out


# ---------------------------------------------------------------------------
# Stage 6: Lines → equipment connectivity (T_perp snap)
# ---------------------------------------------------------------------------

def _lines_to_equipment_edges(
    segments: List[LineSegment],
    detections: List[Detection],
    cfg: StraightLineDetectorConfig,
) -> NodeMap:
    """
    For each line, find equipment boxes that lie on it (within T_perp perpendicular,
    and box center within line span + margin). Two boxes on the same line → edge.
    """
    T_perp = cfg.t_perp_px
    span_margin = cfg.line_span_margin_px
    connectivity: NodeMap = defaultdict(list)

    for seg in segments:
        box_ids_on_line: List[str] = []
        # Segment axis and span
        if abs(seg.x2 - seg.x1) >= abs(seg.y2 - seg.y1):
            # Horizontal line: y = const, x in [x_lo, x_hi]
            line_y = (seg.y1 + seg.y2) / 2
            x_lo = min(seg.x1, seg.x2) - span_margin
            x_hi = max(seg.x1, seg.x2) + span_margin
            for det in detections:
                cx, cy = det.bbox.center
                if abs(cy - line_y) <= T_perp and x_lo <= cx <= x_hi:
                    box_ids_on_line.append(det.node_id)
        else:
            # Vertical line: x = const, y in [y_lo, y_hi]
            line_x = (seg.x1 + seg.x2) / 2
            y_lo = min(seg.y1, seg.y2) - span_margin
            y_hi = max(seg.y1, seg.y2) + span_margin
            for det in detections:
                cx, cy = det.bbox.center
                if abs(cx - line_x) <= T_perp and y_lo <= cy <= y_hi:
                    box_ids_on_line.append(det.node_id)

        for i, a in enumerate(box_ids_on_line):
            for b in box_ids_on_line[i + 1 :]:
                if b not in connectivity[a]:
                    connectivity[a].append(b)
                if a not in connectivity[b]:
                    connectivity[b].append(a)

    return dict(connectivity)
