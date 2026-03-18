# normalization.py
from app.models.intermediate import RawEntity, NormalizedEntity

class NormalizationService:
    async def process_raw_data(self, raws: List[RawEntity]) -> List[NormalizedEntity]:
        """계층 2: 중복 제거 및 이중 시간 축(discourse/story) 계산"""
        # TODO: B님이 정규화 로직 작성
        return []