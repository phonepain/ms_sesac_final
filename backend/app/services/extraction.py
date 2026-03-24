# backend/app/services/extraction.py
import asyncio
import json
import re
from typing import Dict, List

import structlog
from openai import AsyncAzureOpenAI

from app.config import settings
from app.models.api import DocumentChunk
from app.models.intermediate import ExtractionResult
from app.prompts.extract_entities import SCENARIO_PROMPT, SETTINGS_PROMPT, WORLDVIEW_PROMPT

logger = structlog.get_logger(__name__)


class ExtractionService:
    def __init__(self):
        # [CHANGED][PHASE0-3] guide 기준 동시 처리량 5 유지
        self.semaphore = asyncio.Semaphore(5)
        # [CHANGED][PHASE0-3][CONFIG-COMPAT] Config field names aligned to original config.py (AZURE_OPENAI_*).
        self.use_mock = settings.use_mock_extraction or not (
            settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_API_KEY
        )

        if not self.use_mock:
            self.client = AsyncAzureOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )
            self.deployment_name = settings.AZURE_OPENAI_EXTRACTION_DEPLOYMENT

    async def extract_from_chunks(self, chunks: List[DocumentChunk], source_type: str) -> List[ExtractionResult]:
        logger.info("Starting batch extraction", total_chunks=len(chunks), source_type=source_type)
        tasks = [self.extract_from_chunk(chunk.content, source_type, chunk.id) for chunk in chunks]
        results = await asyncio.gather(*tasks)
        logger.info("Batch extraction complete", total_results=len(results))
        return list(results)

    # [CHANGED][PHASE0-3] 서술형 텍스트에서도 캐릭터를 추정하기 위한 경량 규칙
    def _guess_characters_from_narrative(self, text: str, chunk_id: str) -> List[Dict[str, object]]:
        # 대사 형식: "이름: ..."
        dialogue_names = re.findall(r"^\s*([가-힣A-Za-z0-9_ ]{1,30})\s*:\s*", text, flags=re.MULTILINE)

        # 서술형 문장: "이름이/가 말했다" 등
        narrative_name_matches: List[str] = []
        narrative_patterns = [
            r"([가-힣A-Za-z]{2,12})(?:은|는|이|가)\s*(?:말했|물었|소리쳤|외쳤|대답했|중얼거렸|생각했|바라보았|바라봤)",
            r"([가-힣A-Za-z]{2,12})와\s*([가-힣A-Za-z]{2,12})",
        ]

        for pattern in narrative_patterns:
            for match in re.findall(pattern, text):
                if isinstance(match, tuple):
                    narrative_name_matches.extend([m for m in match if m])
                else:
                    narrative_name_matches.append(match)

        # 보수적인 불용어 필터
        stopwords = {
            "그리고",
            "하지만",
            "그때",
            "여기",
            "저기",
            "오늘",
            "내일",
            "어제",
            "학생",
            "교수",
            "기차",
            "학교",
            "장",
            "번",
            "이상",
            "정도",
            "순간",
            "다음",
            "아침",
            "저녁",
            "사람",
            "아이",
            "남자",
            "여자",
            "부부",
        }

        deduped: List[str] = []
        seen = set()
        for raw_name in dialogue_names + narrative_name_matches:
            name = raw_name.strip()
            if not name:
                continue
            if name in stopwords:
                continue
            if name.isdigit():
                continue
            # 한글 1글자는 조사 가능성 → 제외; 영문 단일 대문자(A, B…)는 캐릭터 식별자 → 허용
            if len(name) > 20:
                continue
            if len(name) == 1 and not name.isupper():
                continue
            if name not in seen:
                seen.add(name)
                deduped.append(name)

        return [
            {
                "name": name,
                "possible_aliases": [],
                "role_hint": None,
                "source_chunk_id": chunk_id,
            }
            for name in deduped[:8]
        ]

    # ── mock 보조 메서드 ────────────────────────────────────────

    def _extract_header_characters(self, text: str, chunk_id: str) -> List[Dict[str, object]]:
        """settings 타입의 캐릭터 헤더에서 이름 추출.

        두 가지 포맷 지원:
        1. '=== 형사 A (이아름) ===' → 단일 대문자 'A' 우선, 없으면 한글 이름(2~4자)
        2. '1. 강진우 (주인공, 형사)' 번호 목록 형식 → 한글 이름(2~4자)
        """
        results = []
        seen: set = set()

        def _add(name: str, role_hint: str = ""):
            if name and name not in seen:
                seen.add(name)
                results.append({
                    "name": name,
                    "possible_aliases": [],
                    "role_hint": role_hint,
                    "source_chunk_id": chunk_id,
                })

        # 포맷 1: === 헤더 ===
        for match in re.finditer(r"===(.+?)===", text):
            header = match.group(1).strip()
            letter = re.search(r"\b([A-Z])\b", header)
            if letter:
                _add(letter.group(1), header)
            else:
                kr = re.search(r"([가-힣]{2,4})", header)
                if kr:
                    _add(kr.group(1), header)

        # 포맷 2: "N. 이름 (역할)" 번호 목록
        for match in re.finditer(r"^\d+\.\s+([가-힣]{2,5})\s*[(\（]", text, re.MULTILINE):
            _add(match.group(1), match.group(0).strip())

        return results

    def _extract_mock_traits_and_emotions(
        self,
        text: str,
        source_type: str,
        chunk_id: str,
        char_names: List[str],
    ) -> tuple:
        """settings 블록을 줄 단위로 읽어 traits + emotions 추출.

        Returns (traits, emotions) — 각각 dict 리스트.
        """
        TRAIT_KEYS = [
            "혈액형", "식습관", "성격", "목표", "능력", "특기",
            "직업", "직위", "나이", "키", "출신", "배경", "직급",
        ]
        EMOTION_MAP = {
            "신뢰": "trust", "trust": "trust",
            "증오": "hate", "미워": "hate", "hate": "hate",
            "사랑": "love", "love": "love",
            "두려움": "fear", "두려워": "fear", "무서워": "fear", "fear": "fear",
            "질투": "jealousy",
            "중립": "neutral", "neutral": "neutral",
            "감사": "gratitude",
            "분노": "hate",
            "경멸": "contempt",
            "불신": "distrust",
        }

        traits: List[Dict[str, object]] = []
        emotions: List[Dict[str, object]] = []

        # 헤더(=== 캐릭터명 ===) 기준 블록 파싱 — settings뿐 아니라 scenario에 설정이 포함된 경우도 처리
        if source_type in ("settings", "scenario", "worldview"):
            current_char: str | None = None
            for line in text.split("\n"):
                # 헤더 감지 — 포맷1: === 헤더 ===
                hm = re.search(r"===(.+?)===", line)
                if hm:
                    header = hm.group(1).strip()
                    ltr = re.search(r"\b([A-Z])\b", header)
                    if ltr:
                        current_char = ltr.group(1)
                    else:
                        kr = re.search(r"([가-힣]{2,4})", header)
                        current_char = kr.group(1) if kr else None
                    continue

                # 헤더 감지 — 포맷2: "N. 이름 (역할)" 번호 목록
                nm = re.match(r"^\d+\.\s+([가-힣]{2,5})\s*[(\（]", line)
                if nm:
                    current_char = nm.group(1)
                    continue

                if not current_char:
                    continue

                # "- 특성:" 블록에서 trait 파싱 (번호 목록 포맷)
                trait_block = re.match(r"^[-\s]*특성\s*:\s*(.+)", line)
                if trait_block:
                    desc = trait_block.group(1)
                    # "커피를 극도로 혐오" → key=커피, value=혐오
                    for kw, key in [("커피", "커피"), ("결벽", "결벽증"), ("채식", "식습관"),
                                    ("술", "음주"), ("혈액형", "혈액형")]:
                        if kw in desc:
                            val = "혐오" if "혐오" in desc else (
                                  "결벽증" if "결벽" in desc else desc[:40])
                            traits.append({
                                "character_name": current_char,
                                "key": key,
                                "value": val,
                                "category_hint": "personality",
                                "source_chunk_id": chunk_id,
                            })

                # trait 키워드 파싱 (기존 key:value 포맷)
                for key in TRAIT_KEYS:
                    m = re.search(rf"{key}\s*:\s*([가-힣A-Za-z0-9()\s]+)", line)
                    if m:
                        traits.append({
                            "character_name": current_char,
                            "key": key,
                            "value": m.group(1).strip()[:50],
                            "category_hint": (
                                "physical" if key in ("혈액형", "키", "나이") else "personality"
                            ),
                            "source_chunk_id": chunk_id,
                        })
                        break

                # "X에 대해: 감정" 패턴 → FEELS
                about = re.search(r"([가-힣A-Za-z]{1,10})에 대해\s*:\s*([가-힣A-Za-z()]+)", line)
                if about:
                    target = about.group(1).strip()
                    emotion_text = about.group(2).strip()
                    emo = next((v for k, v in EMOTION_MAP.items() if k in emotion_text), "neutral")
                    emotions.append({
                        "from_char": current_char,
                        "to_char": target,
                        "emotion": emo,
                        "trigger_hint": None,
                        "source_chunk_id": chunk_id,
                    })

        # scenario/worldview: 대화에서 감정 직접 표현 감지
        # "A: B를 증오해" / "A가 B를 사랑한다"
        EMOTION_VERBS = {
            "증오": "hate", "미워": "hate",
            "사랑": "love", "좋아": "love",
            "신뢰": "trust", "믿어": "trust",
            "두려워": "fear", "무서워": "fear",
            "질투": "jealousy",
        }
        for from_char in char_names[:5]:
            for to_char in char_names[:5]:
                if from_char == to_char:
                    continue
                for kw, emo in EMOTION_VERBS.items():
                    # 대사 패턴: "from_char: ...to_char...kw"
                    if re.search(
                        rf"^\s*{re.escape(from_char)}\s*:.*{re.escape(to_char)}.*{kw}",
                        text, re.MULTILINE,
                    ):
                        emotions.append({
                            "from_char": from_char,
                            "to_char": to_char,
                            "emotion": emo,
                            "trigger_hint": None,
                            "source_chunk_id": chunk_id,
                        })

        return traits[:10], emotions[:8]

    def _extract_mock_relationships(
        self,
        text: str,
        chunk_id: str,
        char_names: List[str],
    ) -> List[Dict[str, object]]:
        """관계 추출: 화살표 패턴 + 관계 키워드 패턴."""
        REL_MAP = {
            "동료": "colleague", "파트너": "colleague", "친구": "ally",
            "적": "enemy", "형": "family_sibling", "언니": "family_sibling",
            "오빠": "family_sibling", "누나": "family_sibling",
            "아버지": "family_parent", "어머니": "family_parent", "부모": "family_parent",
            "자녀": "family_child", "부부": "family_spouse", "연인": "romantic",
        }
        results: List[Dict[str, object]] = []
        seen: set = set()

        def _add(a: str, b: str, type_hint: str, detail: str) -> None:
            key = (a, b, type_hint)
            if key not in seen:
                seen.add(key)
                results.append({
                    "char_a": a, "char_b": b,
                    "type_hint": type_hint, "detail": detail[:50],
                    "source_chunk_id": chunk_id,
                })

        # 패턴 1: "A ↔ B: 관계" / "A → B: 관계"
        arrow_pat = re.compile(
            r"([가-힣A-Za-z]{1,10})\s*[↔←→]\s*([가-힣A-Za-z]{1,10})\s*:\s*([가-힣A-Za-z()\s]+)"
        )
        for m in arrow_pat.finditer(text):
            a, b, rel = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            type_hint = next((v for k, v in REL_MAP.items() if k in rel), "colleague")
            _add(a, b, type_hint, rel)

        # 패턴 2: "A와 B는 [관계]"
        for kw, rtype in REL_MAP.items():
            for m in re.finditer(
                rf"([가-힣A-Za-z]{{1,10}})와\s+([가-힣A-Za-z]{{1,10}})(?:는|이|가|은)\s+{kw}",
                text,
            ):
                _add(m.group(1).strip(), m.group(2).strip(), rtype, kw)

        return results[:8]

    def _extract_mock_knowledge_events(
        self,
        text: str,
        source_type: str,
        chunk_id: str,
        char_names: List[str],
    ) -> List[Dict[str, object]]:
        """대화 대사 → mentions, 학습 동사/맥락 → learns."""
        if source_type not in ("scenario", "settings"):
            return []

        results: List[Dict[str, object]] = []

        # 서술형 학습 동사 (narrative)
        LEARN_VERBS = [
            "알았다", "알게됐다", "알게 됐다", "깨달았다",
            "확인했다", "발견했다", "들었다", "봤다", "알려줬다",
            "알게되었다", "파악했다", "인지했다",
        ]
        # 대화 맥락 학습 키워드 — "(진술 검토 후)", "이제 확실해", "알고 있었어" 등
        LEARN_CONTEXT_PATTERNS = [
            r"\(.*?(?:진술|증언|확인|검토|발견).*?\)",   # 지문: (C의 진술 검토 후)
            r"이제\s*(?:확실|알겠|알았|분명)",            # "이제 확실해", "이제 알겠어"
            r"처음부터\s*알고",                            # "처음부터 알고 있었어"
            r"(?:그래서|그러니까|결국)\s*범인",            # 결론 도출 대사
        ]
        STAGE_DIRS = {"무대", "지문", "해설", "자막", "나레이션"}

        # ── 대사 파싱 ────────────────────────────────────────────
        # "화자: (지문) 실제 대사" 형식 처리
        # 지문 부분은 학습 맥락 판단에, 실제 대사 부분은 fact_content로 사용
        dial_pat = re.compile(
            r"^\s*([가-힣A-Za-z]{1,20})\s*:\s*(.{5,200})",
            re.MULTILINE,
        )
        lines = text.split("\n")
        prev_line_is_learn_context = False
        for line in lines:
            stripped = line.strip()

            # 독립 지문/나레이션 줄 ([...] 또는 순수 (...) 줄)
            if (stripped.startswith("[") or
                    (stripped.startswith("(") and not re.match(r"^\s*[가-힣A-Za-z]{1,20}\s*:", line))):
                is_context = any(re.search(pat, stripped) for pat in LEARN_CONTEXT_PATTERNS)
                prev_line_is_learn_context = is_context
                continue

            m = dial_pat.match(line)
            if not m:
                prev_line_is_learn_context = False
                continue

            speaker = m.group(1).strip()
            raw_content = m.group(2).strip()
            if speaker in STAGE_DIRS:
                prev_line_is_learn_context = False
                continue

            # 줄 앞의 인라인 지문 "(지문) 실제 대사" 분리
            # "(C의 진술 검토 후) 이제 확실해." → stage_dir="(C의 진술 검토 후)", content="이제 확실해."
            inline_dir_match = re.match(r"^(\([^)]{1,50}\))\s*(.*)", raw_content, re.DOTALL)
            if inline_dir_match:
                inline_dir = inline_dir_match.group(1)
                content = inline_dir_match.group(2).strip()
                inline_is_learn = any(re.search(pat, inline_dir) for pat in LEARN_CONTEXT_PATTERNS)
            else:
                inline_dir = ""
                content = raw_content
                inline_is_learn = False

            # fact_content가 너무 짧으면 스킵
            if len(content) < 5:
                prev_line_is_learn_context = False
                continue

            # 학습 여부 판단: 직전 독립 지문 OR 인라인 지문 OR 대사 자체 키워드
            content_is_learn = any(re.search(pat, content) for pat in LEARN_CONTEXT_PATTERNS)
            event_type = "learns" if (prev_line_is_learn_context or inline_is_learn or content_is_learn) else "mentions"

            # learns일 때 fact_content 정규화:
            # "이제 확실해. B가 범인이야." → 학습 맥락 접두 문장 제거 → "B가 범인이야."
            # 이렇게 해야 기존 mentions fact("B가 범인이다")와 bi-gram 매칭 성공
            fact_content = content
            if event_type == "learns":
                # 첫 번째 문장이 학습 맥락 키워드만 포함하면 제거
                sentences = re.split(r"(?<=[.?!])\s+", content)
                if len(sentences) > 1:
                    first = sentences[0]
                    if any(re.search(pat, first) for pat in LEARN_CONTEXT_PATTERNS):
                        fact_content = " ".join(sentences[1:]).strip()
                if len(fact_content) < 5:
                    fact_content = content

            results.append({
                "character_name": speaker,
                "fact_content": fact_content[:100],
                "event_type": event_type,
                "method": "testimony" if event_type == "learns" else "direct_speech",
                "via_character": None,
                "dialogue_text": raw_content[:100],
                "source_chunk_id": chunk_id,
            })
            prev_line_is_learn_context = False

        # ── 서술형 learns ("캐릭터가 ~알았다") ──────────────────
        for char_name in char_names[:5]:
            for verb in LEARN_VERBS:
                for m in re.finditer(
                    rf"({re.escape(char_name)}(?:이|가)?\s*.{{5,60}}{verb})",
                    text,
                ):
                    results.append({
                        "character_name": char_name,
                        "fact_content": m.group(1)[:100],
                        "event_type": "learns",
                        "method": "observation",
                        "via_character": None,
                        "dialogue_text": None,
                        "source_chunk_id": chunk_id,
                    })

        return results[:16]

    def _extract_mock_item_events(
        self,
        text: str,
        source_type: str,
        chunk_id: str,
        char_names: List[str],
    ) -> List[Dict[str, object]]:
        """소유/양도/분실 패턴 → POSSESSES / LOSES 엣지용 데이터."""
        results: List[Dict[str, object]] = []

        # settings/scenario: "소유물: 아이템명" → possesses  (=== 헤더 === 및 번호 목록 포맷 모두 지원)
        if source_type in ("settings", "scenario"):
            current_char: str | None = None
            for line in text.split("\n"):
                # 헤더 포맷1: === 이름 ===
                hm = re.search(r"===(.+?)===", line)
                if hm:
                    header = hm.group(1)
                    ltr = re.search(r"\b([A-Z])\b", header)
                    current_char = ltr.group(1) if ltr else (
                        re.search(r"([가-힣]{2,4})", header).group(1)
                        if re.search(r"([가-힣]{2,4})", header) else None
                    )
                    continue
                # 헤더 포맷2: "N. 이름 (역할)"
                nm = re.match(r"^\d+\.\s+([가-힣]{2,5})\s*[(\（]", line)
                if nm:
                    current_char = nm.group(1)
                    continue
                # "- 소유물:" 또는 "소유물:"
                owns = re.search(r"소유물\s*:\s*([가-힣A-Za-z0-9()\s'\"]+)", line)
                if owns and current_char:
                    item_text = re.split(r"[(\[,]", owns.group(1))[0].strip().strip("'\"")
                    results.append({
                        "character_name": current_char,
                        "item_name": item_text[:30],
                        "action": "possesses",
                        "source_chunk_id": chunk_id,
                    })
                # "- 상태: 사망" → HAS_STATUS dead용 특수 item_event (action="loses" → 나중에 상태 추론)
                status_m = re.search(r"상태\s*:\s*(.+)", line)
                if status_m and current_char:
                    status_val = status_m.group(1).strip()
                    if any(kw in status_val for kw in ["사망", "죽", "dead", "사체"]):
                        results.append({
                            "character_name": current_char,
                            "item_name": "__status_dead__",
                            "action": "possesses",   # 특수 마커 — build_mock_result에서 status로 변환
                            "source_chunk_id": chunk_id,
                        })

        # scenario: 양도 패턴 "X이|가 Y을|를 Z에게|한테 건네/주었/양도"
        if source_type == "scenario":
            TRANSFER_VERBS = ["건네", "줬", "주었", "넘겨", "양도", "빼앗", "가져"]
            USE_VERBS = ["보여", "사용했", "들었", "꺼냈", "뽑았"]

            # 명시적 주어 있는 양도
            for m in re.finditer(
                r"([가-힣A-Za-z]{1,10})(?:이|가)\s+(.{1,20})(?:을|를)\s+"
                r"([가-힣A-Za-z]{1,10})(?:에게|한테)\s*([가-힣A-Za-z]+)",
                text,
            ):
                giver, item, receiver, action_text = (
                    m.group(1).strip(), m.group(2).strip(),
                    m.group(3).strip(), m.group(4).strip(),
                )
                if any(v in action_text for v in TRANSFER_VERBS):
                    results.append({"character_name": giver, "item_name": item[:30],
                                    "action": "loses", "source_chunk_id": chunk_id})
                    results.append({"character_name": receiver, "item_name": item[:30],
                                    "action": "possesses", "source_chunk_id": chunk_id})

            # 주어 없는 양도: "아이템을 X에게 건네"
            for m in re.finditer(
                r"(.{1,15})(?:을|를)\s+([가-힣A-Za-z]{1,10})(?:에게|한테)\s*(?:건네|주었|넘겨|양도)",
                text,
            ):
                item, receiver = m.group(1).strip(), m.group(2).strip()
                results.append({"character_name": receiver, "item_name": item[:30],
                                "action": "possesses", "source_chunk_id": chunk_id})

            # 사용: "캐릭터 … 아이템 … 사용/보여"
            COMMON_ITEMS = ["칼", "총", "가방", "서류", "증거", "열쇠", "폰", "핸드폰", "무기"]
            for char_name in char_names[:5]:
                for item_word in COMMON_ITEMS:
                    for verb in USE_VERBS:
                        if re.search(rf"{re.escape(char_name)}.*?{item_word}.*?{verb}", text):
                            results.append({
                                "character_name": char_name,
                                "item_name": item_word,
                                "action": "uses",
                                "source_chunk_id": chunk_id,
                            })

        return results[:10]

    # [CHANGED][PHASE0-3] LLM 미연결 환경에서 빈 추출을 줄이기 위한 fallback
    def _build_mock_result(self, text: str, source_type: str, chunk_id: str) -> ExtractionResult:
        # ── 캐릭터 추출 ─────────────────────────────────────────
        characters = self._guess_characters_from_narrative(text, chunk_id)

        # settings/scenario 타입: === 헤더 === 기반 캐릭터도 병합
        if source_type in ("settings", "scenario"):
            existing_names = {c["name"] for c in characters}
            for hc in self._extract_header_characters(text, chunk_id):
                if hc["name"] not in existing_names:
                    characters.append(hc)
                    existing_names.add(hc["name"])

        char_names = [c["name"] for c in characters]

        # ── 기존 facts / events ──────────────────────────────────
        sentences = [
            seg.strip()
            for seg in re.split(r"[.!?\n]+", text)
            if len(seg.strip()) >= 12
        ]

        raw_events = [
            {
                "description": sentence[:200],
                "characters_involved": [],
                "location_hint": None,
                "source_chunk_id": chunk_id,
            }
            for sentence in sentences[:2]
        ]

        fact_keywords = ["이다", "였다", "있다", "없다", "했다", "된다", "보였다", "말했다", "물었다"]
        fact_candidates: List[Dict[str, object]] = []

        for sentence in sentences[:3]:
            if any(keyword in sentence for keyword in fact_keywords):
                fact_candidates.append(
                    {
                        "content": sentence[:200],
                        "category_hint": "event_fact" if source_type == "scenario" else "world_fact",
                        "is_secret_hint": False,
                        "source_chunk_id": chunk_id,
                    }
                )

        if not fact_candidates and sentences:
            fact_candidates.append(
                {
                    "content": sentences[0][:200],
                    "category_hint": "event_fact" if source_type == "scenario" else "world_fact",
                    "is_secret_hint": False,
                    "source_chunk_id": chunk_id,
                }
            )

        # ── 신규: 엣지 데이터 추출 ───────────────────────────────
        traits, emotions = self._extract_mock_traits_and_emotions(
            text, source_type, chunk_id, char_names
        )
        relationships = self._extract_mock_relationships(text, chunk_id, char_names)
        knowledge_events = self._extract_mock_knowledge_events(
            text, source_type, chunk_id, char_names
        )
        item_events_raw = self._extract_mock_item_events(text, source_type, chunk_id, char_names)

        # "__status_dead__" 마커 → RawEvent(death) + 실제 item_events 분리
        item_events = []
        for ie in item_events_raw:
            if ie.get("item_name") == "__status_dead__":
                # 사망 상태 → events에 death 이벤트 추가
                raw_events.append({
                    "description": f"{ie['character_name']} 사망",
                    "characters_involved": [ie["character_name"]],
                    "location_hint": None,
                    "event_type": "death",
                    "status_char": ie["character_name"],
                    "source_chunk_id": chunk_id,
                })
            else:
                item_events.append(ie)

        logger.debug(
            "mock_extraction_summary",
            source_type=source_type,
            chars=len(characters),
            traits=len(traits),
            emotions=len(emotions),
            relationships=len(relationships),
            knowledge_events=len(knowledge_events),
            item_events=len(item_events),
        )

        return ExtractionResult(
            source_chunk_id=chunk_id,
            characters=characters,
            events=raw_events,
            facts=fact_candidates,
            traits=traits,
            relationships=relationships,
            emotions=emotions,
            knowledge_events=knowledge_events,
            item_events=item_events,
        )

    async def extract_from_chunk(self, text: str, source_type: str, chunk_id: str) -> ExtractionResult:
        async with self.semaphore:
            if self.use_mock:
                return self._build_mock_result(text, source_type, chunk_id)

            if source_type == "worldview":
                prompt_template = WORLDVIEW_PROMPT
            elif source_type == "settings":
                prompt_template = SETTINGS_PROMPT
            else:
                prompt_template = SCENARIO_PROMPT

            prompt = prompt_template.format(text=text)

            try:
                logger.debug("Calling LLM", chunk_id=chunk_id)
                response = None

                # [CHANGED][PHASE0-3] JSON 파싱 실패 대비 3회 재시도
                for _ in range(3):
                    response = await self.client.beta.chat.completions.parse(
                        model=self.deployment_name,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are an extraction assistant. Return strict JSON matching schema.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        response_format=ExtractionResult,
                    )
                    if response and response.choices:
                        break

                try:
                    result = response.choices[0].message.parsed
                    if result is None:
                        content = response.choices[0].message.content
                        data = json.loads(content)
                        result = ExtractionResult(**data)
                except Exception as parse_error:
                    logger.error("JSON parsing error", chunk_id=chunk_id, error=str(parse_error))
                    result = ExtractionResult(source_chunk_id=chunk_id)

                result.source_chunk_id = chunk_id
                return result

            except Exception as api_error:
                logger.error("Extraction API error", chunk_id=chunk_id, error=str(api_error))
                return ExtractionResult(source_chunk_id=chunk_id)
