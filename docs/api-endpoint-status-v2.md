# ContiCheck API 엔드포인트 상태 문서 v2

**작성일:** 2026-03-24
**이전 버전:** `api-endpoint-status.md` (2026-03-21)
**대상 파일:** `backend/app/main.py`

---

## 변경 요약 (v1 → v2)

| 항목 | v1 (2026-03-21) | v2 (2026-03-24) |
|------|----------------|----------------|
| 그래프 구조 | 2트랙 (ws-graph/scenario-graph) 계획 | 단일 컨테이너 (scenario-graph) 확정 |
| `PUT /api/sources/{id}` | 없음 | **신규** — 소스 재업로드 (파일 교체) |
| `DELETE /api/fixes/stage/{id}` | 없음 | **신규** — 스테이징 취소 |
| `StageFixRequest` | `contradiction_id, original_text, fixed_text` | `is_intentional, intent_note` 필드 추가 |
| `PushFixesRequest.source_id` | 필수 | **선택** (미전달 시 scenario 소스 자동 탐색) |
| `_run_graph()` 래퍼 | 없음 | gremlin_python ↔ asyncio 충돌 방지용 ThreadPoolExecutor 래퍼 추가 |
| materialize() | 항상 신규 생성 | 캐릭터/fact upsert 처리 (중복 방지) |
| 정보 비대칭 탐지 | fact 정확 일치만 | bi-gram 유사도 0.5≥ 매칭 추가 |

---

## 1. 전체 엔드포인트 목록

### 1-1. 소스 관리

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `POST` | `/api/sources/upload` | 파일 업로드 + KB 즉시 구축 | ✅ 실 연결 |
| `GET` | `/api/sources` | 소스 목록 (`?source_type=` 필터) | ✅ 실 연결 |
| `GET` | `/api/sources/{id}/download` | 원본 파일 다운로드 | ✅ 실 연결 |
| `DELETE` | `/api/sources/{id}` | 소스 삭제 + Storage 파일 삭제 | ✅ 실 연결 |
| `PUT` | `/api/sources/{id}` | **[신규]** 소스 재업로드 (파일 교체, source_id 유지) | ✅ 실 연결 |

#### POST /api/sources/upload

```
파라미터 (multipart/form-data):
  file: UploadFile          — TXT 또는 PDF (PDF는 5MB 제한)
  source_type: str          — "worldview" | "settings" | "scenario"

처리 흐름:
  1. IngestService.process_file() → Storage 저장 + 청킹
  2. Source vertex 생성 (file_path 포함)
  3. ExtractionService.extract_from_chunks()
  4. NormalizationService.normalize()
  5. graph.materialize()         ← 캐릭터/fact upsert (중복 방지)
  6. SearchService.index_chunks()

응답 (IngestResponse):
  { source_id, source_name, file_path, status, stats, extracted_entities }
```

#### PUT /api/sources/{source_id} [신규]

```
파라미터 (multipart/form-data):
  file: UploadFile          — 교체할 파일

처리 흐름:
  1. 기존 파일 Storage에서 삭제
  2. 새 파일 Storage 저장 + 청킹
  3. Source vertex file_path/name 업데이트 (patch_vertex)
  4. Search 인덱스 재구축
  5. Extract → Normalize → Materialize (동일 source_id)

응답 (IngestResponse): status="reuploaded"
```

---

### 1-2. GraphRAG 구축 (더미 유지)

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `POST` | `/api/graph/build` | 구축 시작 | ⚠️ 더미 |
| `GET` | `/api/graph/status` | 구축 상태 | ⚠️ 더미 |

**더미 유지 이유:** `POST /api/sources/upload`가 이미 즉시 KB 구축을 수행하므로 별도 build 트리거 불필요. 백그라운드 작업 인프라 없이 동기 실행 시 타임아웃 발생 가능성 있음.

---

### 1-3. 모순 탐지

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `POST` | `/api/analyze` | 원고 기반 분석 (스냅샷 격리) | ✅ 실 연결 |
| `POST` | `/api/scan` | canonical graph 전수조사 | ✅ 실 연결 |

