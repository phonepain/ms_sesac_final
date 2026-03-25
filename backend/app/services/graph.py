from typing import List, Dict, Any, Optional, Tuple
import uuid
import copy
import os
import json
import re
import logging
import threading
import structlog
from collections import defaultdict
from datetime import datetime, timezone

from gremlin_python.driver import client, serializer
from gremlin_python.driver.aiohttp.transport import AiohttpTransport

from app.config import settings
from app.models.intermediate import NormalizationResult
from app.services.storage import StorageService
from app.models.edges import RELATIONSHIP_CONFLICT_MATRIX
from app.models.enums import (
    ConfirmationType, ConfirmationStatus, ContradictionType,
    Severity, RelationshipType,
    CharacterTier, FactCategory, FactImportance, EventType
)
from app.models.vertices import (
    Character, KnowledgeFact, Event, UserConfirmation, Source, SourceExcerpt
)
from app.models.api import KBStats


# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 한글 관계명 → RelationshipType enum 매핑
_KO_RELATIONSHIP_MAP: Dict[str, str] = {
    "어머니": "family_parent", "아버지": "family_parent", "부모": "family_parent",
    "아들": "family_parent", "딸": "family_parent", "자녀": "family_parent",
    "형": "family_sibling", "누나": "family_sibling", "오빠": "family_sibling",
    "언니": "family_sibling", "남매": "family_sibling", "형제": "family_sibling",
    "자매": "family_sibling", "쌍둥이": "family_sibling",
    "남편": "family_spouse", "아내": "family_spouse", "배우자": "family_spouse",
    "연인": "romantic", "애인": "romantic",
    "친구": "friend", "절친": "friend",
    "동료": "colleague", "동기": "colleague", "파트너": "colleague",
    "라이벌": "rival", "경쟁자": "rival",
    "적": "enemy", "원수": "enemy", "숙적": "enemy",
    "스승": "mentor_student", "제자": "mentor_student", "사제": "mentor_student",
    "주인": "master_servant", "하인": "master_servant", "종복": "master_servant",
}


def _normalize_relationship_type(raw: str) -> str:
    """한글/영문 관계명을 RelationshipType enum 값으로 정규화."""
    if not raw:
        return "colleague"
    low = raw.strip().lower()
    # 이미 enum 값이면 그대로
    try:
        RelationshipType(low)
        return low
    except ValueError:
        pass
    # 한글 매핑
    for ko, enum_val in _KO_RELATIONSHIP_MAP.items():
        if ko in raw:
            return enum_val
    return raw
DEFAULT_JSON_PATH = os.path.join(BASE_DIR, "data", "graph_input.json")


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger().bind(service="graph_service")


# ─────────────────────────────────────────────────────────────
# 유틸: Gremlin valueMap 결과에서 단일 값 추출 (list 래핑 처리)
# ─────────────────────────────────────────────────────────────

def _prop(v: Dict, key: str) -> Any:
    val = v.get(key)
    if isinstance(val, list):
        return val[0] if val else None
    return val


# ─────────────────────────────────────────────────────────────
# Fact 유사도 매칭 (정보 비대칭 탐지용)
# ─────────────────────────────────────────────────────────────

def _fact_bigrams(text: str) -> set:
    """텍스트를 정규화 후 bi-gram 집합으로 변환. 한국어/영어 공용.

    어미 변화("범인이야" vs "범인이다")에 강건하도록:
    1. 구두점 제거
    2. 공통 한국어 어미/조사 제거 → 어간만 남김
    3. 공백 정규화 후 문자 2-gram
    """
    import re as _re
    t = text.strip()
    t = _re.sub(r'[.!?,。、·…]', ' ', t)
    # 어미 정규화: "이야/이다/이에/이었/이고/이며" → 제거 (어간 보존)
    t = _re.sub(r'(?<=[가-힣])(이야|이다|이에요|이었|이고|이며|이랑|야|다|해요|했다|해|ㅎ)', ' ', t)
    t = _re.sub(r'\s+', ' ', t).strip()
    return {t[i:i+2] for i in range(len(t) - 1)} if len(t) >= 2 else {t}


def _fact_similarity(a: str, b: str) -> float:
    """bi-gram Jaccard 유사도. 0.0~1.0."""
    bg_a = _fact_bigrams(a)
    bg_b = _fact_bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    union = bg_a | bg_b
    return len(bg_a & bg_b) / len(union)


def _find_similar_fact(
    content: str,
    fact_content_to_id: Dict[str, str],
    threshold: float = 0.5,
) -> Optional[str]:
    """fact_content_to_id에서 content와 유사도 >= threshold인 기존 fact_id 반환.

    "B가 범인이야"와 "B가 범인이다"처럼 어미만 다른 동일 사실을 같은 fact로 연결.
    매칭 실패 시 None 반환 → 호출자가 새 fact vertex를 생성.
    """
    best_score, best_id = 0.0, None
    for existing_content, fid in fact_content_to_id.items():
        score = _fact_similarity(content, existing_content)
        if score > best_score:
            best_score, best_id = score, fid
    return best_id if best_score >= threshold else None


# ─────────────────────────────────────────────────────────────
# 공통 위반 레코드 빌더
# ─────────────────────────────────────────────────────────────

def _make_violation(
    vtype: ContradictionType,
    severity: Severity,
    description: str,
    confidence: float,
    character_id: Optional[str] = None,
    character_name: Optional[str] = None,
    evidence: Optional[List[Dict]] = None,
    needs_user_input: bool = False,
    confirmation_type: Optional[ConfirmationType] = None,
    dialogue: Optional[str] = None,
    suggestion: Optional[str] = None,
    original_text: Optional[str] = None,
    chunk_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": vtype,
        "severity": severity,
        "description": description,
        "confidence": confidence,
        "character_id": character_id,
        "character_name": character_name,
        "evidence": evidence or [],
        "needs_user_input": needs_user_input,
        "confirmation_type": confirmation_type,
        "dialogue": dialogue,
        "suggestion": suggestion,
        "original_text": original_text,
        "chunk_id": chunk_id,
        # Hard = confidence≥0.8 이고 사용자 확인 불필요
        "is_hard": confidence >= 0.8 and not needs_user_input,
    }


# ─────────────────────────────────────────────────────────────
# 모순 탐지 Mixin — GremlinGraphService / InMemoryGraphService 공용
# _vertices_by_label / _edges_by_label / get_character /
# find_character_by_name / get_trait / get_item 을 구현한 클래스에 믹스인
# ─────────────────────────────────────────────────────────────

