"""
models.py — Shared dataclasses that flow through the pipeline.

Every stage consumes and/or produces these plain Python objects so modules
remain decoupled from each other.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@dataclass
class BoundingBox:
    """Axis-aligned bounding box in pixel coordinates."""
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def iou(self, other: "BoundingBox") -> float:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def to_dict(self) -> Dict[str, int]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    def expanded(self, px: int) -> "BoundingBox":
        return BoundingBox(
            max(0, self.x1 - px), max(0, self.y1 - px),
            self.x2 + px, self.y2 + px,
        )


@dataclass
class Detection:
    """A single detected symbol."""
    node_id: str                        # unique id, e.g. "valve_0"
    symbol_class: str                   # e.g. "gate_valve"
    bbox: BoundingBox
    confidence: float
    label: Optional[str] = None         # OCR-extracted tag, e.g. "FCV-101"
    isa_tag: Optional[str] = None       # parsed ISA tag
    attributes: Dict[str, Any] = field(default_factory=dict)
    source: str = "classical"           # "classical" | "yolo" | "vlm"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id":      self.node_id,
            "symbol_class": self.symbol_class,
            "bbox":         self.bbox.to_dict(),
            "center":       self.bbox.center,
            "confidence":   round(self.confidence, 4),
            "label":        self.label,
            "isa_tag":      self.isa_tag,
            "attributes":   self.attributes,
            "source":       self.source,
        }


# ---------------------------------------------------------------------------
# Lines / Pipes
# ---------------------------------------------------------------------------

@dataclass
class LineSegment:
    """A detected straight pipe segment."""
    seg_id: str
    x1: int
    y1: int
    x2: int
    y2: int
    line_type: str = "main_process"    # "main_process" | "instrument" | "signal"
    line_number: Optional[str] = None

    @property
    def length(self) -> float:
        return ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5

    @property
    def midpoint(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seg_id":      self.seg_id,
            "start":       (self.x1, self.y1),
            "end":         (self.x2, self.y2),
            "length":      round(self.length, 2),
            "line_type":   self.line_type,
            "line_number": self.line_number,
        }


@dataclass
class Junction:
    """T-junction or crossing in the pipe skeleton."""
    junc_id: str
    x: int
    y: int
    connected_segs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "junc_id":        self.junc_id,
            "position":       (self.x, self.y),
            "connected_segs": self.connected_segs,
        }


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

@dataclass
class TextRegion:
    """An OCR-detected text region."""
    text: str
    confidence: float
    bbox: BoundingBox
    angle: float = 0.0                  # degrees of rotation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text":       self.text,
            "confidence": round(self.confidence, 4),
            "bbox":       self.bbox.to_dict(),
            "angle":      self.angle,
        }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    """A node in the P&ID graph (maps 1-to-1 with a Detection or Junction)."""
    node_id: str
    node_type: str          # symbol_class or "junction" or "endpoint"
    center: Tuple[float, float]
    label: Optional[str] = None
    isa_tag: Optional[str] = None
    bbox: Optional[BoundingBox] = None
    confidence: float = 1.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "node_id":   self.node_id,
            "node_type": self.node_type,
            "center":    self.center,
            "label":     self.label,
            "isa_tag":   self.isa_tag,
            "confidence": round(self.confidence, 4),
            "attributes": self.attributes,
        }
        if self.bbox:
            d["bbox"] = self.bbox.to_dict()
        return d


@dataclass
class GraphEdge:
    """An edge in the P&ID graph (a pipe or signal connection)."""
    edge_id: str
    source: str
    target: str
    line_type: str = "main_process"
    line_number: Optional[str] = None
    length_px: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id":     self.edge_id,
            "source":      self.source,
            "target":      self.target,
            "line_type":   self.line_type,
            "line_number": self.line_number,
            "length_px":   round(self.length_px, 2),
            "attributes":  self.attributes,
        }


# ---------------------------------------------------------------------------
# SOP
# ---------------------------------------------------------------------------

@dataclass
class SopStep:
    """A single procedure step extracted from the SOP document."""
    step_id: str
    heading: str
    text: str
    required_tags: List[str] = field(default_factory=list)
    valve_positions: Dict[str, str] = field(default_factory=dict)   # tag → "open"|"closed"
    parameters: Dict[str, str] = field(default_factory=dict)        # "pressure" → "5 bar"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id":        self.step_id,
            "heading":        self.heading,
            "text":           self.text[:300],
            "required_tags":  self.required_tags,
            "valve_positions": self.valve_positions,
            "parameters":     self.parameters,
        }


# ---------------------------------------------------------------------------
# Discrepancy
# ---------------------------------------------------------------------------

SEVERITY_LEVELS = ["CRITICAL", "WARNING", "INFO"]


@dataclass
class Discrepancy:
    disc_id: str
    severity: str                         # CRITICAL | WARNING | INFO
    disc_type: str                        # missing_component | type_mismatch | ...
    sop_reference: Optional[str] = None
    sop_tag: Optional[str] = None
    graph_tag: Optional[str] = None
    message: str = ""
    suggested_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "disc_id":          self.disc_id,
            "severity":         self.severity,
            "type":             self.disc_type,
            "sop_reference":    self.sop_reference,
            "sop_tag":          self.sop_tag,
            "graph_tag":        self.graph_tag,
            "message":          self.message,
            "suggested_action": self.suggested_action,
        }
