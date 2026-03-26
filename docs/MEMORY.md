# Memory Index — ContiCheck Project

## Project Final Status
- [project_final_status.md](./project_final_status.md) — 프로젝트 최종 상태 요약: 구현 완료, 성능, 배포 준비 (2026-03-26)

## Architecture Decisions
- [project_single_graph_decision.md](./project_single_graph_decision.md) — 단일 그래프 결정 (2026-03-23)
- [project_world_rule_detection_decision.md](./project_world_rule_detection_decision.md) — 세계 규칙 LLM 교체 결정 (C안: LLM 교체 + Soft 병렬화)
- [project_cosmos_db_connection_2026_03_21.md](./project_cosmos_db_connection_2026_03_21.md) — Cosmos DB Gremlin 연결 설정

## Deferred Work
- [project_incremental_rebuild_deferred.md](./project_incremental_rebuild_deferred.md) — 증분 재구축 설계 메모 — 데모 이후 작업

## Feedback
- [feedback_no_sanitize_original.md](./feedback_no_sanitize_original.md) — 원고 텍스트 임의 변경 금지 (content_filter 대응 포함)

## Troubleshooting Log (세션별 작업 기록)

### 초기 구축 (03-20 ~ 03-22)
- [project_code_review_2026_03_20.md](./project_code_review_2026_03_20.md) — Phase 0~7 전체 코드 리뷰, 버그 7건 식별
- [project_backend_full_analysis_2026_03_21.md](./project_backend_full_analysis_2026_03_21.md) — 백엔드 의존성 구조 분석, 확정 오류 14건, 수정 순서
- [project_session_2026_03_21_v2.md](./project_session_2026_03_21_v2.md) — 더미 엔드포인트 연결 + 버그 목록 (C-1~L-3)
- [project_session_2026_03_21_v3.md](./project_session_2026_03_21_v3.md) — E2E 테스트 88/88 통과, NormalizationResult 수정
- [project_session_2026_03_22.md](./project_session_2026_03_22.md) — 백엔드 전면 버그 수정, 99/99 테스트 통과

### Azure 통합 (03-23)
- [project_session_2026_03_23.md](./project_session_2026_03_23.md) — Azure E2E 통합, Gremlin 재연결, blob URL 디코딩, 15/15 API 테스트
- [project_session_2026_03_23_b.md](./project_session_2026_03_23_b.md) — g.E()→g.V().outE() Cosmos 호환, 다중 컨테이너 라우팅 (이후 단일 그래프로 변경)
- [project_session_2026_03_23_frontend.md](./project_session_2026_03_23_frontend.md) — 프론트 서버 데이터 자동 로드 (useEffect)

### 탐지 고도화 (03-24)
- [project_session_2026_03_24.md](./project_session_2026_03_24.md) — 신규 탐지기 2종 (event consistency, world rule)
- [project_session_2026_03_24_b.md](./project_session_2026_03_24_b.md) — Reset All, 이름 변경, AI 질의 개선
- [project_session_2026_03_24_c.md](./project_session_2026_03_24_c.md) — 평가 프레임워크 초안, 탐지 버그 수정, F1 66.7%
- [project_session_2026_03_24_d.md](./project_session_2026_03_24_d.md) — 코드 vs 온톨로지 스키마 분석, edges.py dead code 발견

### 성능 최적화 (03-25)
- [project_session_2026_03_25.md](./project_session_2026_03_25.md) — content_filter 스킵, 세계 규칙 LLM 교체, Soft 병렬화
- [project_session_2026_03_25_b.md](./project_session_2026_03_25_b.md) — Hard 승격 로직 수정, 세계 규칙 3중 중복 제거
- [project_session_2026_03_25_c.md](./project_session_2026_03_25_c.md) — Fix→Push chunk_id 리팩토링, 프론트 표시 버그 3건
- [project_session_2026_03_25_d.md](./project_session_2026_03_25_d.md) — find_fact_event_violations 이동 오분류 수정

### 최종 안정화 (03-26)
- [project_session_2026_03_26.md](./project_session_2026_03_26.md) — dedup 강화, 탐지율 71%→98%, 테스트 인프라 정비
- [project_session_2026_03_26_b.md](./project_session_2026_03_26_b.md) — Soft 원문 전달, 피드백 루프 9종, Push 파이프라인 전면 수정, Azure 검증
- [project_session_2026_03_26_c.md](./project_session_2026_03_26_c.md) — 추출 프롬프트 12패턴 강화, 평가 프레임워크 57케이스/703건
- [project_session_2026_03_26_d.md](./project_session_2026_03_26_d.md) — chunk_id 파이프라인 전면 개선, Diff 버그, 프론트 재업로드 제거, Azure E2E 검증
