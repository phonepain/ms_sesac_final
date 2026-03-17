from enum import Enum
from typing import Optional
import uuid

class EntityType(str, Enum):
    CHARACTER = "character"
    KNOWLEDGE_FACT = "fact"
    EVENT = "event"
    LOCATION = "location"
    ITEM = "item"
    ORGANIZATION = "organization"
    SOURCE = "source"

class ContradictionType(str, Enum):
    INFO_ASYMMETRY = "information_asymmetry"  # 정보 비대칭
    TIMELINE = "timeline"                    # 타임라인
    RELATIONSHIP = "relationship"            # 관계
    TRAIT_INCONSISTENCY = "trait"            # 성격/설정
    EMOTION_INCONSISTENCY = "emotion"        # 감정
    POSSESSION_TRACKING = "possession"       # 소유물
    DECEPTION_LIE = "deception"              # 거짓말/기만

class Severity(str, Enum):
    HARD = "hard"  # 논리적 불가능 (자동 판정 대상)
    SOFT = "soft"  # 맥락적 부자연스러움 (사용자 확인 필수)

class SourceType(str, Enum):
    WORLDVIEW = "worldview"
    SETTINGS = "settings"
    SCENARIO = "scenario"
    MANUSCRIPT = "manuscript"

def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"