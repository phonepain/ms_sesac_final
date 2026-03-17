# extraction.py
from typing import List
from app.models.intermediate import RawEntity

class ExtractionService:
    async def extract_from_manuscript(self, text: str) -> List[RawEntity]:
        """계층 1: 원고에서 인물, 사건, 관계 등을 LLM으로 추출"""
        # TODO: B님이 프롬프트 엔지니어링 후 작성
        return []

# normalization.py
from app.models.intermediate import RawEntity, NormalizedEntity

class NormalizationService:
    async def process_raw_data(self, raws: List[RawEntity]) -> List[NormalizedEntity]:
        """계층 2: 중복 제거 및 이중 시간 축(discourse/story) 계산"""
        # TODO: B님이 정규화 로직 작성
        return []