class _ViolationMixin:
    """9가지 모순 탐지 쿼리.

    하위 클래스는 반드시 아래 메서드를 구현해야 합니다:
      _vertices_by_label(label) -> List[Dict]
      _edges_by_label(label)   -> List[Dict]
      get_character(id)        -> Optional[Dict]
      find_character_by_name(name) -> Optional[Dict]
      get_trait(id)            -> Optional[Dict]
      get_item(id)             -> Optional[Dict]
    """

    # ── 특성-이벤트 탐지 상수 ─────────────────────────────────
    _PROHIBITIVE_MARKERS = [
        "혐오", "절대", "하지 않", "않는다", "못하", "안 마", "마시지 않",
        "먹지 않", "싫어", "거부", "금지", "불가", "불능", "봉인",
        "할 수 없", "사용할 수 없", "수 없는", "참여하지 않",
        "일절", "극혐", "입에 대지", "안 하", "안 함", "대지 않",
    ]
    _PARTICLE_SUFFIXES = (
        "에서", "에게", "로서", "하며", "이며", "이고", "까지", "부터",
        "를", "을", "가", "이", "은", "는", "에", "로", "의", "도", "만", "와", "과", "며", "고",
    )
    _CONTENT_STOP = {
        "하지", "않는", "못하", "않고", "않다", "않는다", "절대", "혐오",
        "마시지", "먹지", "싫어", "거부", "한다", "하며", "이며",
        "최소", "이후", "이상", "이하", "미만", "이내", "초과", "부터", "까지",
        "차로", "걸어", "소요", "걸림",
    }

    def find_knowledge_violations(self) -> List[Dict[str, Any]]:
        """1. 정보 비대칭 탐지.

        (a) 동일 캐릭터: MENTIONS.story_order < LEARNS.story_order
            — 자기가 알기 전에 이미 말하는 경우

        (b) Cross-character: B가 A에게서 배운다(LEARNS, via_character=A)고 기록되었는데
            A의 해당 사실 최초 인지 시점이 B의 LEARNS보다 늦은 경우
            — 아직 모르는 사람에게서 배울 수 없음
        """
        violations = []
        mentions = self._edges_by_label("MENTIONS")
        learns = self._edges_by_label("LEARNS")

        # 이름 → 캐릭터 ID 맵 (cross-character 탐지에 사용)
        name_to_cid: Dict[str, str] = {}
        for cv in self._vertices_by_label("character"):
            name = _prop(cv, "name") or _prop(cv, "canonical_name") or ""
            cid_ = _prop(cv, "id")
            if name and cid_:
                name_to_cid[name] = cid_

        # (char_id, fact_id) → 해당 캐릭터의 LEARNS 최초 시점 (동일 캐릭터 비대칭에 사용)
        learn_index: Dict[Tuple[str, str], float] = {}
        for e in learns:
            cid, fid, so = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "story_order")
            if cid and fid and so is not None:
                key = (cid, fid)
                so_f = float(so)
                if key not in learn_index or so_f < learn_index[key]:
                    learn_index[key] = so_f

        # (char_id, fact_id) → 최초 인지 story_order (LEARNS + MENTIONS 포함, cross-character 탐지에 사용)
        earliest_knowledge: Dict[Tuple[str, str], float] = {}
        for e in learns + mentions:
            cid, fid, so = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "story_order")
            if cid and fid and so is not None:
                key = (cid, fid)
                so_f = float(so)
                if key not in earliest_knowledge or so_f < earliest_knowledge[key]:
                    earliest_knowledge[key] = so_f

        # (a) 동일 캐릭터 비대칭
        for e in mentions:
            cid, fid, m_so = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "story_order")
            if not (cid and fid and m_so is not None):
                continue
            m_so = float(m_so)
            l_so = learn_index.get((cid, fid))
            if l_so is not None and m_so < l_so:
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.ASYMMETRY,
                    severity=Severity.CRITICAL,
                    description=(
                        f"캐릭터 '{char_name}'이(가) 사실을 알기 전(LEARNS story_order={l_so}) "
                        f"이미 언급(MENTIONS story_order={m_so})"
                    ),
                    confidence=0.95,
                    character_id=cid, character_name=char_name,
                    evidence=[
                        {"type": "MENTIONS", "story_order": m_so, "dialogue": _prop(e, "dialogue_text")},
                        {"type": "LEARNS", "story_order": l_so},
                    ],
                    suggestion="MENTIONS 시점을 LEARNS 이후로 수정하거나 LEARNS 시점을 앞당기세요.",
                ))

        # (b) Cross-character 비대칭: B가 A에게서 배웠는데 A가 그 시점에 아직 몰랐던 경우
        seen_cross: set = set()
        for e in learns:
            student_id = _prop(e, "from_id")
            fact_id = _prop(e, "to_id")
            student_so = _prop(e, "story_order")
            via_char_name = _prop(e, "via_character")
            if not (student_id and fact_id and student_so is not None and via_char_name):
                continue
            student_so = float(student_so)
            teacher_id = name_to_cid.get(via_char_name)
            if not teacher_id or teacher_id == student_id:
                continue
            teacher_earliest = earliest_knowledge.get((teacher_id, fact_id))
            if teacher_earliest is None:
                continue  # 교사의 지식 기록 없음 — 검증 불가
            if teacher_earliest <= student_so:
                continue  # 정상: 교사가 먼저 알고 있었음
            vkey = (student_id, teacher_id, fact_id)
            if vkey in seen_cross:
                continue
            seen_cross.add(vkey)
            student_name = (self.get_character(student_id) or {}).get("name", student_id)
            teacher_name = (self.get_character(teacher_id) or {}).get("name", teacher_id)
            violations.append(_make_violation(
                vtype=ContradictionType.ASYMMETRY,
                severity=Severity.CRITICAL,
                description=(
                    f"'{student_name}'이(가) '{teacher_name}'에게서 사실을 배우지만"
                    f"(story_order={student_so}), "
                    f"'{teacher_name}'의 해당 사실 최초 인지는 더 늦음"
                    f"(story_order={teacher_earliest})"
                ),
                confidence=0.85,
                character_id=student_id, character_name=student_name,
                evidence=[{
                    "student": student_name,
                    "teacher": teacher_name,
                    "student_learns_at": student_so,
                    "teacher_knows_at": teacher_earliest,
                    "fact_id": fact_id,
                }],
                suggestion=(
                    f"'{teacher_name}'이(가) 사실을 알기 전에 '{student_name}'에게 "
                    "가르쳐줄 수 없습니다. 정보 전달 시점 또는 출처를 수정하세요."
                ),
            ))
        return violations

    def find_timeline_violations(self) -> List[Dict[str, Any]]:
        """2. 타임라인: 사망 후 재등장, 동시 다중 위치"""
        violations = []
        has_status = self._edges_by_label("HAS_STATUS")
        at_location = self._edges_by_label("AT_LOCATION")

        death_index: Dict[str, float] = {}
        for e in has_status:
            if _prop(e, "status_type") == "dead":
                cid, so = _prop(e, "from_id"), _prop(e, "story_order")
                if cid and so is not None:
                    death_index[cid] = float(so)

        appearance_edges = at_location + self._edges_by_label("MENTIONS") + self._edges_by_label("LEARNS")
        seen_violation: set = set()
        for e in appearance_edges:
            cid, so = _prop(e, "from_id"), _prop(e, "story_order")
            if not (cid and so is not None):
                continue
            so = float(so)
            death_so = death_index.get(cid)
            if death_so is not None and so > death_so:
                key = (cid, death_so)
                if key in seen_violation:
                    continue
                seen_violation.add(key)
                char_name = (self.get_character(cid) or {}).get("name", cid)
                edge_label = _prop(e, "label") or "AT_LOCATION"
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"캐릭터 '{char_name}'이(가) 사망(story_order={death_so}) 후 재등장(story_order={so})",
                    confidence=0.95,
                    character_id=cid, character_name=char_name,
                    evidence=[{"death_at": death_so, "appears_at": so, "edge": edge_label}],
                    suggestion="사망 이벤트 또는 이후 등장 시점을 수정하세요.",
                ))

        # 사망 후 이벤트 참여 체크 (characters_involved 기반)
        name_to_id: Dict[str, str] = {}
        for cv in self._vertices_by_label("character"):
            cname = _prop(cv, "name") or _prop(cv, "canonical_name") or ""
            cid_ = _prop(cv, "id")
            if cname and cid_:
                name_to_id[cname] = cid_
        for ev in self._vertices_by_label("event"):
            so = _prop(ev, "story_order")
            if so is None:
                continue
            so = float(so)
            raw_ci = ev.get("characters_involved") or []
            if isinstance(raw_ci, str):
                try:
                    raw_ci = json.loads(raw_ci)
                except Exception:
                    raw_ci = [raw_ci] if raw_ci else []
            elif not isinstance(raw_ci, list):
                raw_ci = []
            for char_name in raw_ci:
                cid = name_to_id.get(char_name)
                if not cid:
                    continue
                death_so = death_index.get(cid)
                if death_so is not None and so > death_so:
                    key = (cid, death_so)
                    if key in seen_violation:
                        continue
                    seen_violation.add(key)
                    desc = _prop(ev, "description") or ""
                    violations.append(_make_violation(
                        vtype=ContradictionType.TIMELINE,
                        severity=Severity.CRITICAL,
                        description=f"캐릭터 '{char_name}'이(가) 사망(story_order={death_so}) 후 이벤트에 등장(story_order={so}): {desc[:60]}",
                        confidence=0.95,
                        character_id=cid, character_name=char_name,
                        evidence=[{"death_at": death_so, "appears_at": so, "event": desc[:80]}],
                        suggestion="사망 이벤트 또는 이후 등장 시점을 수정하세요.",
                    ))

        time_char_locs: Dict[Tuple[str, float], List[str]] = defaultdict(list)
        for e in at_location:
            cid, so, loc = _prop(e, "from_id"), _prop(e, "story_order"), _prop(e, "to_id")
            if cid and so is not None and loc:
                time_char_locs[(cid, float(so))].append(loc)
        for (cid, so), locs in time_char_locs.items():
            if len(set(locs)) > 1:
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"캐릭터 '{char_name}'이(가) story_order={so}에 동시에 {len(locs)}개 장소 존재",
                    confidence=0.98,
                    character_id=cid, character_name=char_name,
                    evidence=[{"locations": locs, "story_order": so}],
                    suggestion="동시 위치 중 하나의 story_order를 조정하세요.",
                ))

        # "resurrection" event_type → 추출 모델이 사망한 캐릭터의 재등장을 감지한 것 → HARD 모순
        for ev in self._vertices_by_label("event"):
            ev_type = _prop(ev, "event_type")
            ev_type_str = ev_type.value if hasattr(ev_type, "value") else str(ev_type)
            if ev_type_str != "resurrection":
                continue
            raw_involved = ev.get("characters_involved") or []
            if isinstance(raw_involved, str):
                try:
                    raw_involved = json.loads(raw_involved)
                except Exception:
                    raw_involved = [raw_involved] if raw_involved else []
            elif not isinstance(raw_involved, list):
                raw_involved = []
            desc = _prop(ev, "description") or ""
            so = _prop(ev, "story_order") or _prop(ev, "discourse_order") or 0
            for char_name in dict.fromkeys(raw_involved):
                char_vertex = self.find_character_by_name(char_name) or {}
                cid = char_vertex.get("id", char_name)
                # 엣지 기반 탐지와 중복 방지
                death_so_check = death_index.get(cid)
                if death_so_check is not None:
                    dup_key = (cid, death_so_check)
                    if dup_key in seen_violation:
                        continue
                    seen_violation.add(dup_key)
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"캐릭터 '{char_name}'이(가) 사망 후 재등장(story_order={so}): {desc[:80]}",
                    confidence=0.92,
                    character_id=cid, character_name=char_name,
                    evidence=[{"resurrection_event": _prop(ev, "id"), "story_order": so, "description": desc}],
                    suggestion="사망 시점 이후 해당 캐릭터의 등장 장면을 제거하거나 사망 시점을 조정하세요.",
                ))
            if not raw_involved:
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL,
                    description=f"사망 후 재등장 이벤트 감지(story_order={so}): {desc[:80]}",
                    confidence=0.85,
                    character_id=None, character_name=None,
                    evidence=[{"resurrection_event": _prop(ev, "id"), "story_order": so}],
                    suggestion="사망 이벤트 또는 재등장 장면을 확인하세요.",
                ))
        return violations

    def find_relationship_violations(self) -> List[Dict[str, Any]]:
        """3. 관계 모순"""
        violations = []
        related = self._edges_by_label("RELATED_TO")
        pair_index: Dict[frozenset, List[str]] = {}
        for e in related:
            a, b, rtype = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "relationship_type")
            if a and b and rtype:
                pair_index.setdefault(frozenset([a, b]), []).append(rtype)

        for pair, rtypes in pair_index.items():
            pair_list = list(pair)
            for i, rt1 in enumerate(rtypes):
                for rt2 in rtypes[i + 1:]:
                    try:
                        r1, r2 = RelationshipType(rt1), RelationshipType(rt2)
                    except ValueError:
                        continue
                    level = RELATIONSHIP_CONFLICT_MATRIX.get(frozenset([r1, r2]))
                    if level == "critical":
                        violations.append(_make_violation(
                            vtype=ContradictionType.RELATIONSHIP,
                            severity=Severity.CRITICAL,
                            description=f"캐릭터 쌍의 관계 모순: {rt1} ↔ {rt2}",
                            confidence=0.95,
                            evidence=[{"pair": pair_list, "relationship_types": rtypes}],
                            suggestion=f"관계 '{rt1}'과 '{rt2}' 중 하나를 수정하세요.",
                        ))
                    elif level == "warning":
                        violations.append(_make_violation(
                            vtype=ContradictionType.RELATIONSHIP,
                            severity=Severity.MAJOR,
                            description=f"캐릭터 쌍의 관계 경고: {rt1} ↔ {rt2}",
                            confidence=0.6,
                            evidence=[{"pair": pair_list, "relationship_types": rtypes}],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.RELATIONSHIP_AMBIGUITY,
                        ))
        return violations

    # 여러 value를 자연스럽게 가질 수 있는 복합 trait key → 값이 달라도 모순 아님
    _MULTI_VALUE_TRAIT_KEYS = {"성격", "특기", "취미", "능력", "장점", "단점", "기술", "특성"}

    def find_trait_violations(self) -> List[Dict[str, Any]]:
        """4. 성격·설정 모순"""
        violations = []
        has_trait = self._edges_by_label("HAS_TRAIT")
        char_trait_index: Dict[Tuple[str, str], List[Dict]] = {}
        for e in has_trait:
            cid, tid = _prop(e, "from_id"), _prop(e, "to_id")
            trait = self.get_trait(tid) or {}
            key, val = _prop(trait, "key"), _prop(trait, "value")
            immutable = _prop(trait, "is_immutable") in (True, "True", "true", 1)
            if cid and key:
                char_trait_index.setdefault((cid, key), []).append(
                    {"value": val, "is_immutable": immutable}
                )

        for (cid, trait_key), entries in char_trait_index.items():
            # 복합 key는 여러 값이 자연스러우므로 스킵
            if trait_key in self._MULTI_VALUE_TRAIT_KEYS:
                continue
            values = [e["value"] for e in entries]
            if len(set(str(v) for v in values)) > 1:
                is_imm = any(e["is_immutable"] for e in entries)
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.TRAIT,
                    severity=Severity.CRITICAL if is_imm else Severity.MAJOR,
                    description=f"캐릭터 '{char_name}'의 특성 '{trait_key}': {values}",
                    confidence=0.95 if is_imm else 0.6,
                    character_id=cid, character_name=char_name,
                    evidence=[{"trait_key": trait_key, "values": values}],
                    needs_user_input=not is_imm,
                    confirmation_type=ConfirmationType.INTENTIONAL_CHANGE if not is_imm else None,
                    suggestion=f"'{trait_key}' 특성 값을 통일하거나 변화 이유를 명시하세요.",
                ))
        return violations

    def find_emotion_violations(self) -> List[Dict[str, Any]]:
        """5. 감정 일관성"""
        violations = []
        feels = self._edges_by_label("FEELS")
        pair_emotions: Dict[Tuple[str, str], List[Dict]] = {}
        for e in feels:
            fid, tid = _prop(e, "from_id"), _prop(e, "to_id")
            if fid and tid:
                pair_emotions.setdefault((fid, tid), []).append(e)

        OPPOSITES = {
            frozenset(["love", "hate"]),
            frozenset(["trust", "distrust"]),
            frozenset(["admiration", "contempt"]),
            frozenset(["gratitude", "resentment"]),
        }
        for (fid, tid), history in pair_emotions.items():
            sorted_h = sorted(history, key=lambda x: float(_prop(x, "discourse_order") or 0))
            for i in range(1, len(sorted_h)):
                prev, curr = sorted_h[i - 1], sorted_h[i]
                pair = frozenset([str(_prop(prev, "emotion")), str(_prop(curr, "emotion"))])
                if pair in OPPOSITES and not _prop(curr, "trigger_event_id"):
                    char_name = (self.get_character(fid) or {}).get("name", fid)
                    violations.append(_make_violation(
                        vtype=ContradictionType.EMOTION,
                        severity=Severity.MAJOR,
                        description=(
                            f"캐릭터 '{char_name}'의 감정이 트리거 없이 "
                            f"{_prop(prev, 'emotion')} → {_prop(curr, 'emotion')} 급변"
                        ),
                        confidence=0.6,
                        character_id=fid, character_name=char_name,
                        evidence=[{"prev": _prop(prev, "emotion"), "curr": _prop(curr, "emotion")}],
                        needs_user_input=True,
                        confirmation_type=ConfirmationType.EMOTION_SHIFT,
                        suggestion="감정 변화를 유발한 이벤트를 명시하거나 감정 추이를 자연스럽게 조정하세요.",
                    ))
        return violations

    def find_item_violations(self) -> List[Dict[str, Any]]:
        """6. 소유물 추적"""
        violations = []
        possesses = self._edges_by_label("POSSESSES")
        loses = self._edges_by_label("LOSES")

        item_history: Dict[str, List[Dict]] = {}
        for e in possesses:
            iid = _prop(e, "to_id")
            if iid:
                item_history.setdefault(iid, []).append({
                    "type": "possesses", "char_id": _prop(e, "from_id"),
                    "story_order": _prop(e, "story_order"),
                })
        for e in loses:
            iid = _prop(e, "to_id")
            if iid:
                item_history.setdefault(iid, []).append({
                    "type": "loses", "char_id": _prop(e, "from_id"),
                    "story_order": _prop(e, "story_order"),
                })

        for item_id, history in item_history.items():
            item_name = (self.get_item(item_id) or {}).get("name", item_id)
            sorted_h = [h for h in history if h.get("story_order") is not None]
            sorted_h.sort(key=lambda x: float(x["story_order"]))

            time_owners: Dict[float, List[str]] = defaultdict(list)
            for h in sorted_h:
                if h["type"] == "possesses":
                    time_owners[float(h["story_order"])].append(h["char_id"])
            for so, owners in time_owners.items():
                if len(set(owners)) > 1:
                    violations.append(_make_violation(
                        vtype=ContradictionType.ITEM,
                        severity=Severity.CRITICAL,
                        description=f"아이템 '{item_name}'이 story_order={so}에 {len(owners)}명에게 동시 소유",
                        confidence=0.95,
                        evidence=[{"item_id": item_id, "story_order": so, "owners": owners}],
                        suggestion="동시 소유 중 하나의 story_order를 조정하거나 소유권 이전을 추가하세요.",
                    ))

            last_loses: Dict[str, float] = {}
            for h in sorted_h:
                if h["type"] == "loses":
                    last_loses[h["char_id"]] = float(h["story_order"])
                elif h["type"] == "possesses":
                    cid, so = h["char_id"], float(h["story_order"])
                    lost_at = last_loses.get(cid)
                    if lost_at is not None and so > lost_at:
                        char_name = (self.get_character(cid) or {}).get("name", cid)
                        violations.append(_make_violation(
                            vtype=ContradictionType.ITEM,
                            severity=Severity.MAJOR,
                            description=(
                                f"캐릭터 '{char_name}'이(가) '{item_name}' 분실(story_order={lost_at}) "
                                f"후 재소유(story_order={so})"
                            ),
                            confidence=0.65,
                            character_id=cid, character_name=char_name,
                            evidence=[{"lost_at": lost_at, "repossessed_at": so}],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.ITEM_DISCREPANCY,
                        ))

            # 유일 아이템: 이전 소유자가 잃지 않았는데 다른 사람이 소유
            item_vertex = self.get_item(item_id) or {}
            is_unique = item_vertex.get("is_unique") in (True, "True", "true", 1)
            if is_unique:
                possesses_only = [h for h in sorted_h if h["type"] == "possesses"]
                lose_chars = {h["char_id"] for h in sorted_h if h["type"] == "loses"}
                for i in range(1, len(possesses_only)):
                    prev = possesses_only[i - 1]
                    curr = possesses_only[i]
                    if prev["char_id"] != curr["char_id"] and prev["char_id"] not in lose_chars:
                        prev_name = (self.get_character(prev["char_id"]) or {}).get("name", prev["char_id"])
                        curr_name = (self.get_character(curr["char_id"]) or {}).get("name", curr["char_id"])
                        violations.append(_make_violation(
                            vtype=ContradictionType.ITEM,
                            severity=Severity.CRITICAL,
                            description=(
                                f"유일 아이템 '{item_name}': '{prev_name}'이(가) 분실 기록 없이 "
                                f"'{curr_name}'이(가) 소유(story_order={curr['story_order']})"
                            ),
                            confidence=0.85,
                            evidence=[{
                                "item_id": item_id, "prev_owner": prev_name,
                                "curr_owner": curr_name, "is_unique": True,
                            }],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.ITEM_DISCREPANCY,
                            suggestion="소유권 이전 이벤트(양도/분실)를 추가하거나 소유자를 수정하세요.",
                        ))
        return violations

    def find_deception_violations(self) -> List[Dict[str, Any]]:
        """7. 거짓말·기만"""
        violations = []
        facts = {_prop(v, "id"): v for v in self._vertices_by_label("fact")}
        learns = self._edges_by_label("LEARNS")
        mentions = self._edges_by_label("MENTIONS")

        false_fact_ids = {
            fid for fid, fv in facts.items()
            if _prop(fv, "is_true") in (False, "False", "false", 0)
        }

        believed_false: Dict[Tuple[str, str], float] = {}
        for e in learns:
            fid, cid = _prop(e, "to_id"), _prop(e, "from_id")
            believed = _prop(e, "believed_true")
            if believed is None:
                believed = True
            so = _prop(e, "story_order")
            if fid in false_fact_ids and believed in (True, "True", "true", 1):
                if cid and so is not None:
                    believed_false[(cid, fid)] = float(so)

        truth_learn: Dict[Tuple[str, str], float] = {}
        for e in learns:
            fid, cid = _prop(e, "to_id"), _prop(e, "from_id")
            believed = _prop(e, "believed_true")
            if believed is None:
                believed = True
            so = _prop(e, "story_order")
            if fid not in false_fact_ids and believed in (True, "True", "true", 1):
                if cid and so is not None:
                    key = (cid, fid)
                    if key not in truth_learn or float(so) < truth_learn[key]:
                        truth_learn[key] = float(so)

        for e in mentions:
            cid, fid, so = _prop(e, "from_id"), _prop(e, "to_id"), _prop(e, "story_order")
            if not (cid and fid and so is not None and fid in false_fact_ids):
                continue
            so = float(so)
            truth_so = truth_learn.get((cid, fid))
            if truth_so is not None and so > truth_so:
                char_name = (self.get_character(cid) or {}).get("name", cid)
                violations.append(_make_violation(
                    vtype=ContradictionType.DECEPTION,
                    severity=Severity.CRITICAL,
                    description=(
                        f"캐릭터 '{char_name}'이(가) 진실 인지(story_order={truth_so}) 후에도 "
                        f"거짓 사실을 언급(story_order={so})"
                    ),
                    confidence=0.9,
                    character_id=cid, character_name=char_name,
                    dialogue=_prop(e, "dialogue_text"),
                    evidence=[{"truth_learned_at": truth_so, "false_mention_at": so}],
                    suggestion="진실 인지 후 거짓 정보 전달의 의도를 명시하거나 제거하세요.",
                ))

        for (cid, fid), so in believed_false.items():
            char_name = (self.get_character(cid) or {}).get("name", cid)
            violations.append(_make_violation(
                vtype=ContradictionType.DECEPTION,
                severity=Severity.MINOR,
                description=f"캐릭터 '{char_name}'이(가) 거짓 사실을 진실로 학습(story_order={so})",
                confidence=0.55,
                character_id=cid, character_name=char_name,
                evidence=[{"fact_id": fid, "believed_true_at": so}],
                needs_user_input=True,
                confirmation_type=ConfirmationType.UNRELIABLE_NARRATOR,
            ))
        return violations

    def find_trait_event_violations(self) -> List[Dict[str, Any]]:
        """8. 특성-이벤트 모순: 캐릭터의 금지/혐오 특성을 위반하는 행동이 이벤트에 등장"""
        violations = []

        # HAS_TRAIT 엣지에서 캐릭터별 부정 특성 수집
        has_trait = self._edges_by_label("HAS_TRAIT")
        char_neg_traits: Dict[str, List[Dict]] = {}
        for e in has_trait:
            cid, tid = _prop(e, "from_id"), _prop(e, "to_id")
            trait = self.get_trait(tid) or {}
            value = str(_prop(trait, "value") or "")
            if not cid or not self._trait_is_prohibitive(value):
                continue
            keywords = self._extract_subject_keywords(value)
            if not keywords:
                continue
            char_neg_traits.setdefault(cid, []).append({
                "key": _prop(trait, "key"),
                "value": value,
                "keywords": keywords,
                "is_immutable": _prop(trait, "is_immutable") in (True, "True", "true", 1),
            })

        # 이름 → ID 맵 (fact 스캔 전에 구축)
        name_to_id: Dict[str, str] = {}
        for cv in self._vertices_by_label("character"):
            name = _prop(cv, "name") or _prop(cv, "canonical_name") or ""
            cid = _prop(cv, "id")
            if name and cid:
                name_to_id[name] = cid

        # facts에서도 금지 특성 추출 (LLM이 trait 대신 fact로 추출하는 경우)
        # 카테고리 무관 — 캐릭터 이름 + 금지 마커가 있으면 추출
        for fv in self._vertices_by_label("fact"):
            content = str(_prop(fv, "content") or "")
            if not self._trait_is_prohibitive(content):
                continue
            keywords = self._extract_subject_keywords(content)
            if not keywords:
                continue
            # fact content에서 알려진 캐릭터 이름 매칭 (첫 어절 fallback)
            matched_name = None
            for cn in name_to_id:
                if cn in content:
                    matched_name = cn
                    break
            if not matched_name:
                words = re.findall(r'[가-힣A-Za-z0-9]+', content)
                matched_name = words[0] if words else None
            if not matched_name:
                continue
            # 캐릭터 이름은 keyword에서 제외 (이름이 이벤트에 있다고 위반은 아님)
            keywords = [kw for kw in keywords if kw not in name_to_id]
            if not keywords:
                continue
            char_neg_traits.setdefault(f"__fact__{matched_name}", []).append({
                "key": "fact",
                "value": content,
                "keywords": keywords,
                "is_immutable": False,
                "char_name_hint": matched_name,
            })

        if not char_neg_traits:
            return violations

        seen: set = set()
        for ev in self._vertices_by_label("event"):
            desc = str(_prop(ev, "description") or "")
            ev_id = _prop(ev, "id")
            # _prop은 list를 받으면 첫 원소만 반환하므로 직접 접근
            raw_ci = ev.get("characters_involved") or []
            if isinstance(raw_ci, str):
                try:
                    raw_ci = json.loads(raw_ci)
                except Exception:
                    raw_ci = [raw_ci] if raw_ci else []
            elif not isinstance(raw_ci, list):
                raw_ci = []

            involved_ids = [name_to_id[n] for n in raw_ci if n in name_to_id]

            # ① HAS_TRAIT 기반 금지 특성 체크
            for cid in involved_ids:
                for trait in char_neg_traits.get(cid, []):
                    for kw in trait["keywords"]:
                        if kw not in desc:
                            continue
                        # 같은 캐릭터 + 같은 키워드 위반은 1회만 보고
                        # (trait/fact 양쪽에서 추출되어도 중복 방지)
                        vkey = (cid, kw)
                        if vkey in seen:
                            break
                        seen.add(vkey)
                        char_name = (self.get_character(cid) or {}).get("name", cid)
                        so = _prop(ev, "story_order") or _prop(ev, "discourse_order")
                        is_imm = trait["is_immutable"]
                        violations.append(_make_violation(
                            vtype=ContradictionType.TRAIT,
                            severity=Severity.CRITICAL if is_imm else Severity.MAJOR,
                            description=(
                                f"캐릭터 '{char_name}'의 특성 "
                                f"'{trait['key']}: {trait['value']}'을(를) 위반하는 "
                                f"행동 발생(story_order={so}): {desc[:80]}"
                            ),
                            confidence=0.85 if is_imm else 0.7,
                            character_id=cid, character_name=char_name,
                            evidence=[{
                                "trait_key": trait["key"],
                                "trait_value": trait["value"],
                                "event_desc": desc[:100],
                                "matched_keyword": kw,
                            }],
                            needs_user_input=not is_imm,
                            confirmation_type=(
                                ConfirmationType.INTENTIONAL_CHANGE if not is_imm else None
                            ),
                            suggestion=(
                                f"'{trait['key']}' 특성과 모순되는 행동을 수정하거나 "
                                "특성 변화 근거를 명시하세요."
                            ),
                        ))
                        break

            # ② personality facts 기반 금지 특성 체크
            for fact_key, fact_traits in char_neg_traits.items():
                if not fact_key.startswith("__fact__"):
                    continue
                char_name_hint = fact_key[len("__fact__"):]
                cid = name_to_id.get(char_name_hint)
                if not cid or cid not in involved_ids:
                    continue
                for trait in fact_traits:
                    for kw in trait["keywords"]:
                        if kw not in desc:
                            continue
                        vkey = (cid, kw)
                        if vkey in seen:
                            break
                        seen.add(vkey)
                        so = _prop(ev, "story_order") or _prop(ev, "discourse_order")
                        violations.append(_make_violation(
                            vtype=ContradictionType.TRAIT,
                            severity=Severity.MAJOR,
                            description=(
                                f"캐릭터 '{char_name_hint}'의 특성 "
                                f"'{trait['value'][:50]}'을(를) 위반하는 "
                                f"행동 발생(story_order={so}): {desc[:80]}"
                            ),
                            confidence=0.7,
                            character_id=cid, character_name=char_name_hint,
                            evidence=[{
                                "fact_value": trait["value"],
                                "event_desc": desc[:100],
                                "matched_keyword": kw,
                            }],
                            needs_user_input=True,
                            confirmation_type=ConfirmationType.INTENTIONAL_CHANGE,
                            suggestion=(
                                f"특성과 모순되는 행동을 수정하거나 변화 근거를 명시하세요."
                            ),
                        ))
                        break
        return violations

    def find_fact_event_violations(self) -> List[Dict[str, Any]]:
        """9. 세계 규칙-이벤트 모순: 수치 제약 facts vs 이벤트/다른 facts 실제 행동"""
        violations = []

        # 모든 fact에서 수치 제약 추출 (카테고리 무관 — LLM이 worldbuilding/event_fact 등 다양하게 씀)
        all_facts = self._vertices_by_label("fact")
        constraints: List[Dict] = []
        for fv in all_facts:
            content = str(_prop(fv, "content") or "")
            for c in self._extract_fact_constraints(content):
                c["fact_content"] = content
                c["fact_id"] = _prop(fv, "id")
                c["context_keywords"] = self._extract_subject_keywords(content)
                constraints.append(c)

        if not constraints:
            return violations

        # 비교 대상: 이벤트 + 다른 facts (LLM이 "5분 만에" 등을 fact로 추출하는 경우)
        candidate_texts: List[Tuple[str, str, Any]] = []  # (id, text, story_order)
        for ev in self._vertices_by_label("event"):
            candidate_texts.append((
                str(_prop(ev, "id") or ""),
                str(_prop(ev, "description") or ""),
                _prop(ev, "story_order") or _prop(ev, "discourse_order") or 0,
            ))
        for fv in all_facts:
            candidate_texts.append((
                str(_prop(fv, "id") or ""),
                str(_prop(fv, "content") or ""),
                _prop(fv, "established_order") or 0,
            ))

        seen: set = set()
        for cand_id, desc, so in candidate_texts:
            ev_values = self._extract_event_numeric_values(desc)
            if not ev_values:
                continue

            for constraint in constraints:
                if cand_id == constraint.get("fact_id"):
                    continue  # 같은 fact는 비교 안 함
                ctx_kws = constraint.get("context_keywords", [])
                if ctx_kws and not any(kw in desc for kw in ctx_kws):
                    continue
                for ev_val in ev_values:
                    msg = self._check_numeric_violation(constraint, ev_val, desc, so)
                    if not msg:
                        continue
                    # 동일 세계 규칙 위반은 1번만 보고 (constraint 기준 중복 제거)
                    vkey = (constraint["fact_id"], constraint["type"], constraint["value"])
                    if vkey in seen:
                        continue
                    seen.add(vkey)
                    # 수치 비교가 수학적으로 명확한 경우 Hard 승격
                    is_definite = (
                        (constraint["type"] == "min_duration"
                         and ev_val["type"] == "duration_taken"
                         and ev_val["value"] < constraint["value"])
                        or
                        (constraint["type"] == "lockout_after_hour"
                         and ev_val["type"] == "clock_time"
                         and ev_val["value"] >= constraint["value"])
                    )
                    violations.append(_make_violation(
                        vtype=ContradictionType.TIMELINE,
                        severity=Severity.CRITICAL if is_definite else Severity.MAJOR,
                        description=msg,
                        confidence=0.95 if is_definite else 0.75,
                        evidence=[{
                            "fact": constraint["fact_content"],
                            "compared_text": desc[:100],
                            "constraint": constraint,
                            "event_value": ev_val,
                        }],
                        needs_user_input=not is_definite,
                        confirmation_type=ConfirmationType.TIMELINE_AMBIGUITY if not is_definite else None,
                        suggestion=(
                            "세계 규칙의 수치 제약과 이벤트 내용을 일치시키거나 "
                            "예외 상황을 명시하세요."
                        ),
                    ))
        return violations

    # ── 내부 헬퍼 ────────────────────────────────────────────────

    def _trait_is_prohibitive(self, value: str) -> bool:
        return any(m in value for m in self._PROHIBITIVE_MARKERS)

    def _extract_subject_keywords(self, text: str) -> List[str]:
        """텍스트에서 의미 있는 명사 키워드 추출 (조사 제거)"""
        words = re.findall(r'[가-힣A-Za-z0-9]+', text)
        result: List[str] = []
        seen_kw: set = set()
        for word in words:
            stripped = word
            for p in sorted(self._PARTICLE_SUFFIXES, key=len, reverse=True):
                if stripped.endswith(p) and len(stripped) > len(p) + 1:
                    stripped = stripped[:-len(p)]
                    break
            if len(stripped) >= 2 and stripped not in self._CONTENT_STOP and stripped not in seen_kw:
                seen_kw.add(stripped)
                result.append(stripped)
        return result[:5]

    _LOCKOUT_WORDS = re.compile(r'봉쇄|차단|폐쇄|통제|출입금지|진입불가|제한|잠금|락다운|lockdown|봉인')

    def _extract_fact_constraints(self, fact_content: str) -> List[Dict]:
        """세계 규칙 fact에서 수치 제약 추출"""
        constraints = []
        for m in re.finditer(
            r'(?:최소|최단|적어도)?\s*(\d+)\s*(분|시간|초)(?:\s*(?:이상|소요|걸림|이내))?',
            fact_content,
        ):
            constraints.append({
                "type": "min_duration",
                "value": int(m.group(1)),
                "unit": m.group(2),
                "raw": m.group().strip(),
            })
        # 시각 통제: "N시 이후/부터" 패턴 + 같은 fact에 봉쇄/제한 계열 단어 존재
        # "N시까지"(종료 시각)는 제외 — 이후/부터가 명시된 시작 시각만 추출
        if self._LOCKOUT_WORDS.search(fact_content):
            for m in re.finditer(r'(\d+)\s*시\s*(?:이후|부터)', fact_content):
                constraints.append({
                    "type": "lockout_after_hour",
                    "value": int(m.group(1)),
                    "unit": "시",
                    "raw": m.group().strip(),
                })
        return constraints

    def _extract_event_numeric_values(self, desc: str) -> List[Dict]:
        """이벤트 설명에서 소요시간/시각 추출"""
        values = []
        for m in re.finditer(r'(\d+)\s*(분|시간|초)\s*(?:만에|후|내에|안에)', desc):
            values.append({
                "type": "duration_taken",
                "value": int(m.group(1)),
                "unit": m.group(2),
                "raw": m.group().strip(),
            })
        for m in re.finditer(
            r'(?:오전|오후|밤|새벽)?\s*(\d+)\s*시(?:\s*(?:에|쯤|경|정각))?', desc
        ):
            values.append({
                "type": "clock_time",
                "value": int(m.group(1)),
                "unit": "시",
                "raw": m.group().strip(),
            })
        return values

    def _check_numeric_violation(
        self, constraint: Dict, ev_val: Dict, desc: str, so: Any
    ) -> Optional[str]:
        """제약 vs 이벤트 수치 비교. 위반 시 설명 반환, 없으면 None."""
        ctype, cval, unit = constraint["type"], constraint["value"], constraint["unit"]
        evtype, evval, evunit = ev_val["type"], ev_val["value"], ev_val["unit"]

        if ctype == "min_duration" and evtype == "duration_taken" and unit == evunit:
            if evval < cval:
                return (
                    f"세계 규칙 위반 — 최소 {cval}{unit} 소요 구간을 "
                    f"{evval}{evunit} 만에 이동(story_order={so}): {desc[:80]}"
                )
        if ctype == "lockout_after_hour" and evtype == "clock_time" and evunit == "시":
            if evval >= cval:
                return (
                    f"세계 규칙 위반 — {cval}시 이후 봉쇄 구역에 "
                    f"{evval}시 이동/진입(story_order={so}): {desc[:80]}"
                )
        return None

    # ── 타임스탬프 파싱 ────────────────────────────────────────────

    _TS_RE = re.compile(
        r'(?P<ampm>오전|오후|밤|새벽|낮|정오)?\s*(?P<h>\d{1,2})\s*시\s*(?:(?P<m>\d{1,2})\s*분)?'
    )

    @classmethod
    def _parse_timestamp_minutes(cls, text: str) -> Optional[int]:
        """텍스트에서 첫 번째 시각을 분 단위 절대값으로 변환. 없으면 None."""
        m = cls._TS_RE.search(text)
        if not m:
            return None
        h = int(m.group("h"))
        mins = int(m.group("m")) if m.group("m") else 0
        ampm = m.group("ampm") or ""
        if ampm in ("오후", "밤") and h < 12:
            h += 12
        elif ampm in ("새벽",) and h == 12:
            h = 0
        return h * 60 + mins

    def _find_timestamp_violations(self) -> List[Dict[str, Any]]:
        """연속 이벤트의 타임스탬프 간 시간차 vs min_duration 제약 비교."""
        violations = []
        # 제약 수집
        all_facts = self._vertices_by_label("fact")
        constraints = []
        for fv in all_facts:
            content = str(_prop(fv, "content") or "")
            for c in self._extract_fact_constraints(content):
                if c["type"] == "min_duration":
                    c["fact_content"] = content
                    c["fact_id"] = _prop(fv, "id")
                    c["context_keywords"] = self._extract_subject_keywords(content)
                    constraints.append(c)
        if not constraints:
            return violations

        # 이벤트에서 타임스탬프 추출
        events = self._vertices_by_label("event")
        ts_events = []
        for ev in events:
            desc = str(_prop(ev, "description") or "")
            ts = self._parse_timestamp_minutes(desc)
            if ts is not None:
                so = _prop(ev, "story_order") or _prop(ev, "discourse_order") or 0
                ts_events.append({"ts": ts, "desc": desc, "so": so, "id": _prop(ev, "id")})
        ts_events.sort(key=lambda x: float(x["so"]))

        seen: set = set()
        for i in range(1, len(ts_events)):
            prev, curr = ts_events[i - 1], ts_events[i]
            diff = curr["ts"] - prev["ts"]
            if diff <= 0:
                continue  # 시간 역전이거나 동일 시간
            for constraint in constraints:
                cval = constraint["value"]
                if constraint["unit"] == "시간":
                    cval *= 60
                if diff >= cval:
                    continue  # 제약 충족
                # context 키워드 매칭 (완화: 키워드 없거나 1개 이상 매칭)
                ctx_kws = constraint.get("context_keywords", [])
                combined = prev["desc"] + " " + curr["desc"]
                if len(ctx_kws) > 2 and not any(kw in combined for kw in ctx_kws):
                    continue
                vkey = (constraint["fact_id"], constraint["type"], constraint["value"])
                if vkey in seen:
                    continue
                seen.add(vkey)
                # 타임스탬프 차이가 제약보다 확실히 작으면 Hard
                is_definite = diff < cval
                violations.append(_make_violation(
                    vtype=ContradictionType.TIMELINE,
                    severity=Severity.CRITICAL if is_definite else Severity.MAJOR,
                    description=(
                        f"세계 규칙 위반 — 최소 {constraint['value']}{constraint['unit']} 소요 구간을 "
                        f"{diff}분 만에 이동(story_order={curr['so']}): {curr['desc'][:60]}"
                    ),
                    confidence=0.95 if is_definite else 0.75,
                    evidence=[{
                        "fact": constraint["fact_content"],
                        "prev_event": prev["desc"][:60],
                        "curr_event": curr["desc"][:60],
                        "time_diff_min": diff,
                        "required_min": cval,
                    }],
                    needs_user_input=not is_definite,
                    confirmation_type=ConfirmationType.TIMELINE_AMBIGUITY if not is_definite else None,
                    suggestion="이동 시간 또는 장면 시각을 수정하세요.",
                ))
        return violations

    # ── 세계 규칙 위반 탐지 (LLM 기반으로 이관됨) ─────────────────

    def find_world_rule_violations(self) -> List[Dict[str, Any]]:
        """detection.py _check_world_rules_with_llm()으로 이관됨. 빈 리스트 반환."""
        return []

    def find_all_violations(self) -> Dict[str, List[Dict[str, Any]]]:
        """11가지 쿼리 통합 + Hard / Soft 분류 + 탐지기 간 중복 제거"""
        raw = (
            self.find_knowledge_violations()
            + self.find_timeline_violations()
            + self.find_relationship_violations()
            + self.find_trait_violations()
            + self.find_emotion_violations()
            + self.find_item_violations()
            + self.find_deception_violations()
            + self.find_trait_event_violations()
            + self.find_fact_event_violations()
            + self._find_timestamp_violations()
        )
        # 탐지기 간 중복 제거
        # hard를 먼저 처리 → 동일 위반이 hard/soft 양쪽에서 탐지될 때 hard가 남도록
        raw_sorted = sorted(raw, key=lambda v: (0 if v.get("is_hard") else 1))

        all_v: List[Dict[str, Any]] = []
        seen_desc: set = set()
        # (type, character_id) → 이미 등록된 key_parts set 목록 (Jaccard dedup용)
        seen_char_type_parts: Dict[Tuple, List[set]] = {}
        # evidence 내 fact_id 기반 cross-type dedup (세계 규칙 탐지기 간 중복 제거)
        seen_fact_ids: set = set()

        for v in raw_sorted:
            desc = v.get("description", "")
            key_parts = re.findall(r'[가-힣]{2,}', desc)
            key_parts_set = set(key_parts)

            # 0단계: evidence 내 fact_id 기반 cross-type dedup
            # 동일 fact 기반 세계 규칙 위반이 여러 탐지기에서 잡힐 때 Hard 우선 유지
            evidence_list = v.get("evidence") or []
            fact_id = None
            for ev_item in evidence_list:
                if isinstance(ev_item, dict):
                    fact_id = ev_item.get("fact_id") or ev_item.get("fact")
                    if fact_id:
                        break
            if fact_id and fact_id in seen_fact_ids:
                continue
            if fact_id:
                seen_fact_ids.add(fact_id)

            # 1단계: 기존 exact dedup
            dedup_key = (v.get("type", ""), tuple(sorted(key_parts_set)))
            if dedup_key in seen_desc:
                continue

            # 2단계: Jaccard 유사도 dedup (character_id가 있는 경우)
            # 동일 (type, character_id) 조합에서 key_parts가 50% 이상 겹치면 중복으로 판단
            char_id = v.get("character_id") or ""
            if char_id:
                ct_key = (str(v.get("type", "")), char_id)
                prev_parts_list = seen_char_type_parts.get(ct_key, [])
                is_dup = False
                for prev_parts in prev_parts_list:
                    union = key_parts_set | prev_parts
                    inter = key_parts_set & prev_parts
                    if union and len(inter) / len(union) > 0.5:
                        is_dup = True
                        break
                if is_dup:
                    continue
                seen_char_type_parts.setdefault(ct_key, []).append(key_parts_set)

            seen_desc.add(dedup_key)
            all_v.append(v)

        hard = [v for v in all_v if v.get("is_hard")]
        soft = [v for v in all_v if not v.get("is_hard")]
        logger.info("find_all_violations complete", hard=len(hard), soft=len(soft), total=len(all_v))
        return {"hard": hard, "soft": soft, "all": all_v}


