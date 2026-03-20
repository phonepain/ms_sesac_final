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

class NormalizedEvent(BaseModel):
    description: str
    event_type: str = "scene"
    location: Optional[str] = None
    characters_involved: List[str] = Field(default_factory=list)
    merged_from: List[RawEvent] = Field(default_factory=list)

class ConflictDescription(BaseModel):
    """딕셔너리(Dict) 대신 사용할 명시적 키-값 구조체"""
    source_id: str
    text: str

class SourceConflict(BaseModel):
    """다중 소스 간 충돌(세계관 vs 시나리오) 감지용"""
    entity_type: str
    descriptions: List[ConflictDescription] = Field(default_factory=list) # 👈 Dict 대신 List로 변경
    conflicting_values: List[str] = Field(default_factory=list)

class NormalizationResult(BaseModel):
    """정규화 파이프라인의 최종 결과물 (계층 3 Graph Materialization의 입력값)"""
    characters: List[NormalizedCharacter] = Field(default_factory=list)
    facts: List[NormalizedFact] = Field(default_factory=list)
    events: List[NormalizedEvent] = Field(default_factory=list)
    # (필요에 따라 events, traits, relationships 등을 추가/확장합니다)
    source_conflicts: List[SourceConflict] = Field(default_factory=list)

#phase4  모순을 판단한 결과를 담을 그릇
class ContradictionVerification(BaseModel):
    """LLM이 모순 후보를 정밀 검증한 결과"""
    is_contradiction: bool = Field(description="실제 모순인지 여부")
    confidence: float = Field(ge=0.0, le=1.0, description="판단 확신도 (0.8 이상이면 확실한 모순)")
    severity: Literal["critical", "major", "minor"] = Field(description="심각도")
    reasoning: str = Field(description="왜 모순인지(혹은 아닌지)에 대한 논리적 근거")
    suggestion: Optional[str] = Field(None, description="수정 제안")
    alternative_interpretation: Optional[str] = Field(None, description="의도적 장치로 볼 수 있는 대안 해석")
    user_question: Optional[str] = Field(None, description="모호할 때 사용자에게 물어볼 질문")
