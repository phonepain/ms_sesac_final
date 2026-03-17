# backend/app/services/extraction.py

import json
import asyncio
from typing import List
from fastapi import HTTPException

from app.models.api import DocumentChunk
from app.models.intermediate import ExtractionResult
from app.prompts.extract_entities import (
    WORLDVIEW_PROMPT,
    SETTINGS_PROMPT,
    SCENARIO_PROMPT,
)

MAX_RETRIES = 3


class ExtractionService:
    """
    Phase 1: Extraction Layer

    역할:
    DocumentChunk → RawEntity(JSON) → ExtractionResult(Pydantic)

    전체 데이터 흐름:

    File Upload
        ↓
    IngestService
        ↓
    DocumentChunk
        ↓
    ExtractionService (현재 클래스)
        ↓
    LLM 호출
        ↓
    JSON 결과
        ↓
    ExtractionResult (Pydantic validation)
    """

    # ------------------------------------------------------------------
    # CHANGE NOTE
    # 기존 함수: extract_from_manuscript(text: str)
    #
    # 문제:
    # 전체 문서를 한번에 LLM에 보내면
    # 1) 토큰 초과
    # 2) 병렬 처리 불가
    #
    # 해결:
    # ingest 단계에서 문서를 "chunk"로 분할하고
    # 각 chunk를 독립적으로 LLM에 전달하도록 구조 변경
    #
    # 기존
    #   manuscript(text) → extraction
    #
    # 변경
    #   manuscript
    #       ↓
    #   ingest (chunk 분할)
    #       ↓
    #   extract_from_chunk(chunk)
    #
    # 결과
    # - 병렬 처리 가능
    # - 토큰 제한 해결
    # - discourse_order 유지
    # ------------------------------------------------------------------
    async def extract_from_chunk(self, chunk: DocumentChunk) -> ExtractionResult:

        """
        Step 1
        source_type에 따라 extraction 전략 선택
        """

        prompt = self._select_prompt(chunk)

        """
        Step 2
        LLM 호출 + JSON 파싱

        실패 가능 지점:
        - LLM 응답 malformed JSON
        - 네트워크 오류
        - schema mismatch

        → 최대 3회 재시도
        """

        for attempt in range(MAX_RETRIES):

            try:

                """
                Step 3
                LLM 호출
                """

                response = await self._call_llm(
                    system_prompt=prompt,
                    text=chunk.content
                )

                """
                Step 4
                JSON 파싱
                """

                data = json.loads(response)

                """
                Step 5
                Pydantic Validation

                ExtractionResult 구조에 맞지 않으면
                여기서 ValidationError 발생
                """

                result = ExtractionResult(**data)

                return result

            except Exception as e:

                if attempt == MAX_RETRIES - 1:

                    raise HTTPException(
                        status_code=500,
                        detail=f"LLM extraction failed after retries: {str(e)}"
                    )

                await asyncio.sleep(1)

        raise HTTPException(500, "Extraction failed")


    # ------------------------------------------------------------------
    # PIPELINE STAGE
    # 여러 chunk를 병렬 처리하는 단계
    #
    # 이유:
    # 시나리오 파일은 보통 수십~수백 chunk가 되기 때문
    #
    # 처리 전략
    # asyncio + semaphore
    #
    # concurrency limit = 5
    # (LLM rate limit 방지)
    # ------------------------------------------------------------------
    async def extract_from_chunks(self, chunks: List[DocumentChunk]) -> List[ExtractionResult]:

        semaphore = asyncio.Semaphore(5)

        async def process(chunk):

            async with semaphore:
                return await self.extract_from_chunk(chunk)

        tasks = [process(c) for c in chunks]

        return await asyncio.gather(*tasks)


    # ------------------------------------------------------------------
    # Extraction 전략 선택
    #
    # worldview
    # settings
    # scenario
    #
    # 소스 타입에 따라 LLM에게 다른 프롬프트 제공
    # ------------------------------------------------------------------
    def _select_prompt(self, chunk: DocumentChunk) -> str:

        source_name = chunk.location.source_name.lower()

        if "worldview" in source_name:
            return WORLDVIEW_PROMPT

        if "settings" in source_name:
            return SETTINGS_PROMPT

        return SCENARIO_PROMPT


    # ------------------------------------------------------------------
    # LLM 호출 인터페이스
    #
    # 실제 구현 예정:
    #
    # Azure OpenAI (GPT-5-nano) → extraction
    #
    # 또는
    #
    # Anthropic Claude → extraction
    #
    # 현재 단계:
    # Phase1 skeleton
    # ------------------------------------------------------------------
    async def _call_llm(self, system_prompt: str, text: str) -> str:

        """
        Expected LLM Output

        JSON format matching ExtractionResult schema:

        {
            "characters": [],
            "facts": [],
            "events": [],
            "traits": [],
            "relationships": [],
            "emotions": [],
            "item_events": [],
            "knowledge_events": []
        }
        """

        raise NotImplementedError("LLM integration not implemented yet")