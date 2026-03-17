# backend/app/services/mock_extraction.py

import re

from app.models.api import DocumentChunk
from app.models.intermediate import (
    ExtractionResult,
    RawCharacter
)


class MockExtractionService:

    """
    테스트용 Extraction Service

    목적
    - LLM 없이 Extraction pipeline 테스트
    - 대사 패턴 기반 캐릭터 추출
    """

    # STEP 1
    # "캐릭터: 대사" 패턴
    DIALOGUE_PATTERN = r"([A-Za-z가-힣]+)\s*:\s*"

    async def extract_from_chunk(self, chunk: DocumentChunk) -> ExtractionResult:

        characters = []

        # STEP 2
        # 전체 텍스트에서 패턴 검색
        matches = re.findall(self.DIALOGUE_PATTERN, chunk.content)

        # STEP 3
        # 매칭된 캐릭터 생성
        for name in matches:

            characters.append(
                RawCharacter(
                    name=name,
                    possible_aliases=[],
                    role_hint=None,
                    source_chunk_id=chunk.id
                )
            )

        return ExtractionResult(
            characters=characters,
            facts=[],
            events=[],
            traits=[],
            relationships=[],
            emotions=[],
            item_events=[],
            knowledge_events=[],
            source_chunk_id=chunk.id
        )