# ContiCheck — Claude Code 구현 가이드

## 이 문서의 목적

ContiCheck POC를 Claude Code로 구현할 때의 단계별 가이드입니다.
**작은 단위로 나눠서, 이전 결과를 확인한 뒤, 다음 단계를 지시**하는 것이 핵심입니다.

---

## 시스템 아키텍처 — 5계층

```
┌──────────────────────────────────────────────────────────┐
│ 1. Extraction        텍스트 → RawEntity                   │
│    소스 분류별 전략 (세계관/설정집/시나리오)                  │
├──────────────────────────────────────────────────────────┤
│ 2. Normalization     RawEntity → NormalizedEntity          │
│    동일 캐릭터 통합, 동일 사실 병합, 소스 충돌 감지           │
├──────────────────────────────────────────────────────────┤
│ 3. Graph Materialization   NormalizedEntity → Vertex/Edge │
│    discourse_order/story_order 부여, DB 적재               │
├──────────────────────────────────────────────────────────┤
│ 4. Contradiction Detection   그래프 → 모순 리포트          │
│    7가지 구조적 쿼리 + LLM 보조 (confidence≥0.8만 자동)     │
│    Hard Contradiction → 자동 / Soft Inconsistency → 사용자 │
├──────────────────────────────────────────────────────────┤
│ 5. Review Workflow   사용자 확인 + 수정 반영               │
│    확인 → 3단계 피드백(그래프 업데이트) → 4단계 재탐지       │
│    스테이징 → Push → 버전 관리                             │
└──────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────┐
  │ Storage (횡단)                           │
  │ 계층1: 원본 파일 저장                     │
  │ 계층5: 버전별 스냅샷 보관                  │
  │ Blob Storage / 로컬 파일시스템 전환        │
  └─────────────────────────────────────────┘
```

각 계층의 입력/출력이 명확하여 **문제 발생 시 어느 계층 책임인지 바로 식별**:

| 문제 | 원인 계층 |
|------|----------|
| 캐릭터 이름 누락 | 1. Extraction |
| 같은 캐릭터 2개 등록 | 2. Normalization |
| story_order 꼬임 | 3. Materialization |
| 모순인데 못 잡음 | 4. Detection |
| 확인 후 재분석 안 됨 | 5. Review |
| 원본 파일 유실 / 버전 스냅샷 없음 | Storage |

---

## 자료 입력 — 3분류, 2트랙

| 분류 | 용도 | 추출 전략 |
|------|------|----------|
| 세계관 (🌍) | 세계 규칙, 역사, 마법 체계 | 규칙/법칙/제약 중심 |
| 설정집 (📋) | 캐릭터 프로필, 관계도, 특성 | 캐릭터/관계/감정/특성 중심 |
| 시나리오 (🎬) | 실제 스토리, 대본 | 장면/대사/이벤트/정보흐름 중심 |

**위키 크롤링은 사용하지 않습니다.**

GraphRAG 2트랙:
- 트랙 A: 세계관 + 설정집 → 세계관·설정 그래프
- 트랙 B: 시나리오 → 시나리오 그래프

---

## 온톨로지 요약 (v2.2)

**9 Vertices**: Character, KnowledgeFact(+is_true), Event(+discourse_order, story_order, is_linear, environment), Trait(+goal/motivation), Organization, Location, Item(+location_id), Source(+file_path), UserConfirmation

**13 Edges**: LEARNS(+believed_true), MENTIONS, PARTICIPATES_IN, HAS_STATUS, AT_LOCATION, RELATED_TO, BELONGS_TO, FEELS, HAS_TRAIT, VIOLATES_TRAIT(+requires_confirmation), POSSESSES(+possession_type), LOSES, SOURCED_FROM

**7 모순 유형**: 정보 비대칭, 타임라인, 관계, 성격·설정, 감정 일관성, 소유물 추적, 거짓말·기만

**Hard/Soft 형식 구분**: Hard Contradiction(논리적 불가능, 자동 판정) vs Soft Inconsistency(맥락에 따라 의도적, 사용자 확인)

**임시 그래프 격리**: analyze() 시 In-Memory 스냅샷 복제, Push 시에만 canonical graph 업데이트

**9 사용자 확인 유형**: flashback_check, intentional_change, foreshadowing, source_conflict, emotion_shift, relationship_ambiguity, item_discrepancy, timeline_ambiguity, unreliable_narrator

---

## 사전 준비: CLAUDE.md 파일 작성

### 지시 프롬프트

