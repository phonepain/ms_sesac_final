# ContiCheck 온톨로지 설계 문서

> **이 문서는 v2.2 (초기 설계)입니다.**
> **최신 버전은 [`conticheck-ontology-schema-v3.md`](./conticheck-ontology-schema-v3.md) (v3.1, 2026-03-26)를 참고하세요.**
>
> v3.1 주요 차이:
> - FactCategory 6종 (`narration_fact` 추가)
> - Source vertex: `original_file_path` 추가
> - UserConfirmation: `original_text`, `dialogue` 추가
> - RELATIONSHIP_CONFLICT_MATRIX 4개 → 8개 확장
> - 모순 탐지 11종 구조적 쿼리 + LLM 2종
> - LEARNS `via_character_id` → `via_character` (이름 저장)
> - RELATED_TO `relationship_detail` → `detail`

---

> **버전**: 2.2 (초기 설계 — 아카이브용)
> **목적**: 시나리오 정합성 검증을 위한 지식 그래프 스키마 정의
> **범위**: 7가지 모순 유형 + Hard/Soft 형식 구분 + 이중 시간 축 + 사용자 확인 플로우 + 임시 그래프 격리
> **v2.1→v2.2 변경**: 이중 시간 축(discourse_order/story_order) 도입, Hard Contradiction vs Soft Inconsistency 형식 구분, 임시 그래프 격리 모델(In-Memory 스냅샷) 정의, is_flashback/flashback_target_order 제거(이중 축으로 대체)
> **v2→v2.1 변경**: 거짓말·기만(Fact.is_true, LEARNS.believed_true), 장면 환경 제약(Event.environment), 세력·조직(Organization, BELONGS_TO), 목표·동기(Trait category 확장), Fact vs Trait 구분 기준, 아이템 소유 세분화(possession_type, location_id)
> **v1→v2 변경**: 감정/위치/소유물 추적을 확장에서 메인으로 승격, 사용자 확인 플로우 강화, 과거 회상 감지, 다중 소스 충돌 해결, wiki 제거

---

## 1. 설계 원칙

### 1.1 핵심 질문

ContiCheck의 모든 모순 탐지는 다음 여섯 가지 질문으로 귀결됩니다:

| # | 모순 유형 | 핵심 질문 |
|---|----------|----------|
| 1 | 정보 비대칭 | "이 캐릭터가 **이 시점에** 이 정보를 알 수 있는가?" |
| 2 | 타임라인 | "이 캐릭터/사물이 **이 시점에** 이 상태/위치일 수 있는가?" |
| 3 | 관계 | "이 두 캐릭터의 관계가 **서로 모순되지 않는가**?" |
| 4 | 성격·설정 | "이 캐릭터의 행동/대사가 **확립된 설정과 일치하는가**?" |
| 5 | 감정 일관성 | "이 캐릭터의 감정 변화가 **서사적으로 자연스러운가**?" |
| 6 | 소유물 추적 | "이 아이템이 **이 시점에 이 캐릭터에게 있을 수 있는가**?" |
| 7 | 거짓말·기만 | "이 캐릭터가 전달한 정보가 **사실인가, 의도적 거짓인가**? 다른 캐릭터가 이를 믿고 있는가?" |

### 1.2 설계 결정

**[v2.2] 시간 축은 이중 축(`discourse_order` + `story_order`)을 사용합니다.**  
하나의 이벤트에 두 개의 시간 값이 붙습니다:
- `discourse_order`(float): 텍스트에 등장하는 물리적 순서. 독자/관객이 접하는 순서. **항상 단조 증가하며 자동 부여됩니다.**
- `story_order`(float|None): 서사 세계 안에서 실제로 일어난 시간 순서. 회상이면 discourse_order보다 앞선 값을 가집니다. **None이면 미확정 → 사용자 확인 대상.**

이 분리로 회상, 프롤로그, 플래시포워드, 비선형 서사를 예외 분기 없이 처리합니다:
- 정보 비대칭 쿼리: `MENTIONS.story_order < LEARNS.story_order` → 모순 (단일 비교, 예외 없음)
- 비선형 서사 감지: `discourse_order`는 증가하는데 `story_order`가 감소 → 회상/비선형

**출처 추적은 모든 엣지에 포함합니다.**  
어떤 정보든 "어디서 나왔는가"를 추적해야 근거를 제시할 수 있습니다. 모든 엣지에 `source_id`와 `source_location`을 필수 속성으로 붙입니다.

**상태 변화는 "이벤트"로 기록합니다.**  
캐릭터의 상태(생존/사망, 위치 이동, 관계 변화 등)가 바뀔 때마다 별도의 이벤트 노드를 생성합니다. 현재 상태를 직접 수정하지 않고 이벤트를 누적하는 이벤트 소싱 방식입니다.

**[v2 신규] 의도성 판단은 사용자에게 위임합니다.**  
LLM이 "모순인지 복선인지", "설정 변화가 의도적인지" 판단하려 하지 않습니다. 작가의 의도를 알아야만 가능한 판단은 사용자 확인 요청(UserConfirmation)으로 처리합니다.
- 세계관/설정집이 있으면 → 구조적 판단 가능 범위가 넓어져 사용자 확인 감소
- 시나리오만 있으면 → 맥락이 부족하므로 사용자 확인이 증가하지만, 이것이 모순을 놓치는 것보다 안전

**[v2 신규] 다중 소스 충돌 시 사용자가 정본을 결정합니다.**  
여러 소스(세계관, 설정집, 시나리오)에서 같은 사실이 다르게 기술될 때, 시스템은 충돌을 감지하고 원본을 나란히 보여주며 사용자에게 어떤 것이 올바른지 확인을 요청합니다.

**[v2.2] 모순은 Hard Contradiction과 Soft Inconsistency로 형식 구분합니다.**  
- **Hard Contradiction**: 서사 세계의 규칙 내에서 어떤 해석으로도 동시에 참일 수 없는 논리적 모순. confidence와 무관하게 자동 판정. 사용자는 "수정" 또는 "세계관 규칙 변경"만 가능.
- **Soft Inconsistency**: 단독으로 보면 불일치하지만 서사적 맥락에서 의도적일 수 있는 것. 사용자 확인 필요. "의도된 것"으로 확인되면 향후 스킵.

**[v2.2] 신규 원고 분석 시 canonical graph는 격리됩니다 (In-Memory 스냅샷).**  
분석 대상 원고의 데이터를 기존 지식 베이스에 직접 적재하지 않습니다. canonical graph의 관련 서브그래프를 메모리에 복제하고, 복제본에 원고 데이터를 추가한 뒤, 복제본에서 모순 쿼리를 실행합니다. 결과만 반환하고 복제본은 폐기합니다.
- canonical graph 오염 가능성 0%
- 분석 중 에러/중단 시에도 원본 안전
- 동시 분석 간 간섭 없음 (각자 별도 복제본)
- Push 시에만 canonical graph를 업데이트

---

## 2. Vertex (노드) 정의

### 2.1 Character — 캐릭터

서사에 등장하는 인물입니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `name` | string | ✅ | 대표 이름 |
| `aliases` | string[] | | 별명, 다른 호칭 (예: "홍길동", "길동이", "의적") |
| `tier` | int (1~4) | ✅ | 중요도 (1=주인공급, 4=엑스트라) |
| `description` | string | | 캐릭터 요약 |
| `source_id` | string | ✅ | 최초 등장 소스 |
| `partition_key` | string | ✅ | = `"character"` (Cosmos DB용) |

**tier 기준**:
- tier 1: 주인공, 주요 적대자 — 모든 발화를 추적
- tier 2: 주요 조연 — 핵심 사실 관련 발화 추적
- tier 3: 반복 등장 조연 — 설정 모순만 체크
- tier 4: 엑스트라 — 추적 안 함

### 2.2 KnowledgeFact — 사실/정보

서사 세계 내에서 "참"인 정보 단위입니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `content` | string | ✅ | 사실 내용 (예: "범인은 B이다") |
| `category` | enum | ✅ | 분류 (아래 참고) |
| `importance` | enum | ✅ | `"critical"` / `"major"` / `"minor"` |
| `is_secret` | boolean | | 비밀 정보 여부 (정보 비대칭 탐지에 핵심) |
| `is_true` | boolean | ✅ | [v2.1] 서사 세계에서 실제로 참인지 (false=거짓 정보/기만) |
| `established_order` | float | ✅ | 서사 내 최초 확립 시점 |

**[v2.1] KnowledgeFact vs Trait 구분 기준**:

두 타입 모두 캐릭터에 관한 정보를 담지만 역할이 다릅니다:
- **Trait** = 캐릭터에 귀속된 속성 (key-value). "이 캐릭터는 어떤 사람인가?"에 답함. 비교 대상은 같은 캐릭터의 행동/다른 시점 설정. 모순 탐지는 "같은 key에 다른 value" 또는 "행동이 설정 위배".
- **KnowledgeFact** = 서사 세계의 사실. "누가 이걸 알고 있는가?"가 중요함. 비교 대상은 캐릭터의 지식 상태(LEARNS/MENTIONS). 모순 탐지는 "모르는 정보를 언급".

