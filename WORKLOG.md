# WORKLOG — ContiCheck

Date: 2026-03-17
Branch: feature/backend-setup
HEAD commit: 64e913f
PR: https://github.com/phonepain/ms_sesac_final/pull/6

Summary:
- Phase0 (프로젝트 스캐폴딩) 및 Phase1 (문서 인제스트 + Mock Extraction) 구현 완료.
- 문단 기반 청킹, UUID source_id, chunk_index 포함, MockExtraction 규칙 기반 구현.

Tests:
- pytest backend/tests/test_extraction.py → 1 passed
- 주요 확인: chunk_index 전달, 문단 구조 유지, 캐릭터(철수, 영희) 추출

Files changed (주요):
- backend/app/services/ingest.py       — 문단 기반 청킹, source_id UUID 부여
- backend/app/services/extraction.py   — extract_from_chunk skeleton (LLM placeholder)
- backend/app/services/mock_extraction.py — 규칙 기반 캐릭터 추출
- backend/app/models/intermediate.py   — ExtractionResult에 chunk_index 포함
- backend/tests/test_extraction.py     — E2E 단위 테스트

Remaining / Next actions (우선순위):
1. Phase2 Normalization: 캐릭터 alias 통합, 사실 병합, SourceConflict 탐지 (우선: 캐릭터 병합 알고리즘 설계)
2. ExtractionResult/Chunk 모델 정제 (Chunk 중심 구조 고려)
3. Graph Materialization 설계 (Cosmos DB 파티션/키 정책)
4. LLM 통합(Extraction) 및 프롬프트 튜닝

Blockers / Notes:
- 현재 MockExtraction은 규칙 기반(한계 있음). KoNLPy/형태소 분석 또는 LLM 적용 권장.
- source_id를 UUID로 바꿨으므로 기존 데이터와 연동 시 유의.
- 테스트 재현: `pytest -s backend/tests/test_extraction.py` (출력 확인용 -s 옵션 권장)

How to resume (빠른 체크리스트):
- git checkout feature/backend-setup
- git pull origin feature/backend-setup
- python -m venv .venv && .venv\Scripts\activate (Windows) or source .venv/bin/activate
- pip install -r requirements.txt
- pytest -s backend/tests/test_extraction.py

Owner / Contact:
- 작업자: <작성자 이름>
- 다음 작업 담당자: <담당자 이름>
