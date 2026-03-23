# ContiCheck 작업 요약 — 2026-03-20 (금) ~ 2026-03-23 (일)

**작성일:** 2026-03-23
**브랜치:** pdj
**최종 테스트:** 97/97 통과 (2 LLM 게이트 제외)

---

## 전체 진행 타임라인

| 날짜 | 주요 작업 |
|------|----------|
| 2026-03-20 (금) | 전체 코드 리뷰 v1 → v2: 버그 목록 확정 |
| 2026-03-21 (토) | 런타임 버그 수정 (confirmation.py 집중) + 파이프라인 구조 결함 수정 + E2E 테스트 작성 |
| 2026-03-22 (일) | Phase 8 프론트엔드 v4 이식 + 백엔드 갭 수정 (A-1~A-5) + B-4 GremlinGraphService 수정 |
| 2026-03-23 (월) | Azure 서비스 연동 테스트 + 프론트엔드 표시 버그 2건 수정 |

---

## 1. 2026-03-20 (금) — 전체 코드 리뷰

Phase 0~7 전체 백엔드 코드를 직접 열람하여 버그 목록 확정.

### 확인된 주요 버그 (수정 전 상태)

| 분류 | 파일 | 내용 |
|------|------|------|
| Critical | `confirmation.py:364` | `Severity.WARNING` 없는 Enum 값 → `AttributeError` |
| Critical | `confirmation.py` 8곳 | `await self._graph.*` async/sync 불일치 → `TypeError` |
| Critical | `confirmation.py:280,284` | `"resolved"` 없는 ConfirmationStatus 값 → `ValidationError` |
| High | `search.py` → `confirmation.py` | 반환 타입 불일치 (`EvidenceItem` vs `SourceExcerpt`) |
| High | `api.py:19` | `SourceLocation` 중복 정의 (`enums.py`와 동일 이름) |
| High | `main.py:/api/analyze` | `ContiCheckAgent` 미연결 — 더미 응답 반환 |
| High | `agent.py:36` | 원고 전체를 단일 청크로 LLM 호출 (컨텍스트 초과 위험) |

이 날 완료된 수정:
- `main.py` upload 더미 source_id 제거, download `get_file(file_path)` 수정
- `graph.py` `remove_source()`에서 `storage.delete_file()` 호출 분리
- `.env` `USE_LOCAL_STORAGE`, `AZURE_STORAGE_*` 변수 추가

---

## 2. 2026-03-21 (토) — 런타임 버그 수정 + 파이프라인 구조 결함 수정

### 2-1. confirmation.py 런타임 버그 3건 수정

| # | 수정 내용 |
|---|----------|
| A-1 | `Severity.WARNING` → `Severity.MAJOR` |
| A-2 | `await self._graph.*` 8곳 → `await` 제거 (sync 호출) |
| A-3 | `"resolved"` → `ConfirmationStatus.CONFIRMED_CONTRADICTION` / `CONFIRMED_INTENTIONAL` |

### 2-2. 타입 불일치 수정

| # | 수정 내용 |
|---|----------|
| C-1 | `search.get_source_excerpts()` 반환 타입 `List[EvidenceItem]` → `List[SourceExcerpt]` |
| C-2 | `api.py`의 `SourceLocation` 삭제 → `ChunkLocation`으로 리네임 (`enums.SourceLocation`과 분리) |

### 2-3. main.py API 연결

| # | 수정 내용 |
|---|----------|
| main-1 | `POST /api/analyze` → `ContiCheckAgent.analyze_manuscript()` 실제 연결 |
| main-2 | `GET /api/confirmations` → `ConfirmationService.list_pending()` 연결 |
| main-3 | `POST /api/confirmations/{id}/resolve` → `ConfirmationService.resolve()` 연결 |
| pipe-1 | `upload_source()` → Extract→Normalize→Materialize→SearchIndex 파이프라인 연결 |

### 2-4. 코드 리뷰 추가 버그 발견 및 수정 (세션 2)

| # | 파일 | 내용 |
|---|------|------|
| C-1 (code-review) | `detection.py` | Azure OpenAI 키 없을 때 `self.client`를 빈 문자열로 생성 → soft violation 1건만 있어도 500 에러 → `_mock_mode` 플래그 추가, 키 없으면 `confidence=0.5` 반환 |
| H-1 | `graph.py` | `GremlinGraphService.snapshot_graph()` `_discourse_counter` 미복사 → 스냅샷에서 discourse_order 0.1부터 재시작 → `mem._discourse_counter = self._discourse_counter` 추가 |
| H-2 | `graph.py` | `_add_edge_generic()` `data` dict 직접 수정(mutation) → `data = dict(data)` shallow copy 추가 |

