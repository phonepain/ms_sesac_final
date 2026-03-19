# backend/test_e2e_pipeline.py
import nest_asyncio
nest_asyncio.apply()  # 👈 이미 돌고 있는 이벤트 루프 안에서 또 루프를 돌 수 있게 허용하는 마법!

import asyncio
import os
import structlog
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()
logger = structlog.get_logger()

# 앱 설정 로드
from app.config import settings

# 전체 5계층 서비스 임포트
from app.services.ingest import IngestService
from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.services.detection import DetectionService

# 팀원이 만든 실제 Azure Graph Service 임포트
from app.services.graph import GremlinGraphService
from app.models.vertices import Source
from app.models.enums import SourceType
from gremlin_python.process.anonymous_traversal import traversal

async def main():
    print("🚀 [ContiCheck E2E Pipeline] Phase 1~4 통합 테스트 시작...\n")
    
    # 0. 서비스 초기화
    ingest_svc = IngestService()
    extract_svc = ExtractionService()
    normalize_svc = NormalizationService()
    detect_svc = DetectionService()
    
    # ✅ 수정됨: 실제 Azure Cosmos DB 연결 인스턴스 생성
    print("🔗 Azure Cosmos DB(Gremlin)에 연결 중...")
    try:
        graph_svc = GremlinGraphService(
            endpoint=settings.cosmos_endpoint,
            key=settings.cosmos_key,
            database=settings.cosmos_database,
            container=settings.cosmos_container
        )
        print("🔗 DB 연결 성공!\n")
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        return

    file_path = "HP_stone_txt.pdf"
    
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return

    try:
        # ---------------------------------------------------------
        # [Phase 1] 파일 읽기 및 청킹 (Ingest)
        # ---------------------------------------------------------
        print("📖[Phase 1] 파일 읽기 및 청킹 중...")
        with open(file_path, "rb") as f:
            content = f.read()
        
        source_id = "src-hp-001"
        chunks = await ingest_svc.process_file(content, file_path, source_id)
        
        # 상위 10개 청크만 테스트
        test_chunks = chunks[:10] 
        print(f"✅ 총 {len(chunks)}개 청크 중 {len(test_chunks)}개 추출 진행\n")

        # ---------------------------------------------------------
        # [Phase 1.5] LLM 병렬 정보 추출 (Extraction)
        # ---------------------------------------------------------
        print("🔍[Phase 1.5] LLM 정보 추출 중 (gpt-5-mini)...")
        extractions = await extract_svc.extract_from_chunks(test_chunks, source_type="scenario")
        total_raw_chars = sum(len(e.characters) for e in extractions)
        print(f"✅ 추출 완료: 총 {total_raw_chars}개의 캐릭터 조각 및 팩트 발견\n")

        # ---------------------------------------------------------
        # [Phase 2] 데이터 정규화 및 통합 (Normalization)
        # ---------------------------------------------------------
        print("🧹 [Phase 2] 데이터 정규화 및 통합 중...")
        normalized_result = await normalize_svc.normalize(extractions)
        print(f"✅ 정규화 완료: {len(normalized_result.characters)}명의 고유 캐릭터로 통합됨\n")

        # ---------------------------------------------------------
        # [Phase 3] 그래프 DB 적재 (Graph Materialization)
        # ---------------------------------------------------------
        print("🗄️ [Phase 3] Azure Cosmos DB에 데이터 실제 적재 중...")
        # Materialize를 위해 Source 객체 생성
        source_obj = Source(
            source_id=source_id,
            source_type=SourceType.SCENARIO, 
            name=file_path, 
            metadata="{}"
        )
        
        # Graph에 적재 (Azure로 쿼리 전송)
        created_ids = graph_svc.materialize(normalized_result, source_obj)
        
        # ✅ 수정됨: graph_svc.vertices 대신 created_ids 딕셔너리를 확인
        total_nodes_created = len(created_ids.get("characters",[])) + len(created_ids.get("facts",[])) + 1
        print(f"✅ 그래프 적재 완료! (생성된 주요 노드 수: {total_nodes_created}개)\n")

        # ---------------------------------------------------------
        #[Phase 4-1] 모순 탐지 쿼리 실행 (Graph Detection)
        # ---------------------------------------------------------
        print("⚡ [Phase 4-1] 7가지 구조적 모순 쿼리 실행 중...")
        violations = graph_svc.find_all_violations()
        
        all_violations = violations.get("all",[])
        print(f"✅ 탐지 완료: 총 {len(all_violations)}개의 모순 후보 발견!\n")

        # ---------------------------------------------------------
        # [Phase 4-2] LLM 정밀 검증 (Verification)
        # ---------------------------------------------------------
        if len(all_violations) > 0:
            print("🕵️‍♂️ [Phase 4-2] LLM 탐정(gpt-5.3-chat)의 정밀 검증 시작...")
            for i, v_data in enumerate(all_violations, 1):
                print(f"\n--- 🚨 모순 후보 #{i} ({v_data.get('type')}) ---")
                print(f"발견 내용: {v_data.get('description')}")
                
                # LLM에게 팩트 체크 요청
                verification = await detect_svc.verify_violation(v_data)
                
                print(f"  👉 LLM 판정: {'🔴 모순 맞음 (YES)' if verification.is_contradiction else '🟢 모순 아님 (NO)'}")
                print(f"  👉 확신도: {verification.confidence} | 심각도: {verification.severity.upper()}")
                print(f"  👉 이유: {verification.reasoning}")
                if verification.user_question:
                    print(f"  ❓ 사용자 질문: {verification.user_question}")
        else:
            print("🎉 발견된 모순이 없습니다! 완벽한 시나리오입니다.")

    except Exception as e:
        print(f"\n❌ 파이프라인 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # 종료 전 DB 연결 안전하게 닫기
        print("\n🔌 DB 연결 종료 중...")
        try:
            graph_svc.close()
            print("🔌 DB 연결 안전하게 종료됨.")
        except:
            pass

if __name__ == "__main__":
    asyncio.run(main())