"""
ocr_node_injector.py — Post-YOLO OCR label association and gap filling.

Role in the YOLO-first pipeline
---------------------------------
YOLO gives us accurate bounding boxes but no text labels.
This module does two things:

1. associate_labels_to_yolo_dets()
   For each YOLO detection, find the nearest OCR word that looks like an
   ISA tag and attach it as det.isa_tag / det.label.

2. inject_missing_from_ocr()
   For any ISA tag found by OCR that has NO nearby YOLO detection
   (i.e. YOLO missed the symbol), inject a synthetic Detection so the
   graph is complete. Position is estimated from the text label location.
   This is the "gap filler" — it only fires for truly missed symbols.

3. build_connectivity_from_hough()
   Snap Hough line endpoints to detection centers to infer pipe connections.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from pid_graph.models import BoundingBox, Detection, TextRegion
from pid_graph.ocr import parse_isa_tag, tag_to_component_hint, ISA_FIRST_LETTER

log = logging.getLogger(__name__)

_DEFAULT_RADIUS = 25   # synthetic bbox half-size for injected nodes


# ---------------------------------------------------------------------------
def associate_labels_to_yolo_dets(
    text_regions: List[TextRegion],
    detections:   List[Detection],
    search_radius: int = 80,
) -> List[Detection]:
    """
    For each detection that has no isa_tag yet, search nearby OCR words
    for the closest ISA-pattern text and attach it.

    Works for both YOLO detections (accurate bboxes, no text) and
    classical detections.
    """
    for det in detections:
        if det.isa_tag:
            continue
        cx, cy = det.bbox.center
        best_tag = None
        best_dist = float("inf")
        best_conf = 0.0

        for tr in text_regions:
            tx, ty = tr.bbox.center
            dist = math.hypot(cx - tx, cy - ty)
            if dist > search_radius:
                continue
            parsed = parse_isa_tag(tr.text)
            if parsed:
                _, _, norm_tag = parsed
                if dist < best_dist or (dist == best_dist and tr.confidence > best_conf):
                    best_dist = dist
                    best_tag = norm_tag
                    best_conf = tr.confidence

        if best_tag:
            det.isa_tag = best_tag
            det.label = best_tag
            log.debug("Labelled %s → %s (dist=%.0fpx)", det.node_id, best_tag, best_dist)

    labelled = sum(1 for d in detections if d.isa_tag)
    log.info("Label association: %d/%d detections labelled", labelled, len(detections))
    return detections


# ---------------------------------------------------------------------------
def inject_missing_from_ocr(
    text_regions:  List[TextRegion],
    image:         np.ndarray,
    existing_dets: List[Detection],
    snap_radius:   int = 60,
) -> List[Detection]:
    """
    Gap filler: inject a Detection for each ISA tag that OCR found but
    YOLO did not detect nearby.

    Only fires when genuinely needed — if YOLO is good, this adds nothing.
    snap_radius should be small (50–80px) so we don't suppress real
    closely-spaced valves.
    """
    h, w = image.shape[:2]

    # Build best-tag-per-location map (avoid duplicate OCR hits for same tag)
    best_by_tag: Dict[str, Tuple[TextRegion, tuple]] = {}
    for tr in text_regions:
        parsed = parse_isa_tag(tr.text)
        if not parsed:
            continue
        _, _, norm_tag = parsed
        if norm_tag not in best_by_tag or tr.confidence > best_by_tag[norm_tag][0].confidence:
            best_by_tag[norm_tag] = (tr, parsed)

    injected: List[Detection] = []
    counter = 0

    for norm_tag, (tr, (prefix, number, _)) in best_by_tag.items():
        tx, ty = tr.bbox.center

        # Skip if a YOLO/classical detection is already nearby
        if any(
            math.hypot(tx - d.bbox.center[0], ty - d.bbox.center[1]) < snap_radius
            for d in existing_dets
        ):
            continue
        # Skip if we already injected something nearby
        if any(
            math.hypot(tx - d.bbox.center[0], ty - d.bbox.center[1]) < snap_radius
            for d in injected
        ):
            continue

        # Estimate symbol center slightly above label
        sym_cx = tx
        sym_cy = max(_DEFAULT_RADIUS, ty - _DEFAULT_RADIUS - tr.bbox.height)
        r = _DEFAULT_RADIUS
        x1, y1 = max(0, int(sym_cx - r)), max(0, int(sym_cy - r))
        x2, y2 = min(w, int(sym_cx + r)), min(h, int(sym_cy + r))

        sym_class = tag_to_component_hint(prefix)
        if sym_class == "unknown":
            sym_class = _prefix_to_class(prefix)

        node_id = f"ocr_{prefix.lower()}_{counter:04d}"
        counter += 1
        injected.append(Detection(
            node_id=node_id,
            symbol_class=sym_class,
            bbox=BoundingBox(x1, y1, x2, y2),
            confidence=float(tr.confidence),
            label=norm_tag,
            isa_tag=norm_tag,
            source="ocr_injected",
        ))
        log.debug("Injected OCR node: %s @ (%.0f, %.0f)", norm_tag, sym_cx, sym_cy)

    if injected:
        log.info("OCR gap-filler: injected %d missing nodes", len(injected))
    return existing_dets + injected


# ---------------------------------------------------------------------------
def build_connectivity_from_hough(
    lines:       np.ndarray,
    detections:  List[Detection],
    snap_radius: int = 60,
) -> Dict[str, List[str]]:
    """
    Snap Hough line endpoints to detection bbox centers.
    Returns adjacency map {node_id: [node_id, ...]}.
    """
    connectivity: Dict[str, List[str]] = {d.node_id: [] for d in detections}
    if lines is None or not detections:
        return connectivity

    def nearest(px: float, py: float) -> Optional[str]:
        best_id, best_d = None, float("inf")
        for det in detections:
            cx, cy = det.bbox.center
            d = math.hypot(px - cx, py - cy)
            if d < best_d:
                best_d, best_id = d, det.node_id
        return best_id if best_d <= snap_radius else None

    pairs = 0
    for line in lines:
        x1, y1, x2, y2 = line[0].tolist()
        a = nearest(x1, y1)
        b = nearest(x2, y2)
        if a and b and a != b and b not in connectivity[a]:
            connectivity[a].append(b)
            connectivity[b].append(a)
            pairs += 1

    log.info("Hough connectivity: %d connections from %d lines", pairs, len(lines))
    return connectivity


# ---------------------------------------------------------------------------
def _prefix_to_class(prefix: str) -> str:
    p = prefix.upper()
    MAP = {
        "P": "centrifugal_pump", "K": "centrifugal_pump",
        "V": "vessel", "T": "vessel", "D": "vessel",
        "E": "heat_exchanger", "HE": "heat_exchanger",
        "PSV": "relief_valve", "PRV": "relief_valve", "RV": "relief_valve",
        "SV": "relief_valve",
        "XV": "gate_valve", "HV": "gate_valve", "MOV": "gate_valve",
        "BDV": "gate_valve", "MV": "gate_valve",
        "FCV": "control_valve", "LCV": "control_valve",
        "PCV": "control_valve", "TCV": "control_valve",
        "FV": "control_valve", "LV": "control_valve",
        "CV": "check_valve",
    }
    if p in MAP:
        return MAP[p]
    if p.endswith("T"):
        return f"{ISA_FIRST_LETTER.get(p[0], 'flow')}_transmitter"
    if p.endswith("I"):
        return f"{ISA_FIRST_LETTER.get(p[0], 'flow')}_indicator"
    if p.endswith("C"):
        return f"{ISA_FIRST_LETTER.get(p[0], 'flow')}_controller"
    return "instrument"
