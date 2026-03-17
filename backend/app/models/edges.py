from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class BaseEdge(BaseModel):
    id: Optional[str] = None
    label: str
    outV: str  # 시작 노드 ID
    inV: str   # 도착 노드 ID
    # v2.2 핵심: 모든 상태 변화와 지득은 story_order를 가짐
    story_order: float 
    properties: Dict[str, Any] = Field(default_factory=dict)

class Learns(BaseEdge):
    label: str = "LEARNS"
    method: str = "witness"  # witness, told_by, etc.
    believed_true: bool = True

class RelatedTo(BaseEdge):
    label: str = "RELATED_TO"
    relation_type: str
    is_secret: bool = False

class Possesses(BaseEdge):
    label: str = "POSSESSES"
    possession_type: str = "holds"  # owns, holds, guards

class Feels(BaseEdge):
    label: str = "FEELS"
    emotion: str
    target_id: str