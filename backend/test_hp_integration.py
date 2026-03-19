# backend/test_hp_integration.py
import asyncio
import os
import structlog
from dotenv import load_dotenv

# 1. 환경변수 로드
load_dotenv()

from app.services.ingest import IngestService
from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.config import settings

logger = structlog.get_logger()

async def main():
    print("🪄 [Harry Potter 통합 테스트] 시스템 가동...")
    
    # 서비스 초기화
    ingest_svc = IngestService()
    extract_svc = ExtractionService()
    normalize_svc = NormalizationService()

    file_path = "HP.pdf" # 파일이 backend 폴더에 있어야 합니다.
    
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return

    # --- 1단계: Ingest (PDF 읽기 및 청킹) ---
    print("\n📖 1. 파일 읽기 및 청킹 중...")
    with open(file_path, "rb") as f:
        content = f.read()
    
    # 전체를 다 하면 비용이 많이 드니 앞부분 10개 청크만 테스트해봅니다.
    chunks = await ingest_svc.process_file(content, file_path, "src-hp-001")
    test_chunks = chunks[:350] # 앞부분 약 5~10페이지 분량
    print(f"✅ 총 {len(chunks)}개 청크 중 상위 {len(test_chunks)}개 추출 시작")

    # --- 2단계: Extraction (병렬 정보 추출) ---
    print("\n🔍 2. LLM 병렬 정보 추출 시작 (gpt-5-mini)...")
    # source_type을 'scenario' 혹은 'settings'로 가정하여 추출합니다.
    extractions = await extract_svc.extract_from_chunks(test_chunks, source_type="scenario")
    
    total_raw_chars = sum(len(e.characters) for e in extractions)
    print(f"✅ 추출 완료: 총 {total_raw_chars}개의 캐릭터 조각 발견")

    # --- 3단계: Normalization (전체 데이터 통합) ---
    print("\n🧹 3. 데이터 정규화 및 통합 시작 (Global Normalization)...")
    normalization_result = await normalize_svc.normalize(extractions)
    
    print("\n" + "="*60)
    print("🏆 [최종 통합 결과: 마법사 명단]")
    print("="*60)
    
    for char in normalization_result.characters:
        print(f"👤 대표 이름: {char.canonical_name}")
        print(f"   - 별칭: {', '.join(char.all_aliases)}")
        print(f"   - 역할: {char.description}")
        print(f"   - 등장 횟수: {len(char.merged_from)}번의 청크에서 언급됨")
        # 어떤 이름들로 불렸는지 확인
        original_names = set([m.name for m in char.merged_from])
        print(f"   - 원문 표기들: {list(original_names)}")
        print("-" * 40)

    print(f"\n✅ 총 {len(normalization_result.characters)}명의 고유 캐릭터가 식별되었습니다.")

if __name__ == "__main__":
    asyncio.run(main())