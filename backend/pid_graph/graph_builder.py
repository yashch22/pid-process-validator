"""
graph_builder.py — Assemble a NetworkX graph from pipeline stage outputs.

Node types
----------
  symbol      — detected P&ID component (valve, pump, sensor …)
  junction    — pipe T-junction / crossing inferred from skeleton
  endpoint    — dangling pipe end (no symbol found within snap radius)

Edge types
----------
  main_process   — main process piping
  instrument     — instrument tubing / capillary
  signal         — electrical / pneumatic signal line
  unknown        — unclassified connection

Graph serialisation
-------------------
  to_graphml()      → str (GraphML XML)
  to_node_link()    → dict (JSON-compatible node-link format)
  to_cytoscape()    → dict (Cytoscape.js format for web visualisation)
  save()            → writes .graphml + .json side-by-side
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from pid_graph.config import GraphConfig
from pid_graph.models import (
    BoundingBox, Detection, GraphEdge, GraphNode,
    Junction, LineSegment,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------


def _sanitize_for_graphml(G: nx.Graph) -> nx.Graph:
    """Replace None attribute values with empty strings (GraphML requirement)."""
    G2 = G.copy()
    for _, data in G2.nodes(data=True):
        for k, v in list(data.items()):
            if v is None:
                data[k] = ""
    for _, _, data in G2.edges(data=True):
        for k, v in list(data.items()):
            if v is None:
                data[k] = ""
    return G2

class GraphBuilder:
    """
    Constructs a NetworkX MultiGraph (or DiGraph if cfg.directed) from the
    outputs of the detection, OCR, and line-tracing stages.

    Usage
    -----
    >>> builder = GraphBuilder(cfg)
    >>> G = builder.build(detections, text_regions, segments, junctions, connectivity)
    >>> builder.save(G, output_dir)
    """

    def __init__(self, cfg: GraphConfig | None = None):
        self.cfg = cfg or GraphConfig()

    # ------------------------------------------------------------------
    def build(
        self,
        detections: List[Detection],
        segments: List[LineSegment],
        junctions: List[Junction],
        connectivity: Dict[str, List[str]],
    ) -> nx.Graph:
        """
        Build and return a NetworkX Graph.

        Parameters
        ----------
        detections    : List[Detection]  from detector + OCR
        segments      : List[LineSegment] from line tracer
        junctions     : List[Junction]   from line tracer
        connectivity  : {node_id: [node_id, ...]} from line tracer snap step
        """
        G = nx.DiGraph() if self.cfg.directed else nx.Graph()

        # ---- add symbol nodes ----
        for det in detections:
            cx, cy = det.bbox.center
            attrs: Dict[str, Any] = {
                "node_type":    "symbol",
                "symbol_class": det.symbol_class,
                "label":        det.label or "",
                "isa_tag":      det.isa_tag or "",
                "center_x":     round(cx, 2),
                "center_y":     round(cy, 2),
                "bbox_x1":      det.bbox.x1,
                "bbox_y1":      det.bbox.y1,
                "bbox_x2":      det.bbox.x2,
                "bbox_y2":      det.bbox.y2,
                "confidence":   round(det.confidence, 4),
                "source":       det.source,
            }
            attrs.update(det.attributes)
            G.add_node(det.node_id, **attrs)

        # ---- add junction nodes ----
        if self.cfg.add_virtual_junctions:
            for junc in junctions:
                if junc.junc_id in G:
                    continue
                G.add_node(
                    junc.junc_id,
                    node_type="junction",
                    symbol_class="junction",
                    label="",
                    isa_tag="",
                    center_x=float(junc.x),
                    center_y=float(junc.y),
                    confidence=1.0,
                    source="skeleton",
                )

        # ---- segment lookup for edge metadata ----
        seg_map: Dict[str, LineSegment] = {s.seg_id: s for s in segments}

        # ---- add edges from connectivity map ----
        edge_counter = 0
        seen_pairs = set()

        for src, targets in connectivity.items():
            for tgt in targets:
                if src not in G or tgt not in G:
                    continue
                pair = (min(src, tgt), max(src, tgt))
                if pair in seen_pairs and not self.cfg.directed:
                    continue
                seen_pairs.add(pair)

                # Find a matching segment for richer metadata
                seg_meta = _find_segment_for_edge(
                    G.nodes[src], G.nodes[tgt], segments
                )
                length_px = seg_meta.length if seg_meta else _node_dist(G, src, tgt)
                if length_px < self.cfg.min_edge_length:
                    continue

                edge_id = f"edge_{edge_counter:04d}"
                edge_counter += 1

                edge_attrs: Dict[str, Any] = {
                    "edge_id":     edge_id,
                    "line_type":   seg_meta.line_type if seg_meta else "unknown",
                    "line_number": seg_meta.line_number if seg_meta else "",
                    "length_px":   round(length_px, 2),
                }
                G.add_edge(src, tgt, **edge_attrs)

        # ---- remove degree-1 junction nodes (pid2graph-style: fewer spurious entities) ----
        if getattr(self.cfg, "remove_degree1_junctions", True):
            junction_degree1 = [
                n for n in G.nodes()
                if G.nodes[n].get("node_type") == "junction"
                and G.degree(n) == 1
            ]
            if junction_degree1:
                log.debug(
                    "Removing %d degree-1 junction nodes (single connection)",
                    len(junction_degree1),
                )
                G.remove_nodes_from(junction_degree1)

        # ---- remove isolated nodes unless they have an ISA tag (valid components) ----
        isolates = list(nx.isolates(G))
        removable = [n for n in isolates
                     if not G.nodes[n].get("isa_tag")
                     and G.nodes[n].get("source") not in ("ocr_injected",)
                     and G.nodes[n].get("confidence", 1.0) < 0.5]
        if removable:
            log.debug("Removing %d low-confidence isolated nodes", len(removable))
            G.remove_nodes_from(removable)

        log.info(
            "Graph built: %d nodes, %d edges",
            G.number_of_nodes(), G.number_of_edges(),
        )
        _log_summary(G)
        return G

    # ------------------------------------------------------------------
    def to_node_link(self, G: nx.Graph) -> Dict[str, Any]:
        """Serialise to JSON-compatible node-link dict."""
        return nx.node_link_data(G)

    def to_graphml(self, G: nx.Graph) -> str:
        """Serialise to GraphML XML string."""
        import io
        buf = io.BytesIO()
        nx.write_graphml(G, buf)
        return buf.getvalue().decode("utf-8")

    def to_cytoscape(self, G: nx.Graph) -> Dict[str, Any]:
        """
        Cytoscape.js compatible JSON.
        { elements: { nodes: [...], edges: [...] } }
        """
        nodes = []
        for nid, data in G.nodes(data=True):
            nodes.append({
                "data": {
                    "id":           nid,
                    "label":        data.get("label") or data.get("isa_tag") or nid,
                    "node_type":    data.get("node_type", "symbol"),
                    "symbol_class": data.get("symbol_class", ""),
                    "confidence":   data.get("confidence", 1.0),
                },
                "position": {
                    "x": data.get("center_x", 0),
                    "y": data.get("center_y", 0),
                },
            })

        edges = []
        for u, v, data in G.edges(data=True):
            edges.append({
                "data": {
                    "id":        data.get("edge_id", f"{u}_{v}"),
                    "source":    u,
                    "target":    v,
                    "line_type": data.get("line_type", "unknown"),
                    "length_px": data.get("length_px", 0),
                }
            })

        return {"elements": {"nodes": nodes, "edges": edges}}

    def save(
        self,
        G: nx.Graph,
        output_dir: str | Path,
        stem: str = "pid_graph",
    ) -> Dict[str, Path]:
        """
        Save graph in multiple formats.

        Returns dict of format → saved Path.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        saved: Dict[str, Path] = {}

        # GraphML (sanitize None values — GraphML doesn't support NoneType)
        gml_path = output_dir / f"{stem}.graphml"
        G_clean = _sanitize_for_graphml(G)
        nx.write_graphml(G_clean, str(gml_path))
        saved["graphml"] = gml_path
        log.info("Saved GraphML → %s", gml_path)

        # JSON node-link
        json_path = output_dir / f"{stem}.json"
        with open(json_path, "w") as f:
            json.dump(self.to_node_link(G), f, indent=2, default=str)
        saved["json"] = json_path
        log.info("Saved JSON → %s", json_path)

        # Cytoscape JSON
        cyto_path = output_dir / f"{stem}_cytoscape.json"
        with open(cyto_path, "w") as f:
            json.dump(self.to_cytoscape(G), f, indent=2)
        saved["cytoscape"] = cyto_path
        log.info("Saved Cytoscape JSON → %s", cyto_path)

        return saved


