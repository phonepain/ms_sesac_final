import structlog
from typing import Dict, Any, Optional
from openai import AsyncAzureOpenAI

from app.config import settings
from app.models.intermediate import ContradictionVerification
from app.prompts.verify_contradiction import CONTRADICTION_PROMPT

logger = structlog.get_logger()

class DetectionService:
    def __init__(self):
        # API 설정 확인
        if not settings.AZURE_OPENAI_API_KEY:
            logger.error("Azure OpenAI API Key is missing!")
            
        self.client = AsyncAzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION
        )
        # 탐지/추론에는 가장 성능이 좋은 5.3-chat 모델 사용
        self.deployment_name = settings.AZURE_OPENAI_DETECTION_DEPLOYMENT

    async def verify_violation(self, violation_data: Dict[str, Any]) -> ContradictionVerification:
        """
        그래프 엔진에서 발견된 모순 후보를 LLM이 정밀 검증합니다.
        """
        logger.info("Starting LLM verification for violation", violation_type=violation_data.get("type"))
        
        # 프롬프트 구성
        prompt = CONTRADICTION_PROMPT.format(violation_data=str(violation_data))
        
        try:
            # Azure OpenAI Structured Outputs 호출
            response = await self.client.beta.chat.completions.parse(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "당신은 서사 정합성 및 논리 구조 분석 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                response_format=ContradictionVerification,
                # 추론 모델은 기본 temperature(1) 사용 권장 (또는 필요시 0.3 정도로 낮춤)
            )
            
            verification_result = response.choices[0].message.parsed
            logger.info("LLM Verification complete", 
                        is_contradiction=verification_result.is_contradiction,
                        confidence=verification_result.confidence)
            
            return verification_result
            
        except Exception as e:
            logger.error("LLM Verification failed", error=str(e))
            # 에러 발생 시 시스템이 멈추지 않도록 '검토 필요' 상태의 기본 응답 반환
            return ContradictionVerification(
                is_contradiction=True,
                confidence=0.0,
                severity="major",
                reasoning=f"검증 엔진 내부 오류로 자동 분석 실패: {str(e)}",
                user_question="시스템 오류로 인해 수동 검토가 필요합니다."
            )