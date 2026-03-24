# ContiCheck 프로젝트 진행 상황 v2

> **최종 업데이트**: 2026-03-24
> **이전 버전**: `conticheck-project-status.md` (2026-03-21)
> **변경 내용**: 백엔드 구현 완료 반영, 단일 그래프 결정, 오늘 수정된 materialize() 버그픽스 반영

---

## 1. 프로젝트 개요

**ContiCheck**는 드라마/영화/게임/소설 시나리오의 설정 오류를 AI가 자동으로 탐지하는 시스템입니다.

### 핵심 워크플로우

```
[1단계: 지식 베이스 구축]
  사용자가 세계관/설정집/시나리오를 분류하여 TXT/PDF 업로드
  → StorageService에 원본 파일 영구 저장
  → 파싱/청킹 (IngestService)
  → ExtractionService → RawEntity 추출
  → NormalizationService → NormalizedEntity 정규화
  → GraphService.materialize() → 단일 Cosmos DB 컨테이너 적재 (KB 구축)
  → SearchService.index_chunks() → 검색 인덱싱
  ※ 업로드 시 즉시 KB 구축 완료 (별도 build 트리거 불필요)
  ※ 캐릭터/사실 중복 upsert 처리 (2026-03-24 수정)

[2단계: 모순 탐지]
  In-Memory 스냅샷으로 canonical graph 격리 → 7가지 모순 유형 탐지
  → Hard Contradiction: 자동 판정 (confidence 무관)
  → Soft Inconsistency: 사용자 확인 요청 (원본 발췌 함께 표시)
  ※ 정보 비대칭: bi-gram 유사도 매칭으로 fact 연결 (2026-03-24 수정)

[3단계: 수정 반영]
  모순 수정 → 스테이징(Commit) → 일괄 반영(Push)
  → StorageService에 버전별 스냅샷 저장 → GraphRAG 재구축 → 버전 관리
```

### 탐지하는 모순 7가지

| # | 유형 | 설명 | Hard/Soft |
|---|------|------|-----------|
| 1 | 정보 비대칭 | 캐릭터가 아직 모르는 정보를 언급 | story_order 확정 시 Hard |
| 2 | 타임라인 | 사망 후 등장, 동시 존재 불가 | story_order 확정 시 Hard |
| 3 | 관계 | 관계 설정 충돌 | critical=Hard, warning=Soft |
| 4 | 성격·설정 | 확립된 설정과 행동 불일치 | immutable=Hard, mutable=Soft |
| 5 | 감정 일관성 | 이벤트 없는 감정 급변 | Soft |
| 6 | 소유물 추적 | 유일 아이템 중복 소유, 분실 후 재소유 | 중복=Hard, 재소유=Soft |
| 7 | 거짓말·기만 | 진실 인지 후에도 거짓 기반 행동 | Hard |

### 기술 스택

| 영역 | 기술 |
|------|------|
| Backend | Python 3.12, FastAPI, LangGraph |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Database | Azure Cosmos DB (Gremlin API) — **단일 컨테이너** (scenario-graph) |
| Search | Azure AI Search — 벡터 + 키워드 하이브리드 |
| Storage | Azure Blob Storage — 원본 파일 + 버전별 스냅샷 (로컬 폴백: 파일시스템) |
| LLM | Azure OpenAI (GPT-5-nano 계열 추출/검증용) |
| Infra | Azure 전체 |

---

## 2. 구현 완료 현황 (2026-03-24 기준)

### ✅ Phase 0 — 프로젝트 스캐폴딩

- `backend/app/main.py`: FastAPI 앱 + 전체 엔드포인트
- `backend/app/config.py`: 환경변수 로딩 (pydantic-settings)
- `backend/app/models/`: 9 Vertex + 13 Edge + 중간 데이터 + API 모델 (Pydantic v2)
- `.env.example`: 환경변수 템플릿
- `data/uploads/`, `data/versions/`: 로컬 스토리지 디렉토리

### ✅ Phase 1 — Extraction + Storage

- `storage.py`: BlobStorageService / LocalStorageService 전환 (USE_LOCAL_STORAGE)
- `ingest.py`: TXT/PDF 파싱 + 500토큰 청킹 (100 오버랩) + 대본 형식 감지
- `extract_entities.py`: 소스 분류별 프롬프트 (worldview/settings/scenario)
- `extraction.py`: LLM 배치 추출 + mock fallback (API 키 없으면 자동 전환)

### ✅ Phase 2 — Normalization