판별 테스트: **"다른 캐릭터가 이걸 모를 수 있는가?"**
- Yes → KnowledgeFact (정보 흐름 추적 필요)
- No → Trait (설정 일관성 검증용)
- 비밀 속성 (예: "A는 사실 왕족이다") → **양쪽 모두에 등록** (Trait: background/왕족 + Fact: is_secret=true)
| `source_id` | string | ✅ | 출처 소스 |
| `source_location` | string | ✅ | 출처 위치 (페이지, 챕터 등) |
| `partition_key` | string | ✅ | = `"fact"` |

**category 목록**:
- `plot_secret`: 줄거리 핵심 비밀 (범인 정체, 보물 위치 등)
- `character_info`: 캐릭터 관련 정보 (신분, 과거 등)
- `world_fact`: 세계관 설정 (법칙, 역사, 지리 등)
- `relationship_fact`: 관계 관련 사실 (혈연, 소속 등)
- `event_fact`: 사건 관련 사실 (누가 무엇을 했는가)

### 2.3 Event — 이벤트/장면

서사 내에서 발생하는 사건 단위입니다. 상태 변화의 기록 단위이기도 합니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `discourse_order` | float | ✅ | [v2.2] 텍스트 등장 순서 (독자가 접하는 순서, 항상 단조 증가, 자동 부여) |
| `story_order` | float / null | | [v2.2] 서사 세계 내 실제 시점 (null이면 미확정 → 사용자 확인) |
| `is_linear` | boolean | ✅ | [v2.2] discourse_order와 story_order가 동일 방향인가 (false=회상/플래시포워드) |
| `event_type` | enum | ✅ | 분류 (아래 참고) |
| `description` | string | ✅ | 이벤트 설명 |
| `location` | string | | 서사 내 장소 |
| `environment` | object / null | | [v2.1] 장면 환경 조건 (아래 참고) |
| `source_id` | string | ✅ | 출처 소스 |

**[v2.1] environment 속성 구조**:
- `time_of_day`: `dawn` / `morning` / `afternoon` / `evening` / `night` / `unknown`
- `weather`: `clear` / `rain` / `storm` / `snow` / `fog` / `unknown`
- `lighting`: `bright` / `dim` / `dark` / `artificial` / `unknown`
- `special_conditions`: string[] — 특수 조건 (예: "정전", "화재 중", "수중", "밀폐 공간")

→ 환경과 행동의 불일치 탐지 (예: "칠흑 같은 밤에 먼 산을 맨눈으로 관찰", "정전 중 컴퓨터 사용")
| `source_location` | string | ✅ | 출처 위치 |
| `partition_key` | string | ✅ | = `"event"` |

**event_type 목록**:
- `scene`: 일반 장면
- `death`: 캐릭터 사망
- `resurrection`: 캐릭터 부활/생존 확인
- `location_change`: 캐릭터 위치 이동
- `status_change`: 기타 상태 변화 (체포, 부상, 회복 등)
- `relationship_change`: 관계 변화 (결혼, 이별, 배신 등)
- `trait_change`: 설정 변화 (능력 획득/상실 등)
- `item_transfer`: [v2] 아이템 양도/습득
- `emotion_shift`: [v2] 감정 변화 이벤트

> **[v2.2] 참고**: `flashback_start` / `flashback_end`는 제거되었습니다. 이중 시간 축(`discourse_order` ≠ `story_order`, `is_linear=false`)으로 비선형 서사를 자동 표현합니다.

### 2.4 Trait — 캐릭터 특성/설정

캐릭터에 부여된 고정 속성입니다. 성격, 외모, 능력, 취향 등을 포함합니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `category` | enum | ✅ | 분류 (아래 참고) |
| `key` | string | ✅ | 속성 키 (예: "식습관", "혈액형", "직업") |
| `value` | string | ✅ | 속성 값 (예: "채식주의", "A형", "형사") |
| `description` | string | | 상세 설명 |
| `is_immutable` | boolean | | 변경 불가 속성 여부 (혈액형 등) |
| `source_id` | string | ✅ | 출처 소스 |
| `source_location` | string | ✅ | 출처 위치 |
| `partition_key` | string | ✅ | = `"trait"` |

**category 목록**:
- `personality`: 성격 (내성적, 용감한, 잔인한 등)
- `physical`: 신체 특성 (키, 외모, 장애 등)
- `ability`: 능력/기술 (무술, 해킹, 요리 등)
- `preference`: 취향/습관 (채식, 왼손잡이 등)
- `background`: 배경 (직업, 학력, 출신 등)
- `rule`: 캐릭터의 행동 규칙 ("절대 거짓말 안 한다" 등)
- `goal`: [v2.1] 캐릭터의 목표 ("범인을 잡겠다", "복수하겠다" 등)
- `motivation`: [v2.1] 캐릭터의 동기 ("가족을 지키기 위해", "권력욕" 등)

> **참고**: goal/motivation은 거의 모든 위반이 사용자 확인 영역입니다. 구조적 쿼리로 "목표에 반하는 행동"을 자동 탐지하기 어렵기 때문입니다. 다만 Trait으로 기록해두면 사용자 확인 시 맥락 제공에 활용됩니다.

### 2.5 [v2.1 신규] Organization — 세력/조직

캐릭터가 소속된 조직, 세력, 단체입니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `name` | string | ✅ | 조직 이름 |
| `org_type` | enum | ✅ | `government` / `military` / `criminal` / `corporate` / `religious` / `secret` / `other` |
| `description` | string | | 조직 설명 |
| `source_id` | string | ✅ | 출처 소스 |
| `partition_key` | string | ✅ | = `"organization"` |

> **POC 범위**: 조직 노드와 BELONGS_TO 엣지까지만 구현. 조직 간 관계(동맹/적대)는 확장으로 미룸.

### 2.6 [v2 신규] Location — 장소

서사 세계 내의 장소입니다. 위치 추적과 이동 시간 검증에 사용합니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `name` | string | ✅ | 장소 이름 |
| `location_type` | enum | ✅ | `region` / `city` / `building` / `room` / `outdoor` / `abstract` |
| `parent_location_id` | string | | 상위 장소 (예: 방 → 건물 → 도시) |
| `description` | string | | 장소 설명 |
| `travel_constraints` | string | | 이동 제약 조건 (예: "도보 2시간", "비행기만 가능") |
| `source_id` | string | ✅ | 출처 소스 |
| `partition_key` | string | ✅ | = `"location"` |

### 2.6 [v2 신규] Item — 소유물/아이템

서사에서 추적해야 하는 물건입니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `name` | string | ✅ | 아이템 이름 |
| `is_unique` | boolean | ✅ | 유일한 물건 여부 (칼이 2개 있으면 false) |
| `description` | string | | 아이템 설명 |
| `location_id` | string | | [v2.1] 아이템이 현재 놓인 장소 (Location 참조, 누가 들고 있으면 null) |
| `source_id` | string | ✅ | 출처 소스 |
| `partition_key` | string | ✅ | = `"item"` |

### 2.7 Source — 데이터 출처

지식 베이스에 입력된 원본 자료입니다. 다른 모든 노드/엣지의 출처를 추적합니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `source_type` | enum | ✅ | `"worldview"` / `"settings"` / `"scenario"` / `"manuscript"` |
| `name` | string | ✅ | 파일명 |
| `metadata` | string (JSON) | | 페이지 수, 파일 크기 등 |
| `ingested_at` | string | ✅ | 등록 시각 |
| `partition_key` | string | ✅ | = `"source"` |

### 2.8 [v2 신규] UserConfirmation — 사용자 확인 요청

모순인지 의도인지 시스템이 판단할 수 없는 항목을 기록합니다.

| 속성 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | string (uuid) | ✅ | 고유 식별자 |
| `confirmation_type` | enum | ✅ | 확인 유형 (아래 참고) |
| `status` | enum | ✅ | `pending` / `confirmed_contradiction` / `confirmed_intentional` / `deferred` |
| `question` | string | ✅ | 사용자에게 표시할 질문 |
| `context_summary` | string | ✅ | 판단에 필요한 맥락 요약 |
| `source_excerpts` | list[SourceExcerpt] | ✅ | 관련 원본 발췌 목록 (사용자에게 표시) |
| `related_entity_ids` | list[string] | ✅ | 관련 캐릭터/사실/이벤트 ID |
| `user_response` | string | | 사용자의 답변 |
| `resolved_at` | datetime | | 해결 시각 |
| `partition_key` | string | ✅ | = `"confirmation"` |