#### POST /api/analyze

```
요청 (ManuscriptInput): { content: str, title: str }

처리 흐름 (LangGraph 5노드):
  extract → normalize → snapshot → materialize → detect → respond

스냅샷 격리:
  canonical graph → InMemory 복제 → 원고 데이터 적재 → 위반 탐지 → 복제본 폐기
  Soft confirmations만 canonical graph에 저장 (워크플로우 상태)

응답 (AnalysisResponse): { contradictions, confirmations, total, by_severity, by_type }
```

#### POST /api/scan

```
처리 흐름:
  DetectionService.full_scan(graph) → graph.find_all_violations()
  → 7가지 쿼리 → Hard/Soft 분류 → LLM Soft 검증

주의: _run_graph() 래퍼 없이 직접 동기 호출
      (scan은 gremlin 호출이 많으므로 느릴 수 있음)
```

---

### 1-4. 사용자 확인

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `GET` | `/api/confirmations` | 미해결 목록 | ✅ 실 연결 |
| `POST` | `/api/confirmations/{id}/resolve` | 해결 + 피드백 루프 | ✅ 실 연결 |

#### POST /api/confirmations/{id}/resolve

```
요청: { decision: str, user_response: str? }

decision 값:
  "confirmed_contradiction" → ContradictionReport 생성
  "confirmed_intentional"   → 그래프 업데이트 (valid_until 등)
  "deferred"                → 상태만 변경

에러 코드:
  404 — 확인 항목 없음
  409 — 이미 해결됨
  400 — 잘못된 decision 값
```

---

### 1-5. 수정 반영 및 버전 관리

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `POST` | `/api/fixes/stage` | 수정 스테이징 | ✅ 실 연결 |
| `DELETE` | `/api/fixes/stage/{id}` | **[신규]** 스테이징 취소 | ✅ 실 연결 |
| `POST` | `/api/fixes/push` | 일괄 반영 + 버전 생성 | ✅ 실 연결 |
| `GET` | `/api/versions` | 버전 이력 | ✅ 실 연결 |
| `GET` | `/api/versions/{id}` | 버전 상세 | ✅ 실 연결 |
| `GET` | `/api/versions/{id}/content` | 버전 원고 텍스트 | ✅ 실 연결 |
| `GET` | `/api/versions/{a}/diff/{b}` | 버전 비교 | ✅ 실 연결 |

#### POST /api/fixes/stage

```
요청 (StageFixRequest):
  contradiction_id: str        — 모순 ID
  original_text: str?          — 원본 텍스트 (기본 "")
  fixed_text: str?             — 수정된 텍스트 (기본 "")
  is_intentional: bool         — [신규] true=의도 인정 (텍스트 교체 없음)
  intent_note: str             — [신규] 의도 인정 시 메모

응답:
  { status: "staged", contradiction_id, staged_at, is_intentional }
```

#### DELETE /api/fixes/stage/{contradiction_id} [신규]

```
스테이징 큐에서 특정 모순의 수정사항을 제거
응답: { status: "unstaged", contradiction_id }
에러: 404 — 스테이징된 항목 없음
```

#### POST /api/fixes/push

```
요청 (PushFixesRequest):
  source_id: str?     — [선택] 미전달 시 scenario 타입 소스 자동 탐색
  description: str?   — 버전 설명

처리 흐름:
  1. 스테이징 큐에서 수정사항 수집
  2. StorageService.get_file_text(file_path) → 원본 읽기
  3. 텍스트 치환 반영
  4. StorageService.save_version_snapshot() → 버전 스냅샷 저장
  5. Source vertex file_path 업데이트
  6. 새 VersionInfo 생성

응답 (VersionInfo): { id, version, date, fixes_count, description }
에러: 400 — 스테이징된 항목 없거나 소스 없음
```

---

