---
name: ContiCheck 최종 프로젝트 상태
description: "프로젝트 전체 구조, 구현 완료 상태, 성능, 배포 준비 현황 (2026-03-26 기준)"
type: project
---

## ContiCheck POC — 최종 상태 (2026-03-26)

### 프로젝트 개요
드라마/영화/게임/소설 시나리오의 모순을 자동으로 탐지하는 시스템 POC.
5계층 아키텍처 + 7가지 모순 유형 + Hard/Soft 분류 + 사용자 확인 워크플로우.

### 기술 스택
- **Backend**: Python 3.12, FastAPI, LangGraph
- **Frontend**: React 19 + TypeScript 5.9 + Tailwind CSS 4.2 + Vite 8
- **Database**: Azure Cosmos DB (Gremlin API) + InMemory 모드
- **Search**: Azure AI Search + Mock 모드
- **Storage**: Azure Blob Storage + Local 파일시스템
- **LLM**: Anthropic Claude Sonnet 4.6 (추출/탐지/검증)
- **인프라**: Azure 전체

### 구현 완료 현황

| 계층 | 파일 | LOC | 상태 |
|------|------|-----|------|
| Storage | storage.py | 733 | 완료 (Blob/Local 전환) |
| 1. Extraction | extraction.py + prompts | 714 | 완료 (12패턴 강화) |
| 2. Normalization | normalization.py | 524 | 완료 |
| 3. Graph | graph.py | 3,491 | 완료 (Gremlin + InMemory) |
| 4. Detection | detection.py | 1,202 | 완료 (구조적 7종 + LLM 2종) |
| 5. Review | confirmation.py + version.py | 1,720 | 완료 (9종 피드백 루프) |
| API | main.py | 752 | 완료 (25+ 엔드포인트) |
| Frontend | 18 TSX/TS 파일 | ~3,000 | 완료 (3탭 워크스페이스) |

### 핵심 파이프라인
```
Upload → Storage 저장 → 파싱/청킹 → Extract → Normalize → Materialize → Index
Scan → 구조적 쿼리 7종 + LLM 탐지 2종 → Hard/Soft 분류 → 리포트
Stage → Push → 텍스트 치환 → 버전 스냅샷 → 그래프 재구축 → 검색 재인덱싱
```

### 탐지 성능 (2026-03-26 기준)
- **탐지율**: 98% (평가 세트 기준)
- **F1 Score**: ~60% (교차 검증)
- **비용**: ~$10/전체 57케이스 1회 실행 (Claude Sonnet 4.6)
- **토큰**: ~1.7M 토큰/57케이스

### 평가 프레임워크
- 57개 테스트 케이스, 703건 모순 (Gold Standard)
- 카테고리: TRAIT_SETTING 464, TIMELINE_MOVE 62, PHYSICS_RULE 61, SECURITY_ITEM 36, INFO_ASYMMETRY 18, DEATH_REAPPEAR 16, OTHER 9
- 9개 pytest 모듈 + 16개 E2E 테스트 스크립트

### Azure E2E 검증 결과 (Mosoon_test.txt)
- Upload: 200 OK, 36 entities
- Scan: 7건 탐지, 전부 original_text 있음
- Stage/Push: 정상, v1 생성
- Version Content: 수정 반영 확인
- Diff: unified diff 정상 표시

### 프론트엔드 주요 기능
- 프로젝트 목록 사이드바 + 3탭 (개요/모순/버전)
- 모순 카드 (Hard/Soft 배지, 원문 표시, 수정 편집)
- 스테이징 → Push 워크플로우
- 버전 타임라인 + 원고 보기 + Diff 비교
- AI 질의 패널
- KB 통계 표시

### 환경 변수 (로컬/클라우드 전환)
| 변수 | 기본값 | 용도 |
|------|--------|------|
| `USE_LOCAL_GRAPH` | true | InMemory(dev) vs Cosmos DB(prod) |
| `USE_MOCK_EXTRACTION` | false | Mock 추출 (LLM 없이) |
| `USE_MOCK_SEARCH` | false | Mock 검색 |
| `USE_LOCAL_STORAGE` | true | 로컬 파일 vs Azure Blob |
| `ANTHROPIC_API_KEY` | - | Claude API 키 |
| `ANTHROPIC_MODEL` | claude-sonnet-4-6 | 모델 선택 |

### 배포 준비
- Dockerfile 존재 (backend/)
- .dockerignore 존재
- .env.example 존재
- Azure App Service 배포가 가장 간단한 경로
  - 필요: 프론트 API URL 패치 → 빌드 → FastAPI 정적 파일 서빙 → App Service 배포

### 디렉토리 구조 (핵심)
```
project_final/
├── backend/
│   ├── app/
│   │   ├── main.py, config.py
│   │   ├── models/ (vertices, edges, enums, intermediate, api)
│   │   ├── services/ (12 모듈)
│   │   └── prompts/ (5 프롬프트)
│   ├── tests/ (9 모듈)
│   ├── scripts/ (16 E2E + run_all)
│   ├── evaluation/ (gold standard + metrics)
│   └── Dockerfile
├── frontend/
│   └── src/ (pages, components, api, types)
├── data/sample/ (12 테스트 데이터셋)
└── docs/
```
