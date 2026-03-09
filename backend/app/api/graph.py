"""Graph, validate, and search endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import PidDocument, SopDocument, ValidationRun
from app.schemas.api import GraphResponse, NodeOut, EdgeOut, ValidateResponse, IssueOut
from app.services.validation_service import validate_sop_against_graph
from app.services.vector_store import search_pids

router = APIRouter(prefix="", tags=["graph"])
logger = logging.getLogger(__name__)


@router.get("/pids")
async def list_pids(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List P&ID documents (for Dashboard Recent Analyses). Includes latest validation status."""
    result = await db.execute(
        select(PidDocument)
        .where(PidDocument.status == "completed")
        .order_by(PidDocument.created_at.desc())
        .limit(limit)
    )
    pids = result.scalars().all()
    out = []
    for p in pids:
        run_result = await db.execute(
            select(ValidationRun)
            .where(ValidationRun.pid_id == p.id)
            .order_by(ValidationRun.created_at.desc())
            .limit(1)
        )
        run = run_result.scalars().first()
        status = run.status if run else "graph_ready"
        issue_count = len(run.issues) if run and run.issues else 0
        out.append({
            "pid_id": p.id,
            "filename": p.file_name or "P&ID",
            "sopFilename": None,  # SOP not linked per-pid in new model
            "timestamp": p.created_at.isoformat() if p.created_at else "",
            "status": status,
            "issueCount": issue_count,
        })
    return {"pids": out}


@router.get("/sops")
async def list_sops(db: AsyncSession = Depends(get_db)):
    """List all SOP documents (standalone, not linked to a specific P&ID)."""
    result = await db.execute(
        select(SopDocument).order_by(SopDocument.created_at.desc())
    )
    sops = result.scalars().all()
    return {
        "sops": [
            {"sop_id": s.id, "file_name": s.file_name, "created_at": str(s.created_at)}
            for s in sops
        ],
    }


@router.get("/search")
async def search_pid_documents(q: str = Query(..., min_length=1), top_k: int = Query(10, ge=1, le=50)):
    """Search for P&ID documents by text (e.g. component tag, equipment name). Returns matching pid_ids for retrieval."""
    logger.info("GET /search: q=%r, top_k=%d", q[:100], top_k)
    results = search_pids(query=q, top_k=top_k)
    return {"query": q, "results": results}