```
프로젝트 루트에 CLAUDE.md 파일을 만들어줘. 아래 내용을 포함해.

# ContiCheck - 시나리오 정합성 검증 시스템 POC

## 프로젝트 개요
드라마/영화/게임/소설 시나리오의 모순을 자동으로 탐지하는 시스템.
7가지 모순 유형. Hard/Soft 형식 구분. 의도성 판단은 사용자에게 위임.

## 5계층 아키텍처
1. Extraction: 텍스트 → RawEntity
2. Normalization: RawEntity → NormalizedEntity (통합/병합/충돌감지)
3. Graph Materialization: NormalizedEntity → Vertex/Edge (DB 적재)
4. Contradiction Detection: 그래프 → 7가지 쿼리 → Hard/Soft 분류 → 모순 리포트
5. Review Workflow: 사용자 확인 → 그래프 피드백 → 재탐지 → 버전 관리
+ Storage: 횡단 서비스 (원본 파일 + 버전 스냅샷, 계층1/5에서 사용)

## 핵심 워크플로우
1) 3분류 업로드 (세계관/설정집/시나리오) → Storage 저장 → 파싱/청킹 → Extract → Normalize → Materialize(Cosmos DB) → Index(AI Search) [업로드 시 즉시 KB 구축]
2) 모순 탐지: Hard=자동 판정, Soft=사용자 확인(원본 발췌 필수)
3) 수정 반영: 스테이징 → Push → Storage에 버전 스냅샷 저장 → GraphRAG 재구축

## 기술 스택
- Backend: Python 3.12, FastAPI, LangGraph
- Frontend: React 18 + TypeScript + Tailwind CSS
- Database: Azure Cosmos DB (Gremlin API)
- Search: Azure AI Search
- Storage: Azure Blob Storage (원본 + 버전 스냅샷, 로컬 폴백: 파일시스템)
- LLM: Azure Foundry (GPT-5-nano 추출, Claude Opus 4.6 추론)
- 인프라: Azure 전체

## 온톨로지 (9노드 + 13엣지)
Vertices: Character, KnowledgeFact, Event, Trait, Organization,
          Location, Item, Source, UserConfirmation
Edges: LEARNS, MENTIONS, PARTICIPATES_IN, HAS_STATUS, AT_LOCATION,
       RELATED_TO, BELONGS_TO, FEELS, HAS_TRAIT, VIOLATES_TRAIT,
       POSSESSES, LOSES, SOURCED_FROM

## 이중 시간 축
- discourse_order: 텍스트 등장 순서 (항상 단조 증가, 자동 부여)
- story_order: 서사 세계 실제 시점 (null 가능 = 미확정 → 사용자 확인)
- is_linear: 두 축이 동일 방향인가 (false = 회상/비선형)

## 데이터 소스 분류
- worldview: 세계관
- settings: 설정집
- scenario: 시나리오
- manuscript: 검증 대상 신규 원고

## 디렉토리 구조
conticheck/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 앱
│   │   ├── config.py            # 환경 설정
│   │   ├── models/
│   │   │   ├── vertices.py      # 9 Vertex 모델
│   │   │   ├── edges.py         # 13 Edge 모델
│   │   │   ├── enums.py         # 열거형 + 기반 클래스
│   │   │   ├── intermediate.py  # RawEntity, NormalizedEntity
│   │   │   └── api.py           # API 입출력 모델
│   │   ├── services/
│   │   │   ├── storage.py       # 파일 저장 (Blob/로컬 전환)
│   │   │   ├── ingest.py        # 문서 파싱 + 청킹
│   │   │   ├── extraction.py    # 계층1: LLM 원시 추출
│   │   │   ├── normalization.py # 계층2: 정규화/통합
│   │   │   ├── graph.py         # 계층3: Cosmos DB 연동
│   │   │   ├── detection.py     # 계층4: 모순 탐지
│   │   │   ├── confirmation.py  # 계층5: 사용자 확인 관리
│   │   │   ├── version.py       # 계층5: 버전 관리 (Storage 연동)
│   │   │   ├── search.py        # Azure AI Search
│   │   │   └── agent.py         # LangGraph 오케스트레이터
│   │   └── prompts/
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   └── package.json
├── data/
│   ├── sample/                  # 테스트용 샘플 (세계관+설정집+시나리오)
│   ├── uploads/                 # 로컬 모드: 업로드 원본 저장
│   └── versions/                # 로컬 모드: 버전별 스냅샷
├── docs/ontology-schema.md
└── CLAUDE.md

## 코딩 컨벤션
- Python: 타입 힌트 필수, async/await 사용
- 환경변수: .env 파일
- 에러 처리: try/except + 재시도
- 로깅: structlog
```

---

## Phase 0: 프로젝트 스캐폴딩

### Step 0-1: 프로젝트 생성

```
프로젝트 스캐폴딩을 만들어줘.

1) Python 백엔드 (FastAPI):
   - requirements.txt: fastapi, uvicorn, python-dotenv, structlog,
     gremlinpython, azure-search-documents, azure-identity,
     azure-storage-blob, openai, anthropic, langgraph, pydantic,
     python-multipart, pypdf2, httpx
   - app/main.py: FastAPI 앱 + health check
   - app/config.py: 환경변수 로딩
     USE_LOCAL_GRAPH, USE_MOCK_EXTRACTION, USE_MOCK_SEARCH, USE_LOCAL_STORAGE (bool)
     + Azure 키들, Blob 연결 문자열, 서버 설정

2) React 프론트엔드: Vite + React + TypeScript + Tailwind CSS

3) .env.example:
   USE_LOCAL_GRAPH=true
   USE_MOCK_EXTRACTION=true
   USE_MOCK_SEARCH=true
   USE_LOCAL_STORAGE=true
   AZURE_COSMOS_ENDPOINT=
   AZURE_SEARCH_ENDPOINT=
   AZURE_OPENAI_ENDPOINT=
   AZURE_STORAGE_CONNECTION_STRING=
   AZURE_STORAGE_CONTAINER_UPLOADS=conticheck-uploads
   AZURE_STORAGE_CONTAINER_VERSIONS=conticheck-versions

4) CLAUDE.md (위에 정의한 내용)
5) data/uploads/, data/versions/ 디렉토리 생성

디렉토리 구조는 CLAUDE.md를 따라줘.
```

### Step 0-2: Pydantic 모델 — Vertex & Edge