**confirmation_type 목록**:
- `flashback_check`: 과거 회상 장면인지 확인
- `intentional_change`: 설정 변화가 의도적 캐릭터 성장인지 확인
- `foreshadowing`: 모순인지 복선인지 확인
- `source_conflict`: 다중 소스 간 충돌 — 어떤 것이 정본인지 확인
- `unreliable_narrator`: 신뢰할 수 없는 화자인지 확인
- `timeline_ambiguity`: 시간 순서가 불분명할 때 확인
- `relationship_ambiguity`: 관계가 의도적으로 모호한지 확인
- `emotion_shift`: 급격한 감정 변화가 의도적인지 확인
- `item_discrepancy`: 아이템 소유/위치 불일치 확인

**SourceExcerpt (원본 발췌)**: 사용자 확인 시 원본을 나란히 보여주기 위한 구조

| 필드 | 타입 | 설명 |
|------|------|------|
| `source_name` | string | 소스 파일명 |
| `source_location` | string | 페이지/챕터/섹션 |
| `text` | string | 원문 발췌 |
| `highlight_range` | tuple[int,int] | 하이라이트할 범위 (선택) |

---

## 3. Edge (관계) 정의

### 3.1 정보 비대칭 탐지용 엣지

#### LEARNS — "알게 됨"

캐릭터가 특정 시점에 특정 사실을 알게 되었음을 나타냅니다.

| 방향 | Character → KnowledgeFact |
|------|--------------------------|
| `discourse_order` | float — [v2.2] 텍스트 등장 순서 |
| `story_order` | float / null — [v2.2] 서사 세계 내 실제 시점 |
| `method` | enum — 정보 획득 방법 |
| `believed_true` | boolean — [v2.1] 캐릭터가 이 정보를 참이라고 믿는지 (거짓말에 속은 경우 true이지만 Fact.is_true=false) |
| `via_character` | string (id) — 누구를 통해 알게 되었는가 (선택) |
| `event_id` | string — 관련 이벤트 (선택) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |
| `dialogue_text` | string — 관련 대사/서술 원문 (선택) |

**method 목록**:
- `witness`: 직접 목격/경험
- `told_by`: 다른 캐릭터가 알려줌
- `discovered`: 문서/증거 발견
- `overheard`: 엿들음
- `inferred`: 추론으로 알게 됨
- `public`: 공개 정보 (모든 캐릭터가 아는 것)
- `inherent`: 본인에 관한 사실 (자동으로 앎)

#### MENTIONS — "언급함"

캐릭터가 특정 시점에 특정 사실을 대사/행동으로 언급했음을 나타냅니다.

| 방향 | Character → KnowledgeFact |
|------|--------------------------|
| `discourse_order` | float — [v2.2] 텍스트 등장 순서 |
| `story_order` | float / null — [v2.2] 서사 세계 내 실제 시점 |
| `mention_type` | enum — 언급 방식 |
| `dialogue_text` | string — 해당 대사/서술 원문 |
| `event_id` | string — 관련 이벤트 (선택) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**mention_type 목록**:
- `direct_speech`: 직접 대사로 언급
- `action`: 행동으로 해당 정보를 아는 것을 드러냄
- `inner_thought`: 내면 독백/나레이션
- `indirect`: 간접적 암시

**모순 탐지 쿼리**:  
`MENTIONS.story_order < min(LEARNS.story_order)` 이면  
→ 캐릭터가 아직 모르는 정보를 언급한 것 = **정보 비대칭 모순**

> [v2.2] `story_order`를 비교하므로 회상/비선형 서사에서도 예외 분기 없이 정확히 판정됩니다.

### 3.2 타임라인 탐지용 엣지

#### PARTICIPATES_IN — "참여함"

캐릭터가 특정 이벤트에 참여/등장했음을 나타냅니다.

| 방향 | Character → Event |
|------|------------------|
| `role` | string — 이벤트에서의 역할 |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

#### HAS_STATUS — "상태 변화"

캐릭터의 상태가 특정 시점에 변경되었음을 나타냅니다.

| 방향 | Character → Event |
|------|------------------|
| `status_type` | enum — 상태 유형 (`alive`, `dead`, `injured`, `captured`, `missing`, `present`, `absent`) |
| `status_value` | string — 상태 값 |
| `location` | string — 위치 (선택) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**모순 탐지 쿼리**:
- 캐릭터의 마지막 상태가 `dead`인데 이후 `story_order`의 이벤트에 `PARTICIPATES_IN`이 있으면 → **타임라인 모순 (사망 후 등장)**
- [v2.2] `story_order`로 비교하므로 회상 장면(story_order < death)은 자동으로 정상 처리. `story_order`가 null이면 사용자 확인.
- 캐릭터의 위치가 `location_A`인데 같은 시점에 `location_B`에서 참여하면 → **타임라인 모순 (동시 존재)**

#### [v2 신규] AT_LOCATION — "위치"

캐릭터가 특정 시점에 어디에 있는지를 추적합니다.

| 방향 | Character → Location |
|------|---------------------|
| `discourse_order` | float — [v2.2] 텍스트 등장 순서 |
| `story_order` | float / null — [v2.2] 서사 세계 내 시점 |
| `arrived_via` | string — 도착 방법 (도보, 차량, 비행기 등) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**모순 탐지**:
- 같은 시점에 다른 Location에 있으면 → 동시 존재 모순
- 이동 시간이 비현실적이면 → `timeline_ambiguity` 사용자 확인 요청 (텔레포트/마법 가능한 세계관인지)

### 3.3 관계 탐지용 엣지

#### RELATED_TO — "관계 맺음"

두 캐릭터 사이의 관계를 나타냅니다. 관계가 변할 때마다 새 엣지를 추가합니다.

| 방향 | Character → Character |
|------|-----------------------|
| `relationship_type` | enum — 관계 유형 |
| `relationship_detail` | string — 상세 관계 (예: "아버지", "첫째 형") |
| `established_order` | float — 관계가 확립/공개된 서사 시점 |
| `valid_from` | float — 관계가 유효한 시작 시점 |
| `valid_until` | float / null — 관계가 끝나는 시점 (null=현재진행) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**relationship_type 목록**:
- `family_parent`: 부모-자녀
- `family_sibling`: 형제/자매
- `family_spouse`: 배우자
- `family_other`: 기타 친족
- `romantic`: 연인
- `friend`: 친구
- `colleague`: 동료
- `rival`: 라이벌
- `enemy`: 적
- `master_servant`: 주종
- `mentor_student`: 사제
- `organization`: 같은 조직 소속

**모순 탐지 쿼리**:
- A→B가 `family_parent`(아버지)인데, 다른 곳에서 A→B가 `family_sibling`(형제)이면 → **관계 모순**
- A→B가 `family_parent`이고 B→C가 `family_parent`인데, A→C가 `family_sibling`이면 → **관계 추이 모순** (할아버지-손자여야 하는데 형제)
- A→B 관계의 `valid_until`이 설정되었는데 이후 시점에서 해당 관계가 유효한 것처럼 서술되면 → **관계 타임라인 모순**
- [v2] 다중 소스에서 같은 캐릭터 쌍의 관계가 다르면 → `source_conflict` 사용자 확인

#### [v2.1 신규] BELONGS_TO — "소속"

캐릭터가 조직에 소속되어 있음을 나타냅니다.

| 방향 | Character → Organization |
|------|--------------------------|
| `role` | string — 조직 내 역할 (예: "대장", "스파이", "일반 구성원") |
| `is_secret` | boolean — 비밀 소속 여부 (이중 스파이 등) |
| `valid_from` | float — 소속 시작 시점 |
| `valid_until` | float / null — 탈퇴 시점 (null=현재 소속) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**모순 탐지**:
- 적대 조직에 동시 소속 (is_secret=false 둘 다) → 모순
- 비밀 소속(is_secret=true)인데 공개적으로 해당 조직과 행동 → 사용자 확인

#### [v2 신규] FEELS — "감정"

캐릭터가 다른 캐릭터에 대해 느끼는 감정을 추적합니다.

| 방향 | Character → Character |
|------|-----------------------|
| `emotion` | enum — `love` / `hate` / `trust` / `distrust` / `fear` / `jealousy` / `gratitude` / `resentment` / `admiration` / `contempt` / `neutral` |
| `intensity` | float (0.0~1.0) — 감정 강도 |
| `discourse_order` | float — [v2.2] 텍스트 등장 순서 |
| `story_order` | float / null — [v2.2] 서사 세계 내 시점 |
| `trigger_event_id` | string — 감정 변화를 유발한 이벤트 (선택) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**모순 탐지**:
- 이벤트 없이 감정이 급변하면 → `emotion_shift` 사용자 확인 요청
- 감정과 행동이 불일치하면 → 사용자 확인 (의도적 반전일 수 있으므로 단정하지 않음)

### 3.4 성격·설정 탐지용 엣지

#### HAS_TRAIT — "특성 보유"

캐릭터에게 특정 특성이 부여되었음을 나타냅니다.

| 방향 | Character → Trait |
|------|------------------|
| `established_order` | float — 설정이 확립된 시점 |
| `valid_from` | float — 유효 시작 시점 |
| `valid_until` | float / null — 유효 종료 시점 (null=영구) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

