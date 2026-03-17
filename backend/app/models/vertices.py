from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from backend.app.models.enums import EntityType, new_id

class BaseVertex(BaseModel):
    id: str
    label: EntityType
    properties: Dict[str, Any] = Field(default_factory=dict)

class Character(BaseVertex):
    name: str
    aliases: List[str] = []
    description: Optional[str] = None

class KnowledgeFact(BaseVertex):
    content: str
    is_true: bool = True  # v2.1 거짓말 추적용
    category: Optional[str] = None

class Event(BaseVertex):
    description: str
    discourse_order: float  # 서사 순서 (작품 내 등장 순서)
    story_order: float     # 실제 시간 순서 (연대기)
    environment: Optional[str] = None  # 장면 환경 제약
    location_id: Optional[str] = None

class Item(BaseVertex):
    name: str
    description: Optional[str] = None
    current_location_id: Optional[str] = None