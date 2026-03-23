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
        """settings 타입의 '=== 이름 ===' 헤더에서 캐릭터 추출.

        헤더 예: '=== 형사 A (이아름) ===' → 단일 대문자 'A' 우선,
        없으면 한글 이름(2~4자).
        """
        results = []
        seen: set = set()
        for match in re.finditer(r"===(.+?)===", text):
            header = match.group(1).strip()
            # 단일 대문자 식별자 우선 (A, B, C, D …)
            letter = re.search(r"\b([A-Z])\b", header)
            if letter:
                name = letter.group(1)
            else:
                kr = re.search(r"([가-힣]{2,4})", header)
                name = kr.group(1) if kr else None
            if name and name not in seen:
                seen.add(name)
                results.append({
                    "name": name,
                    "possible_aliases": [],
                    "role_hint": header,
                    "source_chunk_id": chunk_id,
                })
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

        # settings: 헤더 기준 블록 파싱
        if source_type == "settings":
            current_char: str | None = None
            for line in text.split("\n"):
                # 헤더 감지
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

                if not current_char:
                    continue

                # trait 키워드 파싱
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
        """대화 대사 → mentions, 학습 동사 → learns."""
        if source_type not in ("scenario", "settings"):
            return []

        results: List[Dict[str, object]] = []
        LEARN_VERBS = [
            "알았다", "알게됐다", "알게 됐다", "깨달았다",
            "확인했다", "발견했다", "들었다", "봤다", "알려줬다",
        ]
        STAGE_DIRS = {"무대", "지문", "해설", "자막", "나레이션"}

        # mentions: 대사 한 줄 = "캐릭터: 내용"
        dial_pat = re.compile(
            r"^\s*([가-힣A-Za-z]{1,20})\s*:\s*(.{10,150})",
            re.MULTILINE,
        )
        for m in dial_pat.finditer(text):
            speaker = m.group(1).strip()
            content = m.group(2).strip()
            if speaker in STAGE_DIRS or content.startswith("("):
                continue
            results.append({
                "character_name": speaker,
                "fact_content": content[:100],
                "event_type": "mentions",
                "method": "direct_speech",
                "via_character": None,
                "dialogue_text": content[:100],
                "source_chunk_id": chunk_id,
            })

        # learns: "캐릭터가 ~을 알았다/발견했다" 등
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

        return results[:12]

    def _extract_mock_item_events(
        self,
        text: str,
        source_type: str,
        chunk_id: str,
        char_names: List[str],
    ) -> List[Dict[str, object]]:
        """소유/양도/분실 패턴 → POSSESSES / LOSES 엣지용 데이터."""
        results: List[Dict[str, object]] = []

        # settings: "소유물: 아이템명" → possesses
        if source_type == "settings":
            current_char: str | None = None
            for line in text.split("\n"):
                hm = re.search(r"===(.+?)===", line)
                if hm:
                    header = hm.group(1)
                    ltr = re.search(r"\b([A-Z])\b", header)
                    current_char = ltr.group(1) if ltr else (
                        re.search(r"([가-힣]{2,4})", header).group(1)
                        if re.search(r"([가-힣]{2,4})", header) else None
                    )
                    continue
                owns = re.search(r"소유물\s*:\s*([가-힣A-Za-z0-9()\s]+)", line)
                if owns and current_char:
                    item_text = re.split(r"[(\[,]", owns.group(1))[0].strip()
                    results.append({
                        "character_name": current_char,
                        "item_name": item_text[:30],
                        "action": "possesses",
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

        # settings 타입: === 헤더 === 기반 캐릭터도 병합
        if source_type == "settings":
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
        item_events = self._extract_mock_item_events(text, source_type, chunk_id, char_names)

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