### 2-5. 파이프라인 구조 결함 수정 (핵심 — LLM 파이프라인이 모순 0건을 반환하는 원인)

**문제:** `ExtractionResult`의 8개 필드 중 `traits`, `relationships`, `emotions`, `item_events`, `knowledge_events` 5개가 `NormalizationResult`에 정의되지 않아 계층 2→3 데이터 전달 자체가 누락. `InMemoryGraphService.materialize()`도 Vertex만 생성하고 Edge 생성 없어서 탐지 쿼리 항상 0건.

| 수정 파일 | 내용 |
|---------|------|
| `models/intermediate.py` | `NormalizationResult`에 5개 필드 추가 (`traits`, `relationships`, `emotions`, `item_events`, `knowledge_events`) |
| `services/normalization.py` | `normalize()`에서 5개 필드 수집·pass-through 추가 |
| `services/graph.py` | `InMemoryGraphService.materialize()`에 엣지 생성 Steps 5~9 추가 (LEARNS/MENTIONS/FEELS/POSSESSES/LOSES/HAS_TRAIT/RELATED_TO) |
| `services/graph.py` | `InMemoryGraphService._assign_time_axes()` 누락 → 추가 |

### 2-6. 기타 버그 수정

| 파일 | 내용 |
|------|------|
| `version.py diff_versions()` | UUID→버전명 전달 버그 수정 (`"v1"`, `"v2"` 문자열로 변경) |
| `test_phase7_api.py` | `from app.main import app`이 FastAPI 인스턴스로 모듈 참조 덮어씌우기 → `import app.main as _app_main`으로 수정 |
| `test_phase3_graph.py` | 타임라인 위반 셋업 엣지 타입 불일치 (`PARTICIPATES_IN` → `HAS_STATUS(dead)` + `AT_LOCATION`) |

### 2-7. Phase 9 샘플 데이터 + E2E 테스트 작성

- `data/sample/설정집_그림자의비밀.txt`, `세계관_그림자의비밀.txt`, `시나리오_그림자의비밀.txt` 생성
- `tests/test_e2e.py` 작성 (Phase 1~5 전체 파이프라인 커버)
- `tests/test_phase3_graph.py` 작성 (9종 Vertex + 7종 위반 탐지)

**결과:** 88/88 비-LLM 테스트 통과

---

## 3. 2026-03-22 (일) — 프론트엔드 v4 이식 + 백엔드 갭 수정

### 3-1. Phase 8 프론트엔드 v4 이식 (7개 파일)

기존 HTML 프로토타입(conticheck-v4.html)을 React/TypeScript로 이식.

| 파일 | 내용 |
|------|------|
| `src/types/index.ts` | `Project`, `StagedFix`, `Contradiction` 타입 정의 |
| `src/api/endpoints.ts` | `sourceApi`, `graphApi`, `analyzeApi`, `versionApi`, `statsApi` |
| `src/components/common/Icons.tsx` | 공통 아이콘 컴포넌트 |
| `src/components/project/ContradictionCard.tsx` | HARD/SOFT/WARNING 배지, 수정 스테이징 UI |
| `src/components/project/SourceList.tsx` | 소스 목록 + 재업로드 |
| `src/components/project/StagedFixes.tsx` | 스테이징된 수정사항 목록 |
| `src/pages/ProjectDetailView.tsx` | 개요/모순/버전 3탭 뷰 |

### 3-2. 백엔드 갭 수정 (A-1~A-5) — v4 프론트엔드 연동

| # | 파일 | 내용 |
|---|------|------|
| A-1 | `main.py`, `version.py` | `StageFixRequest`에 `is_intentional`/`intent_note` 필드 추가. `is_intentional=True`면 텍스트 검증 생략, `_apply_text_fixes()`에서 텍스트 교체 없이 resolved 처리 |
| A-2 | `main.py` | `GET /api/versions/{id}/content` — `source_id` 필수 query param 제거. `VersionService.get_version(version_id)` 위임, 응답 `{content: text}` 단순화 |
| A-3 | `api.py`, `version.py`, `endpoints.ts` | `VersionInfo`에 `src: str = ""` 추가. push 시 source vertex name 조회 → `src` 필드 전달 |
| A-4 | `App.tsx` | `onAnalyze()`, `onNewAnalyze()` — evidence/location/dialogue/alternative/original_text 필드 매핑 수정 |
| A-5 | `main.py`, `endpoints.ts`, `App.tsx` | `PUT /api/sources/{id}` 소스 재업로드 엔드포인트 구현. `sourceApi.reupload()` 추가. `onReupload`에서 upload→reupload로 변경 |

