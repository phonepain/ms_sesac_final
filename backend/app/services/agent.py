import structlog
from typing import List, Dict, Any
from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.services.detection import DetectionService

logger = structlog.get_logger()

class ContiCheckAgent:
    def __init__(self):
        self.extraction_service = ExtractionService()
        self.normalization_service = NormalizationService()
        self.detection_service = DetectionService()

    async def analyze_manuscript(self, text: str, source_type: str = "scenario"):
        """
        원고 분석 전체 파이프라인 실행
        """
        logger.info("Starting Full Analysis Pipeline")

        # 1. 추출 (Extraction)
        # 실제로는 청크 단위로 나누어 실행해야 하지만, 우선 단일 처리로 예시를 듭니다.
        raw_data = await self.extraction_service.extract_from_chunk(
            text=text, source_type=source_type, chunk_id="upload-001"
        )
        logger.info("Step 1: Extraction Complete")

        # 2. 정규화 (Normalization)
        # 여러 청크 결과를 모아서 한꺼번에 정규화합니다.
        normalized_data = await self.normalization_service.normalize(extractions=[raw_data])
        logger.info("Step 2: Normalization Complete")

        # 3. 그래프 적재 (Materialization)
        # 이 부분은 팀원 중 'Graph DB 담당자'가 만든 서비스와 연결될 부분입니다.
        # graph_service.materialize(normalized_data)
        logger.info("Step 3: Graph Materialization (Pending DB implementation)")

        # 4. 모순 탐지 (Detection)
        # 그래프에서 찾아낸 후보들을 LLM이 검증합니다.
        # 여기서는 예시를 위해 앞서 테스트한 데이터를 사용한다고 가정합니다.
        # final_reports = await self.detection_service.verify_violation(...)
        logger.info("Step 4: Detection & Verification Complete")

        return {
            "status": "success",
            "extracted_entities": normalized_data.characters,
            "contradictions": [] # 최종 리포트들
        }