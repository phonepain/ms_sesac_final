# ContiCheck 세션 작업 보고서 — 파이프라인 구조 결함 수정 및 Phase 9 E2E 테스트

**작성일:** 2026-03-21
**브랜치:** `pdj`
**최종 테스트 결과:** 88 passed / 0 failed (LLM 게이트 테스트 2건 별도 관리)

---

## 1. 세션 목표

- Phase 7 API 테스트 오류 수정
- `test_find_timeline_violations` 실패 수정
- `test_diff_versions` 실패 수정
- Phase 9 E2E 테스트 작성 및 실행
- 파이프라인 구조 결함 식별 및 수정

---

## 2. 수정된 버그 (테스트 작성 과정에서 발견)

### 2-1. Phase 7 API 테스트 — `AttributeError: 'FastAPI' object has no attribute 'get_global_storage'`

**파일:** `tests/test_phase7_api.py`

**원인:**
```python
from app.main import app  # 이 줄이 'app' 변수를 FastAPI 인스턴스로 재바인딩
# 이후 patch.object(app, ...) → FastAPI 객체의 속성을 찾으려 해서 AttributeError
```

**수정:**
```python
import app.main as _app_main   # 모듈 참조를 별도 변수에 먼저 보존
from app.main import app        # 이후 이 줄이 app을 재바인딩해도 _app_main은 모듈 그대로 유지

# patch.object 시 _app_main 사용
with patch.object(_app_main, "get_global_storage", return_value=local_storage):
    ...
```

---

### 2-2. `test_find_timeline_violations` 실패

**파일:** `tests/test_phase3_graph.py`

**원인:**
테스트 셋업이 `add_participates_in` 엣지를 사용했으나, `find_timeline_violations()`는
`HAS_STATUS(status_type="dead")` + `AT_LOCATION` 엣지 조합으로 타임라인 위반을 감지.
즉, 탐지 쿼리와 다른 엣지 타입을 셋업해서 항상 0건 반환.

**수정:**
```python
# 기존 (잘못됨)
graph.add_participates_in("char-b", "ev-death", {...})

# 수정 후
graph.add_has_status("char-b", "ev-death", {
    "status_type": "dead", "story_order": 5.0, "source_id": "s1"
})
graph.add_at_location("char-b", "loc-alley", {
    "discourse_order": 6.0, "story_order": 6.0, "source_id": "s1"
})
```

---

### 2-3. `test_diff_versions` — `VersionNotFoundError`

**파일:** `app/services/version.py`

**원인:**
`diff_versions()`가 UUID 형식의 `version_id`를 `storage.diff_version_content()`에 전달했으나,
StorageService는 `"v1"`, `"v2"` 같은 버전 이름 문자열을 기대함.

**수정:**
```python
# 기존 (잘못됨)
diff_text = await self._storage.diff_version_content(
    version_a=version_id_a,   # UUID
    version_b=version_id_b,   # UUID
    source_id=stored_a.source_id,
)

# 수정 후
diff_text = await self._storage.diff_version_content(
    version_a=stored_a.info.version,   # "v1"
    version_b=stored_b.info.version,   # "v2"
    source_id=stored_a.source_id,
)
```

---

### 2-4. `InMemoryGraphService._assign_time_axes` 누락

**파일:** `app/services/graph.py`

**원인:**
`materialize()`가 `self._assign_time_axes()`를 호출하는데, 이 메서드가
`GremlinGraphService`에만 구현되어 있고 `InMemoryGraphService`에는 없었음.
→ 로컬 테스트 환경에서 `materialize()` 호출 시 `AttributeError`.

**수정:**
`InMemoryGraphService`에 `_assign_time_axes()` 메서드 추가.
- `discourse_order`: `_get_next_discourse_order()` 자동 부여
- `story_order`: 시간 점프 힌트("전", "후", "그날 밤", "회상" 등) 감지 시 `None`(타임라인 모호, 사용자 확인 대상), 아니면 `discourse_order`와 동일
- `is_linear`: 시간 점프 감지 시 `False`, 아니면 `True`

---

## 3. 파이프라인 구조 결함 (핵심 수정)

### 3-1. 발견된 결함

