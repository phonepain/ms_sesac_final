from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
# ==========================================
#[계층 1: Extraction 결과물]
# LLM에게 "반드시 이 JSON 형태로 대답해!"라고 강제할 스키마들입니다.
# ==========================================

class RawCharacter(BaseModel):
    name: str
    possible_aliases: List[str] = Field(default_factory=list)
    role_hint: Optional[str] = None
    source_chunk_id: Optional[str] = None

class RawFact(BaseModel):
    content: str
    category_hint: Optional[str] = None
    is_secret_hint: bool = False
    source_chunk_id: Optional[str] = None

class RawEvent(BaseModel):
    description: str
    characters_involved: List[str] = Field(default_factory=list)
    location_hint: Optional[str] = None
    source_chunk_id: Optional[str] = None

class RawTrait(BaseModel):
    character_name: str
    key: str
    value: str
    category_hint: Optional[str] = None
    source_chunk_id: Optional[str] = None

class RawRelationship(BaseModel):
    char_a: str
    char_b: str
    type_hint: Optional[str] = None
    detail: Optional[str] = None
    source_chunk_id: Optional[str] = None

class RawEmotion(BaseModel):
    from_char: str
    to_char: str
    emotion: str
    trigger_hint: Optional[str] = None
    source_chunk_id: Optional[str] = None

class RawItemEvent(BaseModel):
    character_name: str
    item_name: str
    action: Literal["possesses", "loses", "uses"] = Field(description="반드시 이 3개 중 하나여야 함")
    source_chunk_id: Optional[str] = None

class RawKnowledgeEvent(BaseModel):
    """(중요) 정보 비대칭 및 거짓말 탐지를 위한 핵심 추출 모델"""
    character_name: str
    fact_content: str
    event_type: Literal["learns", "mentions"] = Field(description="새로 알게됨(learns), 이미 아는걸 말함(mentions)")
    method: Optional[str] = None
    via_character: Optional[str] = None
    dialogue_text: Optional[str] = None
    source_chunk_id: Optional[str] = None

class ExtractionResult(BaseModel):
    """
    LLM 프롬프트 호출 시 Structured Output의 최종 반환 타입으로 사용됩니다.
    하나의 텍스트 청크에서 뽑아낸 모든 정보가 여기에 담깁니다.
    """
    characters: List[RawCharacter] = Field(default_factory=list)
    facts: List[RawFact] = Field(default_factory=list)
    events: List[RawEvent] = Field(default_factory=list)
    traits: List[RawTrait] = Field(default_factory=list)
    relationships: List[RawRelationship] = Field(default_factory=list)
    emotions: List[RawEmotion] = Field(default_factory=list)
    item_events: List[RawItemEvent] = Field(default_factory=list)
    knowledge_events: List[RawKnowledgeEvent] = Field(default_factory=list)
    source_chunk_id: Optional[str] = None


# ==========================================
#[계층 2: Normalization 결과물]
# LLM이 뽑은 Raw 데이터를 기존 DB와 대조/병합/정규화한 결과입니다.
# (이후 그래프 DB 적재용으로 넘어갑니다.)
# ==========================================

class NormalizedCharacter(BaseModel):
    canonical_name: str
    all_aliases: List[str] = Field(default_factory=list)
    tier: int = 4
    description: Optional[str] = None
    merged_from: List[RawCharacter] = Field(default_factory=list)

class NormalizedFact(BaseModel):
    content: str
    category: str
    importance: str = "minor"
    is_secret: bool = False
    is_true: bool = True
    merged_from: List[RawFact] = Field(default_factory=list)

class SourceConflict(BaseModel):
    """다중 소스 간 충돌(세계관 vs 시나리오) 감지용"""
    entity_type: str
    descriptions: Dict[str, str] = Field(default_factory=dict) # source_id -> text
    conflicting_values: List[str] = Field(default_factory=list)

class NormalizationResult(BaseModel):
    """정규화 파이프라인의 최종 결과물 (계층 3 Graph Materialization의 입력값)"""
    characters: List[NormalizedCharacter] = Field(default_factory=list)
    facts: List[NormalizedFact] = Field(default_factory=list)
    # (필요에 따라 events, traits, relationships 등을 추가/확장합니다)
    source_conflicts: List[SourceConflict] = Field(default_factory=list)