#### VIOLATES_TRAIT — "설정 위반" (탐지 결과용)

캐릭터의 행동/대사가 기존 설정과 충돌할 때 생성됩니다.

| 방향 | Event → Trait |
|------|--------------|
| `character_id` | string — 해당 캐릭터 |
| `violation_description` | string — 위반 설명 |
| `dialogue_text` | string — 위반 대사/행동 |
| `requires_confirmation` | boolean — [v2] 사용자 확인 필요 여부 |
| `confirmation_id` | string — [v2] UserConfirmation 참조 (선택) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**모순 탐지 쿼리**:
- 캐릭터에 `preference:채식주의`가 `is_immutable=false`, `valid_until=null`인데 고기를 먹는 장면 → [v2] `intentional_change` 사용자 확인 (의도된 변화인지)
- 캐릭터에 `physical:왼손잡이`가 `is_immutable=true`인데 오른손으로 글을 쓰는 장면 → **불변 설정 모순**
- 캐릭터의 같은 `key`에 대해 서로 다른 `value`의 Trait이 동시에 유효하면 → **설정 충돌**

### 3.5 [v2 신규] 소유물 추적용 엣지

#### POSSESSES — "소유"

캐릭터가 특정 시점에 아이템을 소유하고 있음을 나타냅니다.

| 방향 | Character → Item |
|------|-----------------|
| `discourse_order` | float — [v2.2] 텍스트 등장 순서 |
| `story_order` | float / null — [v2.2] 서사 세계 내 시점 |
| `method` | enum — `initial` / `purchased` / `received` / `found` / `stolen` / `created` |
| `possession_type` | enum — [v2.1] `owns`(소유권) / `holds`(물리적 보유) / `can_access`(접근 가능) / `guards`(관리/보관) |
| `from_character_id` | string — 양도한 캐릭터 (received, stolen일 때) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

#### LOSES — "상실"

캐릭터가 아이템을 잃거나 넘겨줌을 나타냅니다.

| 방향 | Character → Item |
|------|-----------------|
| `discourse_order` | float — [v2.2] 텍스트 등장 순서 |
| `story_order` | float / null — [v2.2] 서사 세계 내 시점 |
| `method` | enum — `gave_away` / `lost` / `destroyed` / `stolen_from` / `used_up` |
| `to_character_id` | string — 받은 캐릭터 (gave_away일 때) |
| `source_id` | string — 출처 소스 |
| `source_location` | string — 출처 위치 |

**모순 탐지**:
- `is_unique=true`인 아이템이 동시에 두 캐릭터에게 있으면 → **모순**
- LOSES 이후에 해당 아이템을 사용하는 장면 → `item_discrepancy` 사용자 확인 (같은 아이템인지)
- A→B로 아이템을 줬는데 A가 계속 사용 → **모순**
- [v2.1] `can_access` 권한이 없는 캐릭터가 아이템 사용 → **모순** (예: 열쇠 없이 보관함 열기)
- [v2.1] `owns`하는 사람이 없는데 `holds`하는 사람이 있음 → 사용자 확인 (습득/도난?)
- [v2.1] Item.location_id와 캐릭터의 AT_LOCATION이 다른데 아이템 사용 → **모순** (아이템이 다른 장소에 있음)

### 3.6 출처 추적용 엣지

#### SOURCED_FROM — "출처"

모든 노드가 어떤 소스에서 왔는지 추적합니다.

| 방향 | (Any Node) → Source |
|------|---------------------|
| `location` | string — 소스 내 위치 (페이지, 챕터, 섹션) |
| `chunk_id` | string — 원본 청크 ID |

---

## 4. 모순 탐지 쿼리 패턴

### 4.1 정보 비대칭 모순

```
[v2.2] 모든 정보 비대칭 쿼리는 story_order를 기준으로 판정합니다.
회상/비선형 서사에서도 예외 분기 없이 동일 로직입니다.

목표: Character C가 story_order T에서 Fact F를 MENTIONS했는데,
      C가 F를 LEARNS한 가장 빠른 story_order가 T보다 나중인 경우를 찾는다.

의사 코드:
FOR EACH (C)-[m:MENTIONS]->(F):
    IF m.story_order IS NULL: SKIP (시점 미확정 → 사용자 확인 대기)
    
    learns_times = COLLECT (C)-[l:LEARNS]->(F) WHERE l.method != 'public'
    earliest_learn = MIN(learns_times.story_order)  ← story_order 기준
    
    IF earliest_learn IS NULL:
        → 모순! C는 F를 알게 된 적이 없는데 언급함
        [v2] 단, 시나리오만 있고 세계관/설정집이 없으면:
          → source_conflict 사용자 확인 생성
          "이 캐릭터가 이 정보를 다른 경로로 알게 되었을 가능성이 있나요?"
    ELSE IF m.story_order < earliest_learn:
        → 모순! C는 아직 F를 모르는 시점에 언급함
        → 근거: m의 source_location vs earliest_learn의 source_location

예외 처리:
- method='public'인 LEARNS는 서사 시작부터 유효
- method='inherent'인 LEARNS는 해당 캐릭터 본인 정보
- method='inferred'인 LEARNS는 confidence 낮게 처리
- story_order=null인 엣지는 쿼리에서 제외 (미확정 시점)
```

### 4.2 타임라인 모순

```
[v2.2] 모든 타임라인 쿼리는 story_order를 기준으로 판정합니다.
회상 장면은 story_order가 death보다 앞이므로 자동으로 정상 처리됩니다.

목표 A — 사망 후 등장:
FOR EACH (C)-[s:HAS_STATUS]->(E) WHERE s.status_type = 'dead':
    death_story = E.story_order
    IF death_story IS NULL: SKIP (시점 미확정)
    
    later_events = (C)-[p:PARTICIPATES_IN]->(E2) WHERE E2.story_order > death_story
    
    IF later_events IS NOT EMPTY:
        resurrection = (C)-[s2:HAS_STATUS]->(E3) 
                       WHERE s2.status_type = 'alive' AND E3.story_order > death_story
        IF resurrection IS NULL:
            → HARD contradiction! C는 사망했는데 이후 등장
            (story_order 기준이므로 회상 장면은 이미 걸러짐)
        ELSE IF resurrection.story_order > later_events[0].story_order:
            → HARD contradiction! 부활 전에 등장

    story_order IS NULL인 이벤트:
        → timeline_ambiguity 사용자 확인 생성
        "이 장면의 시점이 확정되지 않았습니다. 현재인가요, 회상인가요?"

목표 B — 동시 존재 불가:
FOR EACH Character C:
    events_at_same_time = GROUP (C)-[p:PARTICIPATES_IN]->(E) BY E.story_order
    FOR EACH time_group:
        locations = UNIQUE(events.location)
        IF COUNT(locations) > 1:
            → HARD contradiction! C가 같은 시점에 여러 장소에 존재
            단, 세계관에 텔레포트/순간이동이 있으면:
              → SOFT → timeline_ambiguity 사용자 확인

목표 C — 이동 시간 검증 (AT_LOCATION 엣지 활용):
FOR EACH Character C:
    locations_seq = SORTED (C)-[a:AT_LOCATION]->(L) BY a.story_order
    FOR EACH consecutive pair (L1, L2):
        travel_time = L2.story_order - L1.story_order
        IF travel_time < L1.travel_constraints.minimum_time:
            → SOFT → timeline_ambiguity 사용자 확인
            "이동 시간이 비현실적입니다. 세계관에서 가능한가요?"

[v2.2] 목표 D — 비선형 서사 감지 (이중 시간 축 활용):
FOR EACH consecutive event pair (E1, E2) sorted by discourse_order:
    IF E2.story_order IS NOT NULL AND E1.story_order IS NOT NULL:
        IF E2.story_order < E1.story_order:
            → E2.is_linear = false (회상 또는 비선형 서사)
    IF E2.story_order IS NULL:
        → 시스템이 story_order를 추정 시도
        → 추정 불가 시 timeline_ambiguity 사용자 확인
        "이 장면의 시점이 불분명합니다. 언제 일어난 사건인가요?"
```

### 4.3 관계 모순

```
목표 A — 직접 충돌:
FOR EACH pair (C1, C2):
    relations = ALL (C1)-[r:RELATED_TO]->(C2)
    active_relations = FILTER relations WHERE valid_until IS NULL OR valid_until > current_order
    
    conflicting = CHECK_CONFLICT(active_relations)
    예시: family_parent + family_sibling → 충돌
    예시: family_parent × 2 (아버지가 2명) → 충돌 (입양 제외)

목표 B — 추이 충돌:
IF (A)-[:family_parent]->(B) AND (B)-[:family_parent]->(C):
    expected: A는 C의 조부모
    actual = (A)-[:RELATED_TO]->(C)
    IF actual.type == 'family_sibling':
        → 모순! 추이적 관계 불일치

충돌 매트릭스:
| 관계 A vs B      | 충돌 여부 | [v2] 처리 |
|------------------|----------|----------|
| parent + sibling | ✅ 충돌  | 모순 |
| parent + spouse  | ✅ 충돌  | 모순 |
| sibling + spouse | ⚠️ 확인 필요 | → relationship_ambiguity 사용자 확인 |
| friend + enemy   | ⚠️ 시점에 따라 다름 | → 시점 확인 후 판단 |
| parent × 2       | ⚠️ 확인 필요 | → relationship_ambiguity 사용자 확인 (입양 가능) |

[v2] 목표 C — 다중 소스 충돌:
IF same character pair has different relationship in Source A vs Source B:
    → source_conflict 사용자 확인 생성
    "세계관에서는 'A는 B의 형'이지만 시나리오에서는 'A는 B의 아버지'입니다."
    양쪽 원본을 나란히 표시하고 어느 것이 정본인지 확인
```