LLM E2E 테스트(`test_e2e_llm_full_pipeline`)에서 `result.total = 0`이 반환됨.
LLM 추출은 정상 동작했는데도 모순이 0건인 이유를 추적한 결과, **두 가지 구조적 결함** 발견:

**결함 A: `NormalizationResult`에 5개 필드 누락**

`ExtractionResult`는 8개 필드를 갖지만, `NormalizationResult`는 3개만 가짐:

| ExtractionResult 필드 | NormalizationResult에 포함 여부 |
|----------------------|-------------------------------|
| characters           | ✅ NormalizedCharacter로 변환   |
| facts                | ✅ NormalizedFact로 변환        |
| events               | ✅ NormalizedEvent로 변환       |
| **traits**           | ❌ 누락                         |
| **relationships**    | ❌ 누락                         |
| **emotions**         | ❌ 누락                         |
| **item_events**      | ❌ 누락                         |
| **knowledge_events** | ❌ 누락                         |

**결함 B: `InMemoryGraphService.materialize()`가 엣지를 생성하지 않음**

`materialize()`는 Vertex(Character, KnowledgeFact, Event, UserConfirmation)만 생성하고,
모순 탐지에 필수적인 엣지를 전혀 생성하지 않았음:

| 필요한 엣지 | 기반 데이터 | 누락 여부 |
|------------|-----------|---------|
| HAS_TRAIT  | traits    | ❌ 누락  |
| FEELS      | emotions  | ❌ 누락  |
| LEARNS     | knowledge_events | ❌ 누락 |
| MENTIONS   | knowledge_events | ❌ 누락 |
| POSSESSES  | item_events | ❌ 누락 |
| LOSES      | item_events | ❌ 누락 |
| RELATED_TO | relationships | ❌ 누락 |

**결과:** 그래프에는 Vertex만 있고 Edge가 없으므로
`find_all_violations()`의 7가지 쿼리가 모두 0건 반환. 실질적으로 LLM 파이프라인이 동작해도
탐지가 불가능한 상태였음.

**왜 이전 단계 테스트에서 발견되지 않았는가:**
- Phase 3/4 단위 테스트: 파이프라인을 거치지 않고 직접 `add_learns()`, `add_feels()` 등을 호출하여 엣지를 구성 → 파이프라인 공백을 우회
- 파일별 코드 리뷰: `intermediate.py`의 주석 `"(필요에 따라 추가/확장합니다)"`가 의도적 미구현처럼 보였음
- Phase 4 단위 테스트가 통과하여 탐지 로직 자체는 정상이라고 판단 → 교차 계층 데이터 흐름 검증이 부족

---

### 3-2. 수정 내용

**파일 1: `backend/app/models/intermediate.py`**

`NormalizationResult`에 5개 필드 추가:
```python
class NormalizationResult(BaseModel):
    characters: List[NormalizedCharacter] = Field(default_factory=list)
    facts: List[NormalizedFact] = Field(default_factory=list)
    events: List[NormalizedEvent] = Field(default_factory=list)
    traits: List[RawTrait] = Field(default_factory=list)           # 추가
    relationships: List[RawRelationship] = Field(default_factory=list)  # 추가
    emotions: List[RawEmotion] = Field(default_factory=list)       # 추가
    item_events: List[RawItemEvent] = Field(default_factory=list)  # 추가
    knowledge_events: List[RawKnowledgeEvent] = Field(default_factory=list)  # 추가
    source_conflicts: List[SourceConflict] = Field(default_factory=list)
```

**파일 2: `backend/app/services/normalization.py`**

`_NormalizationCore.normalize()`에서 5개 필드 수집 및 pass-through:
```python
all_traits, all_relationships, all_emotions = [], [], []
all_item_events, all_knowledge_events = [], []
for ext in extractions:
    all_traits.extend(ext.traits)
    all_relationships.extend(ext.relationships)
    all_emotions.extend(ext.emotions)
    all_item_events.extend(ext.item_events)
    all_knowledge_events.extend(ext.knowledge_events)

normalized = NormalizationResult(
    ...,
    traits=all_traits,
    relationships=all_relationships,
    emotions=all_emotions,
    item_events=all_item_events,
    knowledge_events=all_knowledge_events,
)
```

**파일 3: `backend/app/services/graph.py`**

