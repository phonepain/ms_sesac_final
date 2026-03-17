# backend/app/services/normalization.py
import structlog
from typing import List
from app.models.intermediate import ExtractionResult, NormalizationResult
from app.config import settings

logger = structlog.get_logger()

class NormalizationService:
    def __init__(self):
        # 정규화에서도 LLM을 사용할 수 있으므로 클라이언트를 준비합니다.
        pass

    async def normalize(self, extractions: List[ExtractionResult]) -> NormalizationResult:
        """계층 2: 중복 캐릭터 통합, 유사 사실 병합, 소스 간 충돌 감지"""
        logger.info("Starting normalization process", chunk_count=len(extractions))
        
        result = NormalizationResult()
        
        # TODO: 
        # 1. 모든 extractions.characters를 모아서 이름/별명 유사도 기반 통합 로직 (LLM 보조)
        # 2. 모든 extractions.facts를 의미적 유사도로 병합 (Fact vs Trait 분류)
        # 3. SourceConflict 감지 로직
        
        return result