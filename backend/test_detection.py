import asyncio
import os
from dotenv import load_dotenv

# 1. 환경변수 로드
load_dotenv()

# 프로젝트 모듈 임포트
from app.services.detection import DetectionService
from app.config import settings

async def main():
    print("🚀 [계층 4: Detection] 모순 검증 테스트 시작...")
    print(f"▶️ [DEBUG] Endpoint: {settings.AZURE_OPENAI_ENDPOINT}")
    print(f"▶️ [DEBUG] Deployment: {settings.AZURE_OPENAI_DETECTION_DEPLOYMENT}")
    
    try:
        service = DetectionService()
    except Exception as e:
        print(f"❌ 서비스 초기화 실패: {e}")
        return

    # 2. 가상의 모순 후보 데이터 (Violation Data)
    # 그래프 DB가 "어? 이거 이상한데?" 하고 찾아낸 상황을 가정합니다.
    mock_violation_data = {
        "type": "timeline_violation",
        "character_name": "김반장",
        "conflict_summary": "캐릭터의 사망 후 재등장",
        "evidence_items": [
            {
                "source": "시나리오 1장 (페이지 10)",
                "content": "김반장은 총소리와 함께 바닥에 쓰러졌고, 의사는 그의 사망을 공식 확인했다.",
                "order": 1.0
            },
            {
                "source": "시나리오 3장 (페이지 45)",
                "content": "김반장은 사무실 의자에 앉아 여유롭게 커피를 마시며 서류를 검토하고 있다.",
                "order": 3.0
            }
        ],
        "is_linear_story": True  # 과거 회상이 아닌 순차적 진행임을 가정
    }
    
    print("\n[입력 데이터: 모순 후보 상황]")
    print(f"📍 유형: {mock_violation_data['conflict_summary']}")
    print(f"📍 증거 1: {mock_violation_data['evidence_items'][0]['content']}")
    print(f"📍 증거 2: {mock_violation_data['evidence_items'][1]['content']}")
    print("-" * 50)
    
    # 3. LLM 검증 실행
    print("⏳ Azure OpenAI (gpt-5.3-chat)가 논리 분석 중...")
    try:
        result = await service.verify_violation(violation_data=mock_violation_data)
        
        print("\n✅ 검증 완료! [분석 결과]")
        print(f"🔍 모순 여부: {'🔴 YES' if result.is_contradiction else '🟢 NO'}")
        print(f"🔍 확신도: {result.confidence}")
        print(f"🔍 심각도: {result.severity.upper()}")
        print(f"🔍 논리적 근거: {result.reasoning}")
        
        if result.suggestion:
            print(f"💡 수정 제안: {result.suggestion}")
        
        if result.user_question:
            print(f"❓ 사용자 확인 질문: {result.user_question}")
            
    except Exception as e:
        print(f"\n❌ 호출 중 에러 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())