`InMemoryGraphService.materialize()`에 Steps 5~9 추가:

| Step | 처리 내용 | 생성 대상 |
|------|---------|---------|
| Step 5 | `traits` → `character_name`으로 캐릭터 조회 | Trait vertex + HAS_TRAIT edge |
| Step 6 | `emotions` → `from_char`, `to_char`로 캐릭터 조회 | FEELS edge |
| Step 7 | `knowledge_events` → 캐릭터 + Fact 매칭 (없으면 Fact 자동 생성) | LEARNS / MENTIONS edge |
| Step 8 | `item_events` → Item vertex 조회 또는 생성 | POSSESSES / LOSES edge |
| Step 9 | `relationships` → 양측 캐릭터 조회 | RELATED_TO edge |

캐릭터 이름→ID 조회는 `_resolve_char()` 내부 헬퍼로 처리:
- `NormalizationResult`에서 방금 생성한 캐릭터 우선 확인 (이름 맵)
- 없으면 `find_character_by_name()`으로 기존 그래프 검색
- 기존에도 없으면 엣지 생성 건너뜀 (데이터 무결성 유지)

---

## 4. Phase 9 E2E 테스트 작성

**파일:** `backend/tests/test_e2e.py`

### 샘플 데이터 3종 (`data/sample/`)

| 파일 | 분류 | 내용 |
|------|------|------|
| `세계관_그림자의비밀.txt` | worldview | 현대 한국, 야간 골목 조명 없음(50m 이상 식별 불가), 법원 규칙 등 |
| `설정집_그림자의비밀.txt` | settings | 형사 A(혈액형 A형/채식주의자 불변), B(거짓 알리바이), C(증거 칼 소유), D(파트너) |
| `시나리오_그림자의비밀.txt` | scenario | Chapter 1~4 대본. 의도적 모순 5건 내장 |

시나리오 내장 모순:

| # | 모순 유형 | Hard/Soft | 내용 |
|---|---------|---------|------|
| 1 | 정보 비대칭 | **Hard** | A가 C의 진술(Chapter 2) 이전에 "B가 범인"을 발언(Chapter 1) |
| 2 | 거짓말·기만 | **Hard** | A가 진실 인지(story_order=3.0) 후에도 거짓 기반 발언(story_order=4.0) |
| 3 | 소유물 추적 | Soft | C가 칼을 B에게 양도(Chapter 2) 후 A에게 다시 보여줌(Chapter 4) |
| 4 | 감정 급변 | Soft | A→B: neutral → hate, 트리거 이벤트 없음 |
| 5 | 세계관 위반 | Soft | 야간 골목 50m 밖에서 A가 육안으로 물체 식별 |

### 테스트 구성

**Section A: 파이프라인 흐름 (항상 실행)**

| 테스트 | 검증 내용 |
|--------|---------|
| `test_e2e_sample_files_exist` | 샘플 파일 3종 존재 확인 |
| `test_e2e_upload_stores_file` | StorageService에 파일 저장 + 경로 반환 확인 |
| `test_e2e_ingest_creates_chunks` | txt 파싱 후 청크 ≥1건 생성 확인 |
| `test_e2e_search_indexed` | 청크 인덱싱 후 검색 결과 반환 확인 |
| `test_e2e_analyze_no_crash` | Mock 모드에서 `analyze()` 오류 없이 완료 확인 |
| `test_e2e_snapshot_isolation` | `analyze()` 후 canonical graph 미변경 확인 |

**Section B: 그래프→탐지 통합 (항상 실행)**

미리 구성된 모순 그래프 `_build_contradiction_graph()`를 사용:
- 정보 비대칭: A가 LEARNS(story_order=3.0)하기 전 MENTIONS(story_order=2.8)
- 소유물 중복: A와 B 동시에 동일 아이템 POSSESSES(story_order=2.0)
- 감정: A→B FEELS emotion="hate"
- 거짓 학습: A가 is_true=False인 Fact를 LEARNS(believed_true=True)

