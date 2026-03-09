"""
pipeline.py — YOLO-first P&ID graph extraction pipeline.

Stages
------
1. Ingest       load image / PDF page
2. Preprocess   grayscale → denoise → deskew → adaptive threshold
3. OCR          full-image text extraction (Tesseract / PaddleOCR / EasyOCR)
4. Detect       YOLO symbol detection  (fallback: classical CC)
5. Label        attach ISA tags to YOLO boxes via nearest-OCR-word search
6. Gap-fill     inject nodes for any OCR-found tags YOLO missed
7. Trace        skeletonize pipes → connectivity map
8. Hough        Hough-line fallback connectivity if skeleton gives nothing
9. Graph        build NetworkX graph
10. SOP         parse SOP, cross-reference
11. Report      annotated image, GraphML, JSON, HTML

Usage (Python)
--------------
>>> from pid_graph.pipeline import Pipeline
>>> result = Pipeline().run("diagram.jpg", sop_path="sop.docx")

Usage (CLI)
-----------
    python -m pid_graph.pipeline diagram.jpg --sop sop.docx
    python -m pid_graph.pipeline diagram.jpg --weights weights/best.pt --conf 0.3
"""
from __future__ import annotations

import logging
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import networkx as nx
import numpy as np

from pid_graph.config import PipelineConfig, DEFAULT_CONFIG
from pid_graph.ingestion import load_image
from pid_graph.preprocessing import preprocess, mask_symbol_regions
from pid_graph.detection import build_detector, deduplicate_by_proximity
from pid_graph.ocr import build_ocr_engine
from pid_graph.ocr_node_injector import (
    associate_labels_to_yolo_dets,
    inject_missing_from_ocr,
    build_connectivity_from_hough,
)
from pid_graph.line_tracer import trace_lines
from pid_graph.straight_line_detector import detect_straight_lines
from pid_graph.graph_builder import GraphBuilder, graph_summary
from pid_graph.sop_parser import SopParser
from pid_graph.cross_ref import CrossReferenceEngine
from pid_graph.visualizer import annotate_image, draw_graph, draw_graph_interactive
from pid_graph.reporter import (
    build_json_report, save_json_report,
    build_html_report, save_html_report,
)
from pid_graph.models import Detection, Discrepancy, LineSegment, SopStep

log = logging.getLogger(__name__)


def _filter_hough_lines_hv(lines: np.ndarray, tolerance_deg: float) -> Optional[np.ndarray]:
    """Keep only lines within tolerance_deg of horizontal or vertical. lines shape (N, 1, 4)."""
    if lines is None or len(lines) == 0:
        return lines
    kept = []
    for line in lines:
        x1, y1, x2, y2 = line[0].tolist()
        a_deg = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if a_deg > 90:
            a_deg -= 180
        if a_deg < -90:
            a_deg += 180
        if abs(a_deg) <= tolerance_deg or abs(abs(a_deg) - 90) <= tolerance_deg:
            kept.append(line)
    return np.array(kept, dtype=lines.dtype) if kept else None


@dataclass
class PipelineResult:
    graph:         nx.Graph
    detections:    List[Detection]
    segments:      List[LineSegment]
    sop_steps:     List[SopStep]
    discrepancies: List[Discrepancy]
    xref_summary:  Dict[str, Any]
    report:        Dict[str, Any]
    output_files:  Dict[str, Path] = field(default_factory=dict)
    elapsed_sec:   float = 0.0
    text_regions:  List[Any] = field(default_factory=list)  # all OCR text for metadata/retrieval