- `normalization.py`: 캐릭터 통합 (bi-gram 유사도 + LLM 보조), 사실 병합, 소스 충돌 감지
- `normalize_entities.py`: 정규화 프롬프트

### ✅ Phase 3 — Graph Materialization

- `graph.py`: GremlinGraphService (Azure Cosmos DB) + InMemoryGraphService (로컬/테스트)
  - 9종 Vertex CRUD + 13종 Edge 추가
  - `materialize()`: NormalizationResult → Vertex/Edge 적재
    - **[2026-03-24 수정]** 캐릭터 upsert: 이름으로 기존 캐릭터 먼저 검색, 있으면 재사용
    - **[2026-03-24 수정]** Fact upsert: content 기준 기존 fact 검색, 있으면 재사용
    - **[2026-03-24 수정]** `_find_similar_fact()`: bi-gram Jaccard 유사도로 fact 매칭 (정보 비대칭 탐지용)
  - `snapshot_graph()`: canonical → InMemory 복제 (격리 보장)
  - 이중 시간 축: discourse_order 자동 부여, story_order 추정/null, 비선형 감지
  - 7종 위반 탐지 쿼리: find_knowledge/timeline/relationship/trait/emotion/item/deception_violations()
  - `find_all_violations()`: Hard/Soft 분류 통합

### ✅ Phase 4 — Contradiction Detection

- `detection.py`: Hard/Soft 분류, Soft LLM 검증 (confidence≥0.8 자동, 미만 사용자 확인)
- `verify_contradiction.py`: 검증 프롬프트 (의도성 판단 금지, 보수적 confidence)
- `agent.py`: LangGraph 5노드 파이프라인 (extract→normalize→snapshot→materialize→detect→respond)

### ✅ Phase 5 — Review Workflow

- `confirmation.py`: ConfirmationService — 생성, 조회, 해결 + 피드백 루프
- `version.py`: VersionService — stage/unstage/push + StorageService 연동 버전 스냅샷

### ✅ Phase 6 — Azure AI Search

- `search.py`: SearchService (벡터+키워드) + MockSearchService (문자열 매칭)

### ✅ Phase 7 — FastAPI 엔드포인트

전체 엔드포인트 구현 완료. 상세 내용: `docs/api-endpoint-status-v2.md`

### ✅ Phase 8 — 프론트엔드 연동

- React + TypeScript + Tailwind CSS 구현 완료
- `App.tsx`: 마운트 시 4개 API 자동 로드 (sources, stats, versions, confirmations)
- 더미 데이터 제거, 실제 서버 데이터 표시

### ✅ Phase 9 — 샘플 데이터 + 통합 테스트

- 샘플 파일 3종 (`data/sample/`): 세계관 / 설정집 / 시나리오
- 단위 테스트: **99/99** 통과 (pytest, InMemory + MockSearch + LocalStorage)
- Azure E2E 통합 테스트: **15/15** 통과 (실 Cosmos DB + Blob Storage)

---

## 3. 아키텍처 결정 사항

### [2026-03-21 이전] 기존 결정 (conticheck-project-status.md §5 참조)
의사결정 #1~28은 이전 문서에서 그대로 유효합니다.

### [2026-03-23] 신규 결정

| # | 결정 사항 | 이유 |
|---|----------|------|
| 29 | **단일 그래프 컨테이너** | CLAUDE.md의 2트랙(ws-graph/scenario-graph) 분리 폐기. 단일 `scenario-graph` 컨테이너로 세계관/설정집/시나리오 모두 적재. 구현 복잡도 감소 + 소스 간 모순 탐지 직접 연결 |
| 30 | **upload 즉시 KB 구축** | `/api/graph/build` 별도 트리거 없이 업로드 요청 내에서 Extract→Normalize→Materialize→Index 연속 실행 (동기, `/api/graph/build`는 더미 유지) |

### [2026-03-24] 신규 결정

| # | 결정 사항 | 이유 |
|---|----------|------|
| 31 | **캐릭터 upsert (이름 기준)** | 파일 별도 업로드 시 동일 캐릭터가 다른 ID로 중복 생성되어 모든 edge 기반 모순 탐지가 동작하지 않는 버그 수정. materialize() step 1에서 find_character_by_name()으로 먼저 조회 |
| 32 | **Fact upsert (content 기준)** | 동일 내용의 fact가 업로드마다 새 vertex로 생성되어 LEARNS/MENTIONS가 서로 다른 fact를 가리키는 버그 수정 |
| 33 | **bi-gram Jaccard 유사도 fact 매칭** | LEARNS의 fact_content("범인임을 알았다")와 MENTIONS의 fact_content("범인이야")가 정확히 일치하지 않아도 threshold≥0.5이면 같은 fact vertex 재사용 → 정보 비대칭 탐지 가능 |