# ─────────────────────────────────────────────────────────────
# Gremlin 클라이언트 팩토리
# ─────────────────────────────────────────────────────────────

def _vertex_to_dict(v: Any) -> Dict[str, Any]:
    """Pydantic VertexBase → 스토리지용 flat dict.
    - UUID/datetime → str 변환
    - list/dict 필드 → JSON 문자열 (Gremlin 호환)
    - partition_key property 포함
    """
    d = v.model_dump(mode="json")
    d["id"] = str(v.id)
    d["partition_key"] = v.partition_key
    # created_at 이미 model_dump(mode="json")에 의해 str 변환됨
    for k, val in list(d.items()):
        if isinstance(val, (list, dict)):
            d[k] = json.dumps(val, ensure_ascii=False)
    return d


def _safe_enum(enum_cls: Any, value: Any, default: Any) -> Any:
    """문자열 → enum 변환 실패 시 default 반환"""
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        return default


def _deserialize_vertex_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """_vertex_to_dict()가 JSON 문자열로 직렬화한 list/dict 필드를 역직렬화.

    InMemoryGraphService는 Python dict를 그대로 보관하므로,
    저장 시 JSON 문자열을 실제 Python 객체로 복원해야
    Pydantic 모델 역직렬화(UserConfirmation(**raw) 등)가 정상 동작한다.
    """
    result: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, (list, dict)):
                    result[k] = parsed
                    continue
            except (json.JSONDecodeError, ValueError):
                pass
        result[k] = v
    return result


