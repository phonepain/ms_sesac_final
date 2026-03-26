from enum import Enum
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------
# Enums
# ---------------------------------------------------------

class CharacterTier(int, Enum):
    TIER_1 = 1  # 주인공급 (모든 발화 추적)
    TIER_2 = 2  # 주요 조연 (핵심 사실 관련 추적)
    TIER_3 = 3  # 반복 조연 (설정 모순만)
    TIER_4 = 4  # 엑스트라 (추적 X)

class FactCategory(str, Enum):
    PLOT_SECRET = "plot_secret"
    CHARACTER_INFO = "character_info"
    WORLD_FACT = "world_fact"
    NARRATION_FACT = "narration_fact"
    RELATIONSHIP_FACT = "relationship_fact"
    EVENT_FACT = "event_fact"

class FactImportance(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"

class EventType(str, Enum):
    SCENE = "scene"
    DEATH = "death"
    RESURRECTION = "resurrection"
    LOCATION_CHANGE = "location_change"
    STATUS_CHANGE = "status_change"
    RELATIONSHIP_CHANGE = "relationship_change"
    TRAIT_CHANGE = "trait_change"
    ITEM_TRANSFER = "item_transfer"
    EMOTION_SHIFT = "emotion_shift"

class StatusType(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    INJURED = "injured"
    CAPTURED = "captured"
    MISSING = "missing"
    PRESENT = "present"
    ABSENT = "absent"

class TraitCategory(str, Enum):
    PERSONALITY = "personality"
    PHYSICAL = "physical"
    ABILITY = "ability"
    PREFERENCE = "preference"
    BACKGROUND = "background"
    RULE = "rule"
    GOAL = "goal"
    MOTIVATION = "motivation"

class OrgType(str, Enum):
    GOVERNMENT = "government"
    MILITARY = "military"
    CRIMINAL = "criminal"
    CORPORATE = "corporate"
    RELIGIOUS = "religious"
    SECRET = "secret"
    OTHER = "other"

class LearnMethod(str, Enum):
    WITNESS = "witness"
    TOLD_BY = "told_by"
    DISCOVERED = "discovered"
    OVERHEARD = "overheard"
    INFERRED = "inferred"
    PUBLIC = "public"
    INHERENT = "inherent"

class MentionType(str, Enum):
    DIRECT_SPEECH = "direct_speech"
    ACTION = "action"
    INNER_THOUGHT = "inner_thought"
    INDIRECT = "indirect"

class RelationshipType(str, Enum):
    FAMILY_PARENT = "family_parent"
    FAMILY_SIBLING = "family_sibling"
    FAMILY_SPOUSE = "family_spouse"
    FAMILY_OTHER = "family_other"
    ROMANTIC = "romantic"
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    RIVAL = "rival"
    ENEMY = "enemy"
    MASTER_SERVANT = "master_servant"
    MENTOR_STUDENT = "mentor_student"
    ORGANIZATION = "organization"

class EmotionType(str, Enum):
    LOVE = "love"
    HATE = "hate"
    TRUST = "trust"
    DISTRUST = "distrust"
    FEAR = "fear"
    JEALOUSY = "jealousy"
    GRATITUDE = "gratitude"
    RESENTMENT = "resentment"
    ADMIRATION = "admiration"
    CONTEMPT = "contempt"
    NEUTRAL = "neutral"

class PossessionType(str, Enum):
    OWNS = "owns"
    HOLDS = "holds"
    CAN_ACCESS = "can_access"
    GUARDS = "guards"

class SourceType(str, Enum):
    WORLDVIEW = "worldview"
    SETTINGS = "settings"
    SCENARIO = "scenario"
    MANUSCRIPT = "manuscript"

class ConfirmationType(str, Enum):
    FLASHBACK_CHECK = "flashback_check"
    INTENTIONAL_CHANGE = "intentional_change"
    FORESHADOWING = "foreshadowing"
    SOURCE_CONFLICT = "source_conflict"
    UNRELIABLE_NARRATOR = "unreliable_narrator"
    TIMELINE_AMBIGUITY = "timeline_ambiguity"
    RELATIONSHIP_AMBIGUITY = "relationship_ambiguity"
    EMOTION_SHIFT = "emotion_shift"
    ITEM_DISCREPANCY = "item_discrepancy"

class ConfirmationStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED_CONTRADICTION = "confirmed_contradiction"
    CONFIRMED_INTENTIONAL = "confirmed_intentional"
    DEFERRED = "deferred"

class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"

class ContradictionType(str, Enum):
    ASYMMETRY = "information_asymmetry"
    TIMELINE = "timeline"
    RELATIONSHIP = "relationship"
    TRAIT = "trait"
    EMOTION = "emotion"
    ITEM = "item"
    DECEPTION = "deception"


# ---------------------------------------------------------
# Base Models
# ---------------------------------------------------------

class SourceLocation(BaseModel):
    """자료 출처 (source_location) 구조"""
    source_id: str
    source_name: str
    page: Optional[int] = None
    chapter: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None

    def display(self) -> str:
        locs = []
        if self.chapter:
            locs.append(f"Ch.{self.chapter}")
        if self.page:
            locs.append(f"p.{self.page}")
        if self.line_range:
            locs.append(f"L{self.line_range[0]}-{self.line_range[1]}")
        
        detail = f" ({', '.join(locs)})" if locs else ""
        return f"{self.source_name}{detail}"


class VertexBase(BaseModel):
    """Vertex 기본 공통 필드"""
    model_config = ConfigDict(populate_by_name=True)

    id: UUID = Field(default_factory=uuid4)
    source_id: str
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def partition_key(self) -> str:
        raise NotImplementedError


class EdgeBase(BaseModel):
    """Edge 기본 공통 필드"""
    model_config = ConfigDict(populate_by_name=True)

    id: UUID = Field(default_factory=uuid4)
    source_id: str
    source_location: str
    created_at: datetime = Field(default_factory=datetime.now)
