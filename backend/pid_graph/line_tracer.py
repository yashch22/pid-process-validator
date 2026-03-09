"""
line_tracer.py — Pipe / line tracing for P&ID images.

Algorithm (PID2Graph 2411.13929v3 + skeleton fallback)
------------------------------------------------------
When use_pid2graph_lines is True (default):
1. Morphological H/V line detection (dilation + erosion with direction-specific
   kernels; paper: W//40 x 1 for horizontal, 1 x H//40 for vertical).
2. Remove H/V pixels from image; thin remainder; Progressive Probabilistic Hough
   for oblique lines (lower threshold for better coverage).
3. Reconstruct dashed lines: short segments → DBSCAN cluster → merge into full lines.
4. Merge with skeleton-derived segments for curved/complex paths and junctions.
5. Collinear merge + NMS; junction extraction; snap to symbols.

Otherwise: original skeleton + Hough merge only.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
from scipy import ndimage as ndi

from pid_graph.config import LineTracerConfig
from pid_graph.models import BoundingBox, Detection, Junction, LineSegment

log = logging.getLogger(__name__)

# Optional DBSCAN for dashed-line reconstruction (paper Section 3.3-c)
try:
    from sklearn.cluster import DBSCAN
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Point   = Tuple[int, int]
NodeMap = Dict[str, List[str]]  # node_id → [connected node_ids]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def trace_lines(
    binary: np.ndarray,
    detections: List[Detection],
    cfg: LineTracerConfig | None = None,
) -> Tuple[List[LineSegment], List[Junction], NodeMap]:
    """
    Full line-tracing pipeline.

    Parameters
    ----------
    binary     : white-on-black binary image (symbols already masked out)
    detections : detected symbols (for endpoint snapping)
    cfg        : LineTracerConfig

    Returns
    -------
    segments    : detected pipe segments
    junctions   : T / X crossing junctions
    connectivity: {node_id: [node_id, ...]} adjacency map
    """
    cfg = cfg or LineTracerConfig()

    # 1. Morphological cleanup
    clean = _morph_clean(binary, cfg)

    # 2. PID2Graph-style line detection (paper 2411.13929v3): H/V morph + thin + Hough + dashed
    paper_segments: List[LineSegment] = []
    if getattr(cfg, "use_pid2graph_lines", True):
        paper_segments = _pid2graph_line_detection(clean, cfg)
        log.debug("PID2Graph-style lines: %d segments", len(paper_segments))

    # 3. Skeletonize and trace (for junctions and curved/missed lines)
    skeleton = _skeletonize(clean)
    branch_pts, endpoint_pts = _find_skeleton_nodes(skeleton)
    raw_segments = _trace_skeleton_segments(skeleton, branch_pts, endpoint_pts, cfg)

    # 4. Hough on full clean (or on thinned remainder when paper is used, already in paper_segments)
    hough_segments = _hough_detect(clean, cfg)

    # 5. Merge: paper segments + skeleton + Hough (deduplicate by proximity)
    all_segments = _merge_segments(paper_segments + raw_segments, hough_segments, cfg)

    # 6. Collinear merge + NMS (pid2graph-inspired)
    all_segments = _merge_collinear_segments(all_segments, cfg)
    all_segments = _segment_nms(
        all_segments,
        getattr(cfg, "segment_nms_overlap_ratio", 0.6),
    )
    min_len = getattr(cfg, "segment_min_length_after_merge", 15)
    all_segments = [s for s in all_segments if s.length >= min_len]

    # 6b. Drop diagonal segments (P&ID pipes are horizontal/vertical only)
    if getattr(cfg, "filter_hv_only", True):
        all_segments = _filter_hv_segments(
            all_segments,
            getattr(cfg, "segment_hv_angle_deg", 5.0),
        )
        log.debug("After H/V filter: %d segments", len(all_segments))

    # 7. Junctions and cleanup
    junc_endpoint_r = getattr(cfg, "junction_endpoint_radius", 28)
    junctions = _build_junctions(branch_pts, all_segments, endpoint_radius=junc_endpoint_r)
    junc_radius = getattr(cfg, "junction_merge_radius_px", 20)
    junctions = _merge_nearby_junctions(junctions, float(junc_radius))
    min_deg = getattr(cfg, "junction_min_degree", 2)
    junctions = [j for j in junctions if len(j.connected_segs) >= min_deg]

    # 8. Snap endpoints to symbol centers
    connectivity = _snap_and_connect(all_segments, junctions, detections, cfg)

    log.info(
        "Line tracer: %d segments, %d junctions, %d connections",
        len(all_segments), len(junctions), sum(len(v) for v in connectivity.values()) // 2,
    )
    return all_segments, junctions, connectivity


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

def _morph_clean(binary: np.ndarray, cfg: LineTracerConfig) -> np.ndarray:
    """Remove small noise blobs and bridge tiny gaps."""
    k_open  = cv2.getStructuringElement(cv2.MORPH_RECT, (cfg.morph_open_ksize,)  * 2)
    k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (cfg.morph_close_ksize,) * 2)
    opened  = cv2.morphologyEx(binary, cv2.MORPH_OPEN,  k_open)
    closed  = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, k_close)
    return closed


# ---------------------------------------------------------------------------
# PID2Graph-style line detection (paper 2411.13929v3 Section 3.3-c)
# ---------------------------------------------------------------------------

def _morphological_hv_lines(
    binary: np.ndarray,
    cfg: LineTracerConfig,
) -> List[LineSegment]:
    """
    Detect horizontal and vertical lines via dilation/erosion with direction-specific
    kernels (paper: W//40 x 1 for H, 1 x H//40 for V). Returns LineSegment list.
    """
    H, W = binary.shape[:2]
    ratio = max(3, getattr(cfg, "morph_hv_ratio", 40))
    min_len = getattr(cfg, "hough_min_line_length", 30)
    segments: List[LineSegment] = []
    seg_id_prefix = "hv"

    for direction, (kwidth, kheight) in [("horizontal", (max(1, W // ratio), 1)), ("vertical", (1, max(1, H // ratio)))]:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kwidth, kheight))
        opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        num, labels, stats, _ = cv2.connectedComponentsWithStats(opened)
        for i in range(1, num):
            x, y, w, h, area = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3], stats[i, 4]
            if area < min_len:
                continue
            if direction == "horizontal":
                x1, y1, x2, y2 = x, y + h // 2, x + w, y + h // 2
            else:
                x1, y1, x2, y2 = x + w // 2, y, x + w // 2, y + h
            seg_id = f"{seg_id_prefix}_{direction}_{len(segments):04d}"
            segments.append(LineSegment(
                seg_id=seg_id,
                x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                line_type="main_process",
            ))
    return segments


def _thin_for_hough(binary: np.ndarray) -> np.ndarray:
    """
    Thin binary image to single-pixel lines for better Hough detection.
    Uses cv2.ximgproc.thinning when available (opencv-contrib-python), else skeletonize.
    """
    img = (binary > 0).astype(np.uint8) * 255
    if hasattr(cv2, "ximgproc") and hasattr(cv2.ximgproc, "thinning"):
        try:
            # ximgproc.thinning expects single-channel 8-bit (0 or 255)
            thinned = cv2.ximgproc.thinning(img)
            return thinned
        except Exception:
            pass
    return _skeletonize(binary)


def _reconstruct_dashed_dbscan(
    short_segments: List[LineSegment],
    cfg: LineTracerConfig,
) -> List[LineSegment]:
    """
    Cluster short segments (dashed-line fragments) with DBSCAN (midpoint + angle);
    merge each cluster into one line (bounding box of endpoints). Paper Section 3.3-c.
    """
    if not short_segments or not _HAS_SKLEARN:
        return short_segments  # return as-is if no sklearn or empty

    eps = getattr(cfg, "dbscan_eps", 15.0)
    min_samp = getattr(cfg, "dbscan_min_samples", 2)
    feats = []
    for s in short_segments:
        mx = (s.x1 + s.x2) / 2
        my = (s.y1 + s.y2) / 2
        angle = math.atan2(s.y2 - s.y1, s.x2 - s.x1) % math.pi
        feats.append([mx, my, angle * 100])
    X = np.array(feats)
    db = DBSCAN(eps=eps, min_samples=min_samp).fit(X)
    labels = db.labels_

    out: List[LineSegment] = []
    for lbl in set(labels):
        if lbl == -1:
            for i in np.where(labels == lbl)[0]:
                out.append(short_segments[i])  # keep noise as single segments
            continue
        idx = np.where(labels == lbl)[0]
        pts = np.array([[short_segments[i].x1, short_segments[i].y1,
                         short_segments[i].x2, short_segments[i].y2] for i in idx])
        x1 = int(pts[:, [0, 2]].min())
        y1 = int(pts[:, [1, 3]].min())
        x2 = int(pts[:, [0, 2]].max())
        y2 = int(pts[:, [1, 3]].max())
        out.append(LineSegment(
            seg_id=f"dashed_{lbl}_{len(out):04d}",
            x1=x1, y1=y1, x2=x2, y2=y2,
            line_type="instrument",
        ))
    return out


def _pid2graph_line_detection(clean: np.ndarray, cfg: LineTracerConfig) -> List[LineSegment]:
    """
    Full PID2Graph-style pipeline: morphological H/V lines, remove from image,
    thin remainder, Progressive Probabilistic Hough for obliques, then reconstruct
    dashed lines from short segments via DBSCAN.
    """
    # 1. Horizontal and vertical lines (morph)
    hv_segments = _morphological_hv_lines(clean, cfg)

    # 2. Remove H/V pixels so oblique Hough runs on remainder
    remaining = clean.copy()
    for s in hv_segments:
        cv2.line(remaining, (s.x1, s.y1), (s.x2, s.y2), 0, 3)

    # 3. Thin remainder and run Hough with lower threshold (paper: 20)
    thinned = _thin_for_hough(remaining)
    thresh_oblique = getattr(cfg, "hough_threshold_oblique", 20)
    oblique = _hough_detect(
        thinned, cfg,
        override_threshold=thresh_oblique,
        override_min_length=getattr(cfg, "hough_min_line_length", 30),
        override_max_gap=getattr(cfg, "hough_max_line_gap", 15),
    )

    all_segs = hv_segments + oblique
    dash_max = getattr(cfg, "dash_segment_max_length", 25)

    # 4. Split solid vs short (dashed candidates)
    solid, dashed_candidates = [], []
    for s in all_segs:
        if s.length <= dash_max:
            dashed_candidates.append(s)
        else:
            solid.append(s)

    # 5. Reconstruct dashed lines from short segments
    non_solid = _reconstruct_dashed_dbscan(dashed_candidates, cfg)
    return solid + non_solid


def _skeletonize(binary: np.ndarray) -> np.ndarray:
    """
    Skeletonize binary image to single-pixel centerlines.
    Uses iterative thinning (Zhang-Suen) via scikit-image when available,
    falls back to morphological approach otherwise.
    """
    bw = (binary > 0).astype(bool)
    try:
        from skimage.morphology import skeletonize  # type: ignore
        skel = skeletonize(bw)
        return skel.astype(np.uint8) * 255
    except ImportError:
        pass

    # Fallback: iterative morphological thinning
    img = bw.astype(np.uint8)
    skel = np.zeros_like(img)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    for _ in range(100):
        eroded   = cv2.erode(img, kernel)
        opened   = cv2.dilate(eroded, kernel)
        temp     = cv2.subtract(img, opened)
        skel     = cv2.bitwise_or(skel, temp)
        img      = eroded.copy()
        if cv2.countNonZero(img) == 0:
            break
    return skel


def _find_skeleton_nodes(
    skeleton: np.ndarray,
) -> Tuple[List[Point], List[Point]]:
    """
    Classify skeleton pixels as branch points (degree ≥ 3) or
    endpoints (degree == 1).

    Uses a 3×3 neighbour count convolution.
    """
    skel = (skeleton > 0).astype(np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    kernel[1, 1] = 0
    neighbour_count = cv2.filter2D(skel, -1, kernel.astype(np.float32))
    neighbour_count = (neighbour_count * skel).astype(np.uint8)

    branch_mask   = (skel == 1) & (neighbour_count >= 3)
    endpoint_mask = (skel == 1) & (neighbour_count == 1)

    branch_pts   = list(zip(*np.where(branch_mask)[::-1]))   # (x, y)
    endpoint_pts = list(zip(*np.where(endpoint_mask)[::-1]))

    return branch_pts, endpoint_pts


def _trace_skeleton_segments(
    skeleton: np.ndarray,
    branch_pts: List[Point],
    endpoint_pts: List[Point],
    cfg: LineTracerConfig,
) -> List[LineSegment]:
    """
    Walk from each endpoint / branch point along the skeleton until we reach
    another branch/endpoint.  Each walk becomes a LineSegment.
    """
    skel    = (skeleton > 0).astype(np.uint8)
    nodes   = set(map(tuple, branch_pts)) | set(map(tuple, endpoint_pts))
    visited_edges: Set[Tuple] = set()
    segments: List[LineSegment] = []

    def neighbours(x: int, y: int) -> List[Point]:
        h, w = skel.shape
        pts = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and skel[ny, nx]:
                    pts.append((nx, ny))
        return pts

    for start in list(nodes):
        sx, sy = start
        for nx, ny in neighbours(sx, sy):
            if not skel[ny, nx]:
                continue
            edge_key = (min(start, (nx, ny)), max(start, (nx, ny)))
            if edge_key in visited_edges:
                continue
            # Walk
            path = [start, (nx, ny)]
            prev = start
            cur  = (nx, ny)
            while cur not in nodes:
                nbs = [n for n in neighbours(*cur) if n != prev and skel[n[1], n[0]]]
                if not nbs:
                    break
                prev, cur = cur, nbs[0]
                path.append(cur)

            edge_key = (min(start, cur), max(start, cur))
            if edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)

            if len(path) < 2:
                continue
            seg_len = sum(
                math.hypot(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])
                for i in range(len(path)-1)
            )
            if seg_len < cfg.prune_branch_length:
                continue

            seg_id = f"seg_{len(segments):04d}"
            segments.append(LineSegment(
                seg_id=seg_id,
                x1=int(path[0][0]), y1=int(path[0][1]),
                x2=int(path[-1][0]), y2=int(path[-1][1]),
                line_type=_classify_line_type(path),
            ))

    return segments


def _hough_detect(
    binary: np.ndarray,
    cfg: LineTracerConfig,
    override_threshold: Optional[int] = None,
    override_min_length: Optional[int] = None,
    override_max_gap: Optional[int] = None,
) -> List[LineSegment]:
    """Probabilistic Hough transform for straight pipe segments."""
    segments: List[LineSegment] = []
    threshold = override_threshold if override_threshold is not None else cfg.hough_threshold
    min_len = override_min_length if override_min_length is not None else cfg.hough_min_line_length
    max_gap = override_max_gap if override_max_gap is not None else cfg.hough_max_line_gap
    lines = cv2.HoughLinesP(
        binary,
        rho=cfg.hough_rho,
        theta=np.deg2rad(cfg.hough_theta_deg),
        threshold=threshold,
        minLineLength=min_len,
        maxLineGap=max_gap,
    )
    if lines is None:
        return segments
    for i, line in enumerate(lines):
        x1, y1, x2, y2 = line[0].tolist()
        length = math.hypot(x2 - x1, y2 - y1)
        if length < min_len:
            continue
        segments.append(LineSegment(
            seg_id=f"hough_{i:04d}",
            x1=x1, y1=y1, x2=x2, y2=y2,
            line_type="main_process",
        ))
    log.debug("Hough detected %d raw line segments", len(segments))
    return segments


def _merge_segments(
    skeleton_segs: List[LineSegment],
    hough_segs: List[LineSegment],
    cfg: LineTracerConfig,
) -> List[LineSegment]:
    """
    Deduplicate skeleton + Hough segments using endpoint proximity.
    Prefer skeleton segments (more accurate path) when overlap exists.
    """
    merged = list(skeleton_segs)
    snap = cfg.snap_radius // 2

    for hs in hough_segs:
        # Check if any existing segment is very close to this Hough segment
        duplicate = False
        for ss in merged:
            d1 = _pt_dist((hs.x1, hs.y1), (ss.x1, ss.y1))
            d2 = _pt_dist((hs.x2, hs.y2), (ss.x2, ss.y2))
            d3 = _pt_dist((hs.x1, hs.y1), (ss.x2, ss.y2))
            d4 = _pt_dist((hs.x2, hs.y2), (ss.x1, ss.y1))
            if min(d1 + d2, d3 + d4) < snap * 4:
                duplicate = True
                break
        if not duplicate:
            merged.append(hs)

    return merged


# ---------------------------------------------------------------------------
# Segment merge (pid2graph-inspired: reduce duplicates and spurious fragments)
# ---------------------------------------------------------------------------

def _segment_angle_rad(seg: LineSegment) -> float:
    """Angle of segment in radians, in [-pi, pi]."""
    dx = seg.x2 - seg.x1
    dy = seg.y2 - seg.y1
    return math.atan2(dy, dx)


def _filter_hv_segments(
    segments: List[LineSegment],
    tolerance_deg: float,
) -> List[LineSegment]:
    """Keep only segments within tolerance_deg of horizontal (0°) or vertical (±90°)."""
    out: List[LineSegment] = []
    for s in segments:
        a_rad = _segment_angle_rad(s)
        a_deg = math.degrees(a_rad)
        if a_deg > 90:
            a_deg -= 180
        if a_deg < -90:
            a_deg += 180
        if abs(a_deg) <= tolerance_deg:
            out.append(s)
            continue
        if abs(abs(a_deg) - 90) <= tolerance_deg:
            out.append(s)
    return out


def _project_point_onto_segment(
    px: float, py: float,
    x1: float, y1: float, x2: float, y2: float,
) -> Tuple[float, float]:
    """Project point (px,py) onto line through (x1,y1)-(x2,y2). Returns (t, dist) where t is param [0,1] along segment."""
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        return 0.0, _pt_dist((px, py), (x1, y1))
    t = ((px - x1) * dx + (py - y1) * dy) / length_sq
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    dist = _pt_dist((px, py), (proj_x, proj_y))
    return t, dist


def _segments_connectable(
    s1: LineSegment,
    s2: LineSegment,
    angle_deg: float,
    gap_px: float,
) -> bool:
    """True if s1 and s2 are roughly colinear and endpoints are within gap (so they can be merged)."""
    a1 = _segment_angle_rad(s1)
    a2 = _segment_angle_rad(s2)
    diff = abs(math.atan2(math.sin(a1 - a2), math.cos(a1 - a2)))
    if math.degrees(diff) > angle_deg:
        return False
    # Check if any endpoint of s2 is near the line of s1 (and vice versa)
    for (px, py) in [(s2.x1, s2.y1), (s2.x2, s2.y2)]:
        _, d = _project_point_onto_segment(px, py, s1.x1, s1.y1, s1.x2, s1.y2)
        if d <= gap_px:
            return True
    for (px, py) in [(s1.x1, s1.y1), (s1.x2, s1.y2)]:
        _, d = _project_point_onto_segment(px, py, s2.x1, s2.y1, s2.x2, s2.y2)
        if d <= gap_px:
            return True
    return False


def _merge_two_segments(s1: LineSegment, s2: LineSegment) -> LineSegment:
    """Merge two colinear segments into one: endpoints farthest apart (axis-aligned span)."""
    pts = [(s1.x1, s1.y1), (s1.x2, s1.y2), (s2.x1, s2.y1), (s2.x2, s2.y2)]
    # Order along the dominant direction (use first segment's angle)
    angle = _segment_angle_rad(s1)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    def param(p):
        return p[0] * cos_a + p[1] * sin_a
    ordered = sorted(pts, key=param)
    (x1, y1), (x2, y2) = ordered[0], ordered[-1]
    return LineSegment(
        seg_id=s1.seg_id,
        x1=x1, y1=y1, x2=x2, y2=y2,
        line_type=s1.line_type,
        line_number=s1.line_number,
    )


def _merge_collinear_segments(
    segments: List[LineSegment],
    cfg: LineTracerConfig,
) -> List[LineSegment]:
    """
    Merge segments that lie on the same line and are within gap_px.
    Iteratively merge pairs until no more are connectable.
    """
    if not segments:
        return []
    angle_deg = getattr(cfg, "segment_colinear_angle_deg", 8.0)
    gap_px = getattr(cfg, "segment_merge_gap_px", 25)
    out: List[LineSegment] = list(segments)
    while True:
        merged_any = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                if _segments_connectable(out[i], out[j], angle_deg, gap_px):
                    out[i] = _merge_two_segments(out[i], out[j])
                    out.pop(j)
                    merged_any = True
                    break
            if merged_any:
                break
        if not merged_any:
            break
    for idx, seg in enumerate(out):
        seg.seg_id = f"seg_{idx:04d}"
    return out


def _segment_overlap_ratio(short_seg: LineSegment, long_seg: LineSegment) -> float:
    """
    How much of the shorter segment (in length) is covered by the longer?
    Project short segment endpoints onto long segment; compute overlap in parameter space.
    """
    if short_seg.length > long_seg.length:
        short_seg, long_seg = long_seg, short_seg
    t1, _ = _project_point_onto_segment(
        short_seg.x1, short_seg.y1,
        long_seg.x1, long_seg.y1, long_seg.x2, long_seg.y2,
    )
    t2, _ = _project_point_onto_segment(
        short_seg.x2, short_seg.y2,
        long_seg.x1, long_seg.y1, long_seg.x2, long_seg.y2,
    )
    t_lo, t_hi = min(t1, t2), max(t1, t2)
    # Overlap of [t_lo, t_hi] with [0, 1]
    overlap = max(0, min(t_hi, 1) - max(t_lo, 0))
    return overlap


def _segment_nms(
    segments: List[LineSegment],
    overlap_ratio_threshold: float,
) -> List[LineSegment]:
    """
    NMS over segments: keep longer segments, suppress shorter ones that overlap
    by at least overlap_ratio_threshold (proportion of shorter segment covered by longer).
    """
    if not segments:
        return []
    by_length = sorted(segments, key=lambda s: -s.length)
    keep: List[LineSegment] = []
    for cand in by_length:
        suppressed = False
        for kept in keep:
            if _segment_overlap_ratio(cand, kept) >= overlap_ratio_threshold:
                suppressed = True
                break
        if not suppressed:
            keep.append(cand)
    return keep


def _merge_nearby_junctions(
    junctions: List[Junction],
    radius_px: float,
) -> List[Junction]:
    """
    Merge junctions whose positions are within radius_px (pid2graph-style:
    one entity per crossing instead of many tiny ones).
    """
    if not junctions or radius_px <= 0:
        return junctions
    merged: List[Junction] = []
    used = [False] * len(junctions)

    for i, ja in enumerate(junctions):
        if used[i]:
            continue
        cluster = [ja]
        used[i] = True
        for j in range(i + 1, len(junctions)):
            if used[j]:
                continue
            jb = junctions[j]
            if _pt_dist((ja.x, ja.y), (jb.x, jb.y)) <= radius_px:
                cluster.append(jb)
                used[j] = True
        # One junction per cluster: centroid, union of connected_segs
        cx = sum(j.x for j in cluster) / len(cluster)
        cy = sum(j.y for j in cluster) / len(cluster)
        all_segs = []
        for j in cluster:
            all_segs.extend(j.connected_segs)
        merged.append(Junction(
            junc_id=cluster[0].junc_id,
            x=int(cx), y=int(cy),
            connected_segs=list(dict.fromkeys(all_segs)),
        ))
    return merged


def _build_junctions(
    branch_pts: List[Point],
    segments: List[LineSegment],
    endpoint_radius: int = 28,
) -> List[Junction]:
    """Create Junction objects at branch point locations. Segment endpoints
    within endpoint_radius of a branch point are associated so connectivity
    can link via the junction."""
    junctions: List[Junction] = []
    for i, (bx, by) in enumerate(branch_pts):
        junc = Junction(junc_id=f"junc_{i:04d}", x=bx, y=by)
        for seg in segments:
            if _pt_dist((bx, by), (seg.x1, seg.y1)) <= endpoint_radius:
                junc.connected_segs.append(seg.seg_id)
            elif _pt_dist((bx, by), (seg.x2, seg.y2)) <= endpoint_radius:
                junc.connected_segs.append(seg.seg_id)
        junctions.append(junc)
    return junctions


def _pt_to_bbox_dist(px: float, py: float, bbox: BoundingBox) -> float:
    """
    Distance from point (px, py) to the nearest point on the bbox (0 if inside).
    """
    x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2
    dx = 0.0 if x1 <= px <= x2 else min(abs(px - x1), abs(px - x2))
    dy = 0.0 if y1 <= py <= y2 else min(abs(py - y1), abs(py - y2))
    return math.hypot(dx, dy)


def _snap_and_connect(
    segments: List[LineSegment],
    junctions: List[Junction],
    detections: List[Detection],
    cfg: LineTracerConfig,
) -> NodeMap:
    """
    For each pipe segment endpoint, find the nearest symbol node or junction
    within snap_radius. When snap_to_bbox is True, symbols are considered
    "reached" if the endpoint is within snap_radius of the symbol bbox (not
    just center), so lines that end at the edge of a symbol still form edges.
    When extended_snap_radius > 0, if one endpoint snaps and the other does not,
    the other can still snap within the extended radius to create the edge.
    """
    snap_r = cfg.snap_radius
    use_bbox = getattr(cfg, "snap_to_bbox", True)
    extended_r = getattr(cfg, "extended_snap_radius", 0)
    connectivity: Dict[str, List[str]] = defaultdict(list)

    # Nodes: (node_id, distance_fn) where distance_fn(px, py) -> distance
    def dist_bbox(px: float, py: float, det: Detection) -> float:
        return _pt_to_bbox_dist(px, py, det.bbox)

    def dist_center(px: float, py: float, cx: float, cy: float) -> float:
        return _pt_dist((px, py), (cx, cy))

    # Each entry: (node_id, Detection for bbox-distance or (x,y) for center-distance)
    snap_entries: List[Tuple[str, object]] = []
    for det in detections:
        snap_entries.append((det.node_id, det if use_bbox else det.bbox.center))
    for junc in junctions:
        snap_entries.append((junc.junc_id, (float(junc.x), float(junc.y))))

    def nearest_node(px: float, py: float, max_radius: float) -> Optional[str]:
        best_id, best_dist = None, float("inf")
        for nid, ref in snap_entries:
            if isinstance(ref, Detection):
                d = dist_bbox(px, py, ref)
            else:
                cx, cy = ref
                d = dist_center(px, py, cx, cy)
            if d < best_dist:
                best_dist, best_id = d, nid
        return best_id if best_dist <= max_radius else None

    for seg in segments:
        a = nearest_node(seg.x1, seg.y1, snap_r)
        b = nearest_node(seg.x2, seg.y2, snap_r)

        # If one end didn't snap, try extended radius so we still get an edge
        if extended_r > snap_r:
            if a is None and b is not None:
                a = nearest_node(seg.x1, seg.y1, extended_r)
            elif b is None and a is not None:
                b = nearest_node(seg.x2, seg.y2, extended_r)

        if a and b and a != b:
            if b not in connectivity[a]:
                connectivity[a].append(b)
            if a not in connectivity[b]:
                connectivity[b].append(a)

    return dict(connectivity)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pt_dist(a: Tuple, b: Tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _classify_line_type(path: List[Point]) -> str:
    """
    Heuristic: classify a pipe path as main_process, instrument, or signal
    based on length.  Short paths are more likely instrument lines.
    """
    if len(path) < 2:
        return "unknown"
    total = sum(
        math.hypot(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])
        for i in range(len(path)-1)
    )
    if total < 40:
        return "signal"
    if total < 100:
        return "instrument"
    return "main_process"