| 테스트 | 검증 내용 |
|--------|---------|
| `test_e2e_hard_violations_detected` | Hard 위반 ≥2건 탐지 |
| `test_e2e_soft_violations_exist` | Soft 위반 ≥1건 탐지 |
| `test_e2e_process_violations_returns_analysis` | DetectionService.analyze() 오류 없이 완료 |
| `test_e2e_full_scan_with_graph` | full_scan() 오류 없이 완료 |
| `test_e2e_confirmation_create_and_resolve` | UserConfirmation 생성 → resolve → status 변경 확인 |
| `test_e2e_version_stage_push_retrieve` | 스테이징 → push → StorageService 스냅샷 저장 → 내용 조회 |
| `test_e2e_version_list` | 버전 목록 ≥1건 반환 확인 |

**Section C: LLM 의존 테스트 (`@pytest.mark.llm`)**

`.env`에 실제 API 키가 있을 때만 실행:

| 테스트 | 검증 내용 |
|--------|---------|
| `test_e2e_llm_extraction` | 실제 LLM으로 샘플 파일 추출 → characters ≥1건 |
| `test_e2e_llm_full_pipeline` | 전체 파이프라인: 추출→정규화→적재→탐지 → violations ≥1건 |

LLM 테스트 스킵 로직:
```python
def _has_llm_key() -> bool:
    # conftest.py가 환경 변수를 빈 값으로 덮어쓰므로
    # 실제 .env 파일을 직접 읽어서 판단
    env_path = Path(__file__).parent.parent / ".env"
    ...

skip_no_llm = pytest.mark.skipif(not _has_llm_key(), reason="LLM API 키 없음")
```

---

## 5. 최종 테스트 현황

```
총 88개 테스트 통과 (LLM 게이트 2건 제외)

test_phase1_ingest.py        8 passed
test_phase2_normalization.py 8 passed
test_phase3_graph.py        22 passed
test_phase4_detection.py     8 passed
test_phase5_confirmation.py  9 passed
test_phase6_version.py      10 passed
test_phase7_api.py          16 passed
test_search.py               4 passed
test_e2e.py                 13 passed  (LLM 2건 deselected)
```

---

## 6. 남은 작업

| 항목 | 상태 | 비고 |
|------|------|------|
| Phase 8 프론트엔드 (React/TS) | 미착수 | `conticheck-v3.html` 프로토타입 참조 |
| LLM E2E 테스트 (`@pytest.mark.llm`) | LLM 키 필요 | API 엔드포인트/키 확보 후 실행 |
| GremlinGraphService.materialize() 엣지 생성 | 미착수 | 현재 InMemoryGraphService만 수정됨. Azure Cosmos DB 연동 시 동일 로직 적용 필요 |
| C-1: DetectionService mock fallback | 미착수 | `code-review-2026-03-21.md` 참조 |
| H-1: GremlinGraphService snapshot_graph `_discourse_counter` 복사 | 미착수 | `code-review-2026-03-21.md` 참조 |
| H-2: `_add_edge_generic` data mutation 방지 | 미착수 | `code-review-2026-03-21.md` 참조 |

---

## 7. 파일 변경 목록

| 파일 | 변경 유형 | 내용 요약 |
|------|---------|---------|
| `backend/app/models/intermediate.py` | 수정 | `NormalizationResult`에 5개 필드 추가 |
| `backend/app/services/normalization.py` | 수정 | `normalize()`에서 5개 필드 수집·pass-through, import 추가 |
| `backend/app/services/graph.py` | 수정 | `InMemoryGraphService.materialize()`에 Steps 5~9 추가, `_assign_time_axes()` 추가 |
| `backend/app/services/version.py` | 수정 | `diff_versions()`: UUID→버전명 전달 버그 수정 |
| `backend/tests/test_phase3_graph.py` | 수정 | `_setup_timeline_violation()`: 엣지 타입을 탐지 쿼리와 일치시킴 |
| `backend/tests/test_phase7_api.py` | 수정 | `import app.main as _app_main`으로 모듈 참조 보존 |
| `backend/tests/test_e2e.py` | 신규 | Phase 9 E2E 테스트 전체 |
| `data/sample/세계관_그림자의비밀.txt` | 신규 | 세계관 샘플 파일 |
| `data/sample/설정집_그림자의비밀.txt` | 신규 | 설정집 샘플 파일 |
| `data/sample/시나리오_그림자의비밀.txt` | 신규 | 시나리오 샘플 파일 (모순 5건 내장) |
