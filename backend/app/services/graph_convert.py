"""Convert pipeline NetworkX graph to API contract format (nodes with type, label, attributes; edges)."""
from typing import Any, Dict, List

import networkx as nx

# Map symbol_class from pipeline to API node type
SYMBOL_CLASS_TO_TYPE: Dict[str, str] = {
    # Valves
    "gate_valve": "valve",
    "globe_valve": "valve",
    "ball_valve": "valve",
    "butterfly_valve": "valve",
    "check_valve": "valve",
    "needle_valve": "valve",
    "plug_valve": "valve",
    "diaphragm_valve": "valve",
    "relief_valve": "valve",
    "control_valve": "valve",
    "solenoid_valve": "valve",
    "pressure_regulator": "valve",
    # Pumps & Compressors
    "centrifugal_pump": "pump",
    "positive_displacement_pump": "pump",
    "compressor": "compressor",
    "fan": "pump",
    # Vessels & Tanks
    "vessel": "tank",
    "tank": "tank",
    "column": "tank",
    "drum": "tank",
    "separator": "tank",
    "heat_exchanger": "tank",
    "filter": "tank",
    "strainer": "tank",
    # Instruments -> sensor
    "flow_indicator": "sensor",
    "flow_transmitter": "sensor",
    "flow_controller": "sensor",
    "pressure_indicator": "sensor",
    "pressure_transmitter": "sensor",
    "pressure_controller": "sensor",
    "temperature_indicator": "sensor",
    "temperature_transmitter": "sensor",
    "level_indicator": "sensor",
    "level_transmitter": "sensor",
    "level_controller": "sensor",
    "analyzer": "sensor",
    "orifice_plate": "sensor",
    "flow_meter": "sensor",
    # Structural -> pipe (connections/junctions)
    "junction": "pipe",
    "reducer": "pipe",
    "tee": "pipe",
    "elbow": "pipe",
    "flange": "pipe",
    "motor": "pump",
    "agitator": "pump",
    "nozzle": "pipe",
    "vent": "pipe",
    "drain": "pipe",
}

ALLOWED_TYPES = {"pump", "valve", "sensor", "tank", "pipe", "compressor"}


def symbol_class_to_api_type(symbol_class: str) -> str:
    if not symbol_class:
        return "pipe"
    t = SYMBOL_CLASS_TO_TYPE.get(symbol_class.lower(), "pipe")
    return t if t in ALLOWED_TYPES else "pipe"


def graph_to_api_format(G: nx.Graph) -> Dict[str, Any]:
    """Convert NetworkX graph from pipeline to API nodes/edges format."""
    nodes: List[Dict[str, Any]] = []
    for nid, data in G.nodes(data=True):
        symbol_class = data.get("symbol_class") or "junction"
        api_type = symbol_class_to_api_type(symbol_class)
        label = data.get("label") or data.get("isa_tag") or nid
        attributes = {
            k: v
            for k, v in data.items()
            if k
            not in (
                "node_type",
                "symbol_class",
                "label",
                "isa_tag",
            )
            and v is not None
        }
        if data.get("isa_tag"):
            attributes["isa_tag"] = data["isa_tag"]
        nodes.append(
            {
                "id": nid,
                "type": api_type,
                "label": str(label),
                "attributes": attributes,
            }
        )

    edges: List[Dict[str, str]] = []
    for u, v in G.edges():
        edges.append({"source": u, "target": v})

    return {"nodes": nodes, "edges": edges}