```
backend/app/models/ 에 온톨로지 v2.2 기반 모델을 만들어줘.

=== enums.py ===
열거형 14종 + SourceLocation + VertexBase + EdgeBase 기반 클래스:
- CharacterTier(1~4), FactCategory(5종), FactImportance(3종)
- EventType(9종: scene/death/resurrection/location_change/status_change/
  relationship_change/trait_change/item_transfer/emotion_shift)
- StatusType(7종), TraitCategory(8종: personality/physical/ability/
  preference/background/rule/goal/motivation)
- LearnMethod(7종), MentionType(4종), RelationshipType(12종)
- EmotionType(11종: love/hate/trust/distrust/fear/jealousy/gratitude/
  resentment/admiration/contempt/neutral)
- OrgType(7종), PossessionType(4종: owns/holds/can_access/guards)
- SourceType(4종: worldview/settings/scenario/manuscript)
- ConfirmationType(9종), Severity(3종), ContradictionType(7종)

SourceLocation: source_id, source_name, page, chapter, line_range + display()
VertexBase: id(uuid), source_id, created_at, partition_key(property)
EdgeBase: id(uuid), source_id, source_location, created_at

=== vertices.py (9종) ===
1) Character: name, aliases, tier, description
2) KnowledgeFact: content, category, importance, is_secret, is_true(bool),
   established_order(float), source_location
3) Event: discourse_order(float, 항상 단조 증가, 자동 부여),
   story_order(float|None, 서사 세계 실제 시점, null=미확정),
   is_linear(bool, discourse와 story 동일 방향인가),
   event_type(9종: scene/death/resurrection/location_change/
   status_change/relationship_change/trait_change/item_transfer/
   emotion_shift), description, location,
   environment({time_of_day, weather, lighting, special_conditions})
4) Trait: category, key, value, description, is_immutable
5) Organization: name, org_type, description
6) Location: name, location_type, parent_location_id, travel_constraints
7) Item: name, is_unique, description, location_id
8) Source: source_type, name, metadata, ingested_at, status,
   file_path(str, StorageService가 반환한 저장 경로)
9) UserConfirmation: confirmation_type, status, question, context_summary,
   source_excerpts(list[SourceExcerpt]), related_entity_ids,
   user_response, resolved_at

=== edges.py (13종) ===
모든 엣지에 source_id, source_location 필수.
1) Learns: from→to, discourse_order, story_order, method, believed_true(bool),
   via_character_id, event_id, dialogue_text
2) Mentions: from→to, discourse_order, story_order, mention_type, dialogue_text
3) ParticipatesIn: from→to, role
4) HasStatus: from→to, status_type, status_value, location
5) AtLocation: from→to, discourse_order, story_order, arrived_via
6) RelatedTo: from→to, relationship_type, detail, established_order,
   valid_from, valid_until + is_active_at(order) 메서드
7) BelongsTo: from→to, role, is_secret, valid_from, valid_until
8) Feels: from→to, emotion, intensity(0~1), discourse_order, story_order, trigger_event_id
9) HasTrait: from→to, established_order, valid_from, valid_until
10) ViolatesTrait: from→to, character_id, violation_description,
    dialogue_text, requires_confirmation, confirmation_id
11) Possesses: from→to, discourse_order, story_order, method, possession_type,
    from_character_id
12) Loses: from→to, discourse_order, story_order, method, to_character_id
13) SourcedFrom: from→to, location, chunk_id

RELATIONSHIP_CONFLICT_MATRIX도 포함:
frozenset(['family_parent','family_sibling']): 'critical'
frozenset(['family_parent','family_spouse']): 'critical'
frozenset(['family_sibling','family_spouse']): 'warning'
frozenset(['family_parent','romantic']): 'warning'

각 모델에 validator와 json_schema_extra 예제 포함.
```

### Step 0-3: Pydantic 모델 — 중간 데이터 + API

```
backend/app/models/intermediate.py와 api.py를 만들어줘.

=== intermediate.py (계층 간 데이터 모델) ===

RawEntity (계층1 출력):
  - 추출된 원시 데이터. 아직 통합/정규화 전.
  class RawCharacter: name, possible_aliases, role_hint, source_chunk_id
  class RawFact: content, category_hint, is_secret_hint, source_chunk_id
  class RawEvent: description, characters_involved, location_hint, source_chunk_id
  class RawTrait: character_name, key, value, category_hint, source_chunk_id
  class RawRelationship: char_a, char_b, type_hint, detail, source_chunk_id
  class RawEmotion: from_char, to_char, emotion, trigger_hint, source_chunk_id
  class RawItemEvent: character_name, item_name, action(possesses/loses/uses),
                      source_chunk_id
  class RawKnowledgeEvent: character_name, fact_content, event_type(learns/mentions),
                           method, via_character, dialogue_text, source_chunk_id

  class ExtractionResult: characters, facts, events, traits, relationships,
                          emotions, item_events, knowledge_events, source_chunk_id

NormalizedEntity (계층2 출력):
  - 통합/정규화 완료. 그래프 적재 준비 상태.
  class NormalizedCharacter: canonical_name, all_aliases, tier, description,
                             merged_from(list[RawCharacter])
  class NormalizedFact: content, category, importance, is_secret, is_true,
                        merged_from(list[RawFact])
  class NormalizationResult: characters, facts, events, traits, organizations,
                             locations, items, relationships, emotions,
                             knowledge_events, item_events,
                             source_conflicts(list[SourceConflict])

  class SourceConflict: entity_type, descriptions(dict[source_id, str]),
                        conflicting_values

=== api.py ===
- ManuscriptInput: content, title
- DocumentChunk: id, source_id, chunk_index, content, location(SourceLocation)
- ContradictionReport: id, type(7종), severity, character_id, character_name,
  location, dialogue, description, evidence(list[EvidenceItem]),
  confidence, suggestion, alternative, needs_user_input, user_question,
  original_text
- EvidenceItem: source_name, source_location, text
- AnalysisResponse: contradictions, confirmations(list[UserConfirmation]),
  total, by_severity, by_type, processing_time_ms
  + from_contradictions() 팩토리
- KBStats: characters, facts, relationships, events, traits, locations,
  items, organizations, sources, confirmations
- IngestResponse: source_id, source_name, status, stats, extracted_entities
- VersionInfo: id, version, date, fixes_count, description
- ErrorResponse: detail, error_code
```