### 3-3. 버그 수정 (B 항목)

| # | 내용 |
|---|------|
| B-4 | `GremlinGraphService.materialize()` Steps 5~9 추가 — `char_name_to_id`, `fact_content_to_id` 맵, `_resolve_char` 헬퍼 추가. Cosmos DB 모드에서도 엣지 생성 가능 |
| 추가 | `normalization.py` — `NormalizationService.use_mock` 프로퍼티 추가 (ExtractionService와 인터페이스 일관성) |
| 추가 | `main.py` `upload_source` — `source_dict["id"] = source_id` 추가 → Source vertex 키 불일치 수정 |

### 3-4. pytest 마커 등록

`pytest.ini`에 커스텀 마커 등록 추가:
```ini
markers =
    llm: LLM API 키가 필요한 통합 테스트
```

**결과:** 84/84 테스트 통과 (test_e2e.py LLM 게이트 제외)

---

## 4. 2026-03-23 (월) — Azure 연동 테스트 + 프론트엔드 버그 수정

### 4-1. config.py + storage.py pydantic-settings 버그 수정

**원인:** pydantic-settings는 `.env`를 `settings` 객체로 읽지만 `os.environ`에는 주입하지 않음. `get_global_storage()`가 `os.getenv("USE_LOCAL_STORAGE", "true")`를 사용하여 항상 기본값 `"true"` 반환 → Azure Blob Storage 미사용.

| 파일 | 수정 내용 |
|------|----------|
| `config.py` | `os.getenv()` 호출 전부 제거. 모든 필드를 plain Python 기본값으로 변경 |
| `storage.py` | `get_global_storage()`에서 `settings.use_local_storage` 사용 |

### 4-2. graph.py datetime 경고 수정

`datetime.utcnow()` → `datetime.now(timezone.utc)` 전환 (12곳).

```python
# Before
from datetime import datetime
datetime.utcnow().isoformat()

# After
from datetime import datetime, timezone
datetime.now(timezone.utc).isoformat()
```

### 4-3. Azure 전체 파이프라인 테스트 (실제 서비스 연동)

`backend/scripts/azure_pipeline_test.py` 작성 및 실행.

**연결된 Azure 서비스:**
- Blob Storage: `conticheckstorage` (컨테이너: `conticheck-uploads`)
- Cosmos DB: `5555.gremlin.cosmos.azure.com` (DB: `conticheck-db`, 컨테이너: `scenario-graph`)
- Azure AI Search: `ai-search-conticheck` (인덱스: `conticheck-index`)
- Azure OpenAI: `conticheck123.openai.azure.com`
  - 추출: `gpt-5.4-mini`
  - 탐지: `gpt-5.3-chat`

**테스트 결과 (실제 서버 로그):**
```
vertices: 308, edges: 354   ← snapshot_graph() 완료
hard: 3, soft: 9, total: 12 ← find_all_violations() 완료
reports: 3, confirmations: 9 ← detect 완료 (soft LLM 검증 ~121초)
confirmations_persisted: 9   ← Cosmos DB 저장 완료
```

**확인 항목:**
- 5계층 파이프라인 전체 정상 동작
- 스냅샷 격리: `POST /api/analyze` 후 canonical graph 미변경 확인
- Hard 3건 자동 ContradictionReport 생성
- Soft 9건 LLM 검증 → confidence < 0.8 → UserConfirmation 9건 Cosmos DB 저장

### 4-4. 전체 백엔드 테스트 재확인

```
pytest -m "not llm"
결과: 97/97 passed, 2 deselected, 1 warning
```

- `tests/test_e2e.py` 13건 추가 포함 (E2E 파이프라인)
- `tests/test_search.py` 4건 수정 완료

### 4-5. 프론트엔드 버그 수정 2건

**버그 1: Soft 위반(UserConfirmation)이 프론트엔드에 표시되지 않음**

원인: `App.tsx`의 `onNewAnalyze()`와 `onAnalyze()`에서 `res.contradictions`만 매핑하고 `res.confirmations`를 완전히 무시.

수정: `res.confirmations`를 `sv: 'warning'`, `ch: '사용자 확인 필요'`로 매핑하여 Contradiction 목록에 함께 추가.