### 4.4 성격·설정 모순

```
목표 A — 동일 키 충돌:
FOR EACH Character C:
    traits = ALL (C)-[h:HAS_TRAIT]->(T)
    FOR EACH unique T.key:
        active_values = FILTER traits WHERE same key AND (valid_until IS NULL OR overlapping)
        IF COUNT(UNIQUE(active_values.value)) > 1:
            IF T.is_immutable = true:
                → 모순! 불변 속성이 다름 (예: 혈액형 A형 + O형)
            ELSE:
                [v2] → intentional_change 사용자 확인 생성
                "캐릭터의 '{key}' 설정이 '{old}'에서 '{new}'로 변경되었습니다.
                 의도된 캐릭터 성장/변화인가요?"
                원본 발췌를 함께 표시

목표 B — 행동 위반 (LLM 보조 + [v2] 사용자 확인):
FOR EACH action/dialogue in new manuscript:
    character = extract_character(action)
    traits = (character)-[:HAS_TRAIT]->()
    
    LLM_CHECK:
        "이 캐릭터는 {traits}인데 '{action}'을 했습니다. 모순인가요?"
        
    IF LLM confidence >= 0.8:
        → 모순! (확실한 위반)
    ELSE:
        [v2] → foreshadowing 사용자 확인 생성
        "이 행동이 설정을 위반하는 것처럼 보입니다. 복선/의도적 장치인가요?"
    
    is_immutable=true인 trait 위반은 confidence 무관하게 severity=critical

[v2] 목표 C — 다중 소스 설정 충돌:
IF worldview says "마법은 존재하지 않는다" BUT scenario uses magic:
    → source_conflict 사용자 확인 생성
    양쪽 원본을 나란히 표시
```

### 4.5 [v2 신규] 감정 일관성

```
목표 A — 이벤트 없는 감정 급변:
FOR EACH Character C:
    feels_seq = SORTED (C)-[f:FEELS]->(target) BY f.story_order
    FOR EACH consecutive pair (f1, f2) where target is same:
        IF emotion_distance(f1.emotion, f2.emotion) > THRESHOLD:
            IF f2.trigger_event_id IS NULL:
                → emotion_shift 사용자 확인 생성
                "A의 B에 대한 감정이 '{f1.emotion}'에서 '{f2.emotion}'로 변경되었으나
                 원인이 되는 이벤트가 없습니다. 의도된 전개인가요?"

목표 B — 감정과 행동 불일치:
FOR EACH (C)-[f:FEELS{emotion='hate'}]->(target):
    actions_toward_target = FILTER events WHERE C helps target at f.story_order
    IF actions IS NOT EMPTY:
        → emotion_shift 사용자 확인 생성
        (의도적 반전일 수 있으므로 시스템이 단정하지 않음)
```

### 4.6 [v2 신규] 소유물 추적

```
목표 A — 유일 아이템 중복 소유:
FOR EACH Item I WHERE I.is_unique = true:
    possessors_at_time = GROUP (C)-[p:POSSESSES]->(I) BY p.story_order
    FOR EACH time_group:
        # LOSES가 없는 현재 소유자만 카운트
        active_possessors = possessors who haven't LOSES'd this item before this time
        IF COUNT(active_possessors) > 1:
            → 모순! 유일한 아이템을 동시에 여러 명이 소유

목표 B — 상실 후 사용:
FOR EACH (C)-[l:LOSES]->(I):
    later_uses = (C)-[m:MENTIONS or action]->(I) WHERE order > l.story_order
    IF later_uses IS NOT EMPTY:
        → item_discrepancy 사용자 확인 생성
        "A는 이 아이템을 B에게 양도했지만 이후 장면에서 사용합니다."
        (비슷한 다른 아이템일 수 있으므로 확인)
```

### 4.7 [v2.1 신규] 거짓말·기만 탐지

```
목표 A — 거짓 정보 기반 행동:
FOR EACH (C)-[l:LEARNS]->(F) WHERE F.is_true = false AND l.believed_true = true:
    # C는 거짓 정보를 참이라고 믿고 있음
    actions_based_on_F = (C)-[m:MENTIONS]->(F)
    → 이 자체는 모순이 아님 (캐릭터가 속은 것)
    
    BUT IF C가 나중에 진실을 알게 됨 (새 LEARNS with believed_true=false):
        truth_order = new_learns.story_order
        later_mentions = MENTIONS WHERE order > truth_order AND still references F as true
        IF later_mentions IS NOT EMPTY:
            → 모순! 진실을 알게 된 후에도 거짓 정보를 믿는 것처럼 행동

목표 B — 거짓말 전파 추적:
IF A tells B a lie (LEARNS(F, method=told_by, via=A) AND F.is_true=false):
    B가 이 거짓 정보를 C에게 전달:
    (C)-[l:LEARNS(F, method=told_by, via=B)]->(F)
    → 거짓 정보 전파 체인 추적
    → C가 나중에 진실을 아는 경로가 없으면 계속 속아있는 것 (정상)
    → C가 진실을 알면서도 거짓 정보 기반 행동 → 모순
```

### 4.8 [v2.1 신규] 환경적 제약 탐지

```
FOR EACH Event E WHERE E.environment IS NOT NULL:
    actions = characters' actions/dialogue in this event
    
    환경-행동 불일치 체크:
    IF E.environment.lighting = 'dark':
        시각 의존 행동 (멀리 관찰, 문서 읽기 등) → 사용자 확인
        "어두운 환경에서 이 행동이 가능한가요?"
    
    IF E.environment.special_conditions contains '정전':
        전자기기 사용 행동 → 모순 (세계관에 비상발전기 설정 없으면)
    
    IF E.environment.weather = 'storm':
        야외 장시간 대화 → 사용자 확인
        "폭풍우 중 옥외 대화가 의도된 장면인가요?"
    
    환경 연속성 체크:
    IF consecutive events at same location have contradicting environment:
        E1.weather = 'clear', E2.weather = 'storm' (같은 시간대, 같은 장소)
        → 사용자 확인 (급변 가능한 날씨인지)
```

---

## 5. [v2 신규] 사용자 확인 플로우

### 5.1 확인 요청 생성 기준

| 상황 | confirmation_type | 시스템 동작 |
|------|------------------|------------|
| 서사 흐름이 이전 시점으로 점프 | `flashback_check` | 원본 발췌 + "과거 회상인가요?" |
| 설정 변화 (is_immutable=false) | `intentional_change` | 양쪽 설정값 + 원본 + "의도된 변화인가요?" |
| LLM confidence 0.5~0.8 범위 | `foreshadowing` | 모순 설명 + 원본 + "복선/의도적 장치인가요?" |
| 다중 소스에서 같은 사실이 다름 | `source_conflict` | 양쪽 원본을 나란히 + "어느 것이 정본인가요?" |
| 감정 급변에 이벤트가 없음 | `emotion_shift` | 감정 변화 이력 + "의도된 전개인가요?" |
| 관계 충돌 (warning 수준) | `relationship_ambiguity` | 관계 목록 + 원본 + "의도된 설정인가요?" |
| 아이템 소유 불일치 | `item_discrepancy` | 소유 이력 + "같은 아이템인가요?" |
| 시간/공간 비현실적 이동 | `timeline_ambiguity` | 이동 경로 + "세계관에서 가능한가요?" |
| 화자의 서술이 모순적 | `unreliable_narrator` | 해당 서술 + "이 화자를 신뢰해야 하나요?" |

**핵심 원칙**: 사용자 확인 항목에는 반드시 **관련 원본 발췌(source_excerpts)**를 포함합니다. 원본 없이 질문만 던지면 사용자가 판단할 수 없습니다.

### 5.2 세계관 유무에 따른 확인 건수 변화

```
[시나리오만 입력한 경우]
- 캐릭터 배경 정보 부재 → 설정 위반 판단 어려움 → 확인 건수 증가
- 세계관 규칙 부재 → 마법/텔레포트 등 가능 여부 불명 → 확인 건수 증가
- 관계 설정 부재 → 관계 충돌 판단 어려움 → 확인 건수 증가
→ 사용자 확인이 많아지지만, 확인하는 것이 모순을 놓치는 것보다 안전

[세계관 + 설정집 + 시나리오 전부 입력한 경우]
- 세계관 규칙으로 자동 판단 가능 범위 확대
- 설정집으로 캐릭터 특성/관계를 사전 확보
- 사용자 확인 건수가 크게 감소
→ 시스템이 확인 없이 자동 판정할 수 있는 비율이 높아짐
```

