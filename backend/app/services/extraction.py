# backend/app/services/extraction.py
import asyncio
import structlog
import json
from typing import List
from openai import AsyncAzureOpenAI
from app.config import settings
from app.models.intermediate import ExtractionResult
from app.models.api import DocumentChunk # DocumentChunk 모델 추가
from app.prompts.extract_entities import WORLDVIEW_PROMPT, SETTINGS_PROMPT, SCENARIO_PROMPT

logger = structlog.get_logger(__name__)

class ExtractionService:
    def __init__(self):
        # 1. 병렬 처리를 위한 세마포어 설정 (한 번에 최대 10개만 API 호출)
        # Azure OpenAI의 분당 요청 제한(RPM)에 맞춰 조절하세요.
        self.semaphore = asyncio.Semaphore(10)
        
        if not settings.use_mock_extraction:
            self.client = AsyncAzureOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION
            )
            self.deployment_name = settings.AZURE_OPENAI_EXTRACTION_DEPLOYMENT

    async def extract_from_chunks(self, chunks: List[DocumentChunk], source_type: str) -> List[ExtractionResult]:
        """[신규] 100페이지 이상의 대량 청크를 병렬로 처리합니다."""
        logger.info("Starting batch extraction", total_chunks=len(chunks), source_type=source_type)
        
        # 모든 청크에 대해 비동기 작업을 생성
        tasks = [self.extract_from_chunk(c.content, source_type, c.id) for c in chunks]
        
        # 병렬로 실행하고 모든 결과가 돌아올 때까지 기다림
        results = await asyncio.gather(*tasks)
        
        logger.info("Batch extraction complete", total_results=len(results))
        return list(results)

    async def extract_from_chunk(self, text: str, source_type: str, chunk_id: str) -> ExtractionResult:
        """계층 1: 단일 청크에서 정보를 추출 (세마포어 적용)"""
        
        # 세마포어를 사용하여 동시 호출 수 제한
        async with self.semaphore:
            if settings.use_mock_extraction:
                return ExtractionResult(source_chunk_id=chunk_id)

            # 프롬프트 선택
            if source_type == "worldview":
                prompt_template = WORLDVIEW_PROMPT
            elif source_type == "settings":
                prompt_template = SETTINGS_PROMPT
            else:
                prompt_template = SCENARIO_PROMPT
                
            prompt = prompt_template.format(text=text)
            
            try:
                logger.debug("Calling LLM", chunk_id=chunk_id)
                response = await self.client.beta.chat.completions.parse(
                    model=self.deployment_name,
                    messages=[
                        {"role": "system", "content": "당신은 서사 작품 분석 전문가입니다. 주어진 텍스트에서 지정된 JSON 스키마에 맞게 정보를 완벽히 추출하세요."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format=ExtractionResult,
                )
                
                # 안전한 파싱 로직
                try:
                    result = response.choices[0].message.parsed
                    if result is None:
                        # 파싱 실패 시 텍스트 내용으로 직접 로드 시도
                        content = response.choices[0].message.content
                        data = json.loads(content)
                        result = ExtractionResult(**data)
                except Exception as e:
                    logger.error("JSON parsing error", chunk_id=chunk_id, error=str(e))
                    result = ExtractionResult(source_chunk_id=chunk_id)

                result.source_chunk_id = chunk_id
                return result
                
            except Exception as e:
                logger.error("Extraction API error", chunk_id=chunk_id, error=str(e))
                return ExtractionResult(source_chunk_id=chunk_id)