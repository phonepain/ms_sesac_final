# backend/app/services/extraction.py
import structlog
from typing import List
from openai import AsyncAzureOpenAI

from app.config import settings
from app.models.intermediate import ExtractionResult
from app.prompts.extract_entities import WORLDVIEW_PROMPT, SETTINGS_PROMPT, SCENARIO_PROMPT

logger = structlog.get_logger()

class ExtractionService:
    def __init__(self):
        # Mocking 모드가 아닐 때만 Azure Client 초기화
        if not settings.use_mock_extraction:
            self.client = AsyncAzureOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION
            )
            self.deployment_name = settings.AZURE_OPENAI_EXTRACTION_DEPLOYMENT

    async def extract_from_chunk(self, text: str, source_type: str, chunk_id: str) -> ExtractionResult:
        """계층 1: 원고 청크에서 인물, 사건, 관계 등을 LLM으로 추출"""
        
        # 1. Mock 모드 동작
        if settings.use_mock_extraction:
            logger.info("Using mock extraction", chunk_id=chunk_id)
            return ExtractionResult(source_chunk_id=chunk_id)

        # 2. 소스 타입별 프롬프트 선택
        if source_type == "worldview":
            prompt_template = WORLDVIEW_PROMPT
        elif source_type == "settings":
            prompt_template = SETTINGS_PROMPT
        else:
            prompt_template = SCENARIO_PROMPT
            
        prompt = prompt_template.format(text=text)
        
        # 3. Azure OpenAI 호출 (Structured Outputs 강제)
        try:
            logger.info("Calling Azure OpenAI for extraction", chunk_id=chunk_id)
            response = await self.client.beta.chat.completions.parse(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 서사 작품 분석 전문가입니다. 주어진 텍스트에서 지정된 JSON 스키마에 맞게 정보를 완벽히 추출하세요."},
                    {"role": "user", "content": prompt}
                ],
                response_format=ExtractionResult,
            )
            
            result: ExtractionResult = response.choices[0].message.parsed
            result.source_chunk_id = chunk_id
            return result
            
        except Exception as e:
            logger.error("Extraction failed", chunk_id=chunk_id, error=str(e))
            # 파이프라인 중단 방지용 빈 객체 반환
            return ExtractionResult(source_chunk_id=chunk_id)