### 5.3 확인 후 처리 흐름

```
사용자 답변 → 처리:

"모순이 맞다" (confirmed_contradiction):
  → ContradictionReport 생성
  → 사용자가 수정하여 스테이징 가능 (git commit 방식)

"의도된 것이다" (confirmed_intentional):
  → 해당 항목을 '의도적 장치'로 표시
  → 향후 같은 패턴에 대해 자동 스킵 (학습)
  → 설정 변화인 경우: valid_until을 설정하여 변경 이력 반영

"소스 A가 정본이다" (source_conflict 해결):
  → 소스 B의 해당 정보를 비활성화
  → 관련 그래프 엣지 업데이트

"과거 회상이다" (flashback_check 해결):
  → Event.story_order를 사용자가 지정한 과거 시점으로 설정
  → Event.is_linear = false
  → 해당 장면의 정보 흐름을 story_order 기준으로 재평가
  → 재탐지 시 story_order 기준 쿼리가 자동으로 올바른 결과 반환
```

---

## 6. [v2.2] 이중 시간 축 (Dual Time Axis) 설계

### 6.1 두 축의 정의

| 축 | 의미 | 부여 방식 | null 가능 |
|---|------|----------|----------|
| `discourse_order` | 텍스트에 등장하는 물리적 순서 (독자가 접하는 순서) | 자동 부여, 항상 단조 증가 | ❌ 불가 |
| `story_order` | 서사 세계 안에서 실제로 일어난 시간 순서 | 자동 추정 + 사용자 확인 | ✅ 가능 (미확정) |

### 6.2 discourse_order 부여 전략

```
텍스트 물리 순서 그대로 부여합니다. 항상 단조 증가.

소스 파일 내 순서:
  Chapter 1, Scene 1 → discourse_order = 1.0
  Chapter 1, Scene 2 → discourse_order = 1.1
  Chapter 2, Scene 1 → discourse_order = 2.0
  Chapter 3, Scene 1 → discourse_order = 3.0
  Chapter 3, 회상 장면  → discourse_order = 3.1  ← 텍스트 순서 그대로
  Chapter 3, 현재 복귀 → discourse_order = 3.2

규칙:
  - 챕터/장 번호 = 정수부
  - 장면/씬 순서 = 소수부 (0.1씩 증가)
  - 같은 장면 내 세부 순서 = 0.01 단위
```

### 6.3 story_order 부여 전략

```
서사 세계 내 실제 시점을 추정합니다. 미확정이면 null.

선형 서사 (대부분의 경우):
  story_order = discourse_order (동일)
  is_linear = true

비선형 서사 감지:
  시스템이 discourse_order 순서로 읽으면서 "시간 점프" 힌트를 탐지:
  - "10년 전", "그날 밤", "며칠 후" 같은 시간 표현
  - 이미 사망한 캐릭터가 다시 등장
  - 장소/상황이 이전 시점의 것으로 되돌아감

  감지 시:
    story_order = 추정된 과거/미래 시점
    is_linear = false
    확신이 없으면 story_order = null → 사용자 확인

예시:
  E10: discourse=3.0, story=3.0, is_linear=true   "현재 대화"
  E11: discourse=3.1, story=0.5, is_linear=false   "10년 전 회상"
  E12: discourse=3.2, story=3.0, is_linear=true    "현재 복귀"

  → E11에서 캐릭터가 아는 정보는 story_order=0.5 기준으로 판정
  → 예외 분기 없이 MENTIONS.story_order < LEARNS.story_order로 판정
```

### 6.4 여러 소스 간 순서 통합

```
같은 사건이 여러 소스에서 다뤄질 때:
1) 첫 번째 소스의 discourse_order/story_order를 기준점으로 설정
2) 이후 소스에서 같은 사건 → 같은 story_order 매핑
3) 새로운 사건 → 앞뒤 사건의 story_order 사이에 배치
4) 순서가 불명확하면 → timeline_ambiguity 사용자 확인 요청

충돌 발생 시:
  세계관에서 "A는 B보다 먼저 태어남"인데 시나리오에서 반대면:
  → source_conflict 사용자 확인 생성, 양쪽 원본 나란히 표시
```

### 6.5 story_order가 null인 경우의 처리

```
story_order가 null인 이벤트/엣지:
- 모순 탐지 쿼리에서 제외 (판단 보류)
- 대신 timeline_ambiguity UserConfirmation 생성
- 사용자가 시점을 확정하면 story_order 부여 → 재탐지

이 방식의 장점:
- 잘못된 시점 추정으로 인한 false positive 방지
- 사용자가 확인할 때까지 보수적으로 동작
```

---

## 7. Cosmos DB Gremlin 구현 가이드

### 7.1 제약 사항

Cosmos DB Gremlin API는 Apache TinkerPop의 일부만 지원합니다:

| 기능 | 지원 여부 | 대응 방법 |
|------|----------|----------|
| 기본 순회 (V, E, has, out, in) | ✅ 지원 | 그대로 사용 |
| 속성 필터링 (has, hasLabel) | ✅ 지원 | 그대로 사용 |
| 서브쿼리 (coalesce, choose) | ⚠️ 일부 | Python에서 분리 실행 |
| 집계 (count, sum, min, max) | ✅ 지원 | 그대로 사용 |
| 패턴 매칭 (match step) | ❌ 미지원 | Python에서 조합 |
| 복잡한 where 절 | ⚠️ 일부 | 쿼리 분리 + Python 조합 |
| 트랜잭션 | ❌ 미지원 | 멱등성 설계로 대응 |
| 파티션 키 | ✅ 필수 | 모든 쿼리에 포함 |

### 7.2 파티션 키 전략

```
파티션 키: partition_key

Vertex 파티션:
  Character        → partition_key = "character"
  Fact             → partition_key = "fact"  
  Event            → partition_key = "event"
  Trait            → partition_key = "trait"
  Location         → partition_key = "location"     [v2 신규]
  Item             → partition_key = "item"          [v2 신규]
  Organization     → partition_key = "organization"  [v2.1 신규]
  Source           → partition_key = "source"
  UserConfirmation → partition_key = "confirmation"  [v2 신규]

이유:
  - 같은 타입끼리 자주 조회 (list_characters 등)
  - Cross-partition 쿼리가 필요한 경우는 Python에서 조합
  - 데이터 규모가 POC 수준이므로 핫 파티션 문제 없음

프로덕션 확장 시:
  - 작품 ID 기반 파티션 (partition_key = "work_{work_id}")
  - 같은 작품 내 모든 데이터가 한 파티션 → 교차 쿼리 최소화
```

### 7.3 Gremlin 쿼리 예시

#### 정보 비대칭 모순 탐지

```python
# Cosmos DB에서는 복잡한 서브쿼리가 안 되므로 나눠서 실행

async def find_knowledge_violations(self) -> list[dict]:
    violations = []
    
    # 1단계: 모든 MENTIONS 엣지 조회
    mentions = await self._execute("""
        g.E().hasLabel('MENTIONS')
         .project('character_id', 'fact_id', 'order', 'dialogue', 'source_loc')
         .by(outV().id())
         .by(inV().id())
         .by('story_order')
         .by('dialogue_text')
         .by('source_location')
    """)
    
    # 2단계: 각 MENTIONS에 대해 LEARNS 조회
    for mention in mentions:
        learns = await self._execute(f"""
            g.V('{mention['character_id']}')
             .outE('LEARNS')
             .where(inV().hasId('{mention['fact_id']}'))
             .has('story_order', lte({mention['order']}))
             .count()
        """)
        
        if learns[0] == 0:
            # 해당 시점에 LEARNS가 없음 → 모순 후보
            # public/inherent method 체크
            any_learns = await self._execute(f"""
                g.V('{mention['character_id']}')
                 .outE('LEARNS')
                 .where(inV().hasId('{mention['fact_id']}'))
                 .has('method', within('public', 'inherent'))
                 .count()
            """)
            
            if any_learns[0] == 0:
                violations.append(mention)
    
    return violations
```

#### 타임라인 모순 탐지 (사망 후 등장)

