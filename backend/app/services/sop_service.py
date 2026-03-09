"""SOP ingestion: extract text and structure using LangChain + Gemini; vector store for retrieval."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Max chars to log for LLM prompt/response (rest truncated)
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


def extract_sop_text(file_path: str | Path) -> str:
    """Extract plain text from .docx or .txt for embedding/LLM."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            import docx
            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            logger.warning("python-docx failed: %s, trying zip fallback", e)
            return _extract_docx_via_zip(path)
    elif suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    else:
        return path.read_text(encoding="utf-8", errors="replace")


def _extract_docx_via_zip(path: Path) -> str:
    import re
    import zipfile
    with zipfile.ZipFile(str(path), "r") as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"<w:p[ >]", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    xml = xml.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return "\n".join(l.strip() for l in xml.split("\n") if l.strip())


def ingest_sop_with_gemini(file_path: str | Path, pid_id: str) -> Dict[str, Any]:
    """
    Extract SOP content and optionally structure with Gemini.
    Returns dict with extracted_text and optionally steps/components for validation.
    """
    text = extract_sop_text(file_path)
    settings = get_settings()
    if not settings.gemini_api_key:
        return {"extracted_text": text, "steps": [], "components_mentioned": []}

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError as e:
        logger.warning("LangChain/GenAI not installed: %s", e)
        return {"extracted_text": text, "steps": [], "components_mentioned": []}

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert at parsing Standard Operating Procedure (SOP) documents for process plants.
Extract structured information. Focus on:
1. Process steps (numbered or section headings and their instructions).
2. Any equipment or instrument tags mentioned (e.g. FCV-101, PT-203, P-101, tank T-1).
3. Valve positions mentioned (open/close for specific tags).
4. Parameters (pressure, temperature, flow) and setpoints.
Return valid JSON only, no markdown."""),
        ("human", "SOP text:\n\n{text}\n\nReturn a JSON object with keys: steps (list of {{step_id, heading, text, required_tags[], valve_positions{{tag: open|closed}}, parameters{{}}}}), components_mentioned (list of unique equipment/tag names)."),
    ])

    chain = prompt | llm
    sop_input = text[:12000]
    _log_llm_payload("SOP ingestion", {"text": sop_input}, max_chars=4000)
    # Gemini can take 30–90s for long SOPs; 120s timeout then fail with clear error
    resp = chain.invoke({"text": sop_input}, timeout=120)  # limit token
    content = resp.content if hasattr(resp, "content") else str(resp)
    _log_llm_response("SOP ingestion", content, max_chars=4000)
    # LangChain can return content as list of parts (e.g. [str] or [dict]); normalize
    if isinstance(content, list):
        content = content[0] if content else "{}"
    if isinstance(content, dict):
        parsed = content
    else:
        if isinstance(content, (bytes, bytearray)):
            content = content.decode("utf-8", errors="replace")
        if not isinstance(content, str):
            content = str(content)
        # Strip markdown code block if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"steps": [], "components_mentioned": []}
    if not isinstance(parsed, dict):
        parsed = {"steps": [], "components_mentioned": []}
    parsed["extracted_text"] = text
    return parsed


def get_relevant_graph_context(
    graph_summary: str,
    graph_chunks: List[str],
    query: str,
    top_k: int = 10,
) -> List[str]:
    """
    Retrieve graph chunks relevant to the query (SOP step or component).
    Uses in-memory similarity if no vector store; otherwise Chroma.
    """
    settings = get_settings()
    if not graph_chunks:
        return [graph_summary]

    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
    except ImportError:
        # Fallback: return full summary + first chunks
        return [graph_summary] + graph_chunks[:top_k]

    persist_dir = settings.chroma_persist_dir
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    collection_name = f"pid_graph_{hash(graph_summary) % 10**8}"
    try:
        coll = client.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
    except Exception:
        coll = client.create_collection(collection_name, metadata={"hnsw:space": "cosine"})

    # If collection is empty, add graph chunks
    if coll.count() == 0 and graph_chunks:
        coll.add(
            ids=[f"c_{i}" for i in range(len(graph_chunks))],
            documents=graph_chunks,
        )

    results = coll.query(query_texts=[query], n_results=min(top_k, len(graph_chunks)))
    docs = results.get("documents", [[]])
    if docs and docs[0]:
        return [graph_summary] + list(docs[0])
    return [graph_summary] + graph_chunks[:top_k]