### 1-6. 통계 조회

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `GET` | `/api/kb/stats` | KB 통계 (9종 vertex 수) | ✅ 실 연결 |
| `GET` | `/api/characters` | 캐릭터 목록 | ✅ 실 연결 |
| `GET` | `/api/characters/{id}/knowledge` | 캐릭터 지식 목록 | ⚠️ 더미 |
| `GET` | `/api/facts` | 사실 목록 | ✅ 실 연결 |
| `GET` | `/api/events` | 이벤트 목록 | ✅ 실 연결 |

**`/api/characters/{id}/knowledge` 더미 유지 이유:** LEARNS/MENTIONS 엣지 순회 + story_order 기준 필터링 쿼리 미완성. 불완전한 결과보다 빈 목록이 안전.

---

### 1-7. AI 질의

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `POST` | `/api/ai/query` | 지식베이스 질의 (RAG) | ✅ 실 연결 |

```
요청: { query: str }

처리 흐름:
  SearchService.search_context(query) → 관련 청크 검색
  Azure OpenAI 연결 시 → GPT RAG 답변 생성
  미연결 시 → 검색된 청크 텍스트 직접 반환

응답: { answer, sources }
```

---

### 1-8. 헬스체크

| 메서드 | 경로 | 설명 | 상태 |
|--------|------|------|------|
| `GET` | `/api/health` | 상태 확인 | ✅ 항상 ok |

---

## 2. 공통 인프라

### _run_graph() 래퍼 [신규]

```python
async def _run_graph(func, *args, **kwargs):
    """GremlinGraphService 동기 호출을 ThreadPoolExecutor로 분리.
    gremlin_python이 내부적으로 loop.run_until_complete()를 사용하므로
    FastAPI asyncio 루프와 충돌 방지.
    """
```

Gremlin 호출이 필요한 모든 엔드포인트에서 `await _run_graph(graph.method, ...)` 형태로 사용.

### VersionService 싱글턴

스테이징 큐(`_staging`)와 버전 이력(`_versions`)을 인메모리로 유지.
모듈 수준 `_version_service` + `get_version_service()` 팩토리로 관리.

---

## 3. 환경 변수별 동작 모드

| 변수 | `true` | `false` |
|------|--------|---------|
| `USE_LOCAL_GRAPH` | InMemoryGraphService | GremlinGraphService (Cosmos DB) |
| `USE_LOCAL_STORAGE` | LocalStorageService (`data/`) | BlobStorageService (Azure) |
| `USE_MOCK_EXTRACTION` | regex mock 강제 | Azure OpenAI (키 없으면 자동 mock) |
| `USE_MOCK_SEARCH` | MockSearchService | SearchService (Azure AI Search) |

**config.py 기본값:** `USE_LOCAL_GRAPH=true`, `USE_LOCAL_STORAGE=true` (로컬 개발용)
**Azure 연결 시:** `.env`에서 모두 `false`로 설정

---

## 4. 전체 처리 흐름 요약

```
소스 업로드:
POST /api/sources/upload
  → IngestService.process_file()     파일 저장 + 청킹
  → ExtractionService                LLM 추출 (키 없으면 regex mock)
  → NormalizationService             캐릭터 통합, 사실 병합
  → graph.materialize()              vertex/edge 적재 (upsert)
  → SearchService.index_chunks()     검색 인덱싱

소스 교체:
PUT /api/sources/{id}
  → 기존 파일 삭제 → 새 파일 저장 → 인덱스 재구축 → materialize()

모순 탐지 (신규 원고):
POST /api/analyze
  → ContiCheckAgent (LangGraph)
  → 스냅샷 격리 → 7가지 쿼리 → Hard 자동 / Soft LLM 검증

전수조사 (기존 KB):
POST /api/scan
  → DetectionService.full_scan(graph)
  → graph.find_all_violations()

수정 반영:
POST /api/fixes/stage  →  큐 적재
DELETE /api/fixes/stage/{id}  →  큐 취소
POST /api/fixes/push   →  Storage 반영 + 버전 스냅샷 + VersionInfo
```
