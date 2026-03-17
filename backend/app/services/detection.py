# detection.py
from app.models.enums import ContradictionType

class DetectionService:
    async def check_timeline_contradiction(self, character_id: str):
        """계층 4: 특정 캐릭터의 story_order 모순 탐지"""
        # TODO: C님이 그래프 쿼리를 이용한 모순 감지 로직 작성
        pass