def create_gremlin_client(endpoint: str, key: str, database: str, container: str) -> client.Client:
    """Azure Cosmos DB Gremlin용 string-query 클라이언트 생성.

    Cosmos DB Gremlin은 bytecode 미지원 → client.Client + submit(string) 사용.
    """
    url = endpoint if endpoint.startswith("wss://") else f"wss://{endpoint}:443/"
    username = f"/dbs/{database}/colls/{container}"
    return client.Client(
        url, "g",
        username=username,
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
        transport_factory=lambda **kwargs: AiohttpTransport(heartbeat=20, **kwargs),
    )


# ─────────────────────────────────────────────────────────────
# GremlinGraphService  (Azure Cosmos DB)
# ─────────────────────────────────────────────────────────────

class GremlinGraphService(_ViolationMixin):
    """Azure Cosmos DB (Gremlin API) 기반 그래프 서비스.

    Cosmos DB Gremlin은 bytecode 미지원이므로 string-query + client.Client 사용.
    모든 Gremlin 쿼리는 _submit() / _submit_first() 헬퍼를 통해 실행된다.
    """

    def __init__(self, endpoint: str, key: str, database: str, container: str, storage_service: Optional[StorageService] = None):
        self.endpoint = endpoint
        self.key = key
        self.database = database
        self.container = container
        self.client = create_gremlin_client(endpoint, key, database, container)
        self._lock = threading.Lock()
        self._discourse_counter: float = 0.0
        self.storage = storage_service
        logger.info("GremlinGraphService initialized")

    # ── 내부 헬퍼 ─────────────────────────────────────────────

    @staticmethod
    def _qval(value: Any) -> str:
        """Gremlin 쿼리 문자열용 값 이스케이프.

        None → null, bool → true/false, number → 숫자 그대로,
        list/dict → JSON 문자열로 직렬화 후 single-quote 래핑,
        나머지 → single-quote 래핑 + 내부 작은따옴표 이스케이프.
        """
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (list, dict)):
            s = json.dumps(value, ensure_ascii=False)
            return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
        return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"

    def _is_connection_error(self, e: Exception) -> bool:
        """Gremlin 연결 끊김 / 닫힘 계열 에러 여부 판단."""
        msg = str(e).lower()
        return any(kw in msg for kw in (
            "already closed",
            "closing transport",
            "connection closed",
            "connection reset",
            "transport closed",
        ))

    def _reconnect(self) -> None:
        """Gremlin 클라이언트를 새로 생성해 연결을 복구한다.
        새 클라이언트 생성 성공 후에만 기존 클라이언트를 교체한다.
        """
        new_client = create_gremlin_client(
            self.endpoint, self.key, self.database, self.container
        )
        try:
            self.client.close()
        except Exception:
            pass
        self.client = new_client
        logger.info("gremlin_reconnected", endpoint=self.endpoint)

    def _submit(self, query: str) -> List[Any]:
        """Gremlin 쿼리 문자열을 Cosmos DB에 제출하고 결과 리스트 반환.

        - threading.Lock으로 동시 접근 충돌 방지
        - 120초 timeout으로 죽은 연결 hang 방지
        - 연결 끊김 / timeout 발생 시 1회 재연결 후 재시도
        """
        with self._lock:
            try:
                return self.client.submit(query).all().result(timeout=120)
            except Exception as e:
                if self._is_connection_error(e) or isinstance(e, TimeoutError):
                    logger.warning("gremlin_connection_lost_reconnecting", error=str(e))
                    self._reconnect()
                    try:
                        return self.client.submit(query).all().result(timeout=120)
                    except Exception as e2:
                        logger.error("gremlin_submit_failed_after_reconnect", query=query[:300], error=str(e2))
                        raise
                logger.error("gremlin_submit_failed", query=query[:300], error=str(e))
                raise

    def _submit_first(self, query: str) -> Optional[Any]:
        """_submit()의 첫 번째 결과만 반환. 없으면 None."""
        results = self._submit(query)
        return results[0] if results else None

    def _build_props(self, data: dict, exclude: Optional[set] = None) -> str:
        """dict → .property('k', v) 체인 문자열 빌더."""
        exclude = exclude or set()
        parts = []
        for k, v in data.items():
            if k in exclude or v is None:
                continue
            parts.append(f".property({self._qval(k)}, {self._qval(v)})")
        return "".join(parts)

    def _add_vertex_generic(self, label: str, data: dict, partition_key: str) -> str:
        vid = data.get("id", str(uuid.uuid4()))
        data["id"] = vid
        # partition_key는 명시적으로 먼저 설정하므로 _build_props에서 제외
        props = self._build_props(data, exclude={"id", "partition_key"})
        query = (
            f"g.addV({self._qval(label)})"
            f".property('id', {self._qval(vid)})"
            f".property('partition_key', {self._qval(partition_key)})"
            f"{props}"
        )
        self._submit(query)
        logger.debug("Added vertex", label=label, vid=vid)
        return vid

    def _add_edge_generic(self, label: str, from_id: str, to_id: str, data: dict) -> str:
        data = dict(data)  # 호출자의 dict 원본 변조 방지
        eid = data.get("id", str(uuid.uuid4()))
        data["id"] = eid
        # from_id / to_id를 엣지 속성으로도 저장 → valueMap 조회 시 활용
        data["from_id"] = from_id
        data["to_id"] = to_id
        props = self._build_props(data, exclude={"id"})
        query = (
            f"g.V({self._qval(from_id)}).addE({self._qval(label)})"
            f".to(g.V({self._qval(to_id)}))"
            f".property('id', {self._qval(eid)})"
            f"{props}"
        )
        self._submit(query)
        logger.debug("Added edge", label=label, from_id=from_id, to_id=to_id, eid=eid)
        return eid

    def _get_next_discourse_order(self) -> float:
        try:
            results = self._submit(
                "g.V().hasLabel('event').values('discourse_order').order().by(decr).limit(1)"
            )
            base = float(results[0]) if results else self._discourse_counter
        except Exception:
            base = self._discourse_counter
        self._discourse_counter = round(base + 0.1, 4)
        return self._discourse_counter

    def _fetch_all(self, label: str) -> List[Dict]:
        try:
            raw = self._submit(f"g.V().hasLabel({self._qval(label)}).valueMap(true)")
            return [self._normalize_valueMap(r) for r in raw]
        except Exception as e:
            logger.warning("Fetch failed", label=label, error=str(e))
            return []

    def _fetch_edges_by_label(self, label: str) -> List[Dict]:
        """엣지 valueMap 조회. from_id/to_id는 속성으로 저장되어 있음."""
        try:
            raw = self._submit(f"g.V().outE({self._qval(label)}).valueMap(true)")
            return [self._normalize_valueMap(r) for r in raw]
        except Exception as e:
            logger.warning("Edge fetch failed", label=label, error=str(e))
            return []

    # _ViolationMixin 인터페이스 — _fetch_* 메서드의 alias
    def _vertices_by_label(self, label: str) -> List[Dict]:
        return self._fetch_all(label)

    def _edges_by_label(self, label: str) -> List[Dict]:
        return self._fetch_edges_by_label(label)

    # ── Vertex CRUD (9종) ─────────────────────────────────────

    def add_character(self, data: dict) -> str:
        return self._add_vertex_generic("character", data, "character")

    def get_character(self, char_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(char_id)}).hasLabel('character').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def find_character_by_name(self, name: str) -> Optional[Dict]:
        r = self._submit_first(
            f"g.V().hasLabel('character').has('name', {self._qval(name)}).valueMap(true)"
        )
        return self._normalize_valueMap(r) if r else None

    def list_characters(self) -> List[Dict]:
        return self._fetch_all("character")

    def add_fact(self, data: dict) -> str:
        return self._add_vertex_generic("fact", data, "fact")

    def get_fact(self, fact_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(fact_id)}).hasLabel('fact').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_facts(self) -> List[Dict]:
        return self._fetch_all("fact")

    def add_event(self, data: dict) -> str:
        return self._add_vertex_generic("event", data, "event")

    def get_event(self, event_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(event_id)}).hasLabel('event').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_events(self) -> List[Dict]:
        return self._fetch_all("event")

    def add_trait(self, data: dict) -> str:
        return self._add_vertex_generic("trait", data, "trait")

    def get_trait(self, trait_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(trait_id)}).hasLabel('trait').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_traits(self) -> List[Dict]:
        return self._fetch_all("trait")

    def add_organization(self, data: dict) -> str:
        return self._add_vertex_generic("organization", data, "organization")

    def get_organization(self, org_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(org_id)}).hasLabel('organization').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_organizations(self) -> List[Dict]:
        return self._fetch_all("organization")

    def add_location(self, data: dict) -> str:
        return self._add_vertex_generic("location", data, "location")

    def get_location(self, loc_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(loc_id)}).hasLabel('location').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_locations(self) -> List[Dict]:
        return self._fetch_all("location")

    def add_item(self, data: dict) -> str:
        return self._add_vertex_generic("item", data, "item")

    def get_item(self, item_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(item_id)}).hasLabel('item').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_items(self) -> List[Dict]:
        return self._fetch_all("item")

    def add_source(self, data: dict) -> str:
        return self._add_vertex_generic("source", data, "source")

    def get_source(self, source_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(source_id)}).hasLabel('source').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_sources(self) -> List[Dict]:
        return self._fetch_all("source")

    def add_user_confirmation(self, data: dict) -> str:
        return self._add_vertex_generic("confirmation", data, "confirmation")

    def get_user_confirmation(self, conf_id: str) -> Optional[Dict]:
        r = self._submit_first(f"g.V({self._qval(conf_id)}).hasLabel('confirmation').valueMap(true)")
        return self._normalize_valueMap(r) if r else None

    def list_pending_confirmations(self) -> List[Dict]:
        raw = self._submit(
            f"g.V().hasLabel('confirmation')"
            f".has('status', {self._qval(ConfirmationStatus.PENDING.value)}).valueMap(true)"
        )
        return [self._normalize_valueMap(r) for r in raw]

    # ── Edge 추가 (13종) ──────────────────────────────────────

    def add_learns(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("LEARNS", from_id, to_id, data)

    def add_mentions(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("MENTIONS", from_id, to_id, data)

    def add_participates_in(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("PARTICIPATES_IN", from_id, to_id, data)

    def add_has_status(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("HAS_STATUS", from_id, to_id, data)

    def add_at_location(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("AT_LOCATION", from_id, to_id, data)

    def add_related_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("RELATED_TO", from_id, to_id, data)

    def add_belongs_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("BELONGS_TO", from_id, to_id, data)

    def add_feels(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("FEELS", from_id, to_id, data)

    def add_has_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("HAS_TRAIT", from_id, to_id, data)

    def add_violates_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("VIOLATES_TRAIT", from_id, to_id, data)

    def add_possesses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("POSSESSES", from_id, to_id, data)

    def add_loses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("LOSES", from_id, to_id, data)

    def add_sourced_from(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("SOURCED_FROM", from_id, to_id, data)

    # ── 계층 3: Graph 적재 ────────────────────────────────────

    def materialize(self, normalized: NormalizationResult, source: Source, skip_source_vertex: bool = False) -> Dict[str, List[str]]:
        """NormalizationResult → Cosmos DB Graph 적재

        Steps:
          0. Source vertex 적재 (skip_source_vertex=True이면 건너뜀 — 증분 재구축 시 이미 존재)
          1. NormalizedCharacter → Character vertex + SOURCED_FROM
          2. NormalizedFact     → KnowledgeFact vertex + SOURCED_FROM (discourse_order 자동 부여)
          3. NormalizedEvent    → Event vertex + SOURCED_FROM
          4. SourceConflict     → UserConfirmation vertex + SOURCED_FROM
          5. Traits             → Trait vertex + HAS_TRAIT edge
          6. Emotions           → FEELS edge (Character → Character)
          7. KnowledgeEvents    → LEARNS / MENTIONS edge (Character → KnowledgeFact)
          8. ItemEvents         → Item vertex + POSSESSES / LOSES edge
          9. Relationships      → RELATED_TO edge (Character → Character)
        """
        source_id = str(source.source_id) if source.source_id else str(source.id)
        created: Dict[str, List[str]] = {
            "source": [], "characters": [], "facts": [], "events": [], "confirmations": [],
            "traits": [], "edges": [],
        }

        logger.info("Materializing NormalizationResult", source_id=source_id)
        try:
            # 0. Source vertex 적재 (증분 재구축 시 이미 존재하므로 skip)
            if not skip_source_vertex:
                src_dict = _vertex_to_dict(source)
                # Source vertex의 id와 source_id를 비즈니스 키(source_id)로 통일
                # → get_source(source_id) 조회 및 remove_source(source_id) 삭제 일치
                src_dict["id"] = source_id
                src_dict["source_id"] = source_id
                self.add_source(src_dict)
            created["source"].append(source_id)

            # 1. Character vertices — name→id 맵 구축 (기존 캐릭터 재사용)
            char_name_to_id: Dict[str, str] = {}
            for nc in normalized.characters:
                # 이미 같은 이름의 캐릭터가 DB에 있으면 재사용 (중복 생성 방지)
                existing = self.find_character_by_name(nc.canonical_name)
                if existing:
                    existing_id = existing["id"]
                    char_name_to_id[nc.canonical_name] = existing_id
                    for alias in nc.all_aliases:
                        char_name_to_id[alias] = existing_id
                    logger.debug("reuse_existing_character", name=nc.canonical_name, id=existing_id)
                    continue
                char = Character(
                    source_id=source_id,
                    name=nc.canonical_name,
                    aliases=nc.all_aliases,
                    tier=_safe_enum(CharacterTier, nc.tier, CharacterTier.TIER_4),
                    description=nc.description,
                )
                char_dict = _vertex_to_dict(char)
                # chunk_id 기록: merged_from의 첫 번째 source_chunk_id
                if nc.merged_from:
                    char_dict["chunk_id"] = nc.merged_from[0].source_chunk_id or ""
                self.add_character(char_dict)
                self.add_sourced_from(char_dict["id"], source_id, {
                    "source_id": source_id,
                    "source_location": "",
                    "created_at": char_dict["created_at"],
                })
                created["characters"].append(char_dict["id"])
                char_name_to_id[nc.canonical_name] = char_dict["id"]
                for alias in nc.all_aliases:
                    char_name_to_id[alias] = char_dict["id"]

            def _resolve_char(name: str) -> Optional[str]:
                if name in char_name_to_id:
                    return char_name_to_id[name]
                existing = self.find_character_by_name(name)
                if existing:
                    char_name_to_id[name] = existing["id"]
                    return existing["id"]
                return None

            # 2. KnowledgeFact vertices (discourse_order 자동 부여) — content→id 맵 구축
            # 기존 fact도 content 기준으로 인덱싱해 중복 생성 방지
            fact_content_to_id: Dict[str, str] = {
                _prop(v, "content"): _prop(v, "id")
                for v in self._fetch_all("fact")
                if _prop(v, "content") and _prop(v, "id")
            }
            for nf in normalized.facts:
                if nf.content in fact_content_to_id:
                    logger.debug("reuse_existing_fact", content=nf.content[:50])
                    continue
                do = self._get_next_discourse_order()
                fact = KnowledgeFact(
                    source_id=source_id,
                    content=nf.content,
                    category=_safe_enum(FactCategory, nf.category, FactCategory.EVENT_FACT),
                    importance=_safe_enum(FactImportance, nf.importance, FactImportance.MINOR),
                    is_secret=nf.is_secret,
                    is_true=nf.is_true,
                    established_order=do,
                    source_location="",
                )
                fact_dict = _vertex_to_dict(fact)
                # chunk_id 기록
                if nf.merged_from:
                    fact_dict["chunk_id"] = nf.merged_from[0].source_chunk_id or ""
                self.add_fact(fact_dict)
                self.add_sourced_from(fact_dict["id"], source_id, {
                    "source_id": source_id,
                    "source_location": "",
                    "created_at": fact_dict["created_at"],
                })
                created["facts"].append(fact_dict["id"])
                fact_content_to_id[nf.content] = fact_dict["id"]

            # 3. Event vertices (discourse_order/story_order 자동 부여)
            _DEATH_KW = ["사망", "죽", "숨졌", "시체", "피살", "살해", "사망한 상태", "암살", "익사", "사고사", "전사", "처형", "사형", "사망 처리", "사망 판정", "사망자 등록", "사사"]
            raw_event_dicts = [
                {
                    "description": ne.description,
                    "event_type": ne.event_type,
                    "location": ne.location,
                    "status_char": ne.status_char,
                    "characters_involved": ne.characters_involved,
                    "chunk_id": ne.merged_from[0].source_chunk_id if ne.merged_from else "",
                }
                for ne in normalized.events
            ]
            for ev_data in self._assign_time_axes(raw_event_dicts):
                event = Event(
                    source_id=source_id,
                    discourse_order=ev_data["discourse_order"],
                    story_order=ev_data.get("story_order"),
                    is_linear=ev_data.get("is_linear", True),
                    event_type=_safe_enum(EventType, ev_data.get("event_type", "scene"), EventType.SCENE),
                    description=ev_data["description"],
                    location=ev_data.get("location"),
                    source_location="",
                )
                event_dict = _vertex_to_dict(event)
                event_dict["characters_involved"] = ev_data.get("characters_involved") or []
                event_dict["chunk_id"] = ev_data.get("chunk_id") or ""
                self.add_event(event_dict)
                self.add_sourced_from(event_dict["id"], source_id, {
                    "source_id": source_id,
                    "source_location": "",
                    "created_at": event_dict["created_at"],
                })
                created["events"].append(event_dict["id"])

                # 3a. death 이벤트 → HAS_STATUS dead 엣지 자동 생성
                _is_death = (
                    event_dict.get("event_type") == "death"
                    or (ev_data.get("status_char") and any(
                        kw in event_dict.get("description", "")
                        for kw in _DEATH_KW
                    ))
                )
                if _is_death:
                    status_char = ev_data.get("status_char")
                    char_id = _resolve_char(status_char) if status_char else None
                    if char_id:
                        self.add_has_status(char_id, event_dict["id"], {
                            "status_type": "dead",
                            "status_value": "사망",
                            "story_order": event_dict.get("story_order") or event_dict.get("discourse_order"),
                            "source_id": source_id,
                            "source_location": "",
                            "created_at": event_dict["created_at"],
                        })
                        created["edges"].append(f"status-dead-{char_id}")

            # 3b. 사망 관련 Facts → HAS_STATUS dead 엣지 생성
            for nf in normalized.facts:
                content = nf.content
                if not any(kw in content for kw in _DEATH_KW):
                    continue
                for nc in normalized.characters:
                    names_to_check = [nc.canonical_name] + list(nc.all_aliases)
                    if not any(n in content for n in names_to_check):
                        continue
                    char_id_for_death = char_name_to_id.get(nc.canonical_name)
                    if not char_id_for_death:
                        continue
                    do_death = self._get_next_discourse_order()
                    # 설정집/세계관의 사망 사실은 시나리오 이전 상태 → story_order=0.0
                    death_so = 0.0
                    death_event = Event(
                        source_id=source_id,
                        discourse_order=do_death,
                        story_order=death_so,
                        is_linear=True,
                        event_type=_safe_enum(EventType, "death", EventType.SCENE),
                        description=content,
                        location=None,
                        source_location="",
                    )
                    death_dict = _vertex_to_dict(death_event)
                    death_dict["characters_involved"] = [nc.canonical_name]
                    self.add_event(death_dict)
                    self.add_has_status(char_id_for_death, death_dict["id"], {
                        "status_type": "dead",
                        "status_value": "사망",
                        "story_order": death_so,
                        "source_id": source_id,
                        "source_location": "",
                        "created_at": death_dict["created_at"],
                    })
                    created["edges"].append(f"status-dead-fact-{char_id_for_death}")
                    break  # 캐릭터당 1번만

            # 4. SourceConflict → UserConfirmation vertices
            for conflict in normalized.source_conflicts:
                excerpts = [
                    SourceExcerpt(
                        source_name=d.source_id,
                        source_location="",
                        text=d.text,
                    )
                    for d in conflict.descriptions
                ]
                conf = UserConfirmation(
                    source_id=source_id,
                    confirmation_type=ConfirmationType.SOURCE_CONFLICT,
                    status=ConfirmationStatus.PENDING,
                    question=(
                        f"소스 충돌: '{conflict.entity_type}'에 대해 "
                        f"소스들이 서로 다른 내용을 기술합니다. 어느 것이 정본입니까?"
                    ),
                    context_summary=f"충돌 값: {', '.join(conflict.conflicting_values)}",
                    source_excerpts=excerpts,
                    related_entity_ids=[],
                )
                conf_dict = _vertex_to_dict(conf)
                self.add_user_confirmation(conf_dict)
                self.add_sourced_from(conf_dict["id"], source_id, {
                    "source_id": source_id,
                    "source_location": "",
                    "created_at": conf_dict["created_at"],
                })
                created["confirmations"].append(conf_dict["id"])

            # 5. Traits → Trait vertex + HAS_TRAIT edge
            _IMMUTABLE_HINTS = ["절대", "극혐", "일절", "혐오", "불변", "태생", "선천", "혈액형", "입에 대지"]
            for rt in normalized.traits:
                char_id = _resolve_char(rt.character_name)
                if not char_id:
                    continue
                combined = f"{rt.key} {rt.value}"
                is_imm = any(h in combined for h in _IMMUTABLE_HINTS)
                trait_data = {
                    "id": str(uuid.uuid4()),
                    "source_id": source_id,
                    "category": rt.category_hint or "personality",
                    "key": rt.key,
                    "value": rt.value,
                    "description": rt.value,
                    "is_immutable": is_imm,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "label": "trait",
                }
                self.add_trait(trait_data)
                edge_id = self.add_has_trait(char_id, trait_data["id"], {
                    "source_id": source_id,
                    "source_location": "",
                    "created_at": trait_data["created_at"],
                })
                created["traits"].append(trait_data["id"])
                created["edges"].append(edge_id)

            # 6. Emotions → FEELS edge (Character → Character)
            for re_ in normalized.emotions:
                from_id = _resolve_char(re_.from_char)
                to_id = _resolve_char(re_.to_char)
                if not from_id or not to_id:
                    continue
                do = self._get_next_discourse_order()
                edge_id = self.add_feels(from_id, to_id, {
                    "source_id": source_id,
                    "source_location": "",
                    "emotion": re_.emotion,
                    "intensity": 0.5,
                    "discourse_order": do,
                    "story_order": do,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                created["edges"].append(edge_id)

            # 7. KnowledgeEvents → LEARNS / MENTIONS edge (Character → KnowledgeFact)
            for ke in normalized.knowledge_events:
                char_id = _resolve_char(ke.character_name)
                if not char_id:
                    continue
                # 1) 정확히 일치하는 fact 검색
                fact_id = fact_content_to_id.get(ke.fact_content)
                # 2) 없으면 bi-gram 유사도로 기존 fact 매칭 (정보 비대칭 탐지 핵심)
                if not fact_id:
                    fact_id = _find_similar_fact(ke.fact_content, fact_content_to_id)
                    if fact_id:
                        logger.debug(
                            "knowledge_fact_fuzzy_match",
                            content=ke.fact_content[:50],
                            matched_id=fact_id,
                        )
                # 3) 매칭 실패 → 새 fact vertex 생성
                if not fact_id:
                    do = self._get_next_discourse_order()
                    fact = KnowledgeFact(
                        source_id=source_id,
                        content=ke.fact_content,
                        category=_safe_enum(FactCategory, None, FactCategory.EVENT_FACT),
                        importance=_safe_enum(FactImportance, None, FactImportance.MINOR),
                        is_secret=False,
                        is_true=True,
                        established_order=do,
                        source_location="",
                    )
                    fact_dict = _vertex_to_dict(fact)
                    self.add_fact(fact_dict)
                    fact_id = fact_dict["id"]
                    fact_content_to_id[ke.fact_content] = fact_id
                    created["facts"].append(fact_id)
                do = self._get_next_discourse_order()
                edge_data = {
                    "source_id": source_id,
                    "source_location": "",
                    "discourse_order": do,
                    "story_order": do,
                    "believed_true": True,
                    "method": ke.method or "unknown",
                    "via_character": ke.via_character or "",
                    "dialogue_text": ke.dialogue_text or "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if ke.event_type == "learns":
                    edge_id = self.add_learns(char_id, fact_id, edge_data)
                else:
                    edge_id = self.add_mentions(char_id, fact_id, edge_data)
                created["edges"].append(edge_id)

            # 8. ItemEvents → Item vertex + POSSESSES / LOSES edge
            item_name_to_id: Dict[str, str] = {}
            for ie in normalized.item_events:
                char_id = _resolve_char(ie.character_name)
                if not char_id:
                    continue
                item_id = item_name_to_id.get(ie.item_name)
                if not item_id:
                    try:
                        raw = self._submit(
                            f"g.V().hasLabel('item').has('name', {self._qval(ie.item_name)}).valueMap(true).limit(1)"
                        )
                        item_id = self._normalize_valueMap(raw[0]).get("id") if raw else None
                    except Exception:
                        item_id = None
                    if not item_id:
                        item_data = {
                            "id": str(uuid.uuid4()),
                            "source_id": source_id,
                            "name": ie.item_name,
                            "is_unique": False,
                            "description": ie.item_name,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "label": "item",
                        }
                        self.add_item(item_data)
                        item_id = item_data["id"]
                    item_name_to_id[ie.item_name] = item_id
                do = self._get_next_discourse_order()
                edge_data = {
                    "source_id": source_id,
                    "source_location": "",
                    "discourse_order": do,
                    "story_order": do,
                    "method": "transfer",
                    "possession_type": "owns",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if ie.action == "possesses":
                    edge_id = self.add_possesses(char_id, item_id, edge_data)
                elif ie.action == "loses":
                    edge_id = self.add_loses(char_id, item_id, edge_data)
                else:
                    edge_id = self.add_possesses(char_id, item_id, edge_data)
                created["edges"].append(edge_id)

            # 9. Relationships → RELATED_TO edge (Character → Character)
            for rr in normalized.relationships:
                from_id = _resolve_char(rr.char_a)
                to_id = _resolve_char(rr.char_b)
                if not from_id or not to_id:
                    continue
                do = self._get_next_discourse_order()
                edge_id = self.add_related_to(from_id, to_id, {
                    "source_id": source_id,
                    "source_location": "",
                    "relationship_type": _normalize_relationship_type(rr.type_hint or "colleague"),
                    "detail": rr.detail or "",
                    "established_order": do,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                created["edges"].append(edge_id)

            # 10. Fact에서 아이템 유일성 힌트 추출 → is_unique 업데이트
            _UNIQUE_KW = ["하나뿐", "유일", "단 하나", "오직 하나", "1개뿐", "한 개뿐"]
            try:
                items_raw = self._submit("g.V().hasLabel('item').valueMap(true).toList()")
                facts_raw = self._submit("g.V().hasLabel('fact').valueMap(true).toList()")
                for item_r in items_raw:
                    iname = self._prop(item_r.get("name"))
                    is_uniq = self._prop(item_r.get("is_unique"))
                    if is_uniq in (True, "True", "true", 1):
                        continue
                    item_id = self._prop(item_r.get("id")) or self._prop(item_r.get(T.id))
                    for fact_r in facts_raw:
                        fc = self._prop(fact_r.get("content")) or ""
                        if iname and iname in fc and any(kw in fc for kw in _UNIQUE_KW):
                            self._submit(
                                f"g.V('{item_id}').property('is_unique', true)"
                            )
                            break
            except Exception as e:
                logger.warning("unique_hint_update_failed", error=str(e))

            logger.info("Materialization complete", **{k: len(v) for k, v in created.items()})
            return created

        except Exception as e:
            logger.error("Materialization failed", error=str(e))
            raise

    def _assign_time_axes(self, events: List[Dict]) -> List[Dict]:
        """discourse_order 단조 증가 보장 + 비선형 힌트 기반 story_order 추정"""
        TIME_JUMP_HINTS = [
            "전", "후", "년 전", "일 전", "며칠 후", "그날 밤",
            "그때", "과거에", "회상", "flashback", "그 무렵",
        ]
        result = []
        counter = 0.0
        for ev in events:
            counter = round(counter + 0.1, 4)
            ev["discourse_order"] = counter
            desc = str(ev.get("description", ""))
            if any(hint in desc for hint in TIME_JUMP_HINTS):
                ev["is_linear"] = False
                ev["story_order"] = None  # 미확정 → 사용자 확인 대상
            else:
                ev["is_linear"] = True
                ev["story_order"] = ev["discourse_order"]
            result.append(ev)
        return result

    # ── 임시 그래프 격리 ──────────────────────────────────────

    def snapshot_graph(self, relevant_ids: Optional[List[str]] = None) -> "InMemoryGraphService":
        """canonical graph의 서브그래프를 InMemory로 복제. 원본 불변 보장."""
        mem = InMemoryGraphService()
        EDGE_LABELS = [
            "LEARNS", "MENTIONS", "PARTICIPATES_IN", "HAS_STATUS",
            "AT_LOCATION", "RELATED_TO", "BELONGS_TO", "FEELS",
            "HAS_TRAIT", "VIOLATES_TRAIT", "POSSESSES", "LOSES", "SOURCED_FROM",
        ]
        try:
            if relevant_ids:
                for vid in relevant_ids:
                    try:
                        r = self._submit_first(f"g.V({self._qval(vid)}).valueMap(true)")
                        if r:
                            norm = self._normalize_valueMap(r)
                            v_id = norm.get("id") or vid
                            label = norm.get("label") or norm.get("partition_key") or "unknown"
                            mem.vertices[v_id] = {"label": label, **norm}
                    except Exception:
                        pass
                for lbl in EDGE_LABELS:
                    for vid in relevant_ids:
                        try:
                            raw = self._submit(
                                f"g.V({self._qval(vid)}).bothE({self._qval(lbl)}).valueMap(true)"
                            )
                            for e in raw:
                                norm = self._normalize_valueMap(e)
                                eid = norm.get("id") or str(uuid.uuid4())
                                mem.edges.append({"id": eid, "label": lbl, **norm})
                        except Exception:
                            pass
            else:
                raw_vs = self._submit("g.V().valueMap(true)")
                for v in raw_vs:
                    norm = self._normalize_valueMap(v)
                    v_id = norm.get("id") or str(uuid.uuid4())
                    label = norm.get("label") or norm.get("partition_key") or "unknown"
                    mem.vertices[v_id] = {"label": label, **norm}
                for lbl in EDGE_LABELS:
                    for e in self._fetch_edges_by_label(lbl):
                        eid = e.get("id") or str(uuid.uuid4())
                        mem.edges.append({"id": eid, "label": lbl, **e})

            logger.info("snapshot_graph complete", vertices=len(mem.vertices), edges=len(mem.edges))
        except Exception as e:
            logger.error("snapshot_graph failed", error=str(e))
            raise
        mem._discourse_counter = self._discourse_counter
        return mem

    # ── 유틸리티 ──────────────────────────────────────────────

    def get_character_knowledge_at(self, character_id: str, story_order: float) -> List[Dict]:
        """특정 story_order 시점까지 캐릭터가 학습한 사실 목록"""
        try:
            raw = self._submit(
                f"g.V({self._qval(character_id)}).outE('LEARNS').valueMap(true)"
            )
            result = []
            for r in raw:
                e = self._normalize_valueMap(r)
                so = e.get("story_order")
                if so is not None and float(so) <= story_order:
                    result.append(e)
            return result
        except Exception:
            return []

    def get_stats(self) -> KBStats:
        def count_v(label: str) -> int:
            try:
                r = self._submit_first(f"g.V().hasLabel({self._qval(label)}).count()")
                return int(r) if r is not None else 0
            except Exception:
                return 0

        def count_e(label: str) -> int:
            try:
                r = self._submit_first(f"g.V().outE({self._qval(label)}).count()")
                return int(r) if r is not None else 0
            except Exception:
                return 0

        return KBStats(
            characters=count_v("character"),
            facts=count_v("fact"),
            relationships=count_e("RELATED_TO"),
            events=count_v("event"),
            traits=count_v("trait"),
            locations=count_v("location"),
            items=count_v("item"),
            organizations=count_v("organization"),
            sources=count_v("source"),
            confirmations=count_v("confirmation"),
        )

    def remove_source(self, source_id: str) -> Dict[str, int]:
        """소스 및 연관 vertex/edge 전체 삭제. 파일 삭제는 호출자(main.py)가 담당."""
        removed = {"vertices": 0, "edges": 0}
        try:
            e_cnt = self._submit_first(f"g.V().outE().has('source_id', {self._qval(source_id)}).count()")
            self._submit(f"g.V().outE().has('source_id', {self._qval(source_id)}).drop()")
            removed["edges"] = int(e_cnt) if e_cnt else 0

            v_cnt = self._submit_first(f"g.V().has('source_id', {self._qval(source_id)}).count()")
            self._submit(f"g.V().has('source_id', {self._qval(source_id)}).drop()")
            removed["vertices"] = int(v_cnt) if v_cnt else 0

            logger.info("remove_source complete", source_id=source_id, **removed)
        except Exception as e:
            logger.error("remove_source failed", source_id=source_id, error=str(e))
            raise
        return removed

    def clear_all(self) -> Dict[str, int]:
        """그래프의 모든 vertex와 edge를 삭제합니다."""
        try:
            e_cnt = self._submit_first("g.E().count()") or 0
            v_cnt = self._submit_first("g.V().count()") or 0
            self._submit("g.E().drop()")
            self._submit("g.V().drop()")
            logger.info("clear_all complete", vertices=int(v_cnt), edges=int(e_cnt))
            return {"vertices": int(v_cnt), "edges": int(e_cnt)}
        except Exception as e:
            logger.error("clear_all failed", error=str(e))
            raise

    # ── confirmation.py / version.py 연동 메서드 ──────────────────

    def _normalize_valueMap(self, v: dict) -> dict:
        """Gremlin valueMap(True) 결과를 Pydantic 모델 생성에 쓸 수 있는 flat dict로 변환.

        - list 래핑 해제 (Gremlin은 모든 속성을 list로 반환)
        - T.label / T.id 같은 비문자열 키 → 문자열 변환
        - JSON 문자열로 직렬화된 list/dict 필드 역직렬화
        """
        result: Dict[str, Any] = {}
        for k, val in v.items():
            key = k if isinstance(k, str) else str(k).split(".")[-1]
            scalar = val[0] if isinstance(val, list) and val else val
            if isinstance(scalar, str):
                try:
                    parsed = json.loads(scalar)
                    if isinstance(parsed, (list, dict)):
                        scalar = parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            result[key] = scalar
        return result

    def query_vertices(self, partition_key: str, filters: dict) -> List[Dict]:
        """partition_key(label) + filters 조건으로 vertex 목록 반환."""
        try:
            query = f"g.V().hasLabel({self._qval(partition_key)})"
            for k, v in filters.items():
                query += f".has({self._qval(k)}, {self._qval(v)})"
            query += ".valueMap(true)"
            raw_list = self._submit(query)
            return [self._normalize_valueMap(r) for r in raw_list]
        except Exception as e:
            logger.error("query_vertices_failed", partition_key=partition_key, error=str(e))
            return []

    def get_vertex(self, vertex_id: str, partition_key: str) -> Optional[Dict]:
        """vertex_id + label로 단일 vertex 반환. 없으면 None."""
        try:
            r = self._submit_first(
                f"g.V({self._qval(vertex_id)}).hasLabel({self._qval(partition_key)}).valueMap(true)"
            )
            return self._normalize_valueMap(r) if r else None
        except Exception as e:
            logger.error("get_vertex_failed", vertex_id=vertex_id, error=str(e))
            return None

    def patch_vertex(self, vertex_id: str, partition_key: str, fields: dict) -> None:
        """vertex에 fields를 머지 (속성 개별 업데이트)."""
        try:
            query = f"g.V({self._qval(vertex_id)}).hasLabel({self._qval(partition_key)})"
            query += self._build_props(fields)
            self._submit(query)
            logger.info("patch_vertex_ok", vertex_id=vertex_id, fields=list(fields.keys()))
        except Exception as e:
            logger.error("patch_vertex_failed", vertex_id=vertex_id, error=str(e))
            raise

    def upsert_vertex(self, vertex) -> str:
        """vertex 삽입 또는 업데이트.

        - Pydantic 모델: _vertex_to_dict()로 변환
        - partition_key 속성을 label로 사용
        - id가 이미 존재하면 속성 전체 업데이트, 없으면 addV
        """
        if hasattr(vertex, "model_dump"):
            data = _vertex_to_dict(vertex)
        else:
            data = dict(vertex)

        vid = str(data.get("id") or str(uuid.uuid4()))
        data["id"] = vid
        label = str(data.get("partition_key") or data.get("label") or "")
        if not label:
            raise ValueError(f"upsert_vertex: partition_key/label 누락 (id={vid}, keys={list(data.keys())})")

        try:
            exists = self._submit_first(
                f"g.V({self._qval(vid)}).hasLabel({self._qval(label)}).count()"
            )
            if exists and int(exists) > 0:
                query = f"g.V({self._qval(vid)}).hasLabel({self._qval(label)})"
                query += self._build_props(data, exclude={"id", "partition_key"})
                self._submit(query)
                logger.info("upsert_vertex_updated", vertex_id=vid, label=label)
            else:
                self._add_vertex_generic(label, data, label)
                logger.info("upsert_vertex_added", vertex_id=vid, label=label)
            return vid
        except Exception as e:
            logger.error("upsert_vertex_failed", vertex_id=vid, error=str(e))
            raise

    def rebuild_from_canonical_source(self, canonical_id: str) -> None:
        """canonical source 기준 그래프 재구축.

        SOURCE_CONFLICT 해결 후 비정본(inactive) 소스에 속한 vertex/edge를
        그래프에서 제거하고 canonical source의 데이터만 남긴다.
        """
        try:
            inactive = self._submit("g.V().hasLabel('source').has('status', 'inactive').valueMap(true)")
            removed_v = removed_e = 0
            for src in inactive:
                src_norm = self._normalize_valueMap(src)
                src_id = src_norm.get("id")
                if not src_id or src_id == canonical_id:
                    continue
                e_cnt = self._submit_first(f"g.V().outE().has('source_id', {self._qval(src_id)}).count()") or 0
                self._submit(f"g.V().outE().has('source_id', {self._qval(src_id)}).drop()")
                v_cnt = self._submit_first(f"g.V().has('source_id', {self._qval(src_id)}).count()") or 0
                self._submit(f"g.V().has('source_id', {self._qval(src_id)}).drop()")
                removed_v += int(v_cnt)
                removed_e += int(e_cnt)
            logger.info(
                "rebuild_from_canonical_source_complete",
                canonical_id=canonical_id,
                removed_vertices=removed_v,
                removed_edges=removed_e,
            )
        except Exception as e:
            logger.error("rebuild_from_canonical_source_failed", canonical_id=canonical_id, error=str(e))
            raise

    def resolve_trait_violation(self, trait_id: str, confirmation_id: str) -> None:
        """VIOLATES_TRAIT 엣지에 confirmed_intentional=true 마킹."""
        try:
            query = (
                f"g.V({self._qval(trait_id)}).hasLabel('trait')"
                f".inE('VIOLATES_TRAIT')"
                f".property('confirmed_intentional', true)"
                f".property('confirmation_id', {self._qval(confirmation_id)})"
            )
            self._submit(query)
            logger.info("resolve_trait_violation_ok", trait_id=trait_id, confirmation_id=confirmation_id)
        except Exception as e:
            logger.error("resolve_trait_violation_failed", trait_id=trait_id, error=str(e))
            raise

    def remove_vertices_by_chunk_ids(self, chunk_ids: List[str]) -> int:
        """chunk_id 속성이 chunk_ids에 포함된 vertex 및 연관 edge 삭제."""
        if not chunk_ids:
            return 0
        removed = 0
        try:
            for cid in chunk_ids:
                cnt = self._submit_first(f"g.V().has('chunk_id', {self._qval(cid)}).count()") or 0
                self._submit(f"g.V().outE().has('chunk_id', {self._qval(cid)}).drop()")
                self._submit(f"g.V().has('chunk_id', {self._qval(cid)}).drop()")
                removed += int(cnt)
            logger.info("remove_vertices_by_chunk_ids_ok", removed=removed)
        except Exception as e:
            logger.error("remove_vertices_by_chunk_ids_failed", error=str(e))
            raise
        return removed

    def close(self):
        self.client.close()


# ─────────────────────────────────────────────────────────────
# InMemoryGraphService  (테스트 / 로컬 개발)
# ─────────────────────────────────────────────────────────────

class InMemoryGraphService(_ViolationMixin):
    """GremlinGraphService와 동일 인터페이스의 In-Memory 구현체."""

    def __init__(self, json_path: Optional[str] = None, storage_service: Optional[StorageService] = None):
        self.vertices: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self._discourse_counter: float = 0.0
        self.log = logger.bind(instance_id=str(uuid.uuid4()))
        self.storage = storage_service
        self.log.info("graph_initialized")

        # json_path가 주어지면 자동 로드
        if json_path and os.path.exists(json_path):
            self._load_from_json(json_path)

    # ── 내부 헬퍼 ─────────────────────────────────────────────

    def _add_vertex(self, label: str, data: dict) -> str:
        vid = data.get("id", str(uuid.uuid4()))
        self.vertices[vid] = {"label": label, "id": vid, **_deserialize_vertex_dict(data)}
        return vid

    def _add_edge(self, label: str, from_id: str, to_id: str, data: dict) -> str:
        eid = data.get("id", str(uuid.uuid4()))
        self.edges.append({"label": label, "id": eid, "from_id": from_id, "to_id": to_id, **data})
        return eid

    def _vertices_by_label(self, label: str) -> List[Dict]:
        return [v for v in self.vertices.values() if v.get("label") == label]

    def _edges_by_label(self, label: str) -> List[Dict]:
        return [e for e in self.edges if e.get("label") == label]

    def _get_next_discourse_order(self) -> float:
        self._discourse_counter = round(self._discourse_counter + 0.1, 4)
        return self._discourse_counter

    def _assign_time_axes(self, events: List[Dict]) -> List[Dict]:
        """discourse_order 단조 증가 보장 + 비선형 힌트 기반 story_order 추정.
        GremlinGraphService와 동일 로직 — InMemoryGraphService.materialize()에서 사용."""
        TIME_JUMP_HINTS = [
            "전", "후", "년 전", "일 전", "며칠 후", "그날 밤",
            "그때", "과거에", "회상", "flashback", "그 무렵",
        ]
        result = []
        for ev in events:
            do = self._get_next_discourse_order()
            ev["discourse_order"] = do
            desc = str(ev.get("description", ""))
            if any(hint in desc for hint in TIME_JUMP_HINTS):
                ev["is_linear"] = False
                ev["story_order"] = None
            else:
                ev["is_linear"] = True
                ev["story_order"] = do
            result.append(ev)
        return result

    def _assign_time_axes_text(self, text: str) -> Tuple[float, float, bool]:
        """텍스트 힌트 기반 discourse/story_order 추정 (JSON 인제스트용).
        반환: (discourse_order, story_order, is_linear)
        """
        d = self._get_next_discourse_order()
        if re.search(r"(전|과거|years ago)", text):
            return d, round(d - 1.0, 4), False
        if re.search(r"(후|later|며칠 후)", text):
            return d, round(d + 1.0, 4), False
        return d, d, True

    # ── JSON 로딩 ──────────────────────────────────────────────

    def _load_from_json(self, path: str) -> None:
        """JSON 파일에서 그래프 데이터를 로드한다.

        기대 포맷:
        {
            "characters": [{"name": "...", "source_id": "..."}],
            "facts":      [{"content": "...", "is_true": true, "source_id": "..."}],
            "edges": [
                {"type": "LEARNS", "from": "<vertex_id>", "to": "<vertex_id>", ...}
            ]
        }
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.log.info("json_loaded", path=path)
            self._ingest_json(data)
        except Exception as e:
            self.log.error("json_load_failed", path=path, error=str(e))

    def _ingest_json(self, data: dict) -> None:
        """dict 형태의 그래프 데이터를 In-Memory 그래프에 적재한다."""
        # Characters
        for c in data.get("characters", []):
            name = c.get("name", "")
            d, s, lin = self._assign_time_axes_text(name)
            self.add_character({
                "id": c.get("id"),
                "name": name,
                "tier": c.get("tier", 4),
                "description": c.get("description"),
                "discourse_order": d,
                "story_order": s,
                "is_linear": lin,
                "source_id": c.get("source_id"),
            })

        # Facts
        for f in data.get("facts", []):
            self.add_fact({
                "id": f.get("id"),
                "content": f.get("content"),
                "category": f.get("category", "event_fact"),
                "importance": f.get("importance", "minor"),
                "is_true": f.get("is_true", True),
                "is_secret": f.get("is_secret", False),
                "established_order": self._get_next_discourse_order(),
                "source_location": f.get("source_location", ""),
                "source_id": f.get("source_id"),
            })

        # Edges: "from"/"to" 키를 from_id/to_id로 정규화
        for e in data.get("edges", []):
            label = e.get("type", "UNKNOWN")
            from_id = e.get("from") or e.get("from_id")
            to_id = e.get("to") or e.get("to_id")
            if from_id and to_id:
                props = {k: v for k, v in e.items() if k not in ("type", "from", "to")}
                self._add_edge(label, from_id, to_id, props)

    # ── Vertex CRUD (9종) ─────────────────────────────────────

    def add_character(self, data: dict) -> str:
        return self._add_vertex("character", data)

    def get_character(self, char_id: str) -> Optional[Dict]:
        v = self.vertices.get(char_id)
        return v if v and v.get("label") == "character" else None

    def find_character_by_name(self, name: str) -> Optional[Dict]:
        return next((v for v in self._vertices_by_label("character") if v.get("name") == name), None)

    def list_characters(self) -> List[Dict]:
        return self._vertices_by_label("character")

    def add_fact(self, data: dict) -> str:
        return self._add_vertex("fact", data)

    def get_fact(self, fact_id: str) -> Optional[Dict]:
        v = self.vertices.get(fact_id)
        return v if v and v.get("label") == "fact" else None

    def list_facts(self) -> List[Dict]:
        return self._vertices_by_label("fact")

    def add_event(self, data: dict) -> str:
        return self._add_vertex("event", data)

    def get_event(self, event_id: str) -> Optional[Dict]:
        v = self.vertices.get(event_id)
        return v if v and v.get("label") == "event" else None

    def list_events(self) -> List[Dict]:
        return self._vertices_by_label("event")

    def add_trait(self, data: dict) -> str:
        return self._add_vertex("trait", data)

    def get_trait(self, trait_id: str) -> Optional[Dict]:
        v = self.vertices.get(trait_id)
        return v if v and v.get("label") == "trait" else None

    def list_traits(self) -> List[Dict]:
        return self._vertices_by_label("trait")

    def add_organization(self, data: dict) -> str:
        return self._add_vertex("organization", data)

    def get_organization(self, org_id: str) -> Optional[Dict]:
        v = self.vertices.get(org_id)
        return v if v and v.get("label") == "organization" else None

    def list_organizations(self) -> List[Dict]:
        return self._vertices_by_label("organization")

    def add_location(self, data: dict) -> str:
        return self._add_vertex("location", data)

    def get_location(self, loc_id: str) -> Optional[Dict]:
        v = self.vertices.get(loc_id)
        return v if v and v.get("label") == "location" else None

    def list_locations(self) -> List[Dict]:
        return self._vertices_by_label("location")

    def add_item(self, data: dict) -> str:
        return self._add_vertex("item", data)

    def get_item(self, item_id: str) -> Optional[Dict]:
        v = self.vertices.get(item_id)
        return v if v and v.get("label") == "item" else None

    def list_items(self) -> List[Dict]:
        return self._vertices_by_label("item")

    def add_source(self, data: dict) -> str:
        return self._add_vertex("source", data)

    def get_source(self, source_id: str) -> Optional[Dict]:
        v = self.vertices.get(source_id)
        return v if v and v.get("label") == "source" else None

    def list_sources(self) -> List[Dict]:
        return self._vertices_by_label("source")

    def add_user_confirmation(self, data: dict) -> str:
        return self._add_vertex("confirmation", data)

    def get_user_confirmation(self, conf_id: str) -> Optional[Dict]:
        v = self.vertices.get(conf_id)
        return v if v and v.get("label") == "confirmation" else None

    def list_pending_confirmations(self) -> List[Dict]:
        return [
            v for v in self._vertices_by_label("confirmation")
            if v.get("status") == ConfirmationStatus.PENDING.value
        ]

    # ── Edge 추가 (13종) ──────────────────────────────────────

    def add_learns(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("LEARNS", from_id, to_id, data)

    def add_mentions(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("MENTIONS", from_id, to_id, data)

    def add_participates_in(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("PARTICIPATES_IN", from_id, to_id, data)

    def add_has_status(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("HAS_STATUS", from_id, to_id, data)

    def add_at_location(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("AT_LOCATION", from_id, to_id, data)

    def add_related_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("RELATED_TO", from_id, to_id, data)

    def add_belongs_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("BELONGS_TO", from_id, to_id, data)

    def add_feels(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("FEELS", from_id, to_id, data)

    def add_has_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("HAS_TRAIT", from_id, to_id, data)

    def add_violates_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("VIOLATES_TRAIT", from_id, to_id, data)

    def add_possesses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("POSSESSES", from_id, to_id, data)

    def add_loses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("LOSES", from_id, to_id, data)

    def add_sourced_from(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge("SOURCED_FROM", from_id, to_id, data)

    # ── 계층 3: 적재 ──────────────────────────────────────────

    def materialize(self, normalized: NormalizationResult, source: Source, skip_source_vertex: bool = False) -> Dict[str, List[str]]:
        """NormalizationResult → In-Memory Graph 적재

        Steps:
          0. Source vertex 적재 (skip_source_vertex=True이면 건너뜀 — 증분 재구축 시 이미 존재)
          1. NormalizedCharacter → Character vertex + SOURCED_FROM
          2. NormalizedFact     → KnowledgeFact vertex + SOURCED_FROM (discourse_order 자동 부여)
          3. NormalizedEvent    → Event vertex + SOURCED_FROM
          4. SourceConflict     → UserConfirmation vertex + SOURCED_FROM
          5. Traits             → Trait vertex + HAS_TRAIT edge
          6. Emotions           → FEELS edge (Character → Character)
          7. KnowledgeEvents    → LEARNS / MENTIONS edge (Character → KnowledgeFact)
          8. ItemEvents         → Item vertex + POSSESSES / LOSES edge
          9. Relationships      → RELATED_TO edge (Character → Character)
        """
        source_id = str(source.source_id) if source.source_id else str(source.id)
        created: Dict[str, List[str]] = {
            "source": [], "characters": [], "facts": [], "events": [], "confirmations": [],
            "traits": [], "edges": [],
        }

        # 0. Source vertex 적재 (증분 재구축 시 이미 존재하므로 skip)
        if not skip_source_vertex:
            src_dict = _vertex_to_dict(source)
            # Source vertex의 id와 source_id를 비즈니스 키(source_id)로 통일
            # → get_source(source_id) 조회 및 remove_source(source_id) 삭제 일치
            src_dict["id"] = source_id
            src_dict["source_id"] = source_id
            self.add_source(src_dict)
        created["source"].append(source_id)

        # 1. Character vertices — name→id 맵 구축 (기존 캐릭터 재사용)
        char_name_to_id: Dict[str, str] = {}
        for nc in normalized.characters:
            # 이미 같은 이름의 캐릭터가 그래프에 있으면 재사용 (중복 생성 방지)
            existing = self.find_character_by_name(nc.canonical_name)
            if existing:
                existing_id = existing["id"]
                char_name_to_id[nc.canonical_name] = existing_id
                for alias in nc.all_aliases:
                    char_name_to_id[alias] = existing_id
                continue
            char = Character(
                source_id=source_id,
                name=nc.canonical_name,
                aliases=nc.all_aliases,
                tier=_safe_enum(CharacterTier, nc.tier, CharacterTier.TIER_4),
                description=nc.description,
            )
            char_dict = _vertex_to_dict(char)
            # chunk_id 기록: merged_from의 첫 번째 source_chunk_id
            if nc.merged_from:
                char_dict["chunk_id"] = nc.merged_from[0].source_chunk_id or ""
            self.add_character(char_dict)
            self.add_sourced_from(char_dict["id"], source_id, {
                "source_id": source_id,
                "source_location": "",
                "created_at": char_dict["created_at"],
            })
            created["characters"].append(char_dict["id"])
            char_name_to_id[nc.canonical_name] = char_dict["id"]
            for alias in nc.all_aliases:
                char_name_to_id[alias] = char_dict["id"]

        def _resolve_char(name: str) -> Optional[str]:
            """이름으로 character id를 찾음 (기존 vertex 포함)"""
            if name in char_name_to_id:
                return char_name_to_id[name]
            existing = self.find_character_by_name(name)
            if existing:
                char_name_to_id[name] = existing["id"]
                return existing["id"]
            return None

        # 2. KnowledgeFact vertices (discourse_order 자동 부여) — content→id 맵 구축
        # 기존 fact도 포함해 knowledge_events에서 중복 생성 방지
        fact_content_to_id: Dict[str, str] = {
            v.get("content"): v.get("id")
            for v in self._vertices_by_label("fact")
            if v.get("content") and v.get("id")
        }
        for nf in normalized.facts:
            if nf.content in fact_content_to_id:
                continue
            do = self._get_next_discourse_order()
            fact = KnowledgeFact(
                source_id=source_id,
                content=nf.content,
                category=_safe_enum(FactCategory, nf.category, FactCategory.EVENT_FACT),
                importance=_safe_enum(FactImportance, nf.importance, FactImportance.MINOR),
                is_secret=nf.is_secret,
                is_true=nf.is_true,
                established_order=do,
                source_location="",
            )
            fact_dict = _vertex_to_dict(fact)
            # chunk_id 기록
            if nf.merged_from:
                fact_dict["chunk_id"] = nf.merged_from[0].source_chunk_id or ""
            self.add_fact(fact_dict)
            self.add_sourced_from(fact_dict["id"], source_id, {
                "source_id": source_id,
                "source_location": "",
                "created_at": fact_dict["created_at"],
            })
            created["facts"].append(fact_dict["id"])
            fact_content_to_id[nf.content] = fact_dict["id"]

        # 3. Event vertices (discourse_order/story_order 자동 부여)
        # NormalizedEvent의 characters_involved를 raw_event_dicts에 포함
        _DEATH_KW = ["사망", "죽", "숨졌", "시체", "피살", "살해", "사망한 상태", "암살", "익사", "사고사", "전사", "처형", "사형", "사망 처리", "사망 판정", "사망자 등록", "사사"]
        raw_event_dicts = [
            {
                "description": ne.description,
                "event_type": ne.event_type,
                "location": ne.location,
                "status_char": ne.status_char,
                "characters_involved": ne.characters_involved,
                "chunk_id": ne.merged_from[0].source_chunk_id if ne.merged_from else "",
            }
            for ne in normalized.events
        ]
        for ev_data in self._assign_time_axes(raw_event_dicts):
            event = Event(
                source_id=source_id,
                discourse_order=ev_data["discourse_order"],
                story_order=ev_data.get("story_order"),
                is_linear=ev_data.get("is_linear", True),
                event_type=_safe_enum(EventType, ev_data.get("event_type", "scene"), EventType.SCENE),
                description=ev_data["description"],
                location=ev_data.get("location"),
                source_location="",
            )
            event_dict = _vertex_to_dict(event)
            # Event 모델에 없는 characters_involved를 dict에 직접 추가 (resurrection 탐지용)
            event_dict["characters_involved"] = ev_data.get("characters_involved") or []
            event_dict["chunk_id"] = ev_data.get("chunk_id") or ""
            self.add_event(event_dict)
            self.add_sourced_from(event_dict["id"], source_id, {
                "source_id": source_id,
                "source_location": "",
                "created_at": event_dict["created_at"],
            })
            created["events"].append(event_dict["id"])

            # death 이벤트 → HAS_STATUS dead 엣지 자동 생성 (타임라인 모순 탐지용)
            # event_type=="death" 이거나 status_char가 설정된 경우 모두 처리 (LLM이 death 대신 다른 타입 쓸 수 있음)
            _is_death = (
                event_dict.get("event_type") == "death"
                or (ev_data.get("status_char") and any(
                    kw in event_dict.get("description", "")
                    for kw in _DEATH_KW
                ))
            )
            if _is_death:
                status_char = ev_data.get("status_char")
                char_id = None
                if status_char:
                    existing = self.find_character_by_name(status_char)
                    char_id = existing["id"] if existing else None
                if char_id:
                    self.add_has_status(char_id, event_dict["id"], {
                        "status_type": "dead",
                        "status_value": "사망",
                        "story_order": event_dict.get("story_order") or event_dict.get("discourse_order"),
                        "source_id": source_id,
                        "source_location": "",
                        "created_at": event_dict["created_at"],
                    })
                    created["edges"].append(f"status-dead-{char_id}")

        # 3b. 사망 관련 Facts → HAS_STATUS dead 엣지 생성
        # LLM이 death event 대신 fact로 추출하는 경우 대응 (예: "박영호는 사망한 상태로 발견됨")
        for nf in normalized.facts:
            content = nf.content
            if not any(kw in content for kw in _DEATH_KW):
                continue
            for nc in normalized.characters:
                names_to_check = [nc.canonical_name] + list(nc.all_aliases)
                if not any(n in content for n in names_to_check):
                    continue
                char_id_for_death = char_name_to_id.get(nc.canonical_name)
                if not char_id_for_death:
                    continue
                do_death = self._get_next_discourse_order()
                # 설정집/세계관의 사망 사실은 시나리오 이전 상태 → story_order=0.0
                death_so = 0.0
                death_event = Event(
                    source_id=source_id,
                    discourse_order=do_death,
                    story_order=death_so,
                    is_linear=True,
                    event_type=_safe_enum(EventType, "death", EventType.SCENE),
                    description=content,
                    location=None,
                    source_location="",
                )
                death_dict = _vertex_to_dict(death_event)
                death_dict["characters_involved"] = [nc.canonical_name]
                self.add_event(death_dict)
                self.add_has_status(char_id_for_death, death_dict["id"], {
                    "status_type": "dead",
                    "status_value": "사망",
                    "story_order": death_so,
                    "source_id": source_id,
                    "source_location": "",
                    "created_at": death_dict["created_at"],
                })
                created["edges"].append(f"status-dead-fact-{char_id_for_death}")
                break  # 캐릭터당 1번만

        # 4. SourceConflict → UserConfirmation vertices
        for conflict in normalized.source_conflicts:
            excerpts = [
                SourceExcerpt(
                    source_name=d.source_id,
                    source_location="",
                    text=d.text,
                )
                for d in conflict.descriptions
            ]
            conf = UserConfirmation(
                source_id=source_id,
                confirmation_type=ConfirmationType.SOURCE_CONFLICT,
                status=ConfirmationStatus.PENDING,
                question=(
                    f"소스 충돌: '{conflict.entity_type}'의 정본을 선택하세요."
                ),
                context_summary=f"충돌 값: {', '.join(conflict.conflicting_values)}",
                source_excerpts=excerpts,
                related_entity_ids=[],
            )
            conf_dict = _vertex_to_dict(conf)
            self.add_user_confirmation(conf_dict)
            self.add_sourced_from(conf_dict["id"], source_id, {
                "source_id": source_id,
                "source_location": "",
                "created_at": conf_dict["created_at"],
            })
            created["confirmations"].append(conf_dict["id"])

        # 5. Traits → Trait vertex + HAS_TRAIT edge
        _IMMUTABLE_HINTS = ["절대", "극혐", "일절", "혐오", "불변", "태생", "선천", "혈액형", "입에 대지"]
        for rt in normalized.traits:
            char_id = _resolve_char(rt.character_name)
            if not char_id:
                continue
            combined = f"{rt.key} {rt.value}"
            is_imm = any(h in combined for h in _IMMUTABLE_HINTS)
            trait_data = {
                "id": str(uuid.uuid4()),
                "source_id": source_id,
                "category": rt.category_hint or "personality",
                "key": rt.key,
                "value": rt.value,
                "description": rt.value,
                "is_immutable": is_imm,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "label": "trait",
            }
            self.add_trait(trait_data)
            edge_id = self.add_has_trait(char_id, trait_data["id"], {
                "source_id": source_id,
                "source_location": "",
                "created_at": trait_data["created_at"],
            })
            created["traits"].append(trait_data["id"])
            created["edges"].append(edge_id)

        # 6. Emotions → FEELS edge (Character → Character)
        for re_ in normalized.emotions:
            from_id = _resolve_char(re_.from_char)
            to_id = _resolve_char(re_.to_char)
            if not from_id or not to_id:
                continue
            do = self._get_next_discourse_order()
            edge_id = self.add_feels(from_id, to_id, {
                "source_id": source_id,
                "source_location": "",
                "emotion": re_.emotion,
                "intensity": 0.5,
                "discourse_order": do,
                "story_order": do,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            created["edges"].append(edge_id)

        # 7. KnowledgeEvents → LEARNS / MENTIONS edge (Character → KnowledgeFact)
        for ke in normalized.knowledge_events:
            char_id = _resolve_char(ke.character_name)
            if not char_id:
                continue
            # 1) 정확히 일치하는 fact 검색
            fact_id = fact_content_to_id.get(ke.fact_content)
            # 2) 없으면 bi-gram 유사도로 기존 fact 매칭 (정보 비대칭 탐지 핵심)
            if not fact_id:
                fact_id = _find_similar_fact(ke.fact_content, fact_content_to_id)
            # 3) 매칭 실패 → 새 fact vertex 생성
            if not fact_id:
                do = self._get_next_discourse_order()
                fact = KnowledgeFact(
                    source_id=source_id,
                    content=ke.fact_content,
                    category=_safe_enum(FactCategory, None, FactCategory.EVENT_FACT),
                    importance=_safe_enum(FactImportance, None, FactImportance.MINOR),
                    is_secret=False,
                    is_true=True,
                    established_order=do,
                    source_location="",
                )
                fact_dict = _vertex_to_dict(fact)
                self.add_fact(fact_dict)
                fact_id = fact_dict["id"]
                fact_content_to_id[ke.fact_content] = fact_id
                created["facts"].append(fact_id)

            do = self._get_next_discourse_order()
            edge_data = {
                "source_id": source_id,
                "source_location": "",
                "discourse_order": do,
                "story_order": do,
                "believed_true": True,
                "method": ke.method or "unknown",
                "via_character": ke.via_character or "",
                "dialogue_text": ke.dialogue_text or "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if ke.event_type == "learns":
                edge_id = self.add_learns(char_id, fact_id, edge_data)
            else:
                edge_id = self.add_mentions(char_id, fact_id, edge_data)
            created["edges"].append(edge_id)

        # 8. ItemEvents → Item vertex + POSSESSES / LOSES edge
        item_name_to_id: Dict[str, str] = {}
        for ie in normalized.item_events:
            char_id = _resolve_char(ie.character_name)
            if not char_id:
                continue
            # item vertex 조회 또는 생성
            item_id = item_name_to_id.get(ie.item_name)
            if not item_id:
                existing_items = [
                    v for v in self._vertices_by_label("item")
                    if v.get("name") == ie.item_name
                ]
                if existing_items:
                    item_id = existing_items[0]["id"]
                else:
                    item_data = {
                        "id": str(uuid.uuid4()),
                        "source_id": source_id,
                        "name": ie.item_name,
                        "is_unique": False,
                        "description": ie.item_name,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "label": "item",
                    }
                    self.add_item(item_data)
                    item_id = item_data["id"]
                item_name_to_id[ie.item_name] = item_id

            do = self._get_next_discourse_order()
            edge_data = {
                "source_id": source_id,
                "source_location": "",
                "discourse_order": do,
                "story_order": do,
                "method": "transfer",
                "possession_type": "owns",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if ie.action == "possesses":
                edge_id = self.add_possesses(char_id, item_id, edge_data)
            elif ie.action == "loses":
                edge_id = self.add_loses(char_id, item_id, edge_data)
            else:
                edge_id = self.add_possesses(char_id, item_id, edge_data)
            created["edges"].append(edge_id)

        # 9. Relationships → RELATED_TO edge (Character → Character)
        for rr in normalized.relationships:
            from_id = _resolve_char(rr.char_a)
            to_id = _resolve_char(rr.char_b)
            if not from_id or not to_id:
                continue
            do = self._get_next_discourse_order()
            edge_id = self.add_related_to(from_id, to_id, {
                "source_id": source_id,
                "source_location": "",
                "relationship_type": _normalize_relationship_type(rr.type_hint or "colleague"),
                "detail": rr.detail or "",
                "established_order": do,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            created["edges"].append(edge_id)

        # 10. Fact에서 아이템 유일성 힌트 추출 → is_unique 업데이트
        _UNIQUE_KW = ["하나뿐", "유일", "단 하나", "오직 하나", "1개뿐", "한 개뿐"]
        for item_v in self._vertices_by_label("item"):
            if item_v.get("is_unique") in (True, "True", "true", 1):
                continue
            iname = item_v.get("name", "")
            for fact_v in self._vertices_by_label("fact"):
                fc = fact_v.get("content", "")
                if iname and iname in fc and any(kw in fc for kw in _UNIQUE_KW):
                    item_v["is_unique"] = True
                    break

        self.log.info("materialize_complete", **{k: len(v) for k, v in created.items()})
        return created

    # ── 7가지 모순 탐지 쿼리 ──────────────────────────────────

    def snapshot_graph(self, relevant_ids: Optional[List[str]] = None) -> "InMemoryGraphService":
        """자신의 딥카피 반환 (원본 불변 보장)"""
        snap = InMemoryGraphService()
        if relevant_ids:
            id_set = set(relevant_ids)
            snap.vertices = {k: copy.deepcopy(v) for k, v in self.vertices.items() if k in id_set}
            snap.edges = [
                copy.deepcopy(e) for e in self.edges
                if e.get("from_id") in id_set or e.get("to_id") in id_set
            ]
        else:
            snap.vertices = copy.deepcopy(self.vertices)
            snap.edges = copy.deepcopy(self.edges)
        snap._discourse_counter = self._discourse_counter
        return snap

    def get_character_knowledge_at(self, character_id: str, story_order: float) -> List[Dict]:
        return [
            e for e in self._edges_by_label("LEARNS")
            if e.get("from_id") == character_id
            and e.get("story_order") is not None
            and float(e["story_order"]) <= story_order
        ]

    def get_stats(self) -> KBStats:
        return KBStats(
            characters=len(self._vertices_by_label("character")),
            facts=len(self._vertices_by_label("fact")),
            relationships=len(self._edges_by_label("RELATED_TO")),
            events=len(self._vertices_by_label("event")),
            traits=len(self._vertices_by_label("trait")),
            locations=len(self._vertices_by_label("location")),
            items=len(self._vertices_by_label("item")),
            organizations=len(self._vertices_by_label("organization")),
            sources=len(self._vertices_by_label("source")),
            confirmations=len(self._vertices_by_label("confirmation")),
        )

    def remove_source(self, source_id: str) -> Dict[str, int]:
        """소스 및 연관 vertex/edge 전체 삭제. 파일 삭제는 호출자(main.py)가 담당."""
        orig_v, orig_e = len(self.vertices), len(self.edges)
        self.vertices = {k: v for k, v in self.vertices.items() if v.get("source_id") != source_id}
        remaining = set(self.vertices.keys())
        self.edges = [
            e for e in self.edges
            if e.get("source_id") != source_id
            and e.get("from_id") in remaining
            and e.get("to_id") in remaining
        ]
        removed = {"vertices": orig_v - len(self.vertices), "edges": orig_e - len(self.edges)}
        self.log.info("remove_source complete", source_id=source_id, **removed)
        return removed

    def clear_all(self) -> Dict[str, int]:
        """그래프의 모든 vertex와 edge를 삭제합니다."""
        v_cnt, e_cnt = len(self.vertices), len(self.edges)
        self.vertices.clear()
        self.edges.clear()
        self._discourse_counter = 0.0
        self.log.info("clear_all complete", vertices=v_cnt, edges=e_cnt)
        return {"vertices": v_cnt, "edges": e_cnt}

    # ── confirmation.py / version.py 연동 메서드 ─────────────────

    def query_vertices(self, partition_key: str, filters: dict) -> List[Dict]:
        """partition_key(label) + filters 조건으로 vertex 목록 반환."""
        result = [
            v for v in self._vertices_by_label(partition_key)
            if all(v.get(k) == val for k, val in filters.items())
        ]
        self.log.debug("query_vertices", partition_key=partition_key, count=len(result))
        return result

    def get_vertex(self, vertex_id: str, partition_key: str) -> Optional[Dict]:
        """vertex_id로 단일 vertex 반환. 없으면 None."""
        v = self.vertices.get(vertex_id)
        if v is None or v.get("label") != partition_key:
            return None
        return v

    def patch_vertex(self, vertex_id: str, partition_key: str, fields: dict) -> None:
        """vertex에 fields를 머지. vertex가 없으면 경고만 기록."""
        v = self.vertices.get(vertex_id)
        if v is None:
            self.log.warning("patch_vertex_not_found", vertex_id=vertex_id)
            return
        v.update(fields)
        self.log.debug("patch_vertex", vertex_id=vertex_id, fields=list(fields.keys()))

    def upsert_vertex(self, vertex) -> str:
        """id 있으면 업데이트, 없으면 신규 추가. vertex id를 반환."""
        # Pydantic 모델은 _vertex_to_dict()로 변환해 @property partition_key 포함
        if hasattr(vertex, "model_dump"):
            data = _vertex_to_dict(vertex)
        else:
            data = dict(vertex)
        vid = str(data.get("id") or str(uuid.uuid4()))
        data["id"] = vid
        # InMemory는 JSON 문자열 불필요 — 실제 Python 객체로 역직렬화해 보관
        data = _deserialize_vertex_dict(data)
        if vid in self.vertices:
            self.vertices[vid].update(data)
            self.log.debug("upsert_vertex_updated", vertex_id=vid)
        else:
            label = data.get("partition_key") or data.get("label") or ""
            if not label:
                raise ValueError(f"upsert_vertex: partition_key/label 누락 (id={vid}, keys={list(data.keys())})")
            self.vertices[vid] = {"label": label, **data}
            self.log.debug("upsert_vertex_inserted", vertex_id=vid)
        return vid

    def rebuild_from_canonical_source(self, canonical_id: str) -> None:
        """canonical source 기준 그래프 재구축.

        status='inactive'인 소스에 속한 vertex/edge를 제거해
        canonical source 데이터만 남긴다.
        """
        inactive_source_ids = {
            v["id"] for v in self._vertices_by_label("source")
            if v.get("status") == "inactive" and v.get("id") != canonical_id
        }
        if not inactive_source_ids:
            self.log.info("rebuild_from_canonical_source_nothing_to_remove", canonical_id=canonical_id)
            return
        to_remove = [
            vid for vid, v in self.vertices.items()
            if v.get("source_id") in inactive_source_ids
        ]
        for vid in to_remove:
            del self.vertices[vid]
        remaining = set(self.vertices.keys())
        before = len(self.edges)
        self.edges = [
            e for e in self.edges
            if e.get("source_id") not in inactive_source_ids
            and e.get("from_id") in remaining
            and e.get("to_id") in remaining
        ]
        self.log.info(
            "rebuild_from_canonical_source_complete",
            canonical_id=canonical_id,
            removed_vertices=len(to_remove),
            removed_edges=before - len(self.edges),
        )

    def resolve_trait_violation(self, trait_id: str, confirmation_id: str) -> None:
        """VIOLATES_TRAIT 엣지에 confirmed_intentional=True 마킹."""
        updated = 0
        for edge in self.edges:
            if edge.get("label") == "VIOLATES_TRAIT" and edge.get("to_id") == trait_id:
                edge["confirmed_intentional"] = True
                edge["confirmation_id"] = confirmation_id
                updated += 1
        self.log.info("resolve_trait_violation_ok", trait_id=trait_id, updated_edges=updated)

    def remove_vertices_by_chunk_ids(self, chunk_ids: List[str]) -> int:
        """chunk_id 필드가 chunk_ids에 포함된 vertex를 삭제하고 삭제 수 반환."""
        chunk_id_set = set(chunk_ids)
        to_remove = [
            vid for vid, v in self.vertices.items()
            if v.get("chunk_id") in chunk_id_set
        ]
        for vid in to_remove:
            del self.vertices[vid]
        # 삭제된 vertex를 참조하는 edge도 정리
        remaining = set(self.vertices.keys())
        before_edges = len(self.edges)
        self.edges = [
            e for e in self.edges
            if e.get("from_id") in remaining and e.get("to_id") in remaining
        ]
        self.log.info(
            "remove_vertices_by_chunk_ids",
            removed_vertices=len(to_remove),
            removed_edges=before_edges - len(self.edges),
        )
        return len(to_remove)


# ─────────────────────────────────────────────────────────────
# 팩토리 함수 (싱글턴)
# ─────────────────────────────────────────────────────────────

_graph_service_instance: Optional[Any] = None


def get_graph_service(json_path: Optional[str] = None):
    """그래프 서비스 싱글턴을 반환하는 팩토리.

    USE_LOCAL_GRAPH=true  → InMemoryGraphService (로컬 개발/데모)
    USE_LOCAL_GRAPH=false → GremlinGraphService  (Azure Cosmos DB)

    동일 프로세스 내에서는 같은 인스턴스를 반환하여 상태를 유지한다.
    """
    global _graph_service_instance
    if _graph_service_instance is not None:
        return _graph_service_instance

    if settings.use_local_graph:
        _graph_service_instance = InMemoryGraphService(
            json_path=json_path or DEFAULT_JSON_PATH
        )
        logger.info("graph_service_created", backend="InMemory")
    else:
        try:
            _graph_service_instance = GremlinGraphService(
                endpoint=settings.cosmos_endpoint,
                key=settings.cosmos_key,
                database=settings.cosmos_database,
                container=settings.cosmos_container,
            )
            logger.info(
                "graph_service_created",
                backend="Gremlin",
                endpoint=settings.cosmos_endpoint,
                database=settings.cosmos_database,
                container=settings.cosmos_container,
            )
        except Exception as e:
            logger.error(
                "gremlin_connection_failed",
                error=str(e),
                fallback="InMemory",
            )
            _graph_service_instance = InMemoryGraphService(
                json_path=json_path or DEFAULT_JSON_PATH
            )

    return _graph_service_instance


def reset_graph_service() -> None:
    """테스트 등에서 싱글턴을 초기화할 때 사용."""
    global _graph_service_instance
    _graph_service_instance = None