---

## 4. 알려진 제한 사항

| 항목 | 내용 | 우선순위 |
|------|------|---------|
| `/api/graph/build` | 더미 (실제 파이프라인 미연결) | 낮음 — upload가 즉시 KB 구축하므로 불필요 |
| `/api/graph/status` | 더미 | 낮음 |
| `/api/characters/{id}/knowledge` | 더미 (빈 목록 반환) | 중간 |
| 정보 비대칭 탐지 | fact content가 bi-gram 유사도 0.5 미만이면 미탐지 가능 | 중간 |
| Extraction 프롬프트 | few-shot 예제 미포함, LLM 추출 품질 의존 | 중간 |
| LLM 추출 | Azure OpenAI 미연결 시 regex 기반 mock 자동 전환 | 낮음 |

---

## 5. 환경 변수 (config.py 실제 기본값 기준)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `USE_LOCAL_GRAPH` | `true` | true=InMemoryGraphService, false=GremlinGraphService |
| `USE_LOCAL_STORAGE` | `true` | true=로컬 파일시스템, false=Azure Blob |
| `USE_MOCK_EXTRACTION` | `false` | true=regex mock, false=Azure OpenAI (키 없으면 자동 mock) |
| `USE_MOCK_SEARCH` | `false` | true=문자열 매칭 mock, false=Azure AI Search |
| `COSMOS_ENDPOINT` | `wss://localhost:8901/gremlin` | Gremlin 엔드포인트 |
| `COSMOS_CONTAINER` | `scenario-graph` | **단일 컨테이너** (ws-graph 분리 없음) |
| `AZURE_OPENAI_EXTRACTION_DEPLOYMENT` | `gpt-5.4-mini` | 추출/정규화용 |
| `AZURE_OPENAI_DETECTION_DEPLOYMENT` | `gpt-5.3-chat` | 검증용 |

---

## 6. 테스트 현황

| 테스트 | 상태 | 비고 |
|--------|------|------|
| 단위/통합 테스트 (pytest) | **99/99** ✅ | InMemory + MockSearch + LocalStorage |
| Azure E2E 통합 테스트 | **15/15** ✅ | 실 Cosmos DB + Blob + OpenAI |
| LLM 게이트 테스트 (`@pytest.mark.llm`) | 보류 | API 키 확보 후 실행 |

---

## 7. 파일 구조

```
backend/
├── app/
│   ├── main.py              # FastAPI 앱 + 전체 엔드포인트
│   ├── config.py            # 환경변수 (pydantic-settings)
│   ├── models/
│   │   ├── vertices.py      # 9 Vertex 모델
│   │   ├── edges.py         # 13 Edge 모델 + RELATIONSHIP_CONFLICT_MATRIX
│   │   ├── enums.py         # 열거형 14종 + 기반 클래스
│   │   ├── intermediate.py  # RawEntity, NormalizedEntity, ContradictionVerification
│   │   └── api.py           # API 입출력 모델
│   ├── services/
│   │   ├── storage.py       # BlobStorageService / LocalStorageService
│   │   ├── ingest.py        # 문서 파싱 + 청킹
│   │   ├── extraction.py    # 계층1: LLM 추출 + mock
│   │   ├── normalization.py # 계층2: 정규화/통합
│   │   ├── graph.py         # 계층3: Gremlin + InMemory (upsert 수정됨)
│   │   ├── detection.py     # 계층4: Hard/Soft 분류 + LLM 검증
│   │   ├── confirmation.py  # 계층5: 사용자 확인 관리
│   │   ├── version.py       # 계층5: 버전 관리
│   │   ├── search.py        # Azure AI Search + Mock
│   │   └── agent.py         # LangGraph 오케스트레이터
│   └── prompts/
│       ├── extract_entities.py     # 소스 분류별 추출 프롬프트
│       ├── normalize_entities.py   # 정규화 프롬프트
│       └── verify_contradiction.py # 모순 검증 프롬프트
├── tests/
│   ├── test_e2e.py          # 5계층 통합 테스트 (99/99)
│   └── api_e2e_test.py      # Azure 실 연동 E2E (15/15)
└── requirements.txt
```
