"""Gold Standard 데이터셋 정의.

각 테스트 케이스에 대해 전문가가 수동 annotation한 정답 데이터.
모든 평가의 기반이 되는 기준 데이터입니다.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict


# ── 모순 유형 (7종) ──────────────────────────────────────────────

class ContradictionCategory(str, Enum):
    PHYSICS_RULE = "물리/규칙 위반"
    TRAIT_SETTING = "설정/성격 모순"
    INFO_ASYMMETRY = "정보 비대칭"
    TIMELINE_MOVE = "타임라인/이동"
    SECURITY_ITEM = "보안/소유 이력"
    DEATH_REAPPEAR = "사망 후 재등장"
    OTHER = "기타(관계/문서)"


class HardSoft(str, Enum):
    HARD = "hard"
    SOFT = "soft"


# ── Gold 엔티티 ──────────────────────────────────────────────────

@dataclass
class GoldCharacter:
    """Extraction gold: 등장 캐릭터"""
    canonical_name: str
    aliases: List[str] = field(default_factory=list)
    role: str = ""


@dataclass
class GoldFact:
    """Extraction gold: 세계 규칙/사실"""
    content: str
    is_trait: bool = False  # True면 Trait, False면 Fact
    category: str = ""


@dataclass
class GoldRelationship:
    """Extraction gold: 캐릭터 관계"""
    char_a: str
    char_b: str
    type_hint: str  # enum 값 (family_parent, colleague 등)
    detail: str = ""


@dataclass
class GoldContradiction:
    """Detection gold: 의도적으로 삽입한 모순 1건"""
    id: str
    category: ContradictionCategory
    hard_soft: HardSoft
    description: str
    characters_involved: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)  # 매칭용 키워드
    evidence_summary: str = ""


@dataclass
class GoldIntentionalDevice:
    """False Positive 검증용: 의도적 장치 (모순이 아닌 것)"""
    id: str
    device_type: str  # foreshadowing, flashback, unreliable_narrator, character_growth 등
    description: str
    keywords: List[str] = field(default_factory=list)


@dataclass
class GoldTestCase:
    """하나의 테스트 시나리오에 대한 전체 Gold Standard"""
    name: str
    prefix: str  # 파일명 접미사
    genre: str  # 장르 (SF, 판타지, 추리 등)

    # 계층1 Gold (Extraction)
    characters: List[GoldCharacter] = field(default_factory=list)
    facts: List[GoldFact] = field(default_factory=list)
    relationships: List[GoldRelationship] = field(default_factory=list)

    # 계층4 Gold (Detection) — 핵심
    contradictions: List[GoldContradiction] = field(default_factory=list)
    intentional_devices: List[GoldIntentionalDevice] = field(default_factory=list)

    @property
    def total_contradictions(self) -> int:
        return len(self.contradictions)

    @property
    def hard_count(self) -> int:
        return sum(1 for c in self.contradictions if c.hard_soft == HardSoft.HARD)

    @property
    def soft_count(self) -> int:
        return sum(1 for c in self.contradictions if c.hard_soft == HardSoft.SOFT)

    def by_category(self) -> Dict[ContradictionCategory, List[GoldContradiction]]:
        result: Dict[ContradictionCategory, List[GoldContradiction]] = {}
        for c in self.contradictions:
            result.setdefault(c.category, []).append(c)
        return result


# ═══════════════════════════════════════════════════════════════════
# GOLD STANDARD 데이터셋 — Variation Pack 5종
# ═══════════════════════════════════════════════════════════════════

GOLD_CASES: List[GoldTestCase] = [

    # ── 1. 화성기지_적색폭풍 ──────────────────────────────────────
    GoldTestCase(
        name="화성기지_적색폭풍",
        prefix="화성기지_적색폭풍",
        genre="SF",
        characters=[
            GoldCharacter("윤하늘", role="기지 사령관"),
            GoldCharacter("한도윤", role="보안 책임자"),
            GoldCharacter("민세라", role="식물학자"),
            GoldCharacter("K-7", role="지원 봇"),
        ],
        facts=[
            GoldFact("외부 구역(EVA 존)은 우주복 없이는 30초 이상 생존할 수 없다", category="world_fact"),
            GoldFact("핵심 반응로 접근은 이중 생체인증 잠금, 기지 사령관만 인증 키 보유", category="world_fact"),
            GoldFact("23:00~05:00 비상 절전 모드, 본관↔핵심실 방화벽 자동 봉인", category="world_fact"),
            GoldFact("A동↔C동 터널 도보 12분 소요", category="world_fact"),
            GoldFact("야간 로버 운행 금지, 도보만 가능", category="world_fact"),
        ],
        relationships=[],
        contradictions=[
            GoldContradiction("M1-1", ContradictionCategory.PHYSICS_RULE, HardSoft.SOFT,
                "EVA 우주복 없이 외부 활동 규칙 위반",
                ["한도윤"], ["우주복", "EVA", "생존", "외부"]),
            GoldContradiction("M1-2", ContradictionCategory.TRAIT_SETTING, HardSoft.SOFT,
                "한도윤: 카페인 일절 섭취 안 함 → 더블 에스프레소 음용",
                ["한도윤"], ["카페인", "에스프레소", "커피", "마시"]),
            GoldContradiction("M1-3", ContradictionCategory.TRAIT_SETTING, HardSoft.SOFT,
                "윤하늘: 로그 조작 절대 안 함 — 관련 특성 위반",
                ["윤하늘"], ["로그", "조작", "기록"]),
            GoldContradiction("M1-4", ContradictionCategory.INFO_ASYMMETRY, HardSoft.SOFT,
                "한도윤이 로그 확인 전에 코드 변경 사실을 알고 있음",
                ["한도윤"], ["로그", "코드", "알고", "직감"]),
            GoldContradiction("M1-5", ContradictionCategory.TIMELINE_MOVE, HardSoft.SOFT,
                "A동→C동 12분 규칙 vs 2분 이동 주장",
                ["한도윤"], ["12분", "2분", "분"]),
            GoldContradiction("M1-6", ContradictionCategory.SECURITY_ITEM, HardSoft.SOFT,
                "23시 이후 방화벽 봉인 규칙 위반 (방화벽 열림) + 생체인증 키 위반",
                ["한도윤"], ["방화벽", "봉인", "생체", "인증", "키"]),
            GoldContradiction("M1-7", ContradictionCategory.DEATH_REAPPEAR, HardSoft.HARD,
                "민세라 3시간 전 사고 사망 → 온실에서 재등장",
                ["민세라"], ["민세라", "사망", "사고"]),
        ],
    ),

    # ── 2. 마도학원_은빛봉인 ──────────────────────────────────────
    GoldTestCase(
        name="마도학원_은빛봉인",
        prefix="마도학원_은빛봉인",
        genre="판타지",
        characters=[
            GoldCharacter("리안", role="신입 마법사"),
            GoldCharacter("세린", role="사서"),
            GoldCharacter("마엘", role="연금술 교수"),
            GoldCharacter("도윤", role="학생회장"),
        ],
        facts=[
            GoldFact("학원 내부 공간이동 마법(텔레포트) 완전 봉인", category="world_fact"),
            GoldFact("21:00 이후 봉인문 잠김, 문장 열쇠는 단 하나", category="world_fact"),
            GoldFact("중앙도서관→천문탑 도보 20분", category="world_fact"),
            GoldFact("철학자의 돌 없이 완전한 부활 불가능", category="world_fact"),
        ],
        relationships=[
            GoldRelationship("세린", "리안", "family_parent", "어머니"),
            GoldRelationship("세린", "리안", "family_sibling", "남매"),
        ],
        contradictions=[
            GoldContradiction("M2-1", ContradictionCategory.PHYSICS_RULE, HardSoft.SOFT,
                "텔레포트 봉인 규칙 위반: 리안이 마법진으로 순간이동",
                ["리안"], ["텔레포트", "봉인", "마법진", "순간이동", "공간이동"]),
            GoldContradiction("M2-2", ContradictionCategory.TRAIT_SETTING, HardSoft.SOFT,
                "리안: 마나 포션 극혐 절대 안 마심 → 포션 음용",
                ["리안"], ["마나", "포션", "마시", "싫어"]),
            GoldContradiction("M2-3", ContradictionCategory.INFO_ASYMMETRY, HardSoft.SOFT,
                "도윤이 20시 전에 세린의 열쇠 분실을 알고 있음 (세린은 21:10 인지)",
                ["도윤", "세린"], ["열쇠", "분실", "20시", "알고"]),
            GoldContradiction("M2-4", ContradictionCategory.TIMELINE_MOVE, HardSoft.SOFT,
                "중앙도서관→천문탑 20분 규칙 vs 1분 이동",
                ["리안"], ["20분", "1분", "분"]),
            GoldContradiction("M2-5", ContradictionCategory.SECURITY_ITEM, HardSoft.SOFT,
                "문장 열쇠 단 하나 규칙 위반: 세린 착용 + 리안이 다른 열쇠 발견",
                ["세린", "리안"], ["열쇠", "하나", "유일"]),
            GoldContradiction("M2-6", ContradictionCategory.DEATH_REAPPEAR, HardSoft.SOFT,
                "마엘 교수 2년 전 사망 판정 → 어제 밤 금서 봉인 해제 활동",
                ["마엘"], ["마엘", "사망", "죽"]),
            GoldContradiction("M2-7", ContradictionCategory.OTHER, HardSoft.HARD,
                "세린↔리안: 어머니+남매 관계 동시 — 상충",
                ["세린", "리안"], ["어머니", "남매", "family_parent", "family_sibling"]),
        ],
    ),

    # ── 3. 사이버시티_네온추적 ────────────────────────────────────
    GoldTestCase(
        name="사이버시티_네온추적",
        prefix="사이버시티_네온추적",
        genre="사이버펑크",
        characters=[
            GoldCharacter("진서", role="형사"),
            GoldCharacter("루크", role="해커"),
            GoldCharacter("미나", role="목격자"),
            GoldCharacter("태오", role="기업 보안관"),
        ],
        facts=[
            GoldFact("Q-pass는 개인 바이오서명 결합, 양도 불가", category="world_fact"),
            GoldFact("00:00~04:00 시 전역 네트워크 블랙아웃, 외부 통신 차단", category="world_fact"),
            GoldFact("알파→델타 도보 18분", category="world_fact"),
            GoldFact("총기 발사는 드론 로그에 즉시 기록, 건수 위조 불가능", category="world_fact"),
        ],
        relationships=[
            GoldRelationship("진서", "태오", "colleague", "전 동료"),
            GoldRelationship("진서", "태오", "enemy", "적"),
        ],
        contradictions=[
            GoldContradiction("M3-1", ContradictionCategory.PHYSICS_RULE, HardSoft.SOFT,
                "00:00~04:00 블랙아웃 중 본부와 영상통화 성공",
                ["진서"], ["블랙아웃", "통신", "영상통화", "화상"]),
            GoldContradiction("M3-2", ContradictionCategory.TRAIT_SETTING, HardSoft.SOFT,
                "진서: 신경 임플란트 사용 불가(과민반응) → 임플란트 부스트 사용",
                ["진서"], ["임플란트", "신경", "사용 불가", "과민"]),
            GoldContradiction("M3-3", ContradictionCategory.INFO_ASYMMETRY, HardSoft.SOFT,
                "진서가 드론 로그 확인 전에 총성 3발 사실을 알고 있음",
                ["진서"], ["드론", "로그", "총성", "3발", "알고"]),
            GoldContradiction("M3-4", ContradictionCategory.TIMELINE_MOVE, HardSoft.SOFT,
                "알파→델타 18분 규칙 vs 5분 이동",
                ["진서"], ["18분", "5분", "분"]),
            GoldContradiction("M3-5", ContradictionCategory.SECURITY_ITEM, HardSoft.SOFT,
                "Q-pass 양도 불가 규칙 위반: 소매치기 후 타인이 사용",
                ["루크"], ["Q-pass", "양도", "소매치기", "바이오"]),
            GoldContradiction("M3-6", ContradictionCategory.DEATH_REAPPEAR, HardSoft.HARD,
                "미나 이틀 전 사망 처리 → 임시 진료소에서 증언",
                ["미나"], ["미나", "사망", "사망자"]),
            GoldContradiction("M3-7", ContradictionCategory.OTHER, HardSoft.SOFT,
                "진서↔태오: 동료+적 관계 동시 — 상충",
                ["진서", "태오"], ["동료", "적", "colleague", "enemy"]),
        ],
    ),

    # ── 4. 조선궁중_비단암호 ──────────────────────────────────────
    GoldTestCase(
        name="조선궁중_비단암호",
        prefix="조선궁중_비단암호",
        genre="사극",
        characters=[
            GoldCharacter("이겸", role="암행어사"),
            GoldCharacter("연화", role="궁녀"),
            GoldCharacter("한명진", role="전 영의정"),
            GoldCharacter("정우", role="야경꾼"),
        ],
        facts=[
            GoldFact("자시(23:00) 이후 내문 봉쇄, 통과에 어명패 필요", category="world_fact"),
            GoldFact("경복전→비밀정자 도보 25분", category="world_fact"),
            GoldFact("국새/어새 찍힌 원본만 법적 효력", category="world_fact"),
            GoldFact("사사된 인물은 복권 전까지 공식 사망 상태", category="world_fact"),
            GoldFact("내의원 약재고 야간 2중 봉인, 관리자 외 출입 불가", category="world_fact"),
        ],
        relationships=[
            GoldRelationship("연화", "이겸", "family_parent", "어머니"),
            GoldRelationship("연화", "이겸", "family_sibling", "남매"),
        ],
        contradictions=[
            GoldContradiction("M4-1", ContradictionCategory.PHYSICS_RULE, HardSoft.SOFT,
                "내의원 약재고 야간 봉인 규칙 위반",
                ["이겸", "연화"], ["약재고", "봉인", "내의원"]),
            GoldContradiction("M4-2", ContradictionCategory.TRAIT_SETTING, HardSoft.SOFT,
                "이겸: 술을 입에 대지 않음 → 막걸리 두 사발 비움",
                ["이겸"], ["술", "막걸리", "마시", "입에 대지"]),
            GoldContradiction("M4-3", ContradictionCategory.INFO_ASYMMETRY, HardSoft.SOFT,
                "이겸이 22시에 이미 연화 어명패 분실을 알고 있음 (연화는 23:14 인지)",
                ["이겸", "연화"], ["어명패", "분실", "22시", "알고"]),
            GoldContradiction("M4-4", ContradictionCategory.TIMELINE_MOVE, HardSoft.SOFT,
                "경복전→비밀정자 25분 규칙 vs 7분 이동",
                ["이겸"], ["25분", "7분", "분"]),
            GoldContradiction("M4-5", ContradictionCategory.SECURITY_ITEM, HardSoft.SOFT,
                "어명패 없이 봉쇄 구역 통과 + 두 번째 어명패 발견",
                ["이겸", "연화"], ["어명패", "없이", "봉쇄"]),
            GoldContradiction("M4-6", ContradictionCategory.DEATH_REAPPEAR, HardSoft.HARD,
                "한명진 3년 전 사사(처형) 후 마당에 재등장",
                ["한명진"], ["한명진", "사사", "사망", "처형"]),
            GoldContradiction("M4-7", ContradictionCategory.OTHER, HardSoft.HARD,
                "연화↔이겸: 어머니+남매 관계 동시 — 상충",
                ["연화", "이겸"], ["어머니", "남매", "family_parent", "family_sibling"]),
            GoldContradiction("M4-8", ContradictionCategory.OTHER, HardSoft.SOFT,
                "국새 없는 필사본을 정우가 집행 — 문서 정합성 위반",
                ["정우"], ["국새", "필사본", "문서", "집행"]),
        ],
    ),

    # ── 5. 그림자저택_안개섬 ──────────────────────────────────────
    GoldTestCase(
        name="그림자저택_안개섬",
        prefix="그림자저택_안개섬",
        genre="추리",
        characters=[
            GoldCharacter("강진우", role="형사"),
            GoldCharacter("이수현", role="저택 관리인"),
            GoldCharacter("박영호", role="피해자"),
        ],
        facts=[
            GoldFact("전자 마스터키 단 하나 존재", category="world_fact"),
            GoldFact("22:00~06:00 전관 락다운, 모든 문 물리적 잠김", category="world_fact"),
            GoldFact("본관↔별채 지하통로 도보 15분", category="world_fact"),
        ],
        relationships=[
            GoldRelationship("강진우", "이수현", "colleague", "동료"),
            GoldRelationship("강진우", "이수현", "enemy", "적"),
        ],
        contradictions=[
            GoldContradiction("M5-1", ContradictionCategory.PHYSICS_RULE, HardSoft.SOFT,
                "22시 이후 락다운 규칙 위반 (봉쇄 상태에서 이동/행동)",
                ["강진우"], ["락다운", "봉쇄", "잠긴", "22시"]),
            GoldContradiction("M5-2", ContradictionCategory.TRAIT_SETTING, HardSoft.SOFT,
                "강진우: 커피 극혐 절대 안 마심 → 블랙커피 만족스럽게 음용",
                ["강진우"], ["커피", "혐오", "마시", "블랙"]),
            GoldContradiction("M5-3", ContradictionCategory.INFO_ASYMMETRY, HardSoft.SOFT,
                "강진우가 22시부터 수현의 키 분실을 알고 있음 (수현은 23:05 인지)",
                ["강진우", "이수현"], ["키", "분실", "22시", "알고"]),
            GoldContradiction("M5-4", ContradictionCategory.INFO_ASYMMETRY, HardSoft.SOFT,
                "마스터키 위치 모순: 수현 주머니/거실/서재 동시 언급",
                ["강진우", "이수현"], ["마스터키", "주머니", "거실", "서재"]),
            GoldContradiction("M5-5", ContradictionCategory.TIMELINE_MOVE, HardSoft.SOFT,
                "본관→별채 15분 규칙 vs 5분 이동",
                ["강진우"], ["15분", "5분", "분"]),
            GoldContradiction("M5-6", ContradictionCategory.SECURITY_ITEM, HardSoft.SOFT,
                "마스터키 소유/위치 불일치 (수현 소유인데 진우가 서재에서 훔침)",
                ["강진우", "이수현"], ["마스터키", "훔", "소유"]),
            GoldContradiction("M5-7", ContradictionCategory.DEATH_REAPPEAR, HardSoft.HARD,
                "박영호 시체로 발견 → 지하 실험실에서 재등장",
                ["박영호"], ["박영호", "사망", "시체"]),
            GoldContradiction("M5-8", ContradictionCategory.OTHER, HardSoft.SOFT,
                "강진우↔이수현: 동료+적 관계 동시 — 상충",
                ["강진우", "이수현"], ["동료", "적", "colleague", "enemy"]),
        ],
    ),
]

# ═══════════════════════════════════════════════════════════════════
# JSON 기반 Gold Standard 로더 — expectation 파일에서 자동 생성
# ═══════════════════════════════════════════════════════════════════

import os
import json

_CATEGORY_MAP = {
    "PHYSICS_RULE": ContradictionCategory.PHYSICS_RULE,
    "TRAIT_SETTING": ContradictionCategory.TRAIT_SETTING,
    "INFO_ASYMMETRY": ContradictionCategory.INFO_ASYMMETRY,
    "TIMELINE_MOVE": ContradictionCategory.TIMELINE_MOVE,
    "SECURITY_ITEM": ContradictionCategory.SECURITY_ITEM,
    "DEATH_REAPPEAR": ContradictionCategory.DEATH_REAPPEAR,
    "OTHER": ContradictionCategory.OTHER,
}

_HS_MAP = {
    "HARD": HardSoft.HARD,
    "SOFT": HardSoft.SOFT,
}


def load_gold_from_json(json_path: str = "") -> List[GoldTestCase]:
    """gold_standard_cases.json에서 GoldTestCase 리스트 로드."""
    if not json_path:
        json_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "gold_standard_cases.json"
        )
    if not os.path.exists(json_path):
        return []

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    cases = []
    for entry in data:
        contradictions = []
        for con in entry.get("contradictions", []):
            contradictions.append(GoldContradiction(
                id=con["id"],
                category=_CATEGORY_MAP.get(con["category"], ContradictionCategory.OTHER),
                hard_soft=_HS_MAP.get(con["hard_soft"], HardSoft.SOFT),
                description=con["description"],
                characters_involved=con.get("characters", []),
                keywords=con.get("keywords", []),
            ))
        cases.append(GoldTestCase(
            name=entry["name"],
            prefix=entry.get("data_dir", ""),
            genre=entry.get("genre", ""),
            contradictions=contradictions,
        ))
    return cases


def load_all_gold() -> List[GoldTestCase]:
    """기존 GOLD_CASES(variation 5종) + JSON 케이스 통합 로드."""
    json_cases = load_gold_from_json()
    return GOLD_CASES + json_cases


def get_gold_by_set(set_name: str) -> List[GoldTestCase]:
    """특정 테스트 셋의 Gold 케이스만 반환."""
    json_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "gold_standard_cases.json"
    )
    if not os.path.exists(json_path):
        return []
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    return load_gold_from_json(json_path)


def get_gold_by_name(case_name: str) -> Optional[GoldTestCase]:
    """케이스 이름으로 단일 Gold 검색."""
    for gc in load_all_gold():
        if gc.name == case_name:
            return gc
    return None


# 전체 통계 (variation 5종)
TOTAL_CONTRADICTIONS = sum(tc.total_contradictions for tc in GOLD_CASES)
TOTAL_BY_CATEGORY = {}
for tc in GOLD_CASES:
    for cat, items in tc.by_category().items():
        TOTAL_BY_CATEGORY[cat] = TOTAL_BY_CATEGORY.get(cat, 0) + len(items)
