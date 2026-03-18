import asyncio
import os
from dotenv import load_dotenv

# 1. 환경변수 로드
load_dotenv()

# 2. 프로젝트 모듈 임포트
from app.services.normalization import NormalizationService
from app.models.intermediate import ExtractionResult, RawCharacter
from app.config import settings

async def main():
    print("🚀 [계층 2: Normalization] 테스트 시작...")
    print(f"▶️ [DEBUG] Endpoint: {settings.AZURE_OPENAI_ENDPOINT}")
    print(f"▶️ [DEBUG] Deployment: {settings.AZURE_OPENAI_NORMALIZATION_DEPLOYMENT}")
    
    try:
        service = NormalizationService()
    except Exception as e:
        print(f"❌ 서비스 초기화 실패: {e}")
        return

    # 3. 가짜(Mock) 추출 데이터 만들기
    # 계층 1(Extraction)에서 서로 다른 청크(페이지)에서 아래처럼 각각 추출되었다고 가정합니다.
    mock_extractions =[
        ExtractionResult(
            source_chunk_id="chunk-001",
            characters=[
                RawCharacter(name="형사A", possible_aliases=["A", "에이"], role_hint="사건 담당 형사"),
                RawCharacter(name="목격자C", possible_aliases=[], role_hint="사건 목격자")
            ]
        ),
        ExtractionResult(
            source_chunk_id="chunk-002",
            characters=[
                RawCharacter(name="김반장", possible_aliases=["형사A"], role_hint="경찰"),
                RawCharacter(name="C", possible_aliases=[], role_hint="편의점 알바생"),
                RawCharacter(name="범인B", possible_aliases=[], role_hint="용의자")
            ]
        )
    ]
    
    print("\n[입력 데이터: 파편화된 캐릭터 목록]")
    for ext in mock_extractions:
        for char in ext.characters:
            print(f" - 이름: {char.name} / 역할: {char.role_hint} / 출처: {ext.source_chunk_id}")
    print("-" * 50)
    
    # 4. 정규화(통합) 실행
    print("⏳ Azure OpenAI (gpt-5-mini)에게 캐릭터 통합 지시 중...")
    try:
        result = await service.normalize(extractions=mock_extractions)
        
        print("\n✅ 정규화 완료! [통합된 캐릭터 결과]")
        # Pydantic 객체를 JSON 문자열로 예쁘게 출력
        print(result.model_dump_json(indent=2, include={"characters"}))
        
    except Exception as e:
        print(f"\n❌ 호출 중 에러 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())