---

## Phase 1: Extraction — 계층 1 (Day 2~3)

### Step 1-0: 파일 저장 서비스

```
backend/app/services/storage.py를 구현해줘.

StorageService 인터페이스:

1) save_file(file_content, filename, source_id, source_type) → file_path:
   - 원본 파일을 영구 저장하고 경로(로컬) 또는 URL(Blob)을 반환
   - 반환된 file_path는 Source vertex의 file_path 필드에 반드시 기록

2) get_file(file_path) → bytes:
   - save_file()이 반환한 file_path로 파일 바이트 반환
   - source_id가 아닌 file_path를 인자로 받음

3) get_file_text(file_path) → str:
   - save_file()이 반환한 file_path로 텍스트 반환
   - source_id가 아닌 file_path를 인자로 받음

4) delete_file(file_path):
   - save_file()이 반환한 file_path로 파일 삭제
   - source_id가 아닌 file_path를 인자로 받음
   - 호출 전에 Source vertex에서 file_path를 먼저 조회해야 함

5) save_version_snapshot(source_id, version, content) → snapshot_path:
   - Push 시 수정된 원고를 버전별로 저장

6) get_version_content(source_id, version) → str:
   - 특정 버전의 원고 텍스트 반환

7) diff_version_content(version_a, version_b, source_id) → str:
   - 두 버전의 텍스트 차이 반환

8) list_versions(source_id) → list[str]:
   - 해당 소스의 버전 목록 반환

=== BlobStorageService (Azure Blob Storage) ===
- 컨테이너: conticheck-uploads (원본), conticheck-versions (스냅샷)
- 경로: uploads/{source_type}/{source_id}/{filename}
         versions/{version_id}/{source_id}/{filename}
- azure-storage-blob SDK 사용

=== LocalStorageService (로컬 파일시스템) ===
- 경로: data/uploads/{source_type}/{source_id}/{filename}
         data/versions/{version_id}/{source_id}/{filename}

환경변수 USE_LOCAL_STORAGE=true면 LocalStorageService 사용.
```

### Step 1-1: 문서 파싱 + 청킹

```
backend/app/services/ingest.py를 구현해줘.

IngestService 클래스:

upload 흐름:
  파일 수신 → StorageService.save_file()로 원본 저장
  → Source vertex 생성 (file_path 포함)
  → parse → 청킹 → 청크를 SearchService에 인덱싱

1) parse_txt(file_path, source_type) → list[DocumentChunk]:
   - StorageService.get_file_text()로 텍스트 읽기
   - 500토큰 단위, 100토큰 오버랩
   - 챕터/장 구분자 감지 ("# Chapter", "제1장", "EP01")
   - source_type(worldview/settings/scenario)을 청크 메타데이터에 기록

2) parse_pdf(file_path, source_type) → list[DocumentChunk]:
   - StorageService.get_file()로 바이트 읽기
   - PyPDF2 텍스트 추출, 페이지 정보 유지

3) 대본 형식 감지 ("캐릭터명: 대사" 패턴)

MockIngestService도 만들어줘 (로컬 파일 직접 읽기).
```

### Step 1-2: 추출 프롬프트

```
backend/app/prompts/extract_entities.py를 만들어줘.

소스 분류별로 다른 프롬프트 전략:

=== worldview 프롬프트 ===
"이 텍스트는 세계관 설정입니다. 다음을 추출하세요:
- 세계 규칙/법칙 (world_fact)
- 장소 (이름, 유형, 이동 제약)
- 조직/세력 (이름, 유형)
- 환경 조건 (시간/날씨가 중요한 규칙이 있으면)"

=== settings 프롬프트 ===
"이 텍스트는 캐릭터 설정집입니다. 다음을 추출하세요:
- 캐릭터 (이름, 별명, 역할)
- 특성 (key-value, 불변 여부)
- 관계 (두 캐릭터 간 관계 유형)
- 감정 상태 (누가 누구에게 어떤 감정)
- 목표/동기 (category: goal/motivation)
- 소유물 (아이템 이름, 유일 여부)"

=== scenario 프롬프트 ===
"이 텍스트는 시나리오/대본입니다. 다음을 추출하세요:
- 장면/이벤트 (설명, 장소, 환경 조건)
- 대사에서 정보 흐름 (누가 무엇을 알게 됨/언급함)
- 거짓말 감지 (is_true=false인 정보 전달)
- 아이템 이동 (누가 무엇을 얻음/잃음/사용)
- 위치 이동 (누가 어디로 이동)"

공통: JSON 출력 형식은 ExtractionResult 구조.
few-shot 예제 2개씩 포함.
```

### Step 1-3: 추출 서비스

