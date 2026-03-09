"""
config.py — Centralised configuration for pid_graph (YOLO-first version).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


ROOT_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = ROOT_DIR / "data"
OUTPUT_DIR  = ROOT_DIR / "outputs"
WEIGHTS_DIR = ROOT_DIR / "weights"


# ---------------------------------------------------------------------------
# ISA S5.1 symbol taxonomy  (must match your YOLO training labels exactly)
# ---------------------------------------------------------------------------
SYMBOL_CLASSES: List[str] = [
    # Valves
    "gate_valve", "globe_valve", "ball_valve", "butterfly_valve",
    "check_valve", "needle_valve", "plug_valve", "diaphragm_valve",
    "relief_valve", "control_valve", "solenoid_valve", "pressure_regulator",
    # Pumps & Compressors
    "centrifugal_pump", "positive_displacement_pump", "compressor", "fan",
    # Vessels & Tanks
    "vessel", "tank", "column", "drum", "separator", "heat_exchanger",
    "filter", "strainer",
    # Instruments (bubbles)
    "flow_indicator", "flow_transmitter", "flow_controller",
    "pressure_indicator", "pressure_transmitter", "pressure_controller",
    "temperature_indicator", "temperature_transmitter", "level_indicator",
    "level_transmitter", "level_controller", "analyzer",
    "orifice_plate", "flow_meter",
    # Structural
    "junction", "reducer", "tee", "elbow", "flange",
    "motor", "agitator", "nozzle", "vent", "drain",
]

SYMBOL_CLASS_TO_IDX: Dict[str, int] = {c: i for i, c in enumerate(SYMBOL_CLASSES)}
IDX_TO_SYMBOL_CLASS: Dict[int, str] = {i: c for i, c in enumerate(SYMBOL_CLASSES)}


# ---------------------------------------------------------------------------
@dataclass
class IngestionConfig:
    dpi: int = 300
    tile_size: int = 1280        # px per tile — matches YOLO imgsz
    tile_overlap: float = 0.20   # generous overlap so symbols aren't split
    max_image_dim: int = 8192


# ---------------------------------------------------------------------------
@dataclass
class PreprocessConfig:
    grayscale: bool = True
    denoise_h: float = 10.0
    adaptive_block_size: int = 31
    adaptive_C: int = 10
    deskew: bool = True
    deskew_angle_range: float = 15.0
    morph_close_ksize: int = 3


# ---------------------------------------------------------------------------
@dataclass
class YoloConfig:
    """
    YOLOv5 detector settings (torch.hub / local repo).

    Weights
    -------
    Point weights at your best.pt (YOLOv5 format).
    Class names are loaded automatically from dataset.yaml if present
    next to best.pt or in the project root.

    Local repo (recommended — avoids GitHub/SSL on first load)
    ----------------------------------------------------------
    git clone https://github.com/ultralytics/yolov5
    Then set yolov5_repo = Path("./yolov5")  or pass --yolov5-repo ./yolov5

    Tiling
    ------
    Set tile_size=640 for large / zoomed-out drawings so that symbols are
    detected at the training resolution. Set to 0 to disable tiling.
    """
    # Path to YOLOv5 best.pt weights
    weights: Path = WEIGHTS_DIR / "best.pt"

    # Optional: path to local ultralytics/yolov5 clone (no GitHub/SSL needed)
    yolov5_repo: Optional[Path] = None

    # Inference thresholds
    conf_threshold: float = 0.25
    iou_threshold:  float = 0.45

    # Tiling — set > 0 to enable sliding-window for large images
    tile_size:    int   = 640    # px per tile (match training size, usually 640)
    tile_overlap: float = 0.20   # overlap between tiles as fraction

    # Post-processing
    nms_iou_threshold: float = 0.50   # per-class NMS threshold
    dedup_snap_radius: int   = 40     # px — merge centers closer than this


# ---------------------------------------------------------------------------
@dataclass
class ClassicalFallbackConfig:
    """Classical CC detector used when YOLO weights are absent."""
    enabled: bool = True
    nms_iou_threshold: float = 0.40
    min_symbol_area:   int   = 200
    max_symbol_area_fraction: float = 0.05


# ---------------------------------------------------------------------------
@dataclass
class OcrConfig:
    engine: str = "tesseract"       # "tesseract" | "paddleocr" | "easyocr"
    tesseract_lang: str = "eng"
    tesseract_psm:  int = 11        # sparse text
    ocr_scale: float = 2.5          # upscale factor before OCR
    label_search_radius: int = 80   # px around each detected symbol to find its tag
    ocr_snap_radius: int = 60       # px — dedup injected OCR nodes
    min_text_confidence: float = 0.40
    isa_tag_pattern: str = r"\b([A-Z]{1,4})[_\-]?(\d{2,5}[A-Z]?)\b"


# ---------------------------------------------------------------------------
@dataclass
class LineTracerConfig:
    morph_open_ksize:  int   = 3
    morph_close_ksize: int   = 5
    hough_rho:         float = 1.0
    hough_theta_deg:   float = 0.5
    hough_threshold:   int   = 35   # lower = more lines (avoid missing edges)
    hough_min_line_length: int = 20 # shorter segments allowed (fragmented pipes)
    hough_max_line_gap:    int = 25 # bridge larger gaps in one line
    prune_branch_length:   int = 20
    snap_radius:           int = 50   # px — link pipe endpoint to symbol (center or bbox)
    snap_to_bbox:          bool = True # if True, snap when endpoint is within snap_radius of bbox (not just center)
    extended_snap_radius:  int = 75   # when one end snaps, other end can use this radius to still form edge (0=disable)
    hough_fallback_snap:   int = 80   # px snap radius used in Hough-only fallback

    # PID2Graph-style line detection (paper 2411.13929v3): dilation/erosion for H/V,
    # thinning + Progressive Probabilistic Hough for obliques, DBSCAN for dashed lines
    use_pid2graph_lines:       bool   = True   # use paper's morph H/V + thin + Hough + DBSCAN
    morph_hv_ratio:            int   = 40     # kernel length = W//ratio or H//ratio (paper: 40)
    hough_threshold_oblique:   int   = 20     # lower threshold on thinned image (paper: 20)
    dash_segment_max_length:   int   = 25     # segments shorter than this → dashed candidates
    dbscan_eps:                float = 15.0   # DBSCAN epsilon for dashed-line clustering
    dbscan_min_samples:        int   = 2      # DBSCAN min samples per cluster

    # Post-detection merge (inspired by pid2graph NMS/WBF and graph cleanup)
    segment_colinear_angle_deg: float = 12.0  # max angle diff to treat segments as same line
    segment_merge_gap_px:       int   = 45    # max gap between endpoints to merge colinear segments
    segment_nms_overlap_ratio:  float = 0.6   # drop shorter segment if overlap ratio >= this
    segment_min_length_after_merge: int = 10  # keep short segments that may connect two nodes
    filter_hv_only:              bool  = True  # drop diagonal segments (P&ID pipes are H/V only)
    segment_hv_angle_deg:        float = 5.0   # max angle from horizontal or vertical to keep
    junction_merge_radius_px:   int   = 20    # merge junctions within this distance (single entity)
    junction_endpoint_radius:   int   = 28    # associate segment endpoints within this to a junction
    junction_min_degree:       int   = 2     # keep only junctions with >= this many connected segments


# ---------------------------------------------------------------------------
@dataclass
class StraightLineDetectorConfig:
    """
    CV algorithm for P&ID straight pipe detection (Otsu → morph H/V → ROI mask
    → HoughLinesP with large maxLineGap → collinear merge → equipment snap).
    Use on raw binary (before masking symbols) so pipes bridge across equipment.
    """
    enabled: bool = True
    use_otsu_stage: bool = False   # if True and gray provided, re-binarise with Otsu

    # Stage 2: morphological stroke isolation
    morph_kernel_length: int = 40   # px — 40 at 200 DPI ≈ 5mm (sweet spot for P&IDs)

    # Stage 3: ROI masking (exclude border and title block from line detection)
    roi_mask_enabled: bool = True
    roi_border_fill_ratio: float = 0.25   # lower = detect border line sooner
    roi_border_margin: int = 60           # px to black out inward from border (was 20)
    roi_title_bottom_frac: float = 0.40   # black out bottom 40% (title block)
    roi_title_right_frac: float = 0.50    # black out right 50%
    roi_spec_top_frac: float = 0.12

    # Stage 4: HoughLinesP
    hough_rho: float = 1.0
    hough_theta_rad: float = math.pi / 180
    hough_threshold: int = 40
    hough_min_line_length: int = 40
    hough_max_line_gap: int = 600  # bridge largest symbol gaps (e.g. heat exchanger)

    # Stage 5: collinear merge
    merge_coord_gap_px: int = 6
    merge_span_gap_px: int = 600
    min_line_length_final: int = 30

    # Stage 6: line → equipment (T_perp snap)
    t_perp_px: int = 80
    line_span_margin_px: int = 20


# ---------------------------------------------------------------------------
@dataclass
class GraphConfig:
    add_virtual_junctions: bool = True
    min_edge_length: int = 10
    directed: bool = False
    # Remove junction nodes that only have one edge (reduces entity explosion; pid2graph-style cleanup)
    remove_degree1_junctions: bool = True


# ---------------------------------------------------------------------------
@dataclass
class SopConfig:
    isa_tag_pattern: str = r"\b([A-Z]{1,4})[_\-]?(\d{2,5}[A-Z]?)\b"
    fuzzy_match_threshold: float = 0.82
    heading_styles: List[str] = field(
        default_factory=lambda: ["Heading 1", "Heading 2", "Heading 3"]
    )


# ---------------------------------------------------------------------------
@dataclass
class ReportConfig:
    output_dir: Path = OUTPUT_DIR
    save_annotated_image: bool = True
    save_graph_image:     bool = True
    save_json:            bool = True
    save_html:            bool = True
    graph_layout: str = "spring"    # "spring" | "kamada_kawai" | "spatial"
    dpi_output:   int = 150


# ---------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    ingestion:  IngestionConfig          = field(default_factory=IngestionConfig)
    preprocess: PreprocessConfig         = field(default_factory=PreprocessConfig)
    yolo:       YoloConfig               = field(default_factory=YoloConfig)
    fallback:   ClassicalFallbackConfig  = field(default_factory=ClassicalFallbackConfig)
    ocr:        OcrConfig                = field(default_factory=OcrConfig)
    line_tracer: LineTracerConfig           = field(default_factory=LineTracerConfig)
    straight_line: StraightLineDetectorConfig = field(default_factory=StraightLineDetectorConfig)
    graph:      GraphConfig              = field(default_factory=GraphConfig)
    sop:        SopConfig                = field(default_factory=SopConfig)
    report:     ReportConfig             = field(default_factory=ReportConfig)
    verbose:    bool = True


DEFAULT_CONFIG = PipelineConfig()