```python
async def find_timeline_violations(self) -> list[dict]:
    violations = []
    
    # [v2.2] story_order 기준으로 판정 — is_flashback 불필요
    deaths = await self._execute("""
        g.E().hasLabel('HAS_STATUS')
         .has('status_type', 'dead')
         .project('character_id', 'death_story', 'event_id')
         .by(outV().id())
         .by(inV().values('story_order'))
         .by(inV().id())
    """)
    
    # 2단계: 각 사망 캐릭터의 이후 등장 확인 (story_order 기준)
    for death in deaths:
        if death['death_story'] is None: continue  # story_order 미확정 → 스킵
        
        later_appearances = await self._execute(f"""
            g.V('{death['character_id']}')
             .outE('PARTICIPATES_IN')
             .where(inV().has('story_order', gt({death['death_story']})))
             .project('event_id', 'story')
             .by(inV().id())
             .by(inV().values('story_order'))
        """)
        # story_order 기준이므로 회상 장면(story < death)은 자동 제외됨
        
        if later_appearances:
            # story_order가 null인 이벤트 → 사용자 확인
            for app in later_appearances:
                if app['story'] is None:
                    confirmations.append({
                        'type': 'timeline_ambiguity',
                        'question': '이 장면의 시점이 확정되지 않았습니다.',
                        'character_id': death['character_id'],
                        'event_id': app['event_id'],
                    })
                    continue
            
            # story_order 확정된 이후 등장 → HARD contradiction 확인
            confirmed = [a for a in later_appearances if a['story'] is not None]
            if confirmed:
                resurrections = await self._execute(f"""
                    g.V('{death['character_id']}')
                     .outE('HAS_STATUS')
                     .has('status_type', within('alive', 'resurrection'))
                     .where(inV().has('story_order', gt({death['death_story']})))
                     .count()
                """)
                if resurrections[0] == 0:
                    violations.append({
                        'type': 'death_after_appearance',
                        'hard': True,  # HARD contradiction
                        'character_id': death['character_id'],
                        'death_story': death['death_story'],
                        'appearances': confirmed
                    })
    
    return violations
```

#### 관계 모순 탐지

```python
async def find_relationship_violations(self) -> list[dict]:
    violations = []
    
    # 모든 관계 엣지 조회
    relations = await self._execute("""
        g.E().hasLabel('RELATED_TO')
         .project('from', 'to', 'type', 'detail', 'from_order', 'source')
         .by(outV().id())
         .by(inV().id())
         .by('relationship_type')
         .by('relationship_detail')
         .by('established_order')
         .by('source_location')
    """)
    
    # Python에서 충돌 매트릭스 체크
    from collections import defaultdict
    pair_relations = defaultdict(list)
    
    for rel in relations:
        pair = tuple(sorted([rel['from'], rel['to']]))
        pair_relations[pair].append(rel)
    
    CONFLICT_MATRIX = {
        frozenset(['family_parent', 'family_sibling']): 'critical',
        frozenset(['family_parent', 'family_spouse']): 'critical',
        frozenset(['family_parent', 'romantic']): 'warning',  # [v2] 사용자 확인
        frozenset(['family_sibling', 'family_spouse']): 'warning',  # [v2] 사용자 확인
    }
    
    for pair, rels in pair_relations.items():
        types = set(r['relationship_type'] for r in rels)
        for conflict_pair, severity in CONFLICT_MATRIX.items():
            if conflict_pair.issubset(types):
                if severity == 'critical':
                    violations.append({
                        'type': 'relationship_conflict',
                        'characters': pair,
                        'conflicting_relations': [r for r in rels if r['relationship_type'] in conflict_pair],
                        'severity': severity
                    })
                else:
                    # [v2] warning → 사용자 확인
                    confirmations.append({
                        'type': 'relationship_ambiguity',
                        'characters': pair,
                        'question': '이 관계 충돌이 의도된 설정인가요?',
                        'source_excerpts': [r['source'] for r in rels if r['relationship_type'] in conflict_pair],
                    })
    
    return violations
```

#### [v2 신규] 소유물 추적 탐지

```python
async def find_item_violations(self) -> list[dict]:
    violations = []
    
    # 유일 아이템 조회
    unique_items = await self._execute("""
        g.V().hasLabel('Item').has('is_unique', true).id()
    """)
    
    for item_id in unique_items:
        # 소유 이력 조회
        possessions = await self._execute(f"""
            g.V('{item_id}').inE('POSSESSES')
             .project('character', 'order', 'method')
             .by(outV().id())
             .by('story_order')
             .by('method')
        """)
        
        losses = await self._execute(f"""
            g.V('{item_id}').inE('LOSES')
             .project('character', 'order')
             .by(outV().id())
             .by('story_order')
        """)
        
        # 각 시점에서 실제 소유자 계산
        # POSSESSES - LOSES를 시간순으로 추적
        # 동시 소유자 > 1이면 모순
    
    return violations
```

### 7.4 InMemoryGraphService 구현 노트

```python
class InMemoryGraphService:
    """
    Cosmos DB 없이 동작하는 테스트용 그래프 서비스.
    dict 기반으로 동일한 인터페이스를 구현합니다.
    """
    
    def __init__(self):
        self.vertices: dict[str, dict] = {}  # id -> vertex data
        self.edges: list[dict] = []           # edge list
        self.edge_index: dict[str, list] = defaultdict(list)  # vertex_id -> edge indices
        self.confirmations: list[dict] = []   # [v2] UserConfirmation 목록
    
    # 모든 메서드를 GremlinGraphService와 동일한 시그니처로 구현
    # Gremlin 쿼리 대신 Python list comprehension으로 필터링
    
    # 장점: Azure 없이 즉시 테스트 가능
    # 전환: 환경변수 USE_LOCAL_GRAPH=true/false로 전환
```

---

## 8. [v2.2] Hard Contradiction vs Soft Inconsistency 형식 구분

모순을 두 등급으로 형식 구분합니다. 이 구분에 따라 자동 판정 여부와 사용자 확인 여부가 결정됩니다.

### 8.1 Hard Contradiction — 논리적으로 불가능, 자동 판정

서사 세계의 규칙 내에서 **어떤 해석으로도 동시에 참일 수 없는** 논리적 모순입니다.
confidence와 무관하게 자동 판정됩니다. 사용자는 "수정" 또는 "세계관 규칙 변경"만 가능합니다.

| 유형 | 예시 | 판정 조건 |
|------|------|----------|
| 불변 속성 충돌 | 혈액형이 A형이면서 O형 | is_immutable=true인 같은 key에 다른 value 동시 유효 |
| 사망 후 등장 (story_order 확정) | 사망 이후 시점에 등장, 회상 아님 | HAS_STATUS=dead의 story_order < PARTICIPATES_IN의 story_order, 부활 없음 |
| 유일 아이템 중복 소유 | 하나뿐인 칼을 두 사람이 동시 소유 | is_unique=true + 동시점 POSSESSES 2개 이상 |
| 확정 관계 충돌 | A가 B의 부모이면서 형제 | CONFLICT_MATRIX에서 critical인 쌍 |
| 접근 불가능 사용 | 열쇠 없이 잠긴 문 열기 | can_access 권한 없음 + 행동 기록 |
| 진실 인지 후 거짓 기반 행동 | 거짓임을 안 후에도 거짓을 믿는 것처럼 행동 | believed_true 전환 후 + 거짓 기반 MENTIONS |
| 정보 비대칭 (story_order 확정) | 아직 모르는 정보를 확신적 표현으로 언급 | MENTIONS.story_order < LEARNS.story_order, story_order 확정 |
| 동시 존재 불가 | 같은 시점에 두 장소에 있음 | AT_LOCATION story_order 동일 + location 다름 |

**공통 조건**: 두 명제가 동시에 참일 수 없다는 것이 세계관 규칙이나 논리 법칙에 의해 보장됨.

### 8.2 Soft Inconsistency — 맥락에 따라 의도적일 수 있음, 사용자 확인

단독으로 보면 불일치하지만 **추가 맥락이 있으면 해소 가능한** 것입니다.
시스템은 판단하지 않고 사용자에게 확인을 요청합니다.

| 유형 | 예시 | 왜 soft인가 | 확인 내용 |
|------|------|-----------|----------|
| 변경 가능 설정 변화 | 채식주의자가 고기를 먹음 | 캐릭터 성장/변화일 수 있음 | "의도된 변화인가요?" |
| 감정 급변 | love→hate (이벤트 없음) | 의도적 반전, 숨겨진 이유 | "의도된 전개인가요?" |
| 관계 모호성 | 형제이면서 배우자 | 세계관 설정(신화, 왕족) 가능 | "의도된 설정인가요?" |
| 정보 비대칭 (추론 가능) | 형사가 직감으로 범인 맞춤 | 추론/직감으로 설명 가능 | "다른 경로로 알 수 있나요?" |
| 비현실적 이동 | 서울→부산 30분 | 세계관에 고속 이동 수단 가능 | "세계관에서 가능한가요?" |
| 상실 후 사용 | 칼을 줬는데 다시 사용 | 비슷한 다른 칼일 수 있음 | "같은 아이템인가요?" |
| 환경 제약 위반 | 어두운 밤에 먼 곳을 봄 | 야간 투시 능력 가능 | "이 행동이 가능한가요?" |
| 목표/동기 불일치 | 범인 잡겠다면서 증거 숨김 | 내적 갈등의 표현 | "의도된 장치인가요?" |
| 시점 미확정 | story_order가 null인 이벤트 | 회상/프롤로그일 수 있음 | "이 장면은 언제인가요?" |
| 다중 소스 충돌 | 세계관과 시나리오가 다름 | 어느 것이 정본인지 불명 | "어느 것이 맞나요?" |
| 신뢰할 수 없는 화자 | 화자의 서술이 사실과 다름 | 의도된 서사 기법 | "이 서술을 신뢰해야 하나요?" |

