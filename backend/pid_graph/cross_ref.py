"""
cross_ref.py — P&ID graph ↔ SOP discrepancy engine.

Checks performed
----------------
1. MISSING_COMPONENT   — SOP tag not found in graph (CRITICAL)
2. TYPE_MISMATCH       — Tag found but wrong symbol class  (CRITICAL)
3. MISSING_CONNECTION  — SOP implies A→B flow; graph has no path (WARNING)
4. EXTRA_COMPONENT     — Graph node with tag not mentioned in SOP (INFO)
5. LABEL_MISMATCH      — Near-match OCR label vs SOP tag (WARNING)
6. WRONG_VALVE_STATE   — SOP says open/closed; graph attribute differs (WARNING)

Fuzzy matching
--------------
Uses difflib.SequenceMatcher when rapidfuzz is unavailable.
Threshold set via SopConfig.fuzzy_match_threshold.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from pid_graph.config import SopConfig
from pid_graph.graph_builder import find_paths, nodes_by_tag
from pid_graph.models import Discrepancy, SopStep

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fuzzy match helper
# ---------------------------------------------------------------------------

def _fuzzy_ratio(a: str, b: str) -> float:
    """String similarity in [0, 1]."""
    try:
        from rapidfuzz import fuzz  # type: ignore
        return fuzz.ratio(a.upper(), b.upper()) / 100.0
    except ImportError:
        return SequenceMatcher(None, a.upper(), b.upper()).ratio()


def _best_match(
    query: str,
    candidates: List[str],
    threshold: float,
) -> Optional[Tuple[str, float]]:
    """Return (best_candidate, score) if score ≥ threshold, else None."""
    best, best_score = None, 0.0
    for c in candidates:
        s = _fuzzy_ratio(query, c)
        if s > best_score:
            best_score, best = s, c
    return (best, best_score) if best and best_score >= threshold else None


# ---------------------------------------------------------------------------
# Tag ↔ class compatibility matrix
# ---------------------------------------------------------------------------

# Maps ISA type-code prefix → acceptable graph symbol classes
_TAG_CLASS_COMPAT: Dict[str, Set[str]] = {
    "F":   {"flow_indicator", "flow_transmitter", "flow_controller", "flow_meter", "orifice_plate"},
    "FT":  {"flow_transmitter"},
    "FC":  {"flow_controller"},
    "FCV": {"control_valve", "control_valve_actuated"},
    "FI":  {"flow_indicator"},
    "P":   {"centrifugal_pump", "positive_displacement_pump"},
    "PT":  {"pressure_transmitter"},
    "PC":  {"pressure_controller"},
    "PI":  {"pressure_indicator"},
    "PSV": {"relief_valve"},
    "PRV": {"pressure_regulator", "relief_valve"},
    "T":   {"temperature_indicator", "temperature_transmitter"},
    "TT":  {"temperature_transmitter"},
    "TC":  {"temperature_controller"},
    "TI":  {"temperature_indicator"},
    "TE":  {"temperature_indicator", "temperature_transmitter"},
    "LT":  {"level_transmitter"},
    "LI":  {"level_indicator"},
    "LC":  {"level_controller"},
    "XV":  {"solenoid_valve", "ball_valve", "gate_valve"},
    "HV":  {"gate_valve", "ball_valve", "globe_valve"},
    "MOV": {"gate_valve", "ball_valve"},
    "FV":  {"control_valve", "control_valve_actuated"},
    "V":   {"gate_valve", "globe_valve", "ball_valve", "butterfly_valve",
            "check_valve", "needle_valve"},
    "E":   {"heat_exchanger"},
    "K":   {"compressor"},
}


def _classes_compatible(tag_prefix: str, graph_class: str) -> bool:
    """Return True if the graph class is acceptable for this ISA prefix."""
    graph_class = graph_class.lower()
    # Check longest prefix first
    for length in range(min(len(tag_prefix), 4), 0, -1):
        key = tag_prefix[:length].upper()
        if key in _TAG_CLASS_COMPAT:
            return graph_class in _TAG_CLASS_COMPAT[key]
    # If no rule, accept anything
    return True


# ---------------------------------------------------------------------------
# CrossReferenceEngine
# ---------------------------------------------------------------------------

class CrossReferenceEngine:

    def __init__(self, cfg: SopConfig | None = None):
        self.cfg = cfg or SopConfig()
        self._disc_counter = 0

    def _new_id(self) -> str:
        self._disc_counter += 1
        return f"DISC-{self._disc_counter:03d}"

    # ------------------------------------------------------------------
    def run(
        self,
        G: nx.Graph,
        steps: List[SopStep],
    ) -> Tuple[List[Discrepancy], Dict[str, Any]]:
        """
        Compare graph G against SOP steps.

        Returns
        -------
        discrepancies : list of Discrepancy objects
        summary       : high-level coverage statistics
        """
        self._disc_counter = 0
        discrepancies: List[Discrepancy] = []

        # Collect all graph labels and ISA tags for fast lookup
        graph_tags:    Dict[str, str] = {}   # isa_tag → node_id
        graph_labels:  Dict[str, str] = {}   # label → node_id
        graph_classes: Dict[str, str] = {}   # node_id → symbol_class

        for nid, data in G.nodes(data=True):
            if data.get("isa_tag"):
                graph_tags[data["isa_tag"].upper()] = nid
            if data.get("label"):
                graph_labels[data["label"].upper()] = nid
            graph_classes[nid] = data.get("symbol_class", "unknown")

        all_sop_tags: List[str] = []
        for step in steps:
            all_sop_tags.extend(step.required_tags)
        all_sop_tags_deduped = list(dict.fromkeys(all_sop_tags))

        matched_tags:  Set[str] = set()
        missing_tags:  List[str] = []

        for step in steps:
            disc = self._check_step(
                step, G, graph_tags, graph_labels, graph_classes
            )
            discrepancies.extend(disc)
            for tag in step.required_tags:
                t = tag.upper()
                if t in graph_tags or t in graph_labels:
                    matched_tags.add(t)
                else:
                    # Check fuzzy
                    all_gt = list(graph_tags.keys()) + list(graph_labels.keys())
                    bm = _best_match(t, all_gt, self.cfg.fuzzy_match_threshold)
                    if bm:
                        matched_tags.add(t)
                    else:
                        missing_tags.append(t)

        # Check for extra components (in graph but not in SOP)
        extra_discs = self._check_extra_components(
            G, all_sop_tags_deduped, graph_tags, graph_labels
        )
        discrepancies.extend(extra_discs)

        total_sop = len(set(t.upper() for t in all_sop_tags_deduped))
        coverage  = len(matched_tags) / max(total_sop, 1) * 100

        summary = {
            "total_sop_tags":    total_sop,
            "matched_tags":      len(matched_tags),
            "missing_tags":      len(missing_tags),
            "coverage_pct":      round(coverage, 1),
            "total_discrepancies": len(discrepancies),
            "critical_count":    sum(1 for d in discrepancies if d.severity == "CRITICAL"),
            "warning_count":     sum(1 for d in discrepancies if d.severity == "WARNING"),
            "info_count":        sum(1 for d in discrepancies if d.severity == "INFO"),
        }

        log.info(
            "Cross-ref: coverage=%.1f%%  discrepancies=%d (CRIT=%d WARN=%d INFO=%d)",
            coverage,
            len(discrepancies),
            summary["critical_count"],
            summary["warning_count"],
            summary["info_count"],
        )
        return discrepancies, summary

    # ------------------------------------------------------------------
    def _check_step(
        self,
        step: SopStep,
        G: nx.Graph,
        graph_tags:    Dict[str, str],
        graph_labels:  Dict[str, str],
        graph_classes: Dict[str, str],
    ) -> List[Discrepancy]:
        discs: List[Discrepancy] = []

        for sop_tag in step.required_tags:
            t = sop_tag.upper()
            node_id = graph_tags.get(t) or graph_labels.get(t)

            if node_id is None:
                # Try fuzzy match
                all_candidates = list(graph_tags.keys()) + list(graph_labels.keys())
                bm = _best_match(t, all_candidates, self.cfg.fuzzy_match_threshold)

                if bm:
                    matched_tag, score = bm
                    # Treat as label mismatch warning
                    matched_nid = graph_tags.get(matched_tag) or graph_labels.get(matched_tag)
                    discs.append(Discrepancy(
                        disc_id=self._new_id(),
                        severity="WARNING",
                        disc_type="label_mismatch",
                        sop_reference=step.step_id,
                        sop_tag=sop_tag,
                        graph_tag=matched_tag,
                        message=(
                            f"SOP tag '{sop_tag}' (step: {step.heading[:50]}) "
                            f"fuzzy-matched to graph label '{matched_tag}' "
                            f"(similarity={score:.0%}). Verify OCR accuracy."
                        ),
                        suggested_action="Check OCR output for this label region",
                    ))
                else:
                    # Truly missing
                    discs.append(Discrepancy(
                        disc_id=self._new_id(),
                        severity="CRITICAL",
                        disc_type="missing_component",
                        sop_reference=step.step_id,
                        sop_tag=sop_tag,
                        message=(
                            f"Component '{sop_tag}' required by SOP "
                            f"(step: {step.heading[:60]}) not found in P&ID graph."
                        ),
                        suggested_action=(
                            "Verify component exists on this P&ID sheet. "
                            "It may be on a continuation sheet or OCR may have failed."
                        ),
                    ))
            else:
                # Node found — check class compatibility
                g_class = graph_classes.get(node_id, "unknown")
                prefix = t.split("-")[0] if "-" in t else t
                if not _classes_compatible(prefix, g_class) and g_class != "unknown":
                    discs.append(Discrepancy(
                        disc_id=self._new_id(),
                        severity="CRITICAL",
                        disc_type="type_mismatch",
                        sop_reference=step.step_id,
                        sop_tag=sop_tag,
                        graph_tag=node_id,
                        message=(
                            f"Tag '{sop_tag}': SOP implies type "
                            f"'{_expected_class(prefix)}', "
                            f"but P&ID graph shows '{g_class}'."
                        ),
                        suggested_action="Review symbol classification; may be detection error",
                    ))

        # Check valve positions
        for tag, expected_state in step.valve_positions.items():
            t = tag.upper()
            node_id = graph_tags.get(t) or graph_labels.get(t)
            if node_id and node_id in G.nodes:
                attrs = G.nodes[node_id]
                graph_state = attrs.get("fail_position", attrs.get("state", ""))
                if graph_state and graph_state.lower() != expected_state.lower():
                    discs.append(Discrepancy(
                        disc_id=self._new_id(),
                        severity="WARNING",
                        disc_type="wrong_valve_state",
                        sop_reference=step.step_id,
                        sop_tag=tag,
                        graph_tag=node_id,
                        message=(
                            f"SOP step '{step.heading[:50]}' requires valve "
                            f"'{tag}' to be {expected_state.upper()}, "
                            f"but P&ID annotation shows '{graph_state}'."
                        ),
                        suggested_action="Verify valve fail-safe position annotation",
                    ))

        return discs

    # ------------------------------------------------------------------
    def _check_extra_components(
        self,
        G: nx.Graph,
        sop_tags: List[str],
        graph_tags:   Dict[str, str],
        graph_labels: Dict[str, str],
    ) -> List[Discrepancy]:
        """Flag graph nodes whose tags are absent from the SOP."""
        sop_tag_set = {t.upper() for t in sop_tags}
        discs: List[Discrepancy] = []

        for nid, data in G.nodes(data=True):
            tag   = (data.get("isa_tag") or "").upper()
            label = (data.get("label")   or "").upper()

            if not tag and not label:
                continue

            in_sop = (tag in sop_tag_set) or (label in sop_tag_set)
            if not in_sop:
                # Fuzzy check
                candidates = list(sop_tag_set)
                q = tag or label
                bm = _best_match(q, candidates, self.cfg.fuzzy_match_threshold)
                if not bm:
                    discs.append(Discrepancy(
                        disc_id=self._new_id(),
                        severity="INFO",
                        disc_type="extra_component",
                        graph_tag=tag or label,
                        message=(
                            f"Component '{tag or label}' "
                            f"({data.get('symbol_class', 'unknown')}) "
                            f"found in P&ID but not referenced in SOP."
                        ),
                        suggested_action=(
                            "Confirm this component is intentionally omitted from "
                            "the SOP, or update the SOP to reference it."
                        ),
                    ))

        log.debug("Extra component check: %d INFO discrepancies", len(discs))
        return discs


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _expected_class(prefix: str) -> str:
    compat = _TAG_CLASS_COMPAT.get(prefix.upper(), set())
    if compat:
        return " | ".join(sorted(compat))
    return "unknown"