class Pipeline:
    def __init__(self, cfg: Optional[PipelineConfig] = None):
        self.cfg = cfg or DEFAULT_CONFIG
        self._setup_logging()

        log.info("Initialising pipeline…")
        self.detector   = build_detector(self.cfg.yolo, self.cfg.fallback)
        self.ocr        = build_ocr_engine(self.cfg.ocr)
        self.builder    = GraphBuilder(self.cfg.graph)
        self.sop_parser = SopParser(self.cfg.sop)
        self.xref       = CrossReferenceEngine(self.cfg.sop)

        Path(self.cfg.report.output_dir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def run(
        self,
        image_path: str | Path,
        sop_path:   Optional[str | Path] = None,
        run_id:     Optional[str] = None,
        page_index: Optional[int] = None,
    ) -> PipelineResult:
        t0 = time.perf_counter()
        image_path = Path(image_path)
        run_id = run_id or f"run_{int(t0)}"

        log.info("=" * 60)
        log.info("PIPELINE START  id=%s", run_id)
        log.info("  image  : %s", image_path)
        log.info("  sop    : %s", sop_path or "—")
        log.info("  detector: %s", type(self.detector).__name__)
        log.info("=" * 60)

        # ── 1. Ingest ────────────────────────────────────────────────
        log.info("[1/9] Ingesting…")
        image = load_image(image_path, self.cfg.ingestion, page_index=page_index)

        # ── 2. Preprocess ────────────────────────────────────────────
        log.info("[2/9] Preprocessing…")
        gray, binary, skew_deg = preprocess(image, self.cfg.preprocess)

        # ── 3. OCR  ──────────────────────────────────────────────────
        log.info("[3/9] OCR…")
        text_regions = self.ocr.extract_text(image)

        # ── 4. Detect symbols ────────────────────────────────────────
        log.info("[4/9] Detecting symbols (YOLO)…")
        detections = self.detector.detect(image, binary)

        # ── 5. Label YOLO boxes with ISA tags ────────────────────────
        log.info("[5/9] Associating ISA labels…")
        detections = associate_labels_to_yolo_dets(
            text_regions, detections,
            search_radius=self.cfg.ocr.label_search_radius,
        )

        # ── 6. Gap-fill: inject OCR nodes YOLO missed ────────────────
        log.info("[6/9] OCR gap-fill…")
        detections = inject_missing_from_ocr(
            text_regions, image, detections,
            snap_radius=self.cfg.ocr.ocr_snap_radius,
        )

        # Final dedup across all sources
        detections = deduplicate_by_proximity(
            detections, snap_radius=self.cfg.yolo.dedup_snap_radius,
        )

        log.info("  → %d total symbols  (%d labelled, %d ISA-tagged)",
                 len(detections),
                 sum(1 for d in detections if d.label),
                 sum(1 for d in detections if d.isa_tag))

        # ── 7. Trace pipes ───────────────────────────────────────────
        log.info("[7/9] Tracing pipes…")
        pipe_binary = mask_symbol_regions(binary, detections, padding=8)
        segments, junctions, connectivity = trace_lines(
            pipe_binary, detections, self.cfg.line_tracer
        )

        # ── 7b. Straight-line detector (full pipe runs across symbols) ──
        if getattr(self.cfg, "straight_line", None) and self.cfg.straight_line.enabled:
            log.info("[7b/9] Straight-line CV detection…")
            straight_segments, straight_connectivity = detect_straight_lines(
                binary, detections, gray, self.cfg.straight_line
            )
            # Merge connectivity: add edges from straight-line (equipment on same pipe)
            for src, targets in straight_connectivity.items():
                connectivity.setdefault(src, [])
                for t in targets:
                    if t not in connectivity[src]:
                        connectivity[src].append(t)
            # Append straight segments for annotation / graph edge metadata
            segments = segments + straight_segments

        # ── 8. Hough fallback connectivity ───────────────────────────
        if not any(connectivity.values()):
            log.info("[8/9] Hough connectivity fallback…")
            hough_lines = cv2.HoughLinesP(
                binary,
                rho=1.0,
                theta=np.pi / 360,
                threshold=self.cfg.line_tracer.hough_threshold,
                minLineLength=self.cfg.line_tracer.hough_min_line_length,
                maxLineGap=self.cfg.line_tracer.hough_max_line_gap * 3,
            )
            # Only use H/V lines (no diagonals)
            if hough_lines is not None and getattr(self.cfg.line_tracer, "filter_hv_only", True):
                hv_angle_deg = getattr(self.cfg.line_tracer, "segment_hv_angle_deg", 5.0)
                hough_lines = _filter_hough_lines_hv(hough_lines, hv_angle_deg)
            connectivity = build_connectivity_from_hough(
                hough_lines, detections,
                snap_radius=self.cfg.line_tracer.hough_fallback_snap,
            )
        else:
            log.info("[8/9] Skeleton connectivity OK — skipping Hough fallback")

        # ── 9. Build graph ───────────────────────────────────────────
        log.info("[9/9] Building graph…")
        G = self.builder.build(detections, segments, junctions, connectivity)

        # ── SOP cross-reference ──────────────────────────────────────
        sop_steps: List[SopStep] = []
        discrepancies: List[Discrepancy] = []
        xref_summary: Dict[str, Any] = {}
        if sop_path:
            log.info("[SOP] Parsing and cross-referencing…")
            sop_steps = self.sop_parser.parse(sop_path)
            discrepancies, xref_summary = self.xref.run(G, sop_steps)

        # ── Reporting ────────────────────────────────────────────────
        source_files = {"diagram": str(image_path)}
        if sop_path:
            source_files["sop"] = str(sop_path)

        report = build_json_report(
            detections, segments, G,
            sop_steps, discrepancies, xref_summary,
            source_files, run_id=run_id,
        )
        output_files = self._save_outputs(run_id, image, G, detections, segments, report)

        elapsed = time.perf_counter() - t0
        log.info("PIPELINE DONE  %.2fs", elapsed)
        _print_summary(G, discrepancies, xref_summary)

        return PipelineResult(
            graph=G, detections=detections, segments=segments,
            sop_steps=sop_steps, discrepancies=discrepancies,
            xref_summary=xref_summary, report=report,
            output_files=output_files, elapsed_sec=elapsed,
            text_regions=text_regions,
        )

    # ------------------------------------------------------------------
    def _save_outputs(self, run_id, image, G, detections, segments, report):
        out_dir = Path(self.cfg.report.output_dir) / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        files: Dict[str, Path] = {}
        rcfg = self.cfg.report

        if rcfg.save_annotated_image:
            ann = annotate_image(image, detections, segments)
            p = out_dir / "annotated.png"
            cv2.imwrite(str(p), ann)
            files["annotated_image"] = p
            log.info("Annotated image → %s", p)

        graph_files = self.builder.save(G, out_dir, stem="pid_graph")
        files.update(graph_files)

        if rcfg.save_graph_image:
            gp = draw_graph(G, out_dir / "graph.png",
                            layout=rcfg.graph_layout, dpi=rcfg.dpi_output)
            files["graph_image"] = gp

        igh = draw_graph_interactive(G, out_dir / "graph_interactive.html")
        if igh:
            files["interactive_graph"] = igh

        if rcfg.save_json:
            files["json_report"] = save_json_report(report, out_dir / "report.json")

        if rcfg.save_html:
            html = build_html_report(
                report,
                "annotated.png" if "annotated_image" in files else None,
                "graph.png"     if "graph_image"     in files else None,
                "graph_interactive.html" if "interactive_graph" in files else None,
            )
            files["html_report"] = save_html_report(html, out_dir / "report.html")

        return files

    def _setup_logging(self):
        level = logging.DEBUG if self.cfg.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )


# ---------------------------------------------------------------------------
def _print_summary(G, discrepancies, xref_summary):
    gs = graph_summary(G)
    sep = "─" * 52
    print(f"\n{sep}")
    print(f"  📊 GRAPH   {gs['node_count']} nodes · {gs['edge_count']} edges"
          f" · {gs['component_count']} component(s)")
    if xref_summary:
        c = xref_summary.get("critical_count", 0)
        w = xref_summary.get("warning_count", 0)
        cov = xref_summary.get("coverage_pct", 0)
        print(f"  📋 SOP     {cov:.1f}% coverage · CRIT={c} WARN={w}")
    if discrepancies:
        print("  ⚠  TOP DISCREPANCIES:")
        for d in sorted(discrepancies,
                        key=lambda x: ["CRITICAL","WARNING","INFO"].index(x.severity))[:5]:
            print(f"     [{d.severity:8s}] {d.disc_type:25s} {d.sop_tag or d.graph_tag or ''}")
    print(f"{sep}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    p = argparse.ArgumentParser(description="P&ID YOLO-first graph extractor")
    p.add_argument("image",              help="Path to P&ID image or PDF")
    p.add_argument("--sop",              help="SOP .docx or .txt", default=None)
    p.add_argument("--weights",          help="YOLO weights (default: weights/best.pt)", default=None)
    p.add_argument("--conf",             help="YOLO confidence threshold", type=float, default=None)
    p.add_argument("--iou",              help="YOLO NMS IoU threshold", type=float, default=None)
    p.add_argument("--imgsz",            help="YOLO inference size", type=int, default=None)
    p.add_argument("--ocr-engine",       choices=["tesseract","paddleocr","easyocr"],
                   default="tesseract")
    p.add_argument("--output", "-o",     default="outputs")
    p.add_argument("--run-id",           default=None)
    p.add_argument("--layout",           choices=["spring","kamada_kawai","spectral","spatial"],
                   default="spring")
    p.add_argument("--half",             action="store_true", help="FP16 inference (GPU)")
    p.add_argument("--augment",          action="store_true", help="Test-time augmentation")
    p.add_argument("-v", "--verbose",    action="store_true")
    args = p.parse_args()

    cfg = PipelineConfig()
    cfg.report.output_dir  = Path(args.output)
    cfg.report.graph_layout = args.layout
    cfg.ocr.engine          = args.ocr_engine
    cfg.verbose             = args.verbose

    if args.weights:
        cfg.yolo.weights = Path(args.weights)
    if args.conf is not None:
        cfg.yolo.conf_threshold = args.conf
    if args.iou is not None:
        cfg.yolo.iou_threshold = args.iou
    if args.imgsz is not None:
        cfg.yolo.imgsz = args.imgsz
    if args.half:
        cfg.yolo.half = True
    if args.augment:
        cfg.yolo.augment = True

    result = Pipeline(cfg).run(args.image, sop_path=args.sop, run_id=args.run_id)

    print("\nOutput files:")
    for k, v in result.output_files.items():
        print(f"  {k:25s} → {v}")

    sys.exit(0 if result.xref_summary.get("critical_count", 0) == 0 else 1)


if __name__ == "__main__":
    main()
