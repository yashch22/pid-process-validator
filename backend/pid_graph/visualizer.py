"""
visualizer.py — Draw annotated P&ID images and graph visualisations.

Outputs
-------
annotated_image   : original image with bounding boxes, labels, pipe overlays
graph_image       : NetworkX graph rendered with matplotlib
html_graph        : interactive Pyvis HTML  (if pyvis installed)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from pid_graph.models import Detection, LineSegment

log = logging.getLogger(__name__)


# Colour palette: symbol_class → BGR
_CLASS_COLORS: Dict[str, Tuple[int, int, int]] = {
    "gate_valve":          (255,  80,  80),
    "globe_valve":         (255, 140,  80),
    "ball_valve":          (255, 200,  80),
    "butterfly_valve":     (255, 255,  80),
    "check_valve":         (180, 255,  80),
    "control_valve":       ( 80, 255,  80),
    "control_valve_actuated": (80, 200,  80),
    "relief_valve":        ( 80, 255, 160),
    "solenoid_valve":      ( 80, 255, 255),
    "needle_valve":        ( 80, 160, 255),
    "pressure_regulator":  ( 80,  80, 255),
    "centrifugal_pump":    (160,  80, 255),
    "positive_displacement_pump": (200, 80, 255),
    "compressor":          (255,  80, 200),
    "vessel":              (255,  80, 120),
    "tank":                (200, 120, 120),
    "heat_exchanger":      (120, 200, 200),
    "separator":           (120, 160, 255),
    "flow_indicator":      ( 50, 200, 255),
    "flow_transmitter":    ( 50, 150, 255),
    "pressure_indicator":  (255, 200,  50),
    "pressure_transmitter":(255, 150,  50),
    "temperature_indicator":(200, 255,  50),
    "temperature_transmitter":(150, 255, 50),
    "level_indicator":     ( 50, 255, 150),
    "level_transmitter":   ( 50, 255, 100),
    "junction":            (180, 180, 180),
    "unknown":             (150, 150, 150),
}

_DEFAULT_COLOR = (200, 200, 200)


def annotate_image(
    image: np.ndarray,
    detections: List[Detection],
    segments: Optional[List[LineSegment]] = None,
    show_confidence: bool = True,
    thickness: int = 2,
    font_scale: float = 0.45,
) -> np.ndarray:
    """
    Draw bounding boxes, labels, and pipe segments on a copy of *image*.

    Returns annotated BGR image.
    """
    out = image.copy()
    h, w = out.shape[:2]

    # Draw pipe segments first (background layer)
    if segments:
        for seg in segments:
            color = (120, 200, 120)   # green for pipes
            if seg.line_type == "instrument":
                color = (200, 200, 80)
            elif seg.line_type == "signal":
                color = (80, 200, 200)
            cv2.line(out, (seg.x1, seg.y1), (seg.x2, seg.y2), color, 1, cv2.LINE_AA)

    # Draw detections
    for det in detections:
        bb    = det.bbox
        color = _CLASS_COLORS.get(det.symbol_class, _DEFAULT_COLOR)
        # Box
        cv2.rectangle(out, (bb.x1, bb.y1), (bb.x2, bb.y2), color, thickness)

        # Label text
        parts = []
        if det.isa_tag:
            parts.append(det.isa_tag)
        elif det.label:
            parts.append(det.label)
        parts.append(det.symbol_class.replace("_", " "))
        if show_confidence:
            parts.append(f"{det.confidence:.2f}")
        text = " | ".join(parts)

        # Background pill for text
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), bl = cv2.getTextSize(text, font, font_scale, 1)
        tx = bb.x1
        ty = max(bb.y1 - 4, th + 4)
        cv2.rectangle(out, (tx, ty - th - bl), (tx + tw + 4, ty + bl), color, -1)
        # White text
        cv2.putText(out, text, (tx + 2, ty), font, font_scale, (255, 255, 255), 1, cv2.LINE_AA)

        # Center dot
        cx, cy = int(bb.center[0]), int(bb.center[1])
        cv2.circle(out, (cx, cy), 3, color, -1)

    return out


def draw_skeleton(
    image: np.ndarray,
    skeleton: np.ndarray,
    color: Tuple[int, int, int] = (0, 255, 100),
) -> np.ndarray:
    """Overlay skeleton pixels on image."""
    out = image.copy()
    out[skeleton > 0] = color
    return out


def draw_graph(
    G,
    output_path: str | Path,
    layout: str = "spring",
    dpi: int = 120,
    title: str = "P&ID Graph",
) -> Path:
    """
    Render NetworkX graph to a PNG file.

    layout : "spring" | "kamada_kawai" | "spectral" | "spatial"
             "spatial" uses the actual image coordinates stored in node attrs.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import networkx as nx
    except ImportError:
        log.warning("matplotlib not available — skipping graph image")
        return Path(output_path)

    output_path = Path(output_path)
    fig, ax = plt.subplots(figsize=(16, 12), dpi=dpi)

    # Position
    if layout == "spatial":
        pos = {
            n: (d.get("center_x", 0), -d.get("center_y", 0))   # flip Y (image vs plot)
            for n, d in G.nodes(data=True)
        }
    elif layout == "kamada_kawai":
        try:
            pos = nx.kamada_kawai_layout(G)
        except Exception:
            pos = nx.spring_layout(G, seed=42)
    elif layout == "spectral":
        try:
            pos = nx.spectral_layout(G)
        except Exception:
            pos = nx.spring_layout(G, seed=42)
    else:
        pos = nx.spring_layout(G, seed=42, k=2.0)

    # Node colours
    node_colors = []
    for nid, d in G.nodes(data=True):
        cls = d.get("symbol_class", "unknown")
        bgr = _CLASS_COLORS.get(cls, _DEFAULT_COLOR)
        rgb = (bgr[2] / 255, bgr[1] / 255, bgr[0] / 255)
        node_colors.append(rgb)

    # Node labels
    labels = {}
    for nid, d in G.nodes(data=True):
        tag = d.get("isa_tag") or d.get("label") or ""
        labels[nid] = tag if tag else nid[:8]

    # Edge colours by line type
    edge_colors = []
    for _, _, d in G.edges(data=True):
        lt = d.get("line_type", "unknown")
        if lt == "main_process":
            edge_colors.append("#4a9fd4")
        elif lt == "instrument":
            edge_colors.append("#d4a44a")
        elif lt == "signal":
            edge_colors.append("#4ad464")
        else:
            edge_colors.append("#aaaaaa")

    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors,
        node_size=350, alpha=0.90,
    )
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color=edge_colors,
        width=1.5, alpha=0.70, arrows=True, arrowsize=12,
    )
    nx.draw_networkx_labels(
        G, pos, labels, ax=ax,
        font_size=7, font_color="#1a1a1a",
    )

    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.axis("off")

    # Legend
    seen_classes = {d.get("symbol_class", "unknown") for _, d in G.nodes(data=True)}
    patches = []
    for cls in sorted(seen_classes)[:12]:
        bgr = _CLASS_COLORS.get(cls, _DEFAULT_COLOR)
        rgb = (bgr[2] / 255, bgr[1] / 255, bgr[0] / 255)
        patches.append(mpatches.Patch(color=rgb, label=cls.replace("_", " ")))
    if patches:
        ax.legend(handles=patches, loc="upper left", fontsize=7, framealpha=0.8)

    plt.tight_layout()
    fig.savefig(str(output_path), dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    log.info("Graph image saved → %s", output_path)
    return output_path


def draw_graph_interactive(
    G,
    output_path: str | Path,
    title: str = "P&ID Interactive Graph",
    height: str = "750px",
) -> Optional[Path]:
    """
    Generate interactive Pyvis HTML graph (requires pyvis).
    Falls back to None if not installed.
    """
    try:
        from pyvis.network import Network  # type: ignore
    except ImportError:
        log.info("pyvis not installed — skipping interactive graph")
        return None

    output_path = Path(output_path)
    net = Network(height=height, width="100%", directed=G.is_directed(), notebook=False)
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "forceAtlas2Based": {
          "springLength": 120,
          "springConstant": 0.08,
          "damping": 0.6
        },
        "solver": "forceAtlas2Based",
        "stabilization": {"iterations": 180}
      },
      "nodes": {"font": {"size": 11}},
      "edges": {"smooth": {"type": "continuous"}}
    }
    """)

    for nid, data in G.nodes(data=True):
        cls   = data.get("symbol_class", "unknown")
        label = data.get("isa_tag") or data.get("label") or nid[:10]
        bgr   = _CLASS_COLORS.get(cls, _DEFAULT_COLOR)
        color = f"#{bgr[2]:02x}{bgr[1]:02x}{bgr[0]:02x}"
        title_str = (
            f"<b>{label}</b><br>"
            f"Type: {cls.replace('_', ' ')}<br>"
            f"Conf: {data.get('confidence', 0):.2f}"
        )
        net.add_node(
            nid, label=label, title=title_str,
            color=color, size=20,
            x=data.get("center_x", 0) / 2,
            y=data.get("center_y", 0) / 2,
        )

    for u, v, data in G.edges(data=True):
        lt = data.get("line_type", "unknown")
        color = {"main_process": "#4a9fd4", "instrument": "#d4a44a",
                 "signal": "#4ad464"}.get(lt, "#aaaaaa")
        net.add_edge(u, v, title=lt, color=color, width=2)

    net.write_html(str(output_path))
    log.info("Interactive graph → %s", output_path)
    return output_path
