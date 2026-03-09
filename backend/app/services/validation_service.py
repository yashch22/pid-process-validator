"""SOP vs P&ID validation using Gemini and optional retrieval."""
import ast
import json
import logging
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_LLM_LOG_MAX_CHARS = 4000


def _log_llm_payload(label: str, payload: Dict[str, Any], max_chars: int = _LLM_LOG_MAX_CHARS) -> None:
    """Log prompt payload sent to LLM (truncated)."""
    s = json.dumps(payload, indent=0, default=str)[:max_chars]
    if len(s) >= max_chars:
        s += "\n... (truncated)"
    logger.info("LLM request [%s]: %s", label, s)


def _log_llm_response(label: str, content: Any, max_chars: int = _LLM_LOG_MAX_CHARS) -> None:
    """Log raw response from LLM (truncated)."""
    if isinstance(content, (list, dict)):
        s = json.dumps(content, indent=0, default=str)[:max_chars]
    else:
        s = str(content)[:max_chars]
    if len(s) >= max_chars:
        s += "\n... (truncated)"
    logger.info("LLM response [%s]: %s", label, s)

ISSUE_TYPE_MAP = {
    "missing_component": "missing_component",
    "missing_component_in_graph": "missing_component",
    "connection_mismatch": "connection_mismatch",
    "attribute_mismatch": "attribute_mismatch",
    "unexpected_component": "unexpected_component",
    "extra_component": "unexpected_component",
    "type_mismatch": "attribute_mismatch",
    "validation_skipped": "validation_skipped",
}


def _graph_to_summary_and_chunks(graph_json: Dict[str, Any]) -> tuple[str, List[str]]:
    """Produce a short summary and one chunk per node (for retrieval)."""
    nodes = graph_json.get("nodes") or []
    edges = graph_json.get("edges") or []
    summary = f"P&ID graph: {len(nodes)} nodes, {len(edges)} edges."
    chunks = []
    node_by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        nid = n["id"]
        typ = n.get("type", "")
        label = n.get("label", "")
        attrs = n.get("attributes", {})
        chunk = f"Node {nid}: type={typ}, label={label}"
        if attrs:
            chunk += ", " + ", ".join(f"{k}={v}" for k, v in list(attrs.items())[:5])
        chunks.append(chunk)
    for e in edges[:100]:
        s, t = e.get("source"), e.get("target")
        if s and t:
            chunks.append(f"Edge: {s} -> {t}")
    return summary, chunks