**공통 조건**: 추가 맥락이 있으면 해소 가능. 그 맥락은 작가만 알 수 있음.

### 8.3 판정 흐름

```
violation 발생
  ↓
hard_contradiction 조건 충족? ─── Yes → 자동 판정 (severity=critical)
  ↓ No                              ContradictionReport 즉시 생성
  ↓                                  사용자는 "수정" 또는 "규칙 변경"만 가능
  ↓
LLM 검증 → confidence 산출
  ↓
confidence ≥ 0.8? ─── Yes → 자동 판정 (severity=warning, 높은 확신)
  ↓ No                    ContradictionReport 생성
  ↓
  └→ UserConfirmation 생성 (severity=warning, 사용자 확인)
     원본 발췌 필수 포함
     사용자 답변:
       "모순이 맞다" → ContradictionReport로 승격
       "의도된 것이다" → 의도적 장치로 표시, 향후 스킵
```

### 8.4 LLM 보조 판정의 역할과 한계

LLM은 **Hard인지 Soft인지 이미 결정된 후**, Soft 항목에 대해서만 confidence를 산출합니다.

| LLM 역할 | 설명 |
|----------|------|
| 행동-설정 위반 확신도 산출 | 대사/행동을 Trait과 비교하여 위반 가능성 수치화 |
| 추론 가능성 판단 | 정보를 직접 듣지 않아도 추론할 수 있는지 판단 |

| LLM이 하지 않는 것 | 이유 |
|------------------|------|
| "복선일 수 있다" 판단 | 작가의 의도를 알아야 함 → confidence 낮게 산출하여 사용자 확인으로 전환 |
| "캐릭터 성장이다" 판단 | 작가의 의도를 알아야 함 → confidence 낮게 산출 |
| Hard/Soft 분류 자체 | 구조적 조건으로 이미 결정됨, LLM 개입 불필요 |

**핵심**: 8.2(Soft)의 모든 사용자 확인 항목에는 **관련 원본 발췌를 반드시 포함**합니다.

---

## 9. 확장 설계 (POC 이후)

### 9.1 Multi-Work 지원

```
Work Vertex:
- id, title, type("drama", "movie", "novel", "game")
- 시즌/권 정보

BELONGS_TO 엣지: Source → Work
→ 같은 세계관의 여러 작품 간 정합성 검증
```

### 9.2 사용자 확인 학습

```
UserConfirmation의 패턴을 축적하여:
- "이 작가는 과거 회상을 자주 사용한다" → flashback_check 자동 승인 비율 증가
- "이 세계관에서는 텔레포트가 가능하다" → 이동 시간 검증 스킵
→ 프로젝트별 학습으로 점차 사용자 확인 건수 감소
```

---

## 부록 A: 전체 노드/엣지 요약표

### Vertices (9종)

| 노드 | 파티션 키 | 핵심 속성 | POC 구현 |
|------|----------|----------|---------|
| Character | `character` | name, aliases, tier | ✅ |
| KnowledgeFact | `fact` | content, category, is_secret, is_true | ✅ |
| Event | `event` | discourse_order, story_order, is_linear, event_type, environment | ✅ |
| Trait | `trait` | category(+goal/motivation), key, value, is_immutable | ✅ |
| Organization | `organization` | name, org_type | ✅ [v2.1] |
| Location | `location` | name, location_type, parent_location_id | ✅ [v2] |
| Item | `item` | name, is_unique, location_id | ✅ [v2] |
| Source | `source` | source_type (worldview/settings/scenario/manuscript) | ✅ |
| UserConfirmation | `confirmation` | confirmation_type, status, source_excerpts | ✅ [v2] |

### Edges (13종)

| 엣지 | 방향 | 모순 유형 | POC 구현 |
|------|------|----------|---------|
| LEARNS | Character → Fact | 정보 비대칭 (+believed_true, story_order) | ✅ |
| MENTIONS | Character → Fact | 정보 비대칭 | ✅ |
| PARTICIPATES_IN | Character → Event | 타임라인 | ✅ |
| HAS_STATUS | Character → Event | 타임라인 | ✅ |
| AT_LOCATION | Character → Location | 타임라인 (위치) | ✅ [v2] |
| RELATED_TO | Character → Character | 관계 | ✅ |
| BELONGS_TO | Character → Organization | 관계 (소속) | ✅ [v2.1] |
| FEELS | Character → Character | 감정 일관성 | ✅ [v2] |
| HAS_TRAIT | Character → Trait | 성격·설정 | ✅ |
| VIOLATES_TRAIT | Event → Trait | 성격·설정 (결과) | ✅ |
| POSSESSES | Character → Item | 소유물 (+possession_type) | ✅ [v2] |
| LOSES | Character → Item | 소유물 | ✅ [v2] |
| SOURCED_FROM | Any → Source | 출처 추적 | ✅ |

---

## 부록 B: 테스트 시나리오

### 시나리오: "그림자의 비밀"

```
캐릭터: A(형사), B(범인), C(목격자), D(파트너)
소스 1: 그림자의_비밀_시즌1.pdf (시나리오)
소스 2: 캐릭터_설정집.txt (설정집)

=== 기대되는 지식 그래프 ===

Vertices:
  [A:Character] tier=1, name="A"
  [B:Character] tier=2, name="B"
  [C:Character] tier=2, name="C"  
  [D:Character] tier=2, name="D"
  [F1:Fact] content="범인은 B이다", category=plot_secret, is_secret=true
  [F2:Fact] content="C는 범행을 목격했다", category=event_fact
  [F3:Fact] content="B가 C를 위협했다", category=event_fact, is_secret=true
  [T1:Trait] key="직업", value="형사", category=background
  [T2:Trait] key="성격", value="정의감이 강함", category=personality
  [L1:Location] name="경찰서", type=building                              [v2 신규]
  [L2:Location] name="골목", type=outdoor                                 [v2 신규]
  [I1:Item] name="증거 칼", is_unique=true                                [v2 신규]
  [E1:Event] discourse=1.0, story=1.0, is_linear=true,  desc="사건 현장 도착"
  [E2:Event] discourse=2.0, story=2.0, is_linear=true,  desc="C 면담"
  [E3:Event] discourse=2.5, story=2.5, is_linear=true,  desc="B가 C를 위협" 
  [E4:Event] discourse=3.0, story=3.0, is_linear=true,  desc="C가 A에게 고백"
  [E5:Event] discourse=4.0, story=4.0, is_linear=true,  desc="B 체포"

Edges:
  [C]-LEARNS(story=1.0, method=witness)->[F1]
  [C]-LEARNS(story=1.0, method=witness)->[F2]
  [A]-LEARNS(story=3.0, method=told_by, via=C)->[F1]
  [A]-LEARNS(story=3.0, method=told_by, via=C)->[F3]
  [A]-HAS_TRAIT->[T1]
  [A]-HAS_TRAIT->[T2]
  [A]-RELATED_TO(type=colleague)->[D]
  [A]-AT_LOCATION(story=1.0)->[L2]                                        [v2 신규]
  [A]-AT_LOCATION(story=2.0)->[L1]                                        [v2 신규]
  [A]-FEELS(emotion=trust, story=1.0)->[D]                                [v2 신규]
  [C]-POSSESSES(story=2.0, method=found, possession_type=holds)->[I1]     [v2.1 수정]
  [F_LIE:Fact] content="B는 그날 밤 집에 있었다", is_true=false            [v2.1 신규]
  [A]-LEARNS(F_LIE, story=1.0, method=told_by, via=B, believed_true=true) [v2.1 신규]
  [E1].environment = {time_of_day:"night", lighting:"dark"}                [v2.1 신규]
  
=== 검증용 원고에서 탐지될 모순 ===

[v2.2] 모든 판정은 story_order 기준:

HARD 모순 1 (정보 비대칭, critical):
  A가 story=2.8에서 "B가 범인인 것 같아" → MENTIONS(F1, story=2.8)
  A의 LEARNS(F1)는 story=3.0 → 2.8 < 3.0 → HARD contradiction!

HARD 모순 2 (정보 비대칭, critical):
  A가 story=2.8에서 "C가 위협받고 있다" → MENTIONS(F3, story=2.8)
  A의 LEARNS(F3)는 story=3.0 → 2.8 < 3.0 → HARD contradiction!

SOFT — 사용자 확인 예시:
  D가 story=2.0에서 B 알리바이를 조사하다가 story=2.8에서 놀라는 반응
  → foreshadowing 사용자 확인: "D의 반응은 의도된 것인가요?"
  → 원본 발췌: Ch.2 p.65 "B씨 알리바이를 확인해봐야겠어" + 검증 원고 해당 대사
```
