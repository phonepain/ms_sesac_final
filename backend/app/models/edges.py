from typing import Optional
from datetime import datetime
from pydantic import Field

from app.models.enums import (
    EdgeBase, LearnMethod, MentionType, StatusType,
    RelationshipType, EmotionType, PossessionType
)

# ---------------------------------------------------------
# Relations (13종 Edge)
# ---------------------------------------------------------

class Learns(EdgeBase):
    """캐릭터가 사실을 알게 됨 (Character -> KnowledgeFact)"""
    discourse_order: float
    story_order: Optional[float] = None
    method: LearnMethod
    believed_true: bool = True
    via_character_id: Optional[str] = None
    event_id: Optional[str] = None
    dialogue_text: Optional[str] = None


class Mentions(EdgeBase):
    """캐릭터가 사실을 언급함 (Character -> KnowledgeFact)"""
    discourse_order: float
    story_order: Optional[float] = None
    mention_type: MentionType
    dialogue_text: Optional[str] = None
    event_id: Optional[str] = None


class ParticipatesIn(EdgeBase):
    """캐릭터가 이벤트에 참여함 (Character -> Event)"""
    role: str


class HasStatus(EdgeBase):
    """캐릭터 상태 (Character -> Event)"""
    status_type: StatusType
    status_value: str
    location: Optional[str] = None


class AtLocation(EdgeBase):
    """캐릭터가 장소에 위치함 (Character -> Location)"""
    discourse_order: float
    story_order: Optional[float] = None
    arrived_via: Optional[str] = None


class RelatedTo(EdgeBase):
    """캐릭터 간 관계 (Character -> Character)"""
    relationship_type: RelationshipType
    detail: Optional[str] = None
    established_order: float
    valid_from: float
    valid_until: Optional[float] = None

    def is_active_at(self, order: float) -> bool:
        if self.valid_until is None:
            return order >= self.valid_from
        return self.valid_from <= order <= self.valid_until


class BelongsTo(EdgeBase):
    """조직에 소속됨 (Character -> Organization)"""
    role: str
    is_secret: bool = False
    valid_from: float
    valid_until: Optional[float] = None


class Feels(EdgeBase):
    """감정 (Character -> Character)"""
    emotion: EmotionType
    intensity: float = Field(ge=0.0, le=1.0)
    discourse_order: float
    story_order: Optional[float] = None
    trigger_event_id: Optional[str] = None


class HasTrait(EdgeBase):
    """특성 보유 (Character -> Trait)"""
    established_order: float
    valid_from: float
    valid_until: Optional[float] = None


class ViolatesTrait(EdgeBase):
    """설정 위반 [모순 탐지에 사용] (Event -> Trait)"""
    character_id: str
    violation_description: str
    dialogue_text: str
    requires_confirmation: bool = False
    confirmation_id: Optional[str] = None


class Possesses(EdgeBase):
    """소유물 획득 (Character -> Item)"""
    discourse_order: float
    story_order: Optional[float] = None
    method: str  # enum 확장 가능
    possession_type: PossessionType
    from_character_id: Optional[str] = None


class Loses(EdgeBase):
    """소유물 분실 (Character -> Item)"""
    discourse_order: float
    story_order: Optional[float] = None
    method: str  # enum 확장 가능
    to_character_id: Optional[str] = None


class SourcedFrom(EdgeBase):
    """출처 노드 연결 (Any -> Source)"""
    location: Optional[str] = None
    chunk_id: Optional[str] = None

# 관계 모순 판별용 행렬 가이드라인 (Conflict Matrix)
RELATIONSHIP_CONFLICT_MATRIX = {
    frozenset([RelationshipType.FAMILY_PARENT, RelationshipType.FAMILY_SIBLING]): "critical",
    frozenset([RelationshipType.FAMILY_PARENT, RelationshipType.FAMILY_SPOUSE]): "critical",
    frozenset([RelationshipType.FAMILY_SIBLING, RelationshipType.FAMILY_SPOUSE]): "warning",
    frozenset([RelationshipType.FAMILY_PARENT, RelationshipType.ROMANTIC]): "warning",
}