```
backend/app/services/extraction.py를 구현해줘.

ExtractionService 클래스:

1) extract_from_chunk(chunk: DocumentChunk) → ExtractionResult:
   - chunk의 source_type에 따라 프롬프트 선택
   - LLM 호출 → JSON 파싱 → ExtractionResult 변환
   - 파싱 실패 시 재시도 (최대 3회)

2) extract_from_chunks(chunks: list[DocumentChunk]) → list[ExtractionResult]:
   - asyncio.gather + semaphore(동시 5개) 배치 처리

출력: list[ExtractionResult] (RawEntity 수준 — 아직 통합 전)

MockExtractionService: 규칙 기반으로 대사 패턴에서 캐릭터/대화 추출.
```

---

## Phase 2: Normalization — 계층 2 (Day 3~4)

### Step 2-1: 정규화 서비스

```
backend/app/services/normalization.py를 구현해줘.

NormalizationService 클래스:

이 계층이 해결하는 문제:
- "형사 A"와 "A"와 "에이"가 같은 캐릭터인가?
- "범인은 B이다"와 "B가 살인을 저질렀다"가 같은 사실인가?
- 세계관에서 "A는 B의 형"인데 시나리오에서 "A는 B의 아버지"면?

1) normalize(extractions: list[ExtractionResult]) → NormalizationResult:

   a) 캐릭터 통합:
      - 이름/별명 유사도로 같은 캐릭터 판정
      - LLM 보조: "이 두 이름이 같은 캐릭터인가?"
      - 결과: NormalizedCharacter (canonical_name + all_aliases)

   b) 사실 병합:
      - 의미적 유사도로 같은 사실 판정
      - 결과: NormalizedFact (대표 content + merged_from)

   c) Fact vs Trait 분류:
      - "다른 캐릭터가 이걸 모를 수 있는가?" → Yes=Fact, No=Trait
      - 비밀 속성 → 양쪽 모두 등록
      - LLM 보조 판정

   d) 다중 소스 충돌 감지:
      - 같은 엔티티가 소스별로 다르게 기술될 때
      - SourceConflict 생성 → 나중에 UserConfirmation으로 변환

2) _merge_characters(raws: list[RawCharacter]) → list[NormalizedCharacter]
3) _merge_facts(raws: list[RawFact]) → list[NormalizedFact]
4) _detect_source_conflicts(normalized) → list[SourceConflict]

MockNormalizationService: 이름 완전 일치로만 통합, 충돌 감지 안 함.
```

---

## Phase 3: Graph Materialization — 계층 3 (Day 4~5)

### Step 3-1: 그래프 서비스

```
backend/app/services/graph.py를 구현해줘.

GremlinGraphService 클래스:

=== 9종 Vertex CRUD ===
add_character, get_character, find_character_by_name, list_characters
(나머지 8종도 동일 패턴)

=== 13종 Edge 추가 ===
add_learns, add_mentions, add_participates, add_status,
add_at_location, add_related, add_belongs_to, add_feels,
add_has_trait, add_violates_trait, add_possesses, add_loses,
add_sourced_from

=== 적재 메서드 ===
materialize(normalized: NormalizationResult, source: Source):
  - NormalizedEntity → 실제 Vertex/Edge로 변환
  - discourse_order 자동 부여 (텍스트 순서, 항상 단조 증가)
  - story_order 추정 (선형이면 discourse와 동일, 비선형이면 추정 또는 null)
  - Cosmos DB에 적재
  - SourceConflict → UserConfirmation 변환

=== 모순 탐지 쿼리 7종 ===
find_knowledge_violations()       # story_order 기준 비교, null은 스킵
find_timeline_violations()        # story_order 기준, is_linear=false 자동 처리
find_relationship_violations()    # 충돌 매트릭스 + 다중 소스
find_trait_violations()
find_emotion_violations()
find_item_violations()            # possession_type + location_id
find_deception_violations()       # is_true + believed_true
find_all_violations() → 7종 통합 + Hard/Soft 분류

=== 임시 그래프 격리 (analyze 시) ===
snapshot_graph() → canonical graph의 관련 서브그래프를 In-Memory 복제
  - 복제본에 원고 데이터 추가
  - 복제본에서 쿼리 실행
  - 결과만 반환, 복제본 폐기
  - canonical graph는 한 번도 건드리지 않음
  - Push 시에만 canonical graph 업데이트

=== 유틸리티 ===
get_character_knowledge_at(character_id, story_order)
get_stats() → KBStats
remove_source(source_id) → 관련 전부 삭제

주의:
- Cosmos DB: 서브쿼리/match step 미지원 → Python 분리 실행
- 모든 쿼리에 파티션 키 포함
- 연결 풀 + 재시도 로직

InMemoryGraphService도 동일 인터페이스로 구현.
환경변수 USE_LOCAL_GRAPH=true면 인메모리.
```

### Step 3-2: [v2.2] 이중 시간 축 부여

```
graph.py 내 _assign_time_axes 메서드:

discourse_order 부여 (항상 자동):
- 텍스트에 등장하는 물리적 순서 그대로
- 챕터/장 번호 = 정수부, 장면/씬 순서 = 소수부 (0.1씩)
- Chapter 3의 두 번째 장면 → discourse_order = 3.1
- 항상 단조 증가, 예외 없음

story_order 부여 (추정 + 사용자 확인):
- 선형 서사 (대부분): story_order = discourse_order, is_linear = true
- 비선형 감지: discourse_order 순서로 읽으면서 "시간 점프" 힌트 탐지
  "10년 전", "그날 밤", "며칠 후" 같은 시간 표현
  이미 사망한 캐릭터 재등장
  장소/상황이 이전 시점으로 복귀
- 비선형 감지 시:
  story_order = 추정된 과거/미래 시점, is_linear = false
  확신 없으면 story_order = null → timeline_ambiguity 사용자 확인

여러 소스 간 통합:
- 첫 소스의 discourse_order/story_order가 기준점
- 같은 사건 → 같은 story_order 매핑
- 충돌 시 → SourceConflict
```