def validate_sop_against_graph(
    graph_json: Dict[str, Any],
    sop_extracted: Dict[str, Any],
    pid_id: str,
) -> Dict[str, Any]:
    """
    Use Gemini to compare SOP content with P&ID graph and return issues.
    status: completed | failed
    issues: list of { type, component?, description, severity, relatedNodes }
    """
    settings = get_settings()
    issues: List[Dict[str, Any]] = []
    status = "completed"

    if not settings.gemini_api_key:
        return {
            "status": "completed",
            "issues": [
                {
                    "type": "validation_skipped",
                    "component": None,
                    "description": "Gemini API key not set; validation skipped.",
                    "severity": "info",
                    "relatedNodes": [],
                }
            ],
        }

    graph_summary, graph_chunks = _graph_to_summary_and_chunks(graph_json)
    sop_text = sop_extracted.get("extracted_text", "")
    steps = sop_extracted.get("steps", [])
    components_mentioned = sop_extracted.get("components_mentioned", [])

    if not sop_text and not steps:
        return {"status": "completed", "issues": []}

    # Build context for LLM: full graph summary + node list + edges
    nodes_str = json.dumps(graph_json.get("nodes", [])[:200], indent=0)
    edges_str = json.dumps(graph_json.get("edges", [])[:300], indent=0)
    sop_context = sop_text[:8000] if sop_text else json.dumps(steps, indent=2)[:8000]

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        return {
            "status": "failed",
            "issues": [
                {
                    "type": "attribute_mismatch",
                    "description": "LangChain/GenAI not installed.",
                    "severity": "error",
                    "relatedNodes": [],
                }
            ],
        }

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0,
    )

    system = """You are an expert at comparing Piping & Instrumentation Diagrams (P&IDs) with Standard Operating Procedures (SOPs).
Given a P&ID graph (nodes: id, type, label, attributes; edges: source, target) and SOP text/steps, identify discrepancies.
Report each issue as a JSON object with:
- type: one of "missing_component", "connection_mismatch", "attribute_mismatch", "unexpected_component"
- component: optional tag or node id if applicable
- description: short human-readable explanation
- severity: "error" | "warning" | "info"
- relatedNodes: list of node ids or labels involved

Focus on: components mentioned in SOP but not in graph; connections implied by SOP that don't exist; wrong types or attributes; components in graph not referenced in SOP.
Return ONLY a JSON array of issue objects, no other text."""

    user = f"""P&ID graph (nodes):\n{nodes_str}\n\nP&ID graph (edges):\n{edges_str}\n\nSOP content:\n{sop_context}\n\nList all discrepancies as a JSON array."""

    _log_llm_payload("validation", {"system": system, "user": user}, max_chars=4000)
    try:
        # Gemini can take 30–90s for large graphs; 120s timeout then fail with clear error
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)], timeout=120)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        _log_llm_response("validation", raw, max_chars=4000)
        parsed = None
        # LangChain/Gemini can return: list of parts, dict {"type":"text","text":...}, or plain array
        def _extract_issues(obj):
            if obj is None:
                return None
            if isinstance(obj, list):
                return obj if obj and isinstance(obj[0], dict) else None
            if isinstance(obj, dict) and "text" in obj:
                t = obj["text"]
                if isinstance(t, list):
                    return t
                if isinstance(t, str):
                    try:
                        return json.loads(t)
                    except json.JSONDecodeError:
                        try:
                            return ast.literal_eval(t)
                        except (ValueError, SyntaxError):
                            pass
            return None

        if isinstance(raw, list):
            first = raw[0] if raw else None
            parsed = _extract_issues(first)
            if parsed is None and first is not None:
                raw = first
        if parsed is None and isinstance(raw, dict):
            parsed = _extract_issues(raw)
        if parsed is None and isinstance(raw, list):
            parsed = raw if raw and isinstance(raw[0], dict) else None
        if parsed is None:
            content = raw
            if isinstance(content, (bytes, bytearray)):
                content = content.decode("utf-8", errors="replace")
            if not isinstance(content, str):
                content = str(content)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as e:
                # Gemini sometimes returns Python-style literals (single quotes); try ast
                try:
                    parsed = ast.literal_eval(content)
                except (ValueError, SyntaxError):
                    raise e
        if isinstance(parsed, list):
            for i in parsed:
                if isinstance(i, dict):
                    t = i.get("type", "attribute_mismatch")
                    issues.append({
                        "type": ISSUE_TYPE_MAP.get(t, "attribute_mismatch"),
                        "component": i.get("component"),
                        "description": i.get("description", ""),
                        "severity": i.get("severity", "info"),
                        "relatedNodes": i.get("relatedNodes", i.get("related_nodes", [])),
                    })
    except json.JSONDecodeError as e:
        logger.exception("Gemini validation JSON parse error: %s", e)
        status = "failed"
        issues.append({
            "type": "attribute_mismatch",
            "description": f"Validation output parse error: {e}",
            "severity": "error",
            "relatedNodes": [],
        })
    except Exception as e:
        logger.exception("Gemini validation error: %s", e)
        status = "failed"
        issues.append({
            "type": "attribute_mismatch",
            "description": str(e),
            "severity": "error",
            "relatedNodes": [],
        })

    return {"status": status, "issues": issues}
