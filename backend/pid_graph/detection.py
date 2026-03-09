"""
detection.py — YOLOv5 detector for P&ID pipeline.

Uses the same torch.hub / local-repo loading as the working inference.py,
so best.pt (YOLOv5 format) works out of the box.

Load priority
-------------
1. Local yolov5/ folder next to this project (no network, no SSL issues)
2. torch.hub from GitHub (needs internet, SSL bypassed automatically)
3. Classical CC fallback (if torch not installed at all)

Tiling
------
For large P&ID images, symbols can be tiny relative to the full image.
Tiling runs YOLOv5 on overlapping crops at the training resolution (640px)
so symbols are detected at the right scale, then merges results with NMS.

Usage
-----
Just point --weights at your best.pt — nothing else changes.

    python predict.py diagram.jpg --weights best.pt
    python predict.py diagram.jpg --weights best.pt --yolov5-repo ./yolov5
    python predict.py diagram.jpg --weights best.pt --tile 640
"""
from __future__ import annotations

import logging
import math
import ssl
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from pid_graph.config import YoloConfig, ClassicalFallbackConfig, SYMBOL_CLASSES, IDX_TO_SYMBOL_CLASS
from pid_graph.models import BoundingBox, Detection

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-class NMS  (mirrors inference.py _nms_boxes — class-aware)
# ---------------------------------------------------------------------------
def nms_boxes(detections: List[Detection], iou_threshold: float = 0.5) -> List[Detection]:
    """NMS per class: keeps highest-confidence box, suppresses overlapping same-class boxes."""
    if not detections:
        return []

    by_class: Dict[str, List[Detection]] = {}
    for d in detections:
        by_class.setdefault(d.symbol_class, []).append(d)

    kept: List[Detection] = []
    for cls_dets in by_class.values():
        cls_dets = sorted(cls_dets, key=lambda d: d.confidence, reverse=True)
        suppressed = set()
        for i, a in enumerate(cls_dets):
            if i in suppressed:
                continue
            kept.append(a)
            for j, b in enumerate(cls_dets):
                if j <= i or j in suppressed:
                    continue
                if a.bbox.iou(b.bbox) >= iou_threshold:
                    suppressed.add(j)
    return kept


def deduplicate_by_proximity(detections: List[Detection], snap_radius: int) -> List[Detection]:
    """Merge detections whose centers are within snap_radius px (highest-conf wins)."""
    SOURCE_PRIORITY = {"yolov5": 0, "classical": 1, "ocr_injected": 2, "skeleton": 3}
    dets = sorted(detections,
                  key=lambda d: (SOURCE_PRIORITY.get(d.source, 2), -d.confidence))
    kept: List[Detection] = []
    suppressed = set()
    for i, a in enumerate(dets):
        if i in suppressed:
            continue
        kept.append(a)
        cx_a, cy_a = a.bbox.center
        for j, b in enumerate(dets):
            if j <= i or j in suppressed:
                continue
            cx_b, cy_b = b.bbox.center
            if math.hypot(cx_a - cx_b, cy_a - cy_b) < snap_radius:
                suppressed.add(j)
    removed = len(detections) - len(kept)
    if removed:
        log.info("Dedup: removed %d/%d near-duplicates", removed, len(detections))
    return kept


