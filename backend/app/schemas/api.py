"""API request/response schemas matching the contract."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# Node type from API contract
NodeType = Literal["pump", "valve", "sensor", "tank", "pipe", "compressor"]


class NodeOut(BaseModel):
    id: str
    type: NodeType
    label: str = ""
    attributes: Dict[str, Any] = Field(default_factory=dict)


class EdgeOut(BaseModel):
    source: str
    target: str


class GraphResponse(BaseModel):
    nodes: List[NodeOut] = Field(default_factory=list)
    edges: List[EdgeOut] = Field(default_factory=list)


class IssueOut(BaseModel):
    type: Literal[
        "missing_component",
        "connection_mismatch",
        "attribute_mismatch",
        "unexpected_component",
        "validation_skipped",
    ]
    component: Optional[str] = None
    description: str
    severity: Literal["error", "warning", "info"]
    relatedNodes: List[str] = Field(default_factory=list, serialization_alias="relatedNodes")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class ValidateResponse(BaseModel):
    status: Literal["completed", "pending", "failed"]
    issues: List[IssueOut] = Field(default_factory=list)


class UploadPidResponse(BaseModel):
    pid_id: str
    upload_batch_id: Optional[str] = None  # set for multi-page PDFs; use /pids/by-batch/{id} to list pages