### Step 3-3: 쿼리 테스트

```
backend/tests/test_graph.py를 만들어줘.

InMemoryGraphService + LocalStorageService 기반 테스트:

테스트 데이터:
- S1:"세계관.txt"(worldview), S2:"설정집.txt"(settings), S3:"시나리오.pdf"(scenario)
- 캐릭터: A(형사), B(범인), C(목격자), D(파트너)
- 사실: F1:"범인은 B"(is_true=true), F_LIE:"B는 집에 있었다"(is_true=false)
- 위치: L1:"경찰서", L2:"골목"
- 아이템: I1:"증거 칼"(is_unique=true)
- 조직: O1:"경찰서"(government)

=== 정보 비대칭 (2건) ===
- A가 story=2.8에서 F1 언급 → LEARNS story=3.0 → HARD!
- A가 story=4.0에서 F1 언급 → 정상

=== 타임라인 (2건) ===
- B 사망(story=5.0) 후 등장(story=6.0), story_order 확정 → HARD!
- B 사망(story=5.0) 후 등장(story=null) → SOFT → timeline_ambiguity

=== 관계 (1건) ===
- A→D: colleague + family_parent → SOFT → relationship_ambiguity

=== 성격·설정 (2건) ===
- 혈액형 A형 + O형 (immutable) → HARD!
- 식습관 채식→육식 (mutable) → SOFT → intentional_change

=== 감정 (1건) ===
- A→B: trust→hate, trigger=null → SOFT → emotion_shift

=== 소유물 (2건) ===
- C가 I1 holds → B에게 양도 → C가 I1 사용 → SOFT → item_discrepancy
- I1이 A와 B에게 동시 → HARD!

=== 거짓말·기만 (1건) ===
- A가 F_LIE를 believed_true=true로 학습
- 진실 인지(story=3.0) 후에도 F_LIE 기반 행동(story=4.0) → HARD!

=== 소스 삭제 (1건) ===
- S1 삭제 → 관련 전부 삭제 + StorageService.delete_file() 호출 확인

=== Storage 연동 (1건) ===
- 파일 저장 → get_file_text() → 동일 내용 확인
```

---

## Phase 4: Contradiction Detection — 계층 4 (Day 5~7)

### Step 4-1: 탐지 서비스

```
backend/app/services/detection.py를 구현해줘.

DetectionService 클래스:

1) analyze(manuscript: ManuscriptInput) → AnalysisResponse:
   - 원고 → 계층1(추출) → 계층2(정규화) → 계층3(스냅샷에 임시 적재)
   - snapshot_graph()로 canonical 격리
   - find_all_violations() 실행
   - Hard → 자동 판정 (confidence 무관)
   - Soft → LLM 검증 → confidence≥0.8이면 자동, 아니면 UserConfirmation
   - 복제본 폐기 (canonical 보호)
   - contradictions + confirmations 반환

2) full_scan() → AnalysisResponse:
   - 전체 그래프 대상 전수조사

3) _classify_hard_soft(violation) → "hard" | "soft":
   - Hard: immutable 속성 충돌, story_order 확정된 사망 후 등장,
     유일 아이템 중복, 확정 관계 충돌(critical), 진실 인지 후 거짓 기반 행동
   - 나머지 전부: Soft

4) _verify_soft_with_llm(violation) → (confidence, reasoning):
   - Soft 항목만 LLM 검증
   - 의도성 판단 금지 (confidence 낮게 → 사용자 확인)
```

### Step 4-2: 검증 프롬프트

```
backend/app/prompts/verify_contradiction.py:

핵심 지시:
- "복선일 수 있다"고 판단하지 마세요. confidence를 낮게 산출하세요.
- "캐릭터 성장일 수 있다"고 판단하지 마세요. confidence를 낮게 산출하세요.
- 의도성은 작가만 판단할 수 있습니다.

출력:
{
  "is_contradiction": bool,
  "confidence": 0.0~1.0,
  "reasoning": "판단 근거",
  "suggestion": "수정 제안",
  "alternative_interpretation": "대안 해석 (있으면)",
  "user_question": "사용자에게 물을 질문 (confidence<0.8일 때)"
}
```

### Step 4-3: LangGraph 에이전트

```
backend/app/services/agent.py:

[input] → ManuscriptInput
   ↓
[extract] → 계층1: ExtractionService
   ↓
[normalize] → 계층2: NormalizationService
   ↓
[snapshot] → 계층3: GraphService.snapshot_graph() (canonical 격리)
   ↓
[materialize] → 스냅샷에 원고 데이터 적재
   ↓
[detect] → 계층4: DetectionService (7가지 쿼리)
   ↓
   ├─ Hard → [report] → ContradictionReport (자동)
   ├─ Soft + confidence≥0.8 → [report] → ContradictionReport (자동)
   ├─ Soft + confidence<0.8 → [confirm] → UserConfirmation
   └─ 모순 없음 → [approve]
   ↓
[cleanup] → 스냅샷 폐기
   ↓
[respond] → AnalysisResponse (contradictions + confirmations + hard/soft 집계)
```

---

## Phase 5: Review Workflow — 계층 5 (Day 7~8)

### Step 5-1: 사용자 확인 서비스