@router.get("/pids/by-batch/{upload_batch_id}")
async def list_pids_by_batch(
    upload_batch_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all P&ID documents (pages) from the same PDF upload."""
    result = await db.execute(
        select(PidDocument)
        .where(PidDocument.upload_batch_id == upload_batch_id)
        .order_by(PidDocument.page_num.asc().nulls_last())
    )
    pids = result.scalars().all()
    return {
        "upload_batch_id": upload_batch_id,
        "pages": [
            {"pid_id": p.id, "page_num": p.page_num, "file_name": p.file_name, "status": p.status}
            for p in pids
        ],
    }


@router.get("/graph/{pid_id}", response_model=GraphResponse)
async def get_graph(
    pid_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return the extracted graph for a P&ID (nodes and edges in API format)."""
    result = await db.execute(select(PidDocument).where(PidDocument.id == pid_id))
    pid = result.scalars().first()
    if not pid:
        raise HTTPException(404, "P&ID not found")
    if pid.status != "completed":
        raise HTTPException(409, f"P&ID not ready: {pid.status}")
    if not pid.graph_json:
        raise HTTPException(404, "Graph not available")

    nodes = [NodeOut(**n) for n in pid.graph_json.get("nodes", [])]
    edges = [EdgeOut(**e) for e in pid.graph_json.get("edges", [])]
    return GraphResponse(nodes=nodes, edges=edges)


@router.post("/validate/sop/{sop_id}")
async def validate_sop(
    sop_id: str,
    top_k: int = Query(10, ge=1, le=50, description="Max matching P&IDs to validate against"),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate an SOP against matching P&IDs. Searches vector DB for P&IDs that match the SOP content,
    then validates against each. Returns results for all matching P&IDs.
    """
    sop_result = await db.execute(select(SopDocument).where(SopDocument.id == sop_id))
    sop = sop_result.scalars().first()
    if not sop:
        raise HTTPException(404, "SOP not found")

    sop_payload = sop.extracted_json or {"extracted_text": sop.extracted_text or ""}
    extracted_text = sop_payload.get("extracted_text", "")
    components = sop_payload.get("components_mentioned", [])
    search_query = " ".join(str(c) for c in components) + " " + (extracted_text[:3000] or "")

    if not search_query.strip():
        logger.info("Validate SOP %s: empty search query, no vector DB call", sop_id)
        return {"sop_id": sop_id, "matches": [], "results": []}

    logger.info("Validate SOP %s: searching vector DB for matching P&IDs (top_k=%d)", sop_id, top_k)
    matches = search_pids(query=search_query.strip(), top_k=top_k)
    logger.info("Validate SOP %s: vector DB returned %d matches", sop_id, len(matches))
    if not matches:
        return {"sop_id": sop_id, "matches": [], "results": []}

    results = []
    for m in matches:
        pid_id = m.get("pid_id")
        if not pid_id:
            continue
        pid_result = await db.execute(select(PidDocument).where(PidDocument.id == pid_id))
        pid = pid_result.scalars().first()
        if not pid or not pid.graph_json:
            continue

        validation_result = validate_sop_against_graph(pid.graph_json, sop_payload, pid_id)

        run = ValidationRun(
            pid_id=pid_id,
            sop_id=sop_id,
            status=validation_result["status"],
            issues=validation_result["issues"],
        )
        db.add(run)

        issues_list = validation_result.get("issues", [])
        issues_out = [
            IssueOut(
                type=iss.get("type", "attribute_mismatch"),
                component=iss.get("component"),
                description=iss.get("description", ""),
                severity=iss.get("severity", "info"),
                relatedNodes=iss.get("relatedNodes", iss.get("related_nodes", [])),
            )
            for iss in issues_list
        ]
        results.append({
            "pid_id": pid_id,
            "file_name": pid.file_name,
            "page_num": pid.page_num,
            "status": validation_result["status"],
            "issues": issues_out,
        })

    await db.commit()
    return {"sop_id": sop_id, "matches": matches, "results": results}


@router.get("/validation/sop/{sop_id}")
async def get_validation_by_sop(
    sop_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all validation results for an SOP (one result per linked P&ID).
    SOP is not bound to a single pid; it can link to multiple P&IDs.
    """
    sop_result = await db.execute(select(SopDocument).where(SopDocument.id == sop_id))
    sop = sop_result.scalars().first()
    if not sop:
        raise HTTPException(404, "SOP not found")

    run_result = await db.execute(
        select(ValidationRun, PidDocument)
        .join(PidDocument, ValidationRun.pid_id == PidDocument.id)
        .where(ValidationRun.sop_id == sop_id)
        .order_by(ValidationRun.created_at.desc())
    )
    rows = run_result.all()

    # Dedupe by pid_id (keep latest run per P&ID)
    seen: set[str] = set()
    results = []
    for run, pid in rows:
        if pid.id in seen:
            continue
        seen.add(pid.id)
        issues_out = [
            IssueOut(
                type=iss.get("type", "attribute_mismatch"),
                component=iss.get("component"),
                description=iss.get("description", ""),
                severity=iss.get("severity", "info"),
                relatedNodes=iss.get("relatedNodes", iss.get("related_nodes", [])),
            )
            for iss in (run.issues or [])
        ]
        results.append({
            "pid_id": pid.id,
            "file_name": pid.file_name,
            "page_num": pid.page_num,
            "status": run.status,
            "issues": issues_out,
        })

    return {"sop_id": sop_id, "sop_file_name": sop.file_name, "results": results}


@router.get("/validation/{pid_id}", response_model=ValidateResponse)
async def get_validation(
    pid_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the latest validation result for a P&ID (from ValidationRun or run fresh if SOP linked)."""
    result = await db.execute(
        select(ValidationRun)
        .where(ValidationRun.pid_id == pid_id)
        .order_by(ValidationRun.created_at.desc())
        .limit(1)
    )
    run = result.scalars().first()
    if run and run.issues is not None:
        issues_out = [
            IssueOut(
                type=iss.get("type", "attribute_mismatch"),
                component=iss.get("component"),
                description=iss.get("description", ""),
                severity=iss.get("severity", "info"),
                relatedNodes=iss.get("relatedNodes", iss.get("related_nodes", [])),
            )
            for iss in run.issues
        ]
        return ValidateResponse(status=run.status, issues=issues_out)

    # Fallback: run validation if SOP linked
    pid_result = await db.execute(select(PidDocument).where(PidDocument.id == pid_id))
    pid = pid_result.scalars().first()
    if not pid or not pid.graph_json:
        raise HTTPException(404, "P&ID not found or no graph")
    sop_result = await db.execute(
        select(SopDocument).where(SopDocument.pid_id == pid_id).order_by(SopDocument.created_at.desc()).limit(1)
    )
    sop = sop_result.scalars().first()
    sop_payload = sop.extracted_json or {"extracted_text": sop.extracted_text or ""} if sop else {}
    validation_result = validate_sop_against_graph(pid.graph_json, sop_payload, pid_id)
    return ValidateResponse(status=validation_result["status"], issues=validation_result.get("issues", []))


@router.post("/validate/{pid_id}", response_model=ValidateResponse)
async def validate_pid(
    pid_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Validate the SOP (if any linked to this P&ID) against the P&ID graph. Legacy: for explicit pid_id validation."""
    result = await db.execute(select(PidDocument).where(PidDocument.id == pid_id))
    pid = result.scalars().first()
    if not pid:
        raise HTTPException(404, "P&ID not found")
    if not pid.graph_json:
        raise HTTPException(400, "No graph available for this P&ID")

    sop_result = await db.execute(
        select(SopDocument).where(SopDocument.pid_id == pid_id).order_by(SopDocument.created_at.desc()).limit(1)
    )
    sop = sop_result.scalars().first()
    sop_payload = {}
    if sop:
        sop_payload = sop.extracted_json or {"extracted_text": sop.extracted_text or ""}

    validation_result = validate_sop_against_graph(pid.graph_json, sop_payload, pid_id)

    run = ValidationRun(
        pid_id=pid_id,
        status=validation_result["status"],
        issues=validation_result["issues"],
    )
    db.add(run)
    await db.commit()

    issues_list = validation_result.get("issues", [])
    issues_out = [
        IssueOut(
            type=iss.get("type", "attribute_mismatch"),
            component=iss.get("component"),
            description=iss.get("description", ""),
            severity=iss.get("severity", "info"),
            relatedNodes=iss.get("relatedNodes", iss.get("related_nodes", [])),
        )
        for iss in issues_list
    ]
    return ValidateResponse(
        status=validation_result["status"],
        issues=issues_out,
    )