# ---------------------------------------------------------------------------
# Class-name loader  (reads dataset.yaml if present)
# ---------------------------------------------------------------------------
def _load_class_names(search_dirs: List[Path]) -> Dict[int, str]:
    """Load class id→name from dataset.yaml (same logic as inference.py)."""
    candidates = []
    for d in search_dirs:
        candidates.append(d / "dataset.yaml")
    candidates.append(Path.cwd() / "dataset.yaml")
    candidates.append(Path(__file__).resolve().parent.parent / "dataset.yaml")

    for candidate in candidates:
        if not candidate or not candidate.exists():
            continue
        # Try PyYAML first
        try:
            import yaml
            with open(candidate) as f:
                data = yaml.safe_load(f)
            names = data.get("names") or {}
            result = {int(k): str(v) for k, v in names.items()}
            if result:
                log.info("Loaded %d class names from %s", len(result), candidate)
                return result
        except Exception:
            pass
        # Manual parse fallback
        try:
            out: Dict[int, str] = {}
            with open(candidate) as f:
                in_names = False
                for line in f:
                    stripped = line.strip()
                    if stripped == "names:":
                        in_names = True
                        continue
                    if in_names and ":" in stripped:
                        k, v = stripped.split(":", 1)
                        try:
                            out[int(k.strip())] = v.strip()
                        except ValueError:
                            break
                    elif in_names and stripped and not line.startswith(" "):
                        break
            if out:
                log.info("Parsed %d class names from %s (no PyYAML)", len(out), candidate)
                return out
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# YOLOv5 Detector  (torch.hub, mirrors inference.py)
# ---------------------------------------------------------------------------
class YoloV5Detector:
    """
    YOLOv5 detector using torch.hub — same loading logic as the working inference.py.

    Load order:
      1. Local ./yolov5 repo (no network needed)
      2. torch.hub from GitHub (SSL bypassed)
      3. Raises RuntimeError → falls back to ClassicalDetector

    Tiling:
      When tile_size > 0, runs on overlapping crops at that resolution
      then merges with per-class NMS. Good for large / zoomed-out drawings.
    """

    def __init__(self, cfg: YoloConfig):
        self.cfg = cfg
        self._model = None
        self._class_names: Dict[int, str] = {}
        self._available = False
        self._load()

    def _load(self) -> None:
        weights = Path(self.cfg.weights).resolve()
        if not weights.exists():
            log.warning(
                "Weights not found: %s\n"
                "  Place your best.pt at  %s  and re-run.", weights, weights
            )
            return

        log.info("YOLOv5 weights: %s", weights)
        try:
            import torch
        except ImportError:
            log.warning("torch not installed — using classical fallback")
            return

        # Resolve local yolov5 repo — explicit arg, then auto-discover
        repo_cfg = self.cfg.yolov5_repo
        local_candidates = []
        if repo_cfg:
            local_candidates.append(Path(repo_cfg).resolve())
        local_candidates += [
            Path.cwd() / "yolov5",
            Path(__file__).resolve().parent.parent / "yolov5",
        ]
        repo_path: Optional[Path] = None
        for c in local_candidates:
            if c.is_dir() and (c / "models").is_dir():
                repo_path = c
                break

        if repo_path is None:
            log.error(
                "YOLOv5 repo not found.\n"
                "  Clone it next to your project:\n"
                "    git clone https://github.com/ultralytics/yolov5\n"
                "  Then re-run. (torch.hub is not used — avoids ultralytics conflict)"
            )
            return

        log.info("Loading YOLOv5 directly from repo: %s", repo_path)

        # ── Patch ultralytics conflict BEFORE importing yolov5 ───────────────
        # YOLOv5 repo imports `torch_load` from ultralytics.utils.patches,
        # but newer ultralytics (YOLOv8) removed that name.
        # We inject it back into the module so the import succeeds.
        self._patch_ultralytics_conflict(torch)

        # ── Direct import from yolov5 repo (no torch.hub) ────────────────────
        model = None
        _inserted = False
        try:
            repo_str = str(repo_path)
            if repo_str not in sys.path:
                sys.path.insert(0, repo_str)
                _inserted = True

            # Patch torch.load for PyTorch >= 2.6 (weights_only=True by default)
            import functools
            _orig_load = torch.load
            @functools.wraps(_orig_load)
            def _safe_load(*a, **kw):
                kw.setdefault("weights_only", False)
                return _orig_load(*a, **kw)
            torch.load = _safe_load

            from models.experimental import attempt_load   # type: ignore
            from utils.general import non_max_suppression as yolo_nms  # type: ignore
            from utils.augmentations import letterbox      # type: ignore

            self._yolo_nms  = yolo_nms
            self._letterbox = letterbox
            self._torch     = torch

            model = attempt_load(str(weights.resolve()), device="cpu")
            model.eval()
            log.info("YOLOv5 loaded (direct import)")

        except Exception as e:
            log.error("Direct YOLOv5 load failed: %s", e)
            if _inserted:
                try:
                    sys.path.remove(repo_str)
                except ValueError:
                    pass
            return
        finally:
            try:
                torch.load = _orig_load
            except Exception:
                pass

        self._model      = model
        self._repo_path  = repo_path

        # Load class names
        search_dirs = [weights.parent, Path.cwd(), repo_path]
        self._class_names = _load_class_names(search_dirs)
        # Also read from model's own names dict
        if not self._class_names and hasattr(model, "names"):
            names = model.names
            if isinstance(names, dict):
                self._class_names = {int(k): str(v) for k, v in names.items()}
            elif isinstance(names, list):
                self._class_names = {i: str(n) for i, n in enumerate(names)}

        # If names are still numeric defaults (0, 1, 2 or "0", "1", "class_0", ...), use project's SYMBOL_CLASSES
        def _is_numeric_default(namemap: Dict[int, str]) -> bool:
            if not namemap:
                return True
            for k, v in namemap.items():
                s = str(v).strip()
                if s != str(k) and s != f"class_{k}" and not s.isdigit():
                    return False
            return True

        if _is_numeric_default(self._class_names) and IDX_TO_SYMBOL_CLASS:
            self._class_names = dict(IDX_TO_SYMBOL_CLASS)
            log.info("Using class names from config (model had numeric defaults)")

        if self._class_names:
            log.info("Class names: %s", list(self._class_names.values())[:10])

        self._available = True

    @staticmethod
    def _patch_ultralytics_conflict(torch) -> None:
        """
        YOLOv5 repo does:  from ultralytics.utils.patches import torch_load
        Newer ultralytics (YOLOv8 ≥ 8.1) removed `torch_load` from that module.
        We inject the missing name back so the import succeeds.
        """
        try:
            import ultralytics.utils.patches as ulp
            if not hasattr(ulp, "torch_load"):
                import functools

                @functools.wraps(torch.load)
                def _torch_load(*args, **kwargs):
                    kwargs.setdefault("weights_only", False)
                    return torch.load(*args, **kwargs)

                ulp.torch_load = _torch_load
                log.debug("Patched ultralytics.utils.patches.torch_load")
        except ImportError:
            pass  # ultralytics not installed — no conflict possible

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    def detect(self, image: np.ndarray, binary: np.ndarray) -> List[Detection]:
        if not self._available or self._model is None:
            raise RuntimeError("YOLOv5 not available")

        h, w = image.shape[:2]
        tile = self.cfg.tile_size

        if tile and tile > 0 and (h > tile or w > tile):
            raw = self._detect_tiled(image, tile, self.cfg.tile_overlap)
        else:
            raw = self._detect_single(image)

        dets = nms_boxes(raw, self.cfg.nms_iou_threshold)
        dets = deduplicate_by_proximity(dets, self.cfg.dedup_snap_radius)
        log.info("YOLOv5: %d detections  (conf≥%.2f)", len(dets), self.cfg.conf_threshold)
        return dets

    def _detect_single(self, image: np.ndarray) -> List[Detection]:
        """Run YOLOv5 on a single image using direct import (no torch.hub)."""
        torch  = self._torch
        stride = int(self._model.stride.max())
        img_size = self.cfg.tile_size or 640

        # Letterbox resize + pad to model stride
        img, ratio, pad = self._letterbox(image, img_size, stride=stride, auto=True)
        img = img.transpose((2, 0, 1))[::-1]   # HWC BGR → CHW RGB
        img = np.ascontiguousarray(img)
        img_t = torch.from_numpy(img).float() / 255.0
        if img_t.ndimension() == 3:
            img_t = img_t.unsqueeze(0)

        with torch.no_grad():
            pred = self._model(img_t)[0]

        pred = self._yolo_nms(
            pred,
            conf_thres=self.cfg.conf_threshold,
            iou_thres=self.cfg.iou_threshold,
        )[0]

        dets: List[Detection] = []
        if pred is None or len(pred) == 0:
            return dets

        h0, w0 = image.shape[:2]
        h1, w1 = img_t.shape[2], img_t.shape[3]

        # Scale boxes back to original image coords
        from utils.general import scale_boxes  # type: ignore
        pred[:, :4] = scale_boxes((h1, w1), pred[:, :4], (h0, w0)).round()

        for *xyxy, conf, cls in pred.tolist():
            cid  = int(cls)
            name = self._class_names.get(cid, f"class_{cid}")
            sym_class = name.lower().replace(" ", "_").replace("-", "_")
            dets.append(Detection(
                node_id=f"{sym_class}_{len(dets):04x}",
                symbol_class=sym_class,
                bbox=BoundingBox(int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])),
                confidence=round(conf, 4),
                label=name,
                source="yolov5",
            ))
        return dets

    def _detect_tiled(
        self,
        image: np.ndarray,
        tile_size: int,
        overlap: float,
    ) -> List[Detection]:
        """Sliding-window inference — mirrors inference.py tiling logic."""
        h, w = image.shape[:2]
        stride = max(1, int(tile_size * (1 - overlap)))
        all_dets: List[Detection] = []
        n_tiles = 0

        for y in range(0, h, stride):
            for x in range(0, w, stride):
                y2, x2 = min(y + tile_size, h), min(x + tile_size, w)
                # Skip tiny edge slivers (same as inference.py)
                if (y2 - y) < tile_size // 2 and y > 0:
                    continue
                if (x2 - x) < tile_size // 2 and x > 0:
                    continue
                tile = image[y:y2, x:x2]
                if tile.size == 0:
                    continue
                n_tiles += 1
                tile_dets = self._detect_single(tile)
                # Offset coords back to full-image space
                for d in tile_dets:
                    b = d.bbox
                    d.bbox = BoundingBox(b.x1 + x, b.y1 + y, b.x2 + x, b.y2 + y)
                all_dets.extend(tile_dets)

        log.info("Tiled: %d tiles, %d raw dets", n_tiles, len(all_dets))
        return all_dets


