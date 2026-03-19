import asyncio
import os
from dotenv import load_dotenv

# 1. 🚨 가장 먼저 .env 파일을 강제로 읽어옵니다!
load_dotenv()

# 2. Mock 끄기 강제 설정
os.environ["USE_MOCK_EXTRACTION"] = "false"

# 3. 그 다음에 프로젝트 모듈들을 임포트합니다. (이때 config가 세팅됨)
from app.services.extraction import ExtractionService
from app.config import settings # 👈 추가된 부분

async def main():
    print("🚀 [계층 1: Extraction] 테스트 시작...")

        # 👇 추가된 디버깅 코드 (키 값 길이를 출력해 제대로 읽었는지 확인)
    print(f"▶️ [DEBUG] Endpoint: {settings.AZURE_OPENAI_ENDPOINT}")
    print(f"▶️ [DEBUG] Key Length: {len(settings.AZURE_OPENAI_API_KEY)}")
    print(f"▶️ [DEBUG] Deployment: {settings.AZURE_OPENAI_EXTRACTION_DEPLOYMENT}")
    
    # 1. ExtractionService 초기화
    try:
        service = ExtractionService()
    except Exception as e:
        print(f"❌ 서비스 초기화 실패 (환경변수 세팅을 확인하세요): {e}")
        return

    # 2. 테스트용 샘플 시나리오 텍스트 (그림자의 비밀 예시)
    sample_text = """
    # Scene 1. 동네 카페 (오후, 햇살이 따뜻하다)
    직원A: (웃으며) 손님, 두고 가신 지갑 여기 있습니다.
    손님B: 앗, 감사합니다! 정말 다행이네요. (안도하며 지갑을 받아 주머니에 넣는다)
    """
    
    print("\n[입력 텍스트]")
    print(sample_text.strip())
    print("-" * 50)
    
    # 3. 데이터 추출 실행
    print("⏳ Azure OpenAI (gpt-5-mini) 호출 중...")
    try:
        # source_type을 "scenario"로 지정하여 SCENARIO_PROMPT가 사용되게 함
        result = await service.extract_from_chunk(
            text=sample_text, 
            source_type="scenario", 
            chunk_id="chunk-test-001"
        )
        
        print("\n✅ 추출 완료! [Structured JSON 결과]")
        # Pydantic 객체를 보기 좋게 들여쓰기(indent=2)하여 JSON 문자열로 출력
        print(result.model_dump_json(indent=2))
        
    except Exception as e:
        print(f"\n❌ 호출 중 에러 발생: {e}")

if __name__ == "__main__":
    # 비동기 함수 실행
    asyncio.run(main())