```typescript
// 수정 후 (onNewAnalyze, onAnalyze 양쪽 동일 패턴)
contradictions: [
  ...res.contradictions.map((c: any) => ({
    id: c.id, sv: c.severity.toLowerCase() as any, ...
  })),
  ...(res.confirmations || []).map((c: any) => ({
    id: c.id, sv: 'warning' as any, tp: c.confirmation_type,
    ch: '사용자 확인 필요',
    ds: c.question || c.context_summary || '',
    ev: (c.source_excerpts || []).map(...),
    ...
  })),
],
```

**버그 2: 증거(evidence) 텍스트가 Python dict 원시 문자열로 표시됨**

원인: `detection.py`의 `_to_report()`에서 `text=str(e)` 사용 → `{'item_id': 'f3cade...', 'story_order': 0.8, 'owners': [...]}` 형태로 프론트엔드 노출.

수정: `_fmt_evidence()` 정적 메서드 추가, 사람이 읽을 수 있는 형태로 변환.

```python
# 수정 후
@staticmethod
def _fmt_evidence(e: Dict[str, Any]) -> str:
    parts = []
    if "story_order" in e: parts.append(f"story_order={e['story_order']}")
    if "owners" in e: parts.append(f"동시 소유자 {len(e['owners'])}명")
    if "character_name" in e: parts.append(f"캐릭터: {e['character_name']}")
    if "fact_content" in e: parts.append(f"사실: {str(e['fact_content'])[:60]}")
    # ... 추가 필드 처리
    return " | ".join(parts) if parts else "(정보 없음)"

# _to_report()에서
text=self._fmt_evidence(e),  # str(e) 대신
```

---

## 5. 현재 시스템 상태

### 테스트 현황

| 테스트 파일 | 통과 | 비고 |
|------------|------|------|
| `test_e2e.py` | 13/13 | Phase 1~5 E2E, LLM 게이트 테스트 2건 별도 |
| `test_phase0_models.py` | 13/13 | Pydantic 모델 |
| `test_phase1_storage.py` | 8/8 | StorageService |
| `test_phase3_graph.py` | 13/13 | InMemoryGraphService + 7종 위반 탐지 |
| `test_phase4_detection.py` | 7/7 | DetectionService |
| `test_phase5_review.py` | 20/20 | ConfirmationService + VersionService |
| `test_phase7_api.py` | 15/15 | FastAPI 엔드포인트 |
| `test_search.py` | 4/4 | SearchService |
| **합계** | **97/97** | |

### 환경 설정

```
로컬 모드: USE_LOCAL_GRAPH=true, USE_MOCK_EXTRACTION=true, USE_MOCK_SEARCH=true, USE_LOCAL_STORAGE=true
Azure 모드: 전 항목 false + Azure 자격증명 설정 필요
```

### 주요 엔드포인트 상태

| 엔드포인트 | 상태 |
|-----------|------|
| `GET /api/health` | ✅ |
| `GET /api/kb/stats` | ✅ |
| `GET /api/sources` | ✅ |
| `POST /api/sources/upload` | ✅ |
| `PUT /api/sources/{id}` | ✅ (재업로드) |
| `POST /api/analyze` | ✅ (5계층 실제 연결) |
| `GET /api/confirmations` | ✅ |
| `POST /api/confirmations/{id}/resolve` | ✅ |
| `POST /api/fixes/stage` | ✅ |
| `POST /api/fixes/push` | ✅ |
| `GET /api/versions` | ✅ |
| `GET /api/versions/{id}/content` | ✅ |
| `GET /api/versions/{a}/diff/{b}` | ✅ |

---

## 6. 남은 항목

| 항목 | 설명 |
|------|------|
| B-5 | LLM E2E 테스트: `pytest -m llm backend/tests/test_e2e.py` — API 키 확인 후 실행 |
| Azure 데이터 정리 | `python -X utf8 scripts/azure_cleanup.py` — 테스트 2회 누적 데이터 (308 vertices, 9 AI Search docs, 6 Blob files) |
| H-3 | `GremlinGraphService.upsert_vertex()` label 결정 로직: `partition_key` 누락 시 `"unknown"` 레이블 저장 위험 |
| M-5 | `snapshot_graph()` 실패 시 빈 snapshot 반환 → re-raise 또는 호출자 검증 추가 권장 |
| D-1 | `agent.py` 원고 전체 단일 청크 처리 → 대용량 원고 컨텍스트 초과 위험 (단기 데모에서는 허용 범위) |
