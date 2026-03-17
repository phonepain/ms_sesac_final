from pydantic import BaseModel
from typing import List, Optional, Any
from app.models.vertices import BaseVertex
from app.models.edges import BaseEdge

class RawEntity(BaseModel):
    """
    [계층 1: Extraction 결과물]
    LLM이 원고에서 방금 막 추출한 가공되지 않은 상태의 엔티티입니다.
    """
    entity_type: str        # 예: "character", "event"
    name: str               # 추출된 이름
    properties: dict[str, Any] # 추출된 세부 속성들
    source_sentence: str    # 근거가 되는 원문 문장 (추후 검증용)

class NormalizedEntity(BaseModel):
    """
    [계층 2: Normalization 결과물]
    RawEntity를 기존 DB와 대조하여 ID를 부여하거나, 
    이중 시간 축(discourse/story) 계산이 완료된 상태입니다.
    """
    vertex: Optional[BaseVertex] = None
    edge: Optional[BaseEdge] = None
    is_new: bool = True     # 기존에 있던 엔티티인지 신규인지 여부
    confidence: float       # 추출/정규화 확신도 (0.0~1.0)
    needs_user_confirmation: bool = False # 모호해서 사용자 확인이 필요한지