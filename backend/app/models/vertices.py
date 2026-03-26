from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    VertexBase, CharacterTier, FactCategory, FactImportance, EventType,
    TraitCategory, OrgType, SourceType, ConfirmationType, ConfirmationStatus
)

# ---------------------------------------------------------
# Vertices (9종)
# ---------------------------------------------------------

class Character(VertexBase):
    """서사에 등장하는 캐릭터"""
    name: str
    aliases: List[str] = Field(default_factory=list)
    tier: CharacterTier
    description: Optional[str] = None

    @property
    def partition_key(self) -> str:
        return "character"


class KnowledgeFact(VertexBase):
    """서사 세계 내에서 참인 정보 단위"""
    content: str
    category: FactCategory
    importance: FactImportance
    is_secret: bool = False
    is_true: bool = True
    established_order: float
    source_location: str

    @property
    def partition_key(self) -> str:
        return "fact"


class EventEnvironment(VertexBase):
    """이벤트(장면) 환경 조건 - 별도의 Vertex로 분리되거나 Dictionary로 저장 (여기서는 딕셔너리로 Event 모델 내재)"""
    pass


class Event(VertexBase):
    """사건/장면"""
    discourse_order: float
    story_order: Optional[float] = None
    is_linear: bool = True
    event_type: EventType
    description: str
    location: Optional[str] = None
    environment: Optional[dict] = None  # {time_of_day, weather, lighting, special_conditions}
    source_location: str

    @property
    def partition_key(self) -> str:
        return "event"


class Trait(VertexBase):
    """캐릭터에 귀속된 특성/설정"""
    category: TraitCategory
    key: str
    value: str
    description: Optional[str] = None
    is_immutable: bool = False
    source_location: str

    @property
    def partition_key(self) -> str:
        return "trait"


class Organization(VertexBase):
    """조직/세력/단체"""
    name: str
    org_type: OrgType
    description: Optional[str] = None

    @property
    def partition_key(self) -> str:
        return "organization"


class Location(VertexBase):
    """서사 세계 내 물리적 장소"""
    name: str
    location_type: str  # Enum 확장이 가능하나 가이드에 따라 string 선언 (region/city/building/room/outdoor/abstract)
    parent_location_id: Optional[str] = None
    description: Optional[str] = None
    travel_constraints: Optional[str] = None

    @property
    def partition_key(self) -> str:
        return "location"


class Item(VertexBase):
    """유일/추적 아이템"""
    name: str
    is_unique: bool
    description: Optional[str] = None
    location_id: Optional[str] = None

    @property
    def partition_key(self) -> str:
        return "item"


class Source(VertexBase):
    """자료/소스 문서 (세계관, 설정집 등)"""
    source_type: SourceType
    name: str
    metadata: str = "{}"  # JSON string
    ingested_at: datetime = Field(default_factory=datetime.now)
    status: Optional[str] = "active"
    file_path: str = ""  # StorageService가 반환한 저장 경로 (Push 시 최신 스냅샷으로 갱신)
    original_file_path: str = ""  # 최초 업로드 경로 (불변 — diff 기준점)

    @property
    def partition_key(self) -> str:
        return "source"


class SourceExcerpt(BaseModel):
    """UserConfirmation 내부 사용을 위한 발췌 구조"""
    source_name: str
    source_location: str
    text: str
    highlight_range: Optional[tuple[int, int]] = None


class UserConfirmation(VertexBase):
    """사용자가 직접 판별해야 하는 모호한 모순, 의도적 변경 로그"""
    confirmation_type: ConfirmationType
    status: ConfirmationStatus
    question: str
    context_summary: str
    source_excerpts: List[SourceExcerpt] = Field(default_factory=list)
    related_entity_ids: List[str] = Field(default_factory=list)
    user_response: Optional[str] = None
    resolved_at: Optional[datetime] = None
    # 원문 관련 필드 (Soft confirmation에서 수정 UI 지원)
    original_text: Optional[str] = None
    dialogue: Optional[str] = None
    suggestion: Optional[str] = None
    character_id: Optional[str] = None
    character_name: Optional[str] = None
    chunk_id: Optional[str] = None
    violation_type: Optional[str] = None

    @property
    def partition_key(self) -> str:
        return "confirmation"
