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
        self.use_mock = settings.use_mock_extraction or not (
            settings.azure_openai_endpoint and settings.azure_openai_api_key
        )

        if not self.use_mock:
            self.client = AsyncAzureOpenAI(
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
            )
            self.deployment_name = settings.azure_openai_extraction_deployment

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
            if len(name) < 2 or len(name) > 20:
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

    # [CHANGED][PHASE0-3] LLM 미연결 환경에서 빈 추출을 줄이기 위한 fallback
    def _build_mock_result(self, text: str, source_type: str, chunk_id: str) -> ExtractionResult:
        characters = self._guess_characters_from_narrative(text, chunk_id)

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

        return ExtractionResult(
            source_chunk_id=chunk_id,
            characters=characters,
            events=raw_events,
            facts=fact_candidates,
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