# ---------------------------------------------------------------------------
# Graph analysis helpers
# ---------------------------------------------------------------------------

def graph_summary(G: nx.Graph) -> Dict[str, Any]:
    """Compute summary statistics for reporting."""
    type_counts: Dict[str, int] = {}
    for _, data in G.nodes(data=True):
        t = data.get("symbol_class", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    line_type_counts: Dict[str, int] = {}
    for _, _, data in G.edges(data=True):
        lt = data.get("line_type", "unknown")
        line_type_counts[lt] = line_type_counts.get(lt, 0) + 1

    labelled_nodes = sum(1 for _, d in G.nodes(data=True) if d.get("label"))
    tagged_nodes   = sum(1 for _, d in G.nodes(data=True) if d.get("isa_tag"))

    return {
        "node_count":        G.number_of_nodes(),
        "edge_count":        G.number_of_edges(),
        "component_count":   nx.number_connected_components(G.to_undirected() if G.is_directed() else G),
        "labelled_nodes":    labelled_nodes,
        "tagged_nodes":      tagged_nodes,
        "component_types":   type_counts,
        "line_types":        line_type_counts,
        "avg_degree":        round(
            sum(d for _, d in G.degree()) / max(G.number_of_nodes(), 1), 2
        ),
    }


def find_paths(G: nx.Graph, source: str, target: str) -> List[List[str]]:
    """Return all simple paths between source and target (for SOP cross-ref)."""
    try:
        return list(nx.all_simple_paths(G, source, target, cutoff=10))
    except (nx.NodeNotFound, nx.NetworkXError):
        return []


def get_component_subgraph(G: nx.Graph, node_id: str, hops: int = 2) -> nx.Graph:
    """Extract ego-graph around a node for local inspection."""
    return nx.ego_graph(G, node_id, radius=hops)


def nodes_by_class(G: nx.Graph, symbol_class: str) -> List[str]:
    """Return node ids matching a symbol class (supports partial match)."""
    return [
        nid for nid, d in G.nodes(data=True)
        if symbol_class.lower() in d.get("symbol_class", "").lower()
    ]


def nodes_by_tag(G: nx.Graph, tag: str) -> List[str]:
    """Return node ids whose isa_tag matches (case-insensitive)."""
    tag_upper = tag.upper()
    return [
        nid for nid, d in G.nodes(data=True)
        if d.get("isa_tag", "").upper() == tag_upper
        or d.get("label", "").upper() == tag_upper
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_segment_for_edge(
    n1_data: Dict,
    n2_data: Dict,
    segments: List[LineSegment],
) -> Optional[LineSegment]:
    """
    Find the LineSegment whose endpoints are closest to two graph nodes.
    Returns None if nothing reasonable found.
    """
    cx1 = n1_data.get("center_x", 0)
    cy1 = n1_data.get("center_y", 0)
    cx2 = n2_data.get("center_x", 0)
    cy2 = n2_data.get("center_y", 0)

    best, best_score = None, float("inf")
    for seg in segments:
        d1 = _dist(cx1, cy1, seg.x1, seg.y1) + _dist(cx2, cy2, seg.x2, seg.y2)
        d2 = _dist(cx1, cy1, seg.x2, seg.y2) + _dist(cx2, cy2, seg.x1, seg.y1)
        score = min(d1, d2)
        if score < best_score:
            best_score, best = score, seg
    return best if best_score < 200 else None


def _node_dist(G: nx.Graph, u: str, v: str) -> float:
    import math
    du = G.nodes[u]
    dv = G.nodes[v]
    return math.hypot(
        du.get("center_x", 0) - dv.get("center_x", 0),
        du.get("center_y", 0) - dv.get("center_y", 0),
    )


def _dist(x1: float, y1: float, x2: float, y2: float) -> float:
    import math
    return math.hypot(x1 - x2, y1 - y2)


def _log_summary(G: nx.Graph) -> None:
    s = graph_summary(G)
    log.info(
        "  nodes=%d  edges=%d  components=%d  avg_degree=%.2f",
        s["node_count"], s["edge_count"],
        s["component_count"], s["avg_degree"],
    )
    if s["component_types"]:
        top = sorted(s["component_types"].items(), key=lambda x: -x[1])[:5]
        log.info("  top classes: %s", ", ".join(f"{c}×{n}" for c, n in top))
