# backend/app/services/normalization.py
import asyncio
import structlog
import json
from typing import List, Set
from openai import AsyncAzureOpenAI

from app.config import settings
from app.models.intermediate import (
    ExtractionResult, NormalizationResult, NormalizedCharacter, 
    NormalizedFact, RawCharacter, RawFact
)
from app.prompts.normalize_entities import NORMALIZE_PROMPT

logger = structlog.get_logger(__name__)

class NormalizationService:
    def __init__(self):
        self.client = AsyncAzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        self.deployment_name = settings.AZURE_OPENAI_NORMALIZATION_DEPLOYMENT

    async def normalize(self, extractions: List[ExtractionResult]) -> NormalizationResult:
        """[계층 2] 대량의 추출 결과물을 통합 정규화합니다."""
        logger.info("Starting Global Normalization", chunk_count=len(extractions))
        
        # 1. 모든 청크의 데이터를 유형별로 수집
        all_raw_chars: List[RawCharacter] = []
        all_raw_facts: List[RawFact] = []
        for ext in extractions:
            all_raw_chars.extend(ext.characters)
            all_raw_facts.extend(ext.facts)

        # 2. 캐릭터와 사실 통합을 병렬로 처리 (시간 단축)
        char_task = self._normalize_characters(all_raw_chars)
        fact_task = self._normalize_facts(all_raw_facts)
        
        normalized_chars, normalized_facts = await asyncio.gather(char_task, fact_task)
        
        return NormalizationResult(
            characters=normalized_chars,
            facts=normalized_facts
        )

    async def _normalize_characters(self, raws: List[RawCharacter]) -> List[NormalizedCharacter]:
        """수만 개의 캐릭터 파편을 지능적으로 통합합니다."""
        if not raws: return []

        # [대용량 최적화] 동일한 이름은 사전 병합하여 LLM에 보낼 토큰을 줄입니다.
        unique_names_map = {}
        for r in raws:
            if r.name not in unique_names_map:
                unique_names_map[r.name] = r.role_hint
        
        # LLM에게는 중복 없는 이름 리스트만 보냅니다.
        logger.info("Simplifying characters for LLM", unique_count=len(unique_names_map))
        prompt = NORMALIZE_PROMPT.format(json_data=json.dumps(unique_names_map, ensure_ascii=False))
        
        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 데이터 정규화 전문가입니다. 동일 인물을 찾아 그룹화하세요."},
                    {"role": "user", "content": prompt}
                ],
                response_format=NormalizationResult # 캐릭터 리스트 스키마 활용
            )
            
            result: NormalizationResult = response.choices[0].message.parsed
            
            # 3. 통합된 결과에 원본 Raw 데이터(merged_from)를 다시 매핑 (계보 추적)
            for nc in result.characters:
                # canonical_name이나 aliases에 포함된 모든 Raw 데이터를 찾음
                nc.merged_from = [
                    r for r in raws 
                    if r.name == nc.canonical_name or r.name in nc.all_aliases
                ]
            
            return result.characters
            
        except Exception as e:
            logger.error("Character normalization failed", error=str(e))
            return []

    async def _normalize_facts(self, raws: List[RawFact]) -> List[NormalizedFact]:
        """[가이드 반영] 사실 정보의 유사도 병합 및 Fact vs Trait 분류"""
        if not raws: return []
        
        # TODO: 임베딩 기반 유사도 체크 로직이 들어갈 자리입니다.
        # 현재는 내용이 100% 일치하는 것만 합치는 로직으로 구현합니다.
        fact_map = {}
        for r in raws:
            if r.content not in fact_map:
                fact_map[r.content] = NormalizedFact(
                    content=r.content,
                    category=r.category_hint or "world_fact",
                    merged_from=[r]
                )
            else:
                fact_map[r.content].merged_from.append(r)
        
        return list(fact_map.values())