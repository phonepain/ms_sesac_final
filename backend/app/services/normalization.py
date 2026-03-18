# backend/app/services/normalization.py
import structlog
import json
from typing import List
from openai import AsyncAzureOpenAI

from app.config import settings
from app.models.intermediate import ExtractionResult, NormalizationResult, NormalizedCharacter
from app.prompts.normalize_entities import NORMALIZE_PROMPT

logger = structlog.get_logger()

class NormalizationService:
    def __init__(self):
        # 정규화에서도 LLM의 추론 능력이 필요하므로 클라이언트 초기화
        self.client = AsyncAzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        self.deployment_name = settings.AZURE_OPENAI_NORMALIZATION_DEPLOYMENT

    async def normalize(self, extractions: List[ExtractionResult]) -> NormalizationResult:
        """계층 2: 중복 캐릭터 통합, 유사 사실 병합"""
        logger.info("Starting normalization process", chunk_count=len(extractions))
        
        # 1. 모든 청크에서 뽑힌 RawCharacter들을 한 리스트로 모음
        all_raw_characters =[]
        for ext in extractions:
            all_raw_characters.extend(ext.characters)
            
        # 2. LLM에게 넘겨줄 수 있도록 JSON 문자열로 변환
        raw_chars_json = json.dumps([c.model_dump() for c in all_raw_characters], ensure_ascii=False)
        prompt = NORMALIZE_PROMPT.format(json_data=raw_chars_json)
        
        # 3. LLM을 호출하여 '동일 인물 통합(Merge)'을 지시 (이때 모델 스키마의 일부를 재활용하거나 새 모델 정의 가능)
        try:
            # (이번엔 NormalizationResult 스키마 전체를 강제하여 응답받습니다)
            response = await self.client.beta.chat.completions.parse(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 데이터 정규화(Normalization) 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                response_format=NormalizationResult
            )
            
            result: NormalizationResult = response.choices[0].message.parsed
            
            # (TODO: 향후 Facts 통합, Source 충돌 감지 로직도 여기에 추가)
            
            return result
            
        except Exception as e:
            logger.error("Normalization failed", error=str(e))
            return NormalizationResult()