# ---------------------------------------------------------------------------
# Classical fallback (unchanged — zero dependencies)
# ---------------------------------------------------------------------------
class ClassicalDetector:
    def __init__(self, cfg: ClassicalFallbackConfig):
        self.cfg = cfg

    def detect(self, image: np.ndarray, binary: np.ndarray) -> List[Detection]:
        detections: List[Detection] = []
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )
        h_img, w_img = binary.shape[:2]
        img_area = h_img * w_img

        for i in range(1, num_labels):
            x    = int(stats[i, cv2.CC_STAT_LEFT])
            y    = int(stats[i, cv2.CC_STAT_TOP])
            bw   = int(stats[i, cv2.CC_STAT_WIDTH])
            bh   = int(stats[i, cv2.CC_STAT_HEIGHT])
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < self.cfg.min_symbol_area: continue
            if area > img_area * self.cfg.max_symbol_area_fraction: continue
            if bh < 6 or bw < 6: continue
            aspect = bw / max(bh, 1)
            if aspect > 8 or aspect < 0.125: continue
            mask = (labels[y:y + bh, x:x + bw] == i).astype(np.uint8) * 255
            sym_class, conf = self._classify(mask, aspect)
            detections.append(Detection(
                node_id=f"{sym_class}_{len(detections):04d}",
                symbol_class=sym_class,
                bbox=BoundingBox(x, y, x + bw, y + bh),
                confidence=conf,
                source="classical",
            ))

        detections = nms_boxes(detections, self.cfg.nms_iou_threshold)
        log.info("Classical fallback: %d detections", len(detections))
        return detections

    def _classify(self, mask: np.ndarray, aspect: float) -> Tuple[str, float]:
        area = int(np.sum(mask > 0))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        circularity, solidity = 0.0, 0.0
        if contours:
            perim = cv2.arcLength(contours[0], True)
            if perim > 0:
                circularity = 4 * math.pi * area / (perim ** 2)
            hull_area = cv2.contourArea(cv2.convexHull(contours[0]))
            solidity = area / max(hull_area, 1)
        if circularity > 0.70 and 0.7 < aspect < 1.4: return "pressure_indicator", 0.60
        if circularity > 0.55: return "flow_indicator", 0.55
        if solidity < 0.50:    return "gate_valve", 0.50
        if 1.5 < aspect < 4.0: return "centrifugal_pump", 0.45
        return "unknown", 0.35


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def build_detector(yolo_cfg: YoloConfig, fallback_cfg: ClassicalFallbackConfig):
    det = YoloV5Detector(yolo_cfg)
    if det.available:
        return det
    log.info("YOLOv5 unavailable — using classical fallback")
    return ClassicalDetector(fallback_cfg)