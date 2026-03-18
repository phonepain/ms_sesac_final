from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from app.models.enums import (
    CharacterTier, FactCategory, FactImportance, EventType,
    TraitCategory, RelationshipType, EmotionType, ConfirmationType
)
from app.models.vertices import Character, KnowledgeFact, Event, Trait, Organization, Location, Item
from app.models.edges import EdgeBase

# ==========================================
# Raw Entities (계층 1 출력)
# ==========================================

class RawCharacter(BaseModel):
    name: str
    possible_aliases: List[str] = Field(default_factory=list)
    role_hint: Optional[str] = None
    source_chunk_id: str

class RawFact(BaseModel):
    content: str
    category_hint: Optional[FactCategory] = None
    is_secret_hint: bool = False
    source_chunk_id: str

class RawEvent(BaseModel):
    description: str
    characters_involved: List[str] = Field(default_factory=list)
    location_hint: Optional[str] = None
    source_chunk_id: str

class RawTrait(BaseModel):
    character_name: str
    key: str
    value: str
    category_hint: Optional[TraitCategory] = None
    source_chunk_id: str

class RawRelationship(BaseModel):
    char_a: str
    char_b: str
    type_hint: Optional[RelationshipType] = None
    detail: Optional[str] = None
    source_chunk_id: str

class RawEmotion(BaseModel):
    from_char: str
    to_char: str
    emotion: EmotionType
    trigger_hint: Optional[str] = None
    source_chunk_id: str

class RawItemEvent(BaseModel):
    character_name: str
    item_name: str
    action: str  # possesses/loses/uses
    source_chunk_id: str

class RawKnowledgeEvent(BaseModel):
    character_name: str
    fact_content: str
    event_type: str  # learns/mentions
    method: Optional[str] = None
    via_character: Optional[str] = None
    dialogue_text: Optional[str] = None
    source_chunk_id: str

class ExtractionResult(BaseModel):
    """문서 청크 단위 추출 결과 모음"""
    characters: List[RawCharacter] = Field(default_factory=list)
    facts: List[RawFact] = Field(default_factory=list)
    events: List[RawEvent] = Field(default_factory=list)
    traits: List[RawTrait] = Field(default_factory=list)
    relationships: List[RawRelationship] = Field(default_factory=list)
    emotions: List[RawEmotion] = Field(default_factory=list)
    item_events: List[RawItemEvent] = Field(default_factory=list)
    knowledge_events: List[RawKnowledgeEvent] = Field(default_factory=list)
    source_chunk_id: str


# ==========================================
# Normalized Entities (계층 2 출력)
# ==========================================

class NormalizedCharacter(BaseModel):
    canonical_name: str
    all_aliases: List[str] = Field(default_factory=list)
    tier: CharacterTier = CharacterTier.TIER_2
    description: Optional[str] = None
    merged_from: List[RawCharacter] = Field(default_factory=list)

class NormalizedFact(BaseModel):
    content: str
    category: FactCategory
    importance: FactImportance = FactImportance.MAJOR
    is_secret: bool = False
    is_true: bool = True
    merged_from: List[RawFact] = Field(default_factory=list)

class SourceConflict(BaseModel):
    """다중 소스 간 충돌 감지 결과"""
    entity_type: str
    descriptions: Dict[str, str]  # source_id -> value
    conflicting_values: List[str]

class NormalizationResult(BaseModel):
    """정규화/병합이 완료된 결과물. 그래프 적재 직전 단계."""
    characters: List[NormalizedCharacter] = Field(default_factory=list)
    facts: List[NormalizedFact] = Field(default_factory=list)
    events: List[Event] = Field(default_factory=list)
    traits: List[Trait] = Field(default_factory=list)
    organizations: List[Organization] = Field(default_factory=list)
    locations: List[Location] = Field(default_factory=list)
    items: List[Item] = Field(default_factory=list)
    
    # 엣지에 해당하는 관계형 데이터
    relationships: List[RawRelationship] = Field(default_factory=list)
    emotions: List[RawEmotion] = Field(default_factory=list)
    knowledge_events: List[RawKnowledgeEvent] = Field(default_factory=list)
    item_events: List[RawItemEvent] = Field(default_factory=list)
    
    source_conflicts: List[SourceConflict] = Field(default_factory=list)