```
backend/app/services/confirmation.py:

ConfirmationService 클래스:

1) create_confirmation(type, question, context, source_excerpts, entity_ids):
   - source_excerpts 필수 (원본 없이 생성 금지)

2) list_pending() → list[UserConfirmation]

3) resolve(id, user_response, decision):
   decision별 처리:
   - confirmed_contradiction → DetectionService에 리포트 생성 요청
   - confirmed_intentional → 그래프 업데이트 (valid_until 등)
   - deferred → 상태만 변경

   피드백 루프:
   - flashback_check 해결 → Event.story_order 확정 + is_linear=false → 계층4 재탐지
   - source_conflict 해결 → 비정본 비활성화 → 계층3 그래프 업데이트
   - intentional_change 해결 → Trait valid_until 설정 → 계층3 업데이트

4) get_source_excerpts(entity_ids) → SearchService에서 원본 검색
```

### Step 5-2: 버전 관리 서비스

```
backend/app/services/version.py:

VersionService 클래스 (StorageService 연동):

1) stage_fix(contradiction_id, original_text, fixed_text)

2) push_staged_fixes(fixes) → VersionInfo:
   - Source vertex에서 file_path 조회 → StorageService.get_file_text(file_path)로 현재 원본 읽기
   - 원본에 수정사항 반영 (텍스트 치환)
   - StorageService.save_version_snapshot(version_id, source_id, 수정된 텍스트)
   - Source vertex의 file_path 업데이트 (최신 버전 가리킴)
   - 새 버전 정보 생성 (VersionInfo with snapshot_path)
   - 변경 영역만 계층1~3 재실행 (증분 재구축)
   - 반영된 모순을 resolved로 마킹

3) list_versions() → list[VersionInfo]

4) get_version(version_id) → str:
   - StorageService.get_version_content(version_id, source_id)

5) diff_versions(a, b) → str:
   - StorageService.diff_version_content(a, b, source_id)
```

---

## Phase 6: Azure AI Search 연동 (Day 8)

```
backend/app/services/search.py:

SearchService 클래스:
1) index_chunks(source_id, chunks): 벡터+키워드 하이브리드 인덱싱
2) search_context(query, top_k=5): 모순 근거 원문 검색
3) get_source_excerpts(entity_ids): UserConfirmation용 원본 발췌
4) remove_source(source_id): 인덱스 정리

MockSearchService: 문자열 매칭 기반.
```

---

## Phase 7: FastAPI 엔드포인트 (Day 8~9)

```
backend/app/main.py:

=== 소스 관리 ===
POST /api/sources/upload       — 3분류 업로드 → StorageService.save_file() + 파싱
GET  /api/sources              — 소스 목록 (분류별 필터)
GET  /api/sources/{id}/download — 원본 파일 다운로드 (StorageService.get_file())
DELETE /api/sources/{id}       — 삭제 + StorageService.delete_file() + 그래프/인덱스 정리

=== GraphRAG 구축 ===
POST /api/graph/build          — { track: "ws" | "sc" }
GET  /api/graph/status         — 구축 상태

=== 모순 탐지 ===
POST /api/analyze              — ManuscriptInput → AnalysisResponse
POST /api/scan                 — 전수조사

=== 사용자 확인 ===
GET  /api/confirmations        — 미해결 목록
POST /api/confirmations/{id}/resolve  — 해결

=== 수정 반영 ===
POST /api/fixes/stage          — 스테이징
POST /api/fixes/push           — 일괄 반영 → StorageService.save_version_snapshot() → 재구축

=== 버전 ===
GET  /api/versions             — 이력
GET  /api/versions/{id}        — 상세
GET  /api/versions/{id}/content — 해당 버전 원고 텍스트 (StorageService)
GET  /api/versions/{a}/diff/{b} — 비교 (StorageService)

=== 조회 ===
GET  /api/kb/stats
GET  /api/characters
GET  /api/characters/{id}/knowledge
GET  /api/facts
GET  /api/events

=== AI 질의 ===
POST /api/ai/query

=== 헬스 ===
GET  /api/health

CORS + 에러 처리 + structlog.
```

---

## Phase 8: 프론트엔드 실제 구현 (Day 5~9, 병렬)

```
v3 프로토타입(conticheck-v3.html) 구조를 따라:

레이아웃: 좌측 사이드바(260px) + 메인 콘텐츠

사이드바: 프로젝트 목록, 새 프로젝트 버튼
프로젝트뷰: 3탭 (개요/모순/버전)

개요: KB 통계 5종 + 소스 목록 + 모순 알림 + AI 질의 버튼
모순: 스테이징 + 필터 + 모순 카드(HARD/SOFT 배지, 수정/Commit) + AI 질의 2컬럼
버전: 타임라인 이력 + 원고 보기(/content) + 비교(/diff)

새 프로젝트: 온보딩 + 3분류 업로드 + 2트랙 구축

AI 질의 버튼: 그라데이션, 눈에 띄는 디자인
사용자 확인 UI: 원본 발췌 나란히 + 응답 입력
```

---

## Phase 9: 샘플 데이터 + 통합 테스트 (Day 9~10)

### Step 9-1: 샘플 파일

```
data/sample/ 에 3종:

1) 세계관_그림자의비밀.txt (worldview):
   - 현대 한국, 마법 없음
   - 경찰서 ↔ 골목: 차량 15분
   - 야간 골목: 조명 없음 (dark)

2) 설정집_그림자의비밀.txt (settings):
   - A: 형사, 정의감, 채식, 혈액형A, 목표=범인체포
   - B: 범인, 근처 거주, 조직=없음
   - C: 목격자, 증거 칼 소유(holds)
   - D: 파트너, A와 동료
   - 감정: A→D=trust, A→B=neutral

3) 시나리오_그림자의비밀.txt (scenario):
   Chapter 1~4 대본 형식
   의도적 모순:
   - 정보 비대칭: A가 C 고백 전에 "B가 범인" 발언 → HARD
   - 거짓말: B가 A에게 거짓 알리바이 → A가 나중에 진실 인지 후에도 거짓 기반 행동 → HARD
   - 감정: A→B 갑자기 hate (이벤트 없음) → SOFT
   - 소유물: C가 칼을 B에게 양도 후 A에게 보여줌 → SOFT
   - 환경: 칠흑 밤에 A가 먼 곳을 맨눈으로 관찰 → SOFT
```

### Step 9-2: E2E 테스트

```
backend/tests/test_e2e.py:

5계층 전체 파이프라인 + Storage:
1) InMemory + MockSearch + LocalStorage 사용
2) 세계관+설정집 upload → StorageService에 원본 저장 확인 → 트랙A 구축
3) 시나리오 upload → 트랙B 구축
4) 검증 원고 analyze (스냅샷 격리 확인: canonical 미변경)
5) 결과 검증:
   - HARD 모순 ≥2건 (정보 비대칭, 거짓말)
   - SOFT UserConfirmation ≥2건 (감정, 소유물)
   - 각 근거에 소스 파일명+위치
6) UserConfirmation 해결 → 피드백 루프 → 재탐지
7) Push 테스트:
   - StorageService.save_version_snapshot() 호출 확인
   - data/versions/ 에 스냅샷 존재 확인
   - 새 버전 생성 → resolved 확인
8) 원본 다운로드 테스트:
   - /api/sources/{id}/download → 원본 내용 일치
9) 버전 비교 테스트:
   - /api/versions/{v1}/diff/{v2} → diff 결과 존재
```

---

## Claude Code 사용 팁

### 1. 한 번에 하나씩
Step 하나 → 결과 확인 → 다음 Step.

### 2. 이전 코드 참조
"storage.py에서 만든 StorageService를 사용해서 ingest.py를 구현해줘"

### 3. 에러 시
에러 메시지 그대로: "이 에러가 나. 수정해줘: [에러]"

### 4. 테스트 먼저
각 계층마다 테스트. StorageService는 가장 먼저 테스트 (다른 서비스가 의존).

### 5. 계층별 디버깅
"파일은 업로드됐는데 청크가 안 만들어져. StorageService.get_file_text()는 정상인데 IngestService.parse_txt()에서 빈 결과가 나와."
→ 문제 계층을 특정해서 전달하면 해결이 빠름.

### 6. 프롬프트 튜닝
"extraction 프롬프트에서 emotions가 누락돼. 실패: [입력] → [기대] vs [실제]"

---

## 팀원별 가이드

### 온톨로지 + DB 담당
- Phase 3 (Graph Materialization) 집중
- "9종 노드와 13종 엣지의 Cosmos DB 쿼리를 만들어줘"
- "이중 시간 축(discourse_order/story_order) 부여 + 비선형 서사 감지 로직"
- "UserConfirmation 해결 시 그래프 피드백 업데이트 쿼리"

### LLM 엔지니어 (추출)
- Phase 1 (Extraction) + Phase 2 (Normalization) 집중
- "세계관 텍스트에서 규칙/법칙 추출 프롬프트 개선"
- "Fact vs Trait 자동 분류 프롬프트"
- "같은 캐릭터 다른 이름 통합 로직"

### LLM 엔지니어 (탐지)
- Phase 4 (Detection) 집중
- "Hard/Soft 분류 로직 구현 (_classify_hard_soft)"
- "confidence를 보수적으로 산출하는 검증 프롬프트"
- "거짓말 탐지: believed_true 기반 쿼리 로직"

### 백엔드 개발자
- Phase 0 (Storage) + Phase 5 (Review) + Phase 7 (API) 집중
- "StorageService Blob/로컬 전환 구현"
- "Push 시 원본 반영 → 버전 스냅샷 저장 → 증분 재구축 파이프라인"
- "소스 다운로드 / 버전 content / diff API"

### 프론트엔드 개발자
- Phase 8 집중
- "v3 프로토타입의 사이드바를 React 컴포넌트로"
- "모순 카드에 HARD/SOFT 배지 표시"
- "버전 탭: 원고 보기(/content) + 비교(/diff) UI"
- "AI 질의 버튼: 그라데이션 디자인"

---

## 데모 당일 체크리스트

- [ ] LocalStorage 모드에서 파일 업로드 → data/uploads/ 저장 확인
- [ ] InMemory + MockSearch + LocalStorage E2E 테스트 통과
- [ ] 샘플 파일 3종 (세계관+설정집+시나리오) 업로드 성공
- [ ] 3분류 업로드 → 2트랙 GraphRAG 구축
- [ ] 7가지 모순 중 최소 4가지 탐지 (HARD 2건 + SOFT 2건)
- [ ] 스냅샷 격리 확인 (analyze 후 canonical graph 미변경)
- [ ] 사용자 확인 → 해결 → 피드백 루프 → 재탐지
- [ ] 모순 수정 → 스테이징 → Push → data/versions/ 스냅샷 확인 → 버전 생성
- [ ] /api/sources/{id}/download → 원본 다운로드 성공
- [ ] /api/versions/{id}/content → 버전 원고 표시 성공
- [ ] AI 질의가 GraphRAG 참조하여 응답
- [ ] 각 근거에 소스 파일명+위치 표시
- [ ] 5계층 각각의 중간 결과 확인 가능 (디버깅 로그)