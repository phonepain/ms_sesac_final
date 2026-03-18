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
    - LLM 없이 extraction pipeline 테스트
    - 간단한 규칙 기반 캐릭터 추출
    """

    DIALOGUE_PATTERN = r"([A-Za-z가-힣]+)\s*:"

    NARRATIVE_PATTERN = r"\b([가-힣]{2,})[은는이가]\b"

    # 캐릭터가 아닌 단어들
    STOPWORDS = {
        "그러나",
        "그리고",
        "하지만",
        "또한",
        "그때",
        "그래서",
    }

    # 대명사
    PRONOUNS = {
        "그",
        "그녀",
        "그것",
        "그들"
    }

    def _is_valid_character(self, name: str) -> bool:

        if name in self.STOPWORDS:
            return False

        if name in self.PRONOUNS:
            return False

        # 동사 제거
        if name.endswith("다"):
            return False

        return True

    async def extract_from_chunk(self, chunk: DocumentChunk) -> ExtractionResult:

        characters = set()

        text = chunk.content

        # STEP 1 대사 패턴
        dialogue_matches = re.findall(self.DIALOGUE_PATTERN, text)

        for name in dialogue_matches:

            if self._is_valid_character(name):
                characters.add(name)

        # STEP 2 서술형 패턴
        narrative_matches = re.findall(self.NARRATIVE_PATTERN, text)

        for name in narrative_matches:

            if self._is_valid_character(name):
                characters.add(name)

        raw_characters = []

        for name in characters:

            raw_characters.append(
                RawCharacter(
                    name=name,
                    possible_aliases=[],
                    role_hint=None,
                    source_chunk_id=chunk.id
                )
            )

        return ExtractionResult(
            characters=raw_characters,
            facts=[],
            events=[],
            traits=[],
            relationships=[],
            emotions=[],
            item_events=[],
            knowledge_events=[],
            source_chunk_id=chunk.id,
            chunk_index=chunk